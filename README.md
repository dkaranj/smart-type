# Smart Type Emulator v2.1

Windows desktop app that loads text files or a folder and replays their contents as keyboard input in VS Code.

## v2.1 fixes
- Responsive, scrollable interface so controls and logs are not clipped on smaller screens.
- Detects VS Code from PATH and common Windows install folders.
- Adds a **Browse Code.exe** control for installations in custom locations.
- Replaces the previous unreliable control-character shortcuts with explicit Ctrl+A and Backspace key events.
- Adds a five-second focus countdown. Click inside the VS Code editor during the countdown.

## Build with GitHub Actions
1. Extract this ZIP.
2. Upload the contents of `SmartType-Emulator` to the root of your `dkaranj/smart-type` repository, replacing the old files.
3. Commit to `main`.
4. Open **Actions → Build Smart Type Emulator → Run workflow**.
5. Download the `SmartType-Windows` artifact and extract `SmartType.exe`.

## Local run
```powershell
py -m pip install -r requirements.txt
py smart_type.py
```

## Important
Smart Type sends keystrokes to whichever window has focus. During each countdown, click inside the intended VS Code editor. Do not use the computer while replay is running. Destination files can be overwritten.
