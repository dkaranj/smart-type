import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QPlainTextEdit,
    QProgressBar, QScrollArea, QSlider, QTabWidget, QVBoxLayout, QWidget
)
from google import genai
from pynput.keyboard import Controller

try:
    import keyring
except ImportError:
    keyring = None


APP_NAME = "Smart Type"
DEFAULT_MODEL = "gemini-3.8-flash"


def safe_relative_path(value: str) -> Path:
    """Reject absolute paths and traversal outside the selected project."""
    value = value.replace("\\", "/").strip()
    p = Path(value)
    if not value or p.is_absolute() or ".." in p.parts:
        raise ValueError(f"Unsafe project path: {value!r}")
    if not re.fullmatch(r"[A-Za-z0-9._ /@+-]+", value):
        raise ValueError(f"Unsupported characters in project path: {value!r}")
    return p


def extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("Gemini did not return a valid JSON project.")
        return json.loads(match.group(0))


class GenerateWorker(QThread):
    finished_project = Signal(dict)
    failed = Signal(str)
    status = Signal(str)

    def __init__(self, api_key, prompt, model):
        super().__init__()
        self.api_key = api_key
        self.prompt = prompt
        self.model = model

    def run(self):
        try:
            self.status.emit("Connecting to Gemini…")
            client = genai.Client(api_key=self.api_key)
            instruction = f"""
You are an expert web developer. Create a complete, runnable website project
from the user's brief. Return ONLY valid JSON, no markdown fences, using this
exact shape:
{{
  "project_name": "short-folder-name",
  "summary": "brief description",
  "files": [
    {{"path": "index.html", "content": "complete file content"}}
  ],
  "run_instructions": ["step one", "step two"]
}}
Include every necessary file (HTML/CSS/JS or framework files as appropriate),
a README.md, and sensible defaults. Keep paths relative. Do not use absolute
paths or ../. Do not include secrets or API keys in generated files.
User brief:
{self.prompt}
"""
            self.status.emit("Generating with Gemini… waiting for first response chunk.")
            # Use the standard Gemini streaming generation endpoint.
            # This avoids the Interactions API event-schema changes and exposes
            # each generated text chunk directly as chunk.text.
            chunks = []
            last_update = time.monotonic()
            stream = client.models.generate_content_stream(
                model=self.model,
                contents=instruction,
                config={"http_options": {"timeout": 180000}},
            )
            for chunk in stream:
                piece = getattr(chunk, "text", None)
                if piece:
                    chunks.append(piece)
                    now = time.monotonic()
                    if now - last_update >= 1:
                        received = sum(len(part) for part in chunks)
                        self.status.emit(
                            f"Gemini is writing your project… {received:,} characters received."
                        )
                        last_update = now
            response_text = "".join(chunks).strip()
            if not response_text:
                raise RuntimeError(
                    "Gemini returned an empty response. Check that the selected model is enabled "
                    "for this API key and that your Google AI Studio quota is available."
                )
            self.status.emit(
                f"Gemini response received ({len(response_text):,} characters). Preparing project files…"
            )
            data = extract_json(response_text)
            if not isinstance(data.get("files"), list) or not data["files"]:
                raise ValueError("Gemini returned no project files.")
            self.finished_project.emit(data)
        except Exception as exc:
            self.failed.emit(str(exc))


