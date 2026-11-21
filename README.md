# Smart Type Emulator

A Windows desktop app that loads existing text files or recursively imports a source folder, chooses a destination workspace, opens destination files in Visual Studio Code, and replays each file's contents using simulated keyboard input.

## Workflow
1. **Add files** to choose individual text files, or **Load folder** to import all files recursively.
2. Choose the destination VS Code workspace folder.
3. Preview the files and set typing speed (1–300 characters/second).
4. Start emulation. Smart Type creates destination files, opens them in VS Code, and types their contents.
5. Pause, resume, or stop the queue.

## Build
Upload the contents of this folder to the root of your GitHub repository, including `.github/workflows/build-windows.yml`. Run **Actions → Build Smart Type Emulator** and download the `SmartType-Windows` artifact.

Local run:
```powershell
py -m pip install -r requirements.txt
py smart_type.py
```

## Requirements and safety
- Windows, Python 3.10+ if running from source, Visual Studio Code installed.
- The `code` command must be available on PATH. If not, disable automatic opening and open the destination workspace manually.
- Only UTF-8 text files are supported. Binary files are skipped.
- The destination files are created/overwritten. Choose a dedicated workspace folder.
- Keyboard simulation sends keystrokes to the currently focused window. Keep VS Code focused and do not use the computer during emulation. Test on disposable files first.
- This is a file replay tool. It does not call Gemini or generate new website code.
