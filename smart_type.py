import sys, os, time, threading, subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QFileDialog, QLineEdit,
    QSlider, QProgressBar, QPlainTextEdit, QMessageBox, QCheckBox, QGroupBox
)
from pynput.keyboard import Controller


class TypingWorker(QThread):
    progress = Signal(int, int)
    status = Signal(str)
    current_file = Signal(str)
    finished_all = Signal()
    failed = Signal(str)

    def __init__(self, jobs, speed, countdown=True, open_vscode=True):
        super().__init__()
        self.jobs = jobs
        self.speed = max(1, speed)
        self.countdown = countdown
        self.open_vscode = open_vscode
        self._paused = threading.Event()
        self._paused.set()
        self._stopped = threading.Event()
        self.keyboard = Controller()

    def pause(self): self._paused.clear()
    def resume(self): self._paused.set()
    def stop(self):
        self._stopped.set()
        self._paused.set()

    def run(self):
        try:
            total_chars = sum(len(text) for _, _, text in self.jobs)
            completed = 0
            for source, target, content in self.jobs:
                if self._stopped.is_set(): break
                self.current_file.emit(str(target))
                target.parent.mkdir(parents=True, exist_ok=True)
                # Create/open the destination file in VS Code, preserving its relative path.
                if not target.exists():
                    target.touch()
                if self.open_vscode:
                    subprocess.Popen(["code", "--reuse-window", str(target)])
                    time.sleep(2.0)
                    self.status.emit(f"Opened {target.name} in VS Code. Keep the editor focused.")
                if self.countdown:
                    for n in range(3, 0, -1):
                        if self._stopped.is_set(): break
                        self.status.emit(f"Typing {target.name} in {n}…")
                        time.sleep(1)
                if self._stopped.is_set(): break

                # Clear existing destination content before replaying the source file.
                self.keyboard.press('\u0001')  # Ctrl+A
                self.keyboard.release('\u0001')
                time.sleep(0.08)
                self.keyboard.press('\u0008')  # Backspace
                self.keyboard.release('\u0008')
                time.sleep(0.08)

                for char in content:
                    if self._stopped.is_set(): break
                    self._paused.wait()
                    if self._stopped.is_set(): break
                    self.keyboard.type(char)
                    completed += 1
                    self.progress.emit(completed, max(1, total_chars))
                    if char not in "\r\n":
                        time.sleep(1.0 / self.speed)
                if not self._stopped.is_set():
                    self.status.emit(f"Finished typing {target.name}.")
                    time.sleep(0.25)
            self.finished_all.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class SmartTypeEmulator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Type | VS Code File Emulator")
        self.resize(1100, 780)
        self.setMinimumSize(850, 620)
        self.source_root = None
        self.workspace = None
        self.files = []
        self.worker = None
        self._ui()

    def _ui(self):
        self.setStyleSheet("""
          QMainWindow,QWidget{background:#101827;color:#eaf1fb}
          QGroupBox{background:#172338;border:1px solid #30425d;border-radius:10px;margin-top:10px;padding:12px;font-weight:600}
          QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 5px;color:#45c9e8}
          QListWidget,QPlainTextEdit,QLineEdit{background:#0c1524;color:#eaf1fb;border:1px solid #344761;border-radius:7px;padding:8px}
          QPushButton{background:#087fae;color:white;border:0;border-radius:7px;padding:10px 14px;font-weight:600}
          QPushButton:hover{background:#0798c9}
          QPushButton:disabled{background:#3b4b61;color:#9aa9bc}
          QPushButton#secondary{background:#293a55}
          QLabel#muted{color:#9eb0c8}
          QProgressBar{background:#0c1524;border:1px solid #344761;border-radius:6px;text-align:center}
          QProgressBar::chunk{background:#08a6cf;border-radius:5px}
          QSlider::groove:horizontal{height:6px;background:#344761;border-radius:3px}
          QSlider::handle:horizontal{background:#08a6cf;width:16px;margin:-5px 0;border-radius:8px}
        """)
        w = QWidget(); self.setCentralWidget(w)
        layout = QVBoxLayout(w); layout.setContentsMargins(22,18,22,18); layout.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel("SMART TYPE"); title.setStyleSheet("font-size:23px;font-weight:800;color:#31c5e8")
        header.addWidget(title); header.addWidget(QLabel("File-to-VS-Code keyboard emulator")); header.addStretch()
        layout.addLayout(header)

        source_box = QGroupBox("1. Load files to emulate")
        sv = QVBoxLayout(source_box)
        row = QHBoxLayout()
        self.add_files_btn = QPushButton("Add files")
        self.add_files_btn.clicked.connect(self.add_files)
        self.add_folder_btn = QPushButton("Load folder")
        self.add_folder_btn.setObjectName("secondary"); self.add_folder_btn.clicked.connect(self.load_folder)
        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.setObjectName("secondary"); self.remove_btn.clicked.connect(self.remove_selected)
        row.addWidget(self.add_files_btn); row.addWidget(self.add_folder_btn); row.addWidget(self.remove_btn); row.addStretch()
        sv.addLayout(row)
        self.source_label = QLabel("No source files loaded")
        self.source_label.setObjectName("muted"); sv.addWidget(self.source_label)
        self.file_list = QListWidget(); self.file_list.currentRowChanged.connect(self.show_preview)
        self.file_list.setMinimumHeight(145); sv.addWidget(self.file_list)
        layout.addWidget(source_box, 2)

        target_box = QGroupBox("2. Choose the VS Code project folder")
        tv = QHBoxLayout(target_box)
        self.workspace_label = QLabel("No destination workspace selected")
        self.workspace_label.setObjectName("muted")
        choose = QPushButton("Choose workspace folder"); choose.clicked.connect(self.choose_workspace)
        tv.addWidget(self.workspace_label,1); tv.addWidget(choose)
        layout.addWidget(target_box)

        preview_box = QGroupBox("3. Preview selected file")
        pv = QVBoxLayout(preview_box)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True); self.preview.setPlaceholderText("Select a loaded file to preview its contents.")
        self.preview.setMinimumHeight(130); pv.addWidget(self.preview)
        layout.addWidget(preview_box, 2)

        settings = QGroupBox("4. Emulation settings")
        st = QVBoxLayout(settings)
        speedrow = QHBoxLayout()
        self.speed_label = QLabel("Typing speed: 40 characters/second")
        self.speed = QSlider(Qt.Horizontal); self.speed.setRange(1,300); self.speed.setValue(40)
        self.speed.valueChanged.connect(lambda n:self.speed_label.setText(f"Typing speed: {n} characters/second"))
        speedrow.addWidget(self.speed_label); speedrow.addWidget(self.speed,1); st.addLayout(speedrow)
        self.countdown = QCheckBox("3-second countdown before each file"); self.countdown.setChecked(True)
        self.open_code = QCheckBox("Open each destination file in VS Code automatically"); self.open_code.setChecked(True)
        st.addWidget(self.countdown); st.addWidget(self.open_code)
        layout.addWidget(settings)

        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start emulation"); self.start_btn.clicked.connect(self.start)
        self.pause_btn = QPushButton("Pause"); self.pause_btn.setObjectName("secondary"); self.pause_btn.clicked.connect(self.pause)
        self.resume_btn = QPushButton("Resume"); self.resume_btn.setObjectName("secondary"); self.resume_btn.clicked.connect(self.resume)
        self.stop_btn = QPushButton("Stop"); self.stop_btn.setObjectName("secondary"); self.stop_btn.clicked.connect(self.stop)
        for b in (self.start_btn,self.pause_btn,self.resume_btn,self.stop_btn): controls.addWidget(b)
        layout.addLayout(controls)
        self.progress = QProgressBar(); self.progress.setValue(0); layout.addWidget(self.progress)
        self.status = QLabel("Ready. Load files or a folder, choose a workspace, then start.")
        self.status.setObjectName("muted"); layout.addWidget(self.status)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(85); layout.addWidget(self.log)

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to emulate")
        if not paths: return
        for path in paths:
            p=Path(path)
            if p.is_file() and p not in [x[0] for x in self.files]:
                self.files.append((p,p.name))
        self.refresh_files()

    def load_folder(self):
        folder=QFileDialog.getExistingDirectory(self,"Select source folder")
        if not folder:return
        self.source_root=Path(folder)
        found=sorted(p for p in self.source_root.rglob("*") if p.is_file())
        self.files=[(p,str(p.relative_to(self.source_root))) for p in found]
        self.source_label.setText(f"Loaded {len(self.files)} files from {self.source_root}")
        self.refresh_files()

    def refresh_files(self):
        self.file_list.clear()
        for p,rel in self.files:
            item=QListWidgetItem(f"{rel}   ({p.stat().st_size:,} bytes)")
            item.setData(Qt.UserRole,str(p)); self.file_list.addItem(item)
        if not self.source_root:
            self.source_label.setText(f"{len(self.files)} individual files loaded")
        if self.files:self.file_list.setCurrentRow(0)

    def remove_selected(self):
        row=self.file_list.currentRow()
        if row>=0:
            self.files.pop(row); self.refresh_files()

    def show_preview(self,row):
        if 0<=row<len(self.files):
            p,_=self.files[row]
            try:self.preview.setPlainText(p.read_text(encoding="utf-8"))
            except UnicodeDecodeError:self.preview.setPlainText("[Binary or non-UTF-8 file. This emulator supports text files only.]")
            except Exception as e:self.preview.setPlainText(str(e))

    def choose_workspace(self):
        folder=QFileDialog.getExistingDirectory(self,"Choose destination VS Code workspace")
        if folder:
            self.workspace=Path(folder); self.workspace_label.setText(str(self.workspace))

    def start(self):
        if not self.files:
            QMessageBox.warning(self,"No files","Load one or more text files or a source folder first."); return
        if not self.workspace:
            QMessageBox.warning(self,"Workspace required","Choose the destination project folder first."); return
        jobs=[]
        for source,relative in self.files:
            try: content=source.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                self.log.appendPlainText(f"Skipped binary/non-UTF-8 file: {source.name}"); continue
            target=self.workspace / relative
            try: target.resolve().relative_to(self.workspace.resolve())
            except ValueError: continue
            jobs.append((source,target,content))
        if not jobs:
            QMessageBox.warning(self,"No text files","No readable text files were found."); return
        if QMessageBox.question(self,"Confirm emulation",
            f"Smart Type will create/overwrite {len(jobs)} destination files and type their contents using keyboard input.\\n\\n"
            "The keystrokes go to the focused window. Do not use the computer during emulation. Continue?",
            QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes:return
        self.progress.setValue(0)
        self.worker=TypingWorker(jobs,self.speed.value(),self.countdown.isChecked(),self.open_code.isChecked())
        self.worker.status.connect(self.set_status)
        self.worker.current_file.connect(lambda f:self.log.appendPlainText("Emulating: "+f))
        self.worker.progress.connect(self.update_progress)
        self.worker.failed.connect(self.failed)
        self.worker.finished_all.connect(self.finished)
        self.start_btn.setEnabled(False); self.worker.start()

    def set_status(self,s):self.status.setText(s)
    def update_progress(self,n,total):
        self.progress.setMaximum(max(1,total)); self.progress.setValue(n)
    def pause(self):
        if self.worker and self.worker.isRunning():self.worker.pause();self.set_status("Paused")
    def resume(self):
        if self.worker and self.worker.isRunning():self.worker.resume();self.set_status("Resumed")
    def stop(self):
        if self.worker and self.worker.isRunning():self.worker.stop();self.set_status("Stopping…")
    def failed(self,e):
        self.start_btn.setEnabled(True); self.set_status("Error: "+e); QMessageBox.critical(self,"Emulation error",e)
    def finished(self):
        self.start_btn.setEnabled(True); self.set_status("Emulation finished."); self.log.appendPlainText("All queued files processed.")

def main():
    app=QApplication(sys.argv)
    win=SmartTypeEmulator(); win.show()
    sys.exit(app.exec())

if __name__=="__main__":main()
