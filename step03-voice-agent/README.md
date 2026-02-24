Japanese: [README.ja.md](README.ja.md)

# Step 03: Voice-first Enterprise Copilot (Main)

This is the main project that integrates Step00 (SDK Chat + tray app), Step01 (Env Builder), and Step02 (Dictation).

## References

- Overall design: [../docs/design.md](../docs/design.md)
- SDK prerequisites / security: [../docs/tech-reference.md](../docs/tech-reference.md)
- Progress / remaining tasks: [../DASHBOARD.md](../DASHBOARD.md)

## Current status

- `src/` is still at the skeleton stage (integration is next)
- Until implementation progresses, validate by running Step00/01/02 independently

## Setup (common)

From the workspace root:

```powershell
uv venv
uv pip install -e .
```

## Planned layout

- `src/app.py`: tray/hotkey resident app + mode switching (dictation / agent)
- `src/sdk/`: Copilot SDK wrappers (port/integrate from Step00)
- `src/speech/`: Azure Speech STT/TTS (port/integrate from Step02)
- `src/skills/`: skills sync + inject `skill_directories`
- `src/tools/`: onPreToolUse (allow/deny/confirm)
