import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QThread, Signal, Qt
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSlider,
    QTextEdit, QVBoxLayout, QWidget
)

APP_NAME = "Smart Type"
ORG_NAME = "EazyRadius"
MODELS = ["gemini-2.5-flash", "gemini-2.5-pro"]


def get_keyring():
    import keyring
    return keyring


def load_api_key():
    try:
        return get_keyring().get_password("SmartType", "gemini_api_key") or ""
    except Exception:
        return ""


def save_api_key(value):
    if not value.strip():
        raise ValueError("Enter an API key first.")
    get_keyring().set_password("SmartType", "gemini_api_key", value.strip())


def find_vscode():
    code = shutil.which("code")
    if code:
        return code
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Microsoft VS Code/Code.exe",
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Microsoft VS Code/Code.exe",
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft VS Code/Code.exe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


def parse_generated_files(raw):
    text = raw.strip()
    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise ValueError("Gemini response must be JSON containing a 'files' array.")

    files = []
    seen = set()
    for item in data["files"]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("path", "")).replace("\\", "/").strip()
        content = item.get("content", "")
        if not name or not isinstance(content, str):
            continue
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", name):
            raise ValueError("Gemini returned an unsafe file path: " + name)
        if name in seen:
            raise ValueError("Gemini returned a duplicate file path: " + name)
        if len(content) > 500_000:
            raise ValueError("Generated file is too large: " + name)
        seen.add(name)
        files.append((name, content))

    if not files:
        raise ValueError("Gemini did not return any usable files.")
    if len(files) > 40:
        raise ValueError("Gemini returned more than 40 files. Try a smaller website request.")
    return files


class GenerateWorker(QObject):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, api_key, model, prompt):
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.prompt = prompt

    def run(self):
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            instruction = (
                "You are an expert web developer. Create a complete, responsive, runnable website "
                "from the specification. Return ONLY valid JSON, without markdown fences, in this "
                "exact structure: {\"files\":[{\"path\":\"relative/path\",\"content\":\"full file contents\"}]}. "
                "Include all required code, assets as text files where practical, package/config files, "
                "and README.md with run instructions. Do not include secrets, API keys, absolute paths, "
                "or parent-directory paths. Keep the project self-contained."
            )
            response = client.models.generate_content(
                model=self.model,
                contents=instruction + "\n\nWEBSITE SPECIFICATION:\n" + self.prompt,
            )
            if not response.text:
                raise RuntimeError("Gemini returned an empty response.")
            self.succeeded.emit(parse_generated_files(response.text))
        except Exception as exc:
            self.failed.emit(str(exc))


class TypingWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, project_folder, files, characters_per_second):
        super().__init__()
        self.project_folder = Path(project_folder)
        self.files = files
        self.delay = 1.0 / max(1, characters_per_second)
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            from pynput.keyboard import Controller, Key
            keyboard = Controller()
            vscode = find_vscode()
            if not vscode:
                raise RuntimeError(
                    "Visual Studio Code was not found. Install VS Code and make sure its 'code' command is available."
                )

            total = sum(max(1, len(content)) for _, content in self.files)
            typed = 0

            for index, (relative_path, content) in enumerate(self.files, start=1):
                if self.stop_event.is_set():
                    self.finished.emit(False, "Typing was stopped.")
                    return

                target = self.project_folder / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch(exist_ok=True)

                # Open the target file in VS Code. The short delay allows the editor to focus.
                subprocess.Popen([vscode, "--reuse-window", str(target)])
                time.sleep(1.8)

                # Select the editor contents before entering the generated file.
                with keyboard.pressed(Key.ctrl):
                    keyboard.press("a")
                    keyboard.release("a")
                time.sleep(0.15)

                for character in content:
                    if self.stop_event.is_set():
                        self.finished.emit(
                            False,
                            "Typing was stopped. The current file may be incomplete; review it in VS Code."
                        )
                        return
                    keyboard.type(character)
                    if self.delay > 0.001:
                        time.sleep(self.delay)
                    typed += 1
                    if typed % 100 == 0:
                        percent = int(typed * 100 / max(total, 1))
                        self.progress.emit(percent, "Typing " + relative_path)

                with keyboard.pressed(Key.ctrl):
                    keyboard.press("s")
                    keyboard.release("s")

                percent = int(typed * 100 / max(total, 1))
                self.progress.emit(percent, "Saved " + relative_path + " (" + str(index) + "/" + str(len(self.files)) + ")")

            self.finished.emit(True, "All generated files have been typed and saved in Visual Studio Code.")
        except Exception as exc:
            self.finished.emit(False, str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Type | Gemini Website Builder")
        self.setMinimumSize(960, 720)
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.generated_files = []
        self.generate_thread = None
        self.type_thread = None
        self.type_worker = None
        self._build_ui()
        self.folder_edit.setText(self.settings.value("project_folder", ""))
        self.api_key_edit.setText(load_api_key())

    def _build_ui(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #0b1220; color: #e5edf8; font-family: Segoe UI; }
            QFrame#panel { background: #111c2e; border: 1px solid #26364d; border-radius: 12px; }
            QLabel#muted { color: #8fa3bd; }
            QLineEdit, QTextEdit, QComboBox { background: #08101d; border: 1px solid #30435e; border-radius: 8px; padding: 10px; color: #eef5ff; }
            QPushButton { background: #087eaa; border: 0; border-radius: 8px; padding: 11px 16px; color: white; font-weight: 600; }
            QPushButton:hover { background: #0b9acb; }
            QPushButton:disabled { background: #334155; color: #94a3b8; }
            QPushButton#secondary { background: #26364d; }
            QPushButton#danger { background: #9f3545; }
            QSlider::groove:horizontal { height: 6px; background: #26364d; border-radius: 3px; }
            QSlider::handle:horizontal { background: #20b8df; width: 16px; margin: -5px 0; border-radius: 8px; }
            QProgressBar { background: #08101d; border: 1px solid #30435e; border-radius: 6px; text-align: center; height: 18px; }
            QProgressBar::chunk { background: #08a5c9; border-radius: 5px; }
        """)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(13)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        title = QLabel("SMART TYPE")
        title.setStyleSheet("font-size: 27px; font-weight: 800; letter-spacing: 2px; color: #32c5e8;")
        subtitle = QLabel("Gemini-powered website builder • Windows desktop")
        subtitle.setObjectName("muted")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch()
        self.status = QLabel("● Ready")
        self.status.setStyleSheet("color: #5bd6a3; font-weight: 700;")
        header.addWidget(self.status)
        layout.addLayout(header)

        key_panel = QFrame()
        key_panel.setObjectName("panel")
        key_layout = QVBoxLayout(key_panel)
        key_layout.addWidget(QLabel("GEMINI API KEY"))
        key_row = QHBoxLayout()
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Paste your Gemini API key")
        save_key = QPushButton("Save key")
        save_key.setObjectName("secondary")
        save_key.clicked.connect(self.save_key)
        key_row.addWidget(self.api_key_edit, 1)
        key_row.addWidget(save_key)
        key_layout.addLayout(key_row)
        self.model = __import__("PySide6.QtWidgets", fromlist=["QComboBox"]).QComboBox()
        self.model.addItems(MODELS)
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Gemini model"))
        model_row.addWidget(self.model)
        model_row.addStretch()
        key_layout.addLayout(model_row)
        layout.addWidget(key_panel)

        folder_panel = QFrame()
        folder_panel.setObjectName("panel")
        folder_layout = QVBoxLayout(folder_panel)
        folder_layout.addWidget(QLabel("PROJECT FOLDER"))
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Choose where the website project should live")
        browse = QPushButton("Browse folder")
        browse.setObjectName("secondary")
        browse.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse)
        folder_layout.addLayout(folder_row)
        layout.addWidget(folder_panel)

        prompt_panel = QFrame()
        prompt_panel.setObjectName("panel")
        prompt_layout = QVBoxLayout(prompt_panel)
        prompt_layout.addWidget(QLabel("DESCRIBE THE WEBSITE YOU WANT"))
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setMinimumHeight(150)
        self.prompt_edit.setPlaceholderText(
            "Example: Build a modern ISP website with a homepage, internet packages, customer login, "
            "coverage checker, contact form and responsive mobile layout..."
        )
        prompt_layout.addWidget(self.prompt_edit)
        layout.addWidget(prompt_panel, 1)

        speed_panel = QFrame()
        speed_panel.setObjectName("panel")
        speed_layout = QVBoxLayout(speed_panel)
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("KEYBOARD TYPING SPEED"))
        speed_row.addStretch()
        self.speed_label = QLabel("80 characters/sec")
        self.speed_label.setStyleSheet("color: #32c5e8; font-weight: 700;")
        speed_row.addWidget(self.speed_label)
        speed_layout.addLayout(speed_row)
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(5, 300)
        self.speed_slider.setValue(80)
        self.speed_slider.valueChanged.connect(
            lambda value: self.speed_label.setText(str(value) + " characters/sec")
        )
        speed_layout.addWidget(self.speed_slider)
        hint = QLabel("5 = slow typing • 300 = very fast typing. Keep VS Code focused during automation.")
        hint.setObjectName("muted")
        speed_layout.addWidget(hint)
        layout.addWidget(speed_panel)

        buttons = QHBoxLayout()
        self.generate_button = QPushButton("✦  Generate website")
        self.generate_button.clicked.connect(self.generate_website)
        self.type_button = QPushButton("⌨  Type into VS Code")
        self.type_button.setObjectName("secondary")
        self.type_button.setEnabled(False)
        self.type_button.clicked.connect(self.start_typing)
        self.stop_button = QPushButton("Stop typing")
        self.stop_button.setObjectName("danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_typing)
        buttons.addWidget(self.generate_button)
        buttons.addWidget(self.type_button)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.setPlaceholderText("Activity log...")
        layout.addWidget(self.log)

        footer = QLabel(
            "Smart Type does not execute generated terminal commands. Review generated code before running it. "
            "Use a new or empty folder for your first test."
        )
        footer.setObjectName("muted")
        footer.setWordWrap(True)
        layout.addWidget(footer)

    def log_message(self, message):
        self.log.append(message)

    def save_key(self):
        try:
            save_api_key(self.api_key_edit.text())
            self.log_message("Gemini API key saved in the Windows credential store.")
            QMessageBox.information(self, "Saved", "Your Gemini API key has been saved securely.")
        except Exception as exc:
            QMessageBox.critical(self, "Could not save key", str(exc))

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose website project folder",
            self.folder_edit.text() or str(Path.home() / "Desktop")
        )
        if folder:
            self.folder_edit.setText(folder)
            self.settings.setValue("project_folder", folder)

    def generate_website(self):
        api_key = self.api_key_edit.text().strip()
        prompt = self.prompt_edit.toPlainText().strip()
        folder = self.folder_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, "API key required", "Enter your Gemini API key first.")
            return
        if not prompt:
            QMessageBox.warning(self, "Description required", "Describe the website you want.")
            return
        if not folder:
            QMessageBox.warning(self, "Folder required", "Choose a project folder.")
            return

        self.settings.setValue("project_folder", folder)
        self.generate_button.setEnabled(False)
        self.type_button.setEnabled(False)
        self.status.setText("● Generating with Gemini...")
        self.log_message("Sending your website description to Gemini...")

        self.generate_thread = QThread()
        self.generate_worker = GenerateWorker(api_key, self.model.currentText(), prompt)
        self.generate_worker.moveToThread(self.generate_thread)
        self.generate_thread.started.connect(self.generate_worker.run)
        self.generate_worker.succeeded.connect(self.generated)
        self.generate_worker.failed.connect(self.generation_failed)
        self.generate_worker.succeeded.connect(self.generate_thread.quit)
        self.generate_worker.failed.connect(self.generate_thread.quit)
        self.generate_thread.finished.connect(self.generate_thread.deleteLater)
        self.generate_thread.start()

    def generated(self, files):
        self.generated_files = files
        self.generate_button.setEnabled(True)
        self.type_button.setEnabled(True)
        self.progress.setValue(0)
        self.status.setText("● " + str(len(files)) + " files generated")
        self.log_message("Gemini generated these files:")
        for name, content in files:
            self.log_message(" • " + name + " (" + format(len(content), ",") + " characters)")
        QMessageBox.information(
            self, "Website generated",
            str(len(files)) + " files generated. Review the list in the activity log, then click Type into VS Code."
        )

    def generation_failed(self, error):
        self.generate_button.setEnabled(True)
        self.status.setText("● Generation failed")
        self.log_message("ERROR: " + error)
        QMessageBox.critical(self, "Gemini error", error)

    def start_typing(self):
        folder = self.folder_edit.text().strip()
        if not self.generated_files or not folder:
            return
        names = "\n".join("• " + name for name, _ in self.generated_files)
        answer = QMessageBox.question(
            self, "Confirm keyboard automation",
            "Smart Type will open each generated file in VS Code and type its contents using simulated keyboard input.\n\n"
            + names + "\n\nUse a new/empty project folder. Keep VS Code focused and do not switch windows. Start?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        Path(folder).mkdir(parents=True, exist_ok=True)
        self.generate_button.setEnabled(False)
        self.type_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status.setText("● Typing into VS Code...")
        self.log_message("Keyboard automation started. Keep VS Code focused.")

        self.type_thread = QThread()
        self.type_worker = TypingWorker(folder, self.generated_files, self.speed_slider.value())
        self.type_worker.moveToThread(self.type_thread)
        self.type_thread.started.connect(self.type_worker.run)
        self.type_worker.progress.connect(self.typing_progress)
        self.type_worker.finished.connect(self.typing_finished)
        self.type_worker.finished.connect(self.type_thread.quit)
        self.type_thread.finished.connect(self.type_thread.deleteLater)
        self.type_thread.start()

    def typing_progress(self, value, message):
        self.progress.setValue(value)
        self.log_message(message)

    def stop_typing(self):
        if self.type_worker:
            self.type_worker.stop()
            self.stop_button.setEnabled(False)
            self.log_message("Stop requested...")

    def typing_finished(self, success, message):
        self.generate_button.setEnabled(True)
        self.type_button.setEnabled(bool(self.generated_files))
        self.stop_button.setEnabled(False)
        self.status.setText("● Complete" if success else "● Stopped / error")
        self.log_message(message)
        if success:
            self.progress.setValue(100)
            QMessageBox.information(self, "Smart Type", message)
        else:
            QMessageBox.warning(self, "Smart Type", message)


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
