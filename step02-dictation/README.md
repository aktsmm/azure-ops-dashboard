Japanese: [README.ja.md](README.ja.md)

# Step 02: Dictation Tool

Types speech into the **active window** using Azure Speech STT + `pyautogui`.
(This does not use the Copilot SDK; it is a speech-layer prototype for Voice Agent integration.)

## Prerequisites

- Windows
- Python 3.11+
- `uv` available
- Environment variables:
  - `AZURE_SPEECH_KEY`
  - `AZURE_SPEECH_REGION`

Note: recognition language is currently fixed to `ja-JP` (see [main.py](main.py)).

## Setup (common)

From the workspace root:

```powershell
uv venv
uv pip install -e .
```

## Run

```powershell
cd .\step02-dictation
uv run python .\main.py
```

## Stop

- `Ctrl+C`

## Notes

- Input goes to the currently focused window (it may type into an unintended place).