class TypingWorker(QThread):
    progress = Signal(int, int)
    status = Signal(str)
    done = Signal()
    failed = Signal(str)

    def __init__(self, text, cps):
        super().__init__()
        self.text = text
        self.cps = max(1, cps)
        self._pause = threading.Event()
        self._pause.set()
        self._stop = threading.Event()
        self.keyboard = Controller()

    def pause(self):
        self._pause.clear()

    def resume(self):
        self._pause.set()

    def stop(self):
        self._stop.set()
        self._pause.set()

    def run(self):
        try:
            total = len(self.text)
            delay = 1.0 / self.cps
            self.status.emit("Typing started. Keep the intended editor focused.")
            for index, char in enumerate(self.text, start=1):
                if self._stop.is_set():
                    self.status.emit("Typing stopped.")
                    break
                self._pause.wait()
                if self._stop.is_set():
                    break
                self.keyboard.type(char)
                self.progress.emit(index, total)
                if char not in "\r\n":
                    time.sleep(delay)
            self.done.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class SmartTypeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Type | Gemini Website Builder")
        self.resize(1180, 900)
        self.setMinimumSize(900, 650)
        self.project_data = None
        self.project_dir = None
        self.typing_worker = None
        self.generated_files = []
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#101827; color:#e8eef8; }
            QFrame#panel { background:#172338; border:1px solid #293a55; border-radius:12px; }
            QLineEdit, QPlainTextEdit, QComboBox {
                background:#0d1523; color:#f2f6ff; border:1px solid #344761;
                border-radius:7px; padding:9px; selection-background-color:#087fba;
            }
            QPushButton {
                background:#087fae; color:white; border:0; border-radius:8px;
                padding:10px 15px; font-weight:600;
            }
            QPushButton:hover { background:#0798c9; }
            QPushButton:disabled { background:#39485d; color:#9aa8bb; }
            QPushButton#secondary { background:#293a55; }
            QLabel#muted { color:#9eb0c8; }
            QProgressBar { border:1px solid #344761; border-radius:6px; text-align:center; background:#0d1523; }
            QProgressBar::chunk { background:#08a6cf; border-radius:5px; }
            QTabWidget::pane { border:1px solid #293a55; border-radius:8px; }
            QTabBar::tab { background:#172338; padding:10px 18px; }
            QTabBar::tab:selected { background:#087fae; }
            QSlider::groove:horizontal { height:6px; background:#344761; border-radius:3px; }
            QSlider::handle:horizontal { background:#08a6cf; width:16px; margin:-5px 0; border-radius:8px; }
        """)
        central = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(central)
        self.setCentralWidget(scroll)
        central.setMinimumWidth(860)
        central.setMinimumHeight(900)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("SMART TYPE")
        title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        title.setStyleSheet("color:#31c5e8;")
        subtitle = QLabel("Gemini-powered website builder")
        subtitle.setObjectName("muted")
        header.addWidget(title)
        header.addSpacing(12)
        header.addWidget(subtitle)
        header.addStretch()
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(680)
        self.tabs.setSizePolicy(self.tabs.sizePolicy().horizontalPolicy(), self.tabs.sizePolicy().verticalPolicy())
        layout.addWidget(self.tabs, 1)

        build_tab = QWidget()
        build_layout = QVBoxLayout(build_tab)
        build_layout.setSpacing(12)

        key_panel = QFrame(objectName="panel")
        key_layout = QVBoxLayout(key_panel)
        key_layout.addWidget(QLabel("Gemini API key"))
        key_row = QHBoxLayout()
        self.api_key = QLineEdit()
        self.api_key.setPlaceholderText("Paste your Google Gemini API key")
        self.api_key.setEchoMode(QLineEdit.Password)
        key_row.addWidget(self.api_key)
        self.save_key_btn = QPushButton("Save key")
        self.save_key_btn.setObjectName("secondary")
        self.save_key_btn.clicked.connect(self.save_api_key)
        key_row.addWidget(self.save_key_btn)
        self.show_key = QCheckBox("Show")
        self.show_key.toggled.connect(
            lambda checked: self.api_key.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        )
        key_row.addWidget(self.show_key)
        key_layout.addLayout(key_row)
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model"))
        self.model = QComboBox()
        self.model.addItems(["gemini-3.8-flash", "gemini-3.1-pro-preview"])
        model_row.addWidget(self.model)
        model_row.addStretch()
        key_layout.addLayout(model_row)
        build_layout.addWidget(key_panel)

        prompt_panel = QFrame(objectName="panel")
        prompt_layout = QVBoxLayout(prompt_panel)
        prompt_layout.addWidget(QLabel("Describe the website you want"))
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "Example: Build a modern ISP website for EazyRadius with a homepage, "
            "internet packages, coverage checker, customer login and contact page…"
        )
        self.prompt.setMinimumHeight(150)
        prompt_layout.addWidget(self.prompt)
        folder_row = QHBoxLayout()
        self.folder_label = QLabel("No project folder selected")
        self.folder_label.setObjectName("muted")
        choose = QPushButton("Choose project folder")
        choose.setObjectName("secondary")
        choose.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.folder_label, 1)
        folder_row.addWidget(choose)
        prompt_layout.addLayout(folder_row)
        build_layout.addWidget(prompt_panel)

        actions = QHBoxLayout()
        self.generate_btn = QPushButton("Generate website")
        self.generate_btn.clicked.connect(self.generate)
        self.open_vscode_btn = QPushButton("Open in VS Code")
        self.open_vscode_btn.setObjectName("secondary")
        self.open_vscode_btn.clicked.connect(self.open_vscode)
        self.open_vscode_btn.setEnabled(False)
        actions.addWidget(self.generate_btn)
        actions.addWidget(self.open_vscode_btn)
        build_layout.addLayout(actions)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.log.setPlaceholderText("Smart Type activity will appear here.")
        build_layout.addWidget(self.log, 1)
        self.tabs.addTab(build_tab, "Website Builder")

        typing_tab = QWidget()
        typing_layout = QVBoxLayout(typing_tab)
        typing_panel = QFrame(objectName="panel")
        tp = QVBoxLayout(typing_panel)
        tp.addWidget(QLabel("Keyboard simulation"))
        note = QLabel(
            "Select a generated file, open it in VS Code, click inside the editor, "
            "then start typing. A 5-second countdown gives you time to focus the editor."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        tp.addWidget(note)
        self.file_combo = QComboBox()
        self.file_combo.currentIndexChanged.connect(self.preview_selected_file)
        tp.addWidget(self.file_combo)
        self.speed_label = QLabel("Typing speed: 40 characters/second")
        tp.addWidget(self.speed_label)
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(5, 300)
        self.speed.setValue(40)
        self.speed.valueChanged.connect(lambda v: self.speed_label.setText(f"Typing speed: {v} characters/second"))
        tp.addWidget(self.speed)
        self.countdown = QCheckBox("Use 5-second focus countdown")
        self.countdown.setChecked(True)
        tp.addWidget(self.countdown)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Choose a generated file to preview its contents.")
        tp.addWidget(self.preview, 1)
        self.type_progress = QProgressBar()
        self.type_progress.setValue(0)
        tp.addWidget(self.type_progress)
        controls = QHBoxLayout()
        self.start_type = QPushButton("Start typing")
        self.start_type.clicked.connect(self.start_typing)
        self.pause_type = QPushButton("Pause")
        self.pause_type.setObjectName("secondary")
        self.pause_type.clicked.connect(self.pause_typing)
        self.resume_type = QPushButton("Resume")
        self.resume_type.setObjectName("secondary")
        self.resume_type.clicked.connect(self.resume_typing)
        self.stop_type = QPushButton("Stop")
        self.stop_type.setObjectName("secondary")
        self.stop_type.clicked.connect(self.stop_typing)
        for button in (self.start_type, self.pause_type, self.resume_type, self.stop_type):
            controls.addWidget(button)
        tp.addLayout(controls)
        typing_layout.addWidget(typing_panel)
        self.tabs.addTab(typing_tab, "Keyboard Typing")

        footer = QLabel("API key stays on this PC. Save key stores it in Windows Credential Manager.")
        footer.setObjectName("muted")
        layout.addWidget(footer)

    def log_message(self, message):
        self.log.appendPlainText(message)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose project folder")
        if folder:
            self.project_dir = Path(folder)
            self.folder_label.setText(str(self.project_dir))

    def save_api_key(self):
        key = self.api_key.text().strip()
        if not key:
            QMessageBox.warning(self, "API key missing", "Paste your Gemini API key first.")
            return
        if not keyring:
            QMessageBox.warning(self, "Secure storage unavailable",
                                "Install the keyring package to save the key securely. "
                                "The key can still be used for this session.")
            return
        try:
            keyring.set_password("SmartType", "GeminiAPI", key)
            self.log_message("Gemini API key saved in the Windows credential store.")
            QMessageBox.information(self, "Saved", "Gemini API key saved securely in Windows Credential Manager.")
        except Exception as exc:
            QMessageBox.critical(self, "Could not save key", str(exc))

    def generate(self):
        key = self.api_key.text().strip()
        brief = self.prompt.toPlainText().strip()
        if not key:
            QMessageBox.warning(self, "Gemini API key required", "Enter your Gemini API key first.")
            return
        if not brief:
            QMessageBox.warning(self, "Website description required", "Describe the website you want to build.")
            return
        if not self.project_dir:
            self.choose_folder()
            if not self.project_dir:
                return
        self.generate_btn.setEnabled(False)
        self.log_message("Starting website generation…")
        self.worker = GenerateWorker(key, brief, self.model.currentText())
        self.worker.status.connect(self.log_message)
        self.worker.failed.connect(self.generation_failed)
        self.worker.finished_project.connect(self.save_project)
        self.worker.start()

    def generation_failed(self, message):
        self.generate_btn.setEnabled(True)
        self.log_message("ERROR: " + message)
        QMessageBox.critical(self, "Generation failed", message)

    def save_project(self, data):
        try:
            files = data["files"]
            written = []
            for item in files:
                rel = safe_relative_path(str(item.get("path", "")))
                content = item.get("content", "")
                if not isinstance(content, str):
                    raise ValueError(f"File content must be text: {rel}")
                target = self.project_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="")
                written.append((str(rel).replace("\\", "/"), content))
            self.project_data = data
            self.generated_files = written
            self.file_combo.clear()
            for name, _ in written:
                self.file_combo.addItem(name)
            self.open_vscode_btn.setEnabled(True)
            self.generate_btn.setEnabled(True)
            self.log_message(f"Created {len(written)} files in {self.project_dir}")
            self.log_message("Project summary: " + str(data.get("summary", "Website generated.")))
            for instruction in data.get("run_instructions", []):
                self.log_message("Run: " + str(instruction))
            if written:
                self.preview.setPlainText(written[0][1])
            QMessageBox.information(self, "Website generated", f"Created {len(written)} files in:\n{self.project_dir}")
        except Exception as exc:
            self.generate_btn.setEnabled(True)
            self.generation_failed(str(exc))

    def open_vscode(self):
        if not self.project_dir:
            return
        try:
            subprocess.Popen(["code", str(self.project_dir)])
            self.log_message("Opened project in Visual Studio Code.")
        except FileNotFoundError:
            QMessageBox.warning(
                self, "VS Code command not found",
                "The 'code' command was not found. In VS Code, enable 'Shell Command: Install code command in PATH', "
                "or launch VS Code manually and open this folder:\n" + str(self.project_dir)
            )

    def preview_selected_file(self, index):
        if 0 <= index < len(self.generated_files):
            self.preview.setPlainText(self.generated_files[index][1])

    def start_typing(self):
        index = self.file_combo.currentIndex()
        if index < 0 or not self.generated_files:
            QMessageBox.warning(self, "No file selected", "Generate a project and select a file first.")
            return
        if self.typing_worker and self.typing_worker.isRunning():
            QMessageBox.warning(self, "Typing in progress", "Stop the current typing session first.")
            return
        text = self.generated_files[index][1]
        if not text:
            return
        answer = QMessageBox.question(
            self, "Confirm keyboard automation",
            "Smart Type will send keystrokes to whichever window has focus. "
            "Open the matching file in VS Code, click inside its editor, then continue.\n\n"
            "Start the 5-second countdown?",
            QMessageBox.Yes | QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return
        self.tabs.setCurrentIndex(1)
        if self.countdown.isChecked():
            for seconds in range(5, 0, -1):
                self.log_message(f"Typing begins in {seconds}…")
                QApplication.processEvents()
                time.sleep(1)
        self.type_progress.setMaximum(len(text))
        self.type_progress.setValue(0)
        self.typing_worker = TypingWorker(text, self.speed.value())
        self.typing_worker.progress.connect(self.update_typing_progress)
        self.typing_worker.status.connect(self.log_message)
        self.typing_worker.failed.connect(lambda e: self.log_message("Typing error: " + e))
        self.typing_worker.done.connect(lambda: self.log_message("Typing session finished."))
        self.typing_worker.start()

    def update_typing_progress(self, current, total):
        self.type_progress.setMaximum(max(1, total))
        self.type_progress.setValue(current)

    def pause_typing(self):
        if self.typing_worker and self.typing_worker.isRunning():
            self.typing_worker.pause()
            self.log_message("Typing paused.")

    def resume_typing(self):
        if self.typing_worker and self.typing_worker.isRunning():
            self.typing_worker.resume()
            self.log_message("Typing resumed.")

    def stop_typing(self):
        if self.typing_worker and self.typing_worker.isRunning():
            self.typing_worker.stop()
            self.log_message("Stopping keyboard automation…")

    def closeEvent(self, event):
        if self.typing_worker and self.typing_worker.isRunning():
            self.typing_worker.stop()
            self.typing_worker.wait(1500)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = SmartTypeWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
