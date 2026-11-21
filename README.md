# Smart Type

Smart Type is a Windows desktop MVP for generating website projects with Google's Gemini API, saving generated files into a folder you choose, opening that folder in Visual Studio Code, and optionally simulating keyboard typing into the focused editor.

## Features

- Gemini website generation using Google's current Interactions API through the official `google-genai` SDK
- Choose any local project folder
- Writes generated files and creates nested directories
- Opens the selected project in VS Code using the `code` command
- Keyboard typing mode with adjustable speed (5–300 characters/second)
- Pause, resume, stop and progress display
- Windows EXE build through GitHub Actions

## Run from source

1. Install Python 3.10 or newer.
2. Open a terminal in this folder.
3. Run `py -m pip install -r requirements.txt`.
4. Run `py smart_type.py`.
5. Paste your Gemini API key into the app.

Get an API key from https://aistudio.google.com/app/apikey.

## Build the EXE locally

```powershell
py -m pip install -r requirements.txt
py -m PyInstaller --noconfirm --clean --onefile --windowed --name SmartType --collect-all google.genai --collect-all pynput smart_type.py
```

The executable will be at `dist\SmartType.exe`.

## Build with GitHub Actions

Upload the contents of this folder to the root of your GitHub repository, including the hidden `.github` folder. Open **Actions → Build Smart Type for Windows → Run workflow**. Download the `SmartType-Windows` artifact after the run succeeds.

To create a GitHub Release, push a tag such as `v1.0.0`.

## Keyboard typing safety

Keyboard simulation sends keystrokes to whichever application currently has focus. Before starting, open the matching generated file in VS Code and click inside its editor. The app asks for confirmation and provides a five-second countdown. Test with an empty or disposable file first. The Stop button ends the typing worker.

## Notes and current limitations

- This is an initial working MVP, not a reverse-engineered copy of Bona.Bot.
- Gemini output is parsed as JSON and written as text files. Very large projects may need a follow-up generation workflow.
- VS Code must be installed, and its `code` command must be available on PATH. Otherwise open the selected folder manually.
- The API key can be saved in Windows Credential Manager using the Save key button.
- Generated project files are written directly into the selected folder. Choose a dedicated folder to avoid overwriting existing work.
- Keyboard automation is optional. Direct file writing is the reliable default.

## v1.1 fixes

- Updated model choices to `gemini-3.8-flash` and `gemini-3.1-pro-preview`.
- Switched generation requests to Google's Interactions API.
- Added a scrollable main window and larger default dimensions to prevent clipped controls.
- Added optional secure API-key storage through Windows Credential Manager (`keyring`).

## v1.2 generation responsiveness fix

- Gemini generation now streams response text into the worker instead of waiting silently for the full response.
- The activity log reports response progress as text arrives.
- A 180-second request timeout turns stalled calls into a visible error instead of an indefinite wait.

## v1.3 Gemini streaming compatibility update

- Uses the standard Gemini `generateContent` streaming endpoint (`generate_content_stream`) rather than the Interactions API.
- Reads streamed text from each chunk's `.text` field.
- Keeps a 180-second HTTP timeout and progress updates while text arrives.
- Recommended when the app only needs one-shot website/project generation rather than persistent multi-turn interactions.
