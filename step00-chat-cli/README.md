Japanese: [README.ja.md](README.ja.md)

# Step 0: SDK Chat CLI

A chat app to validate the GitHub Copilot SDK (Python).
It runs as a **tray resident app** and shows a popup window on **double-tapping Alt**.
Designed to be reusable as the SDK + GUI foundation for the Voice Agent (Step 3).

## Prerequisites

- Python 3.11+
- `copilot` CLI installed and `copilot auth login` completed
- Windows (system tray + global hotkey)

## Setup

```bash
# From the workspace root
uv venv
uv pip install -e .
```

## Run

```bash
cd step00-chat-cli
uv run python main.py
```

## How to use

1. On startup, a tray icon appears and the app connects to the SDK
2. Double-tap **Alt** → the chat window pops up
3. Type a message and press **Enter** → responses stream in
4. Press **Escape** to hide the window (conversation history is kept)
5. Double-tap Alt again to show the window
6. Right-click the tray icon → Exit to quit

- If SDK connection fails: right-click the tray icon → Reconnect

## Hotkey configuration

Edit `settings.json` to change the hotkey:

Invalid values (type mismatch/out of range) are ignored and defaults are used.

```json
{
  "hotkey_key": "alt",
  "hotkey_interval": 0.35,
  "model": "gpt-4.1"
}
```

| Setting           | Description                            | Default     |
| ----------------- | -------------------------------------- | ----------- |
| `hotkey_key`      | Key to detect as the double-tap hotkey | `"alt"`     |
| `hotkey_interval` | Double-tap detection window (seconds)  | `0.35`      |
| `model`           | AI model to use                        | `"gpt-4.1"` |
| `window_width`    | Window width                           | `500`       |
| `window_height`   | Window height                          | `600`       |
| `font_size`       | Font size                              | `11`        |

## Files

| File                 | Responsibility                                      |
| -------------------- | --------------------------------------------------- |
| `main.py`            | Entry point (thread integration, App class)         |
| `chat_window.py`     | tkinter chat window (streaming output)              |
| `tray_app.py`        | pystray system tray management                      |
| `sdk_client.py`      | CopilotClient wrapper (connection + retry)          |
| `session_manager.py` | Session creation, event subscriptions, send/receive |
| `event_handler.py`   | Event router (callback injection)                   |
| `config.py`          | Config constants + `settings.json` loading          |
| `settings.json`      | User settings (hotkey/model/etc.)                   |
| `DESIGN.md`          | Design docs                                         |

## Extension points for Voice Agent integration

| Module           | What to replace                                                   |
| ---------------- | ----------------------------------------------------------------- |
| `EventHandler`   | Replace `on_delta` to send into a TTS queue                       |
| `SessionManager` | Inject `skill_directories` and `mcpServers` into `session_config` |
| `ChatWindow`     | Add voice input button / hotkey to switch voice mode              |
| `TrayApp`        | Add menu items (skills refresh, settings, logs, etc.)             |
