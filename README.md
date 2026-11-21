# Smart Type

Smart Type is a Windows desktop website builder. Describe a website, ask Gemini to generate its project files, choose a local folder, then use simulated keyboard input to type the generated code into Visual Studio Code at a speed you control.

## Features

- Gemini integration using Google's official `google-genai` SDK.
- Dark desktop interface built with PySide6.
- Choose a local project folder.
- Generate a multi-file website project.
- Open generated files in VS Code and type them using simulated keyboard input.
- Adjustable speed from 5 to 300 characters per second.
- Stop control, progress bar and activity log.
- API key stored locally using the operating system credential store through `keyring`.

## Requirements

- Windows 10/11, 64-bit.
- Visual Studio Code installed.
- Gemini API key from https://aistudio.google.com/apikey.
- Python 3.10+ to run from source.

## Run from source (PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python smart_type.py
```

## Build locally

```powershell
pyinstaller --noconfirm --clean --onefile --windowed --name SmartType --collect-all google.genai --collect-all keyring smart_type.py
```

The executable will be at `dist\SmartType.exe`.

## Build using GitHub Actions

1. Upload the contents of this folder to your GitHub repository `dkaranj/smart-type`.
2. Open the repository's **Actions** tab.
3. Select **Build Smart Type for Windows** and click **Run workflow**.
4. When complete, open the workflow run and download the `SmartType-Windows` artifact.
5. To publish a GitHub Release, push a version tag such as `v0.1.0`.

## Usage

1. Launch SmartType.exe.
2. Paste your Gemini API key and click **Save key**.
3. Choose a project folder.
4. Describe your website and click **Generate website**.
5. Review the generated file list in the activity log.
6. Click **Type into VS Code** and confirm the automation prompt.
7. Keep VS Code focused until typing finishes. Use **Stop typing** to interrupt.

## Safety

- Smart Type does not execute generated terminal commands.
- Review generated code before running it.
- Keyboard automation sends keystrokes to the currently focused application. Do not switch windows while typing.
- Use a new or empty project folder for your first test. Files with matching names may be overwritten.
- Keep your Gemini API key private. It is stored locally and is not committed to GitHub.

Version 0.1.0 - Initial MVP.
