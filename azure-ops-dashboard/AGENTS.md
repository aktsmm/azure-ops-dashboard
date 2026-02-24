# AGENTS.md — Azure Ops Dashboard

> Custom instructions for AI coding agents working with this repository.

## Project Overview

Azure Ops Dashboard is a **tkinter desktop application** that reads a live Azure
environment and generates Draw.io architecture diagrams plus AI-powered
security/cost reports using the **GitHub Copilot SDK**.

## Architecture

```
main.py            ← GUI entry point (tkinter, threading)
├── collector.py   ← Azure data collection (az graph query, Security Center, Cost Mgmt, Advisor)
├── drawio_writer.py ← .drawio XML generation (deterministic layout, Azure icons)
├── ai_reviewer.py ← Copilot SDK integration (review, report gen, streaming)
│   └── docs_enricher.py ← Microsoft Learn Search API enrichment
├── exporter.py    ← Markdown → Word (.docx) / PDF / diff report
├── gui_helpers.py ← Shared GUI constants and utilities
├── i18n.py        ← Japanese/English runtime switching
└── app_paths.py   ← Resource path abstraction (PyInstaller + user override)
```

## Key Design Decisions

### Threading Model

- GUI runs on the main thread (tkinter requirement)
- AI/Azure operations run in background threads via `threading.Thread`
- Communication: atomic buffer swap (attribute rebinding) polled at 100ms intervals
- **Never call `StringVar.get()` from a background thread** — capture all GUI values before spawning

### Copilot SDK Usage

- `CopilotClient` → `create_session()` → streaming `send()` with token callbacks
- Dynamic model selection: prefer latest `claude-sonnet-*`, fallback `gpt-4.1`
- Read-only tool permissions only (`_ALLOWED_TOOLS` frozenset in ai_reviewer.py)
- Microsoft Docs MCP server connected for document-grounded reports
- Retry with exponential backoff (max 2 retries)
- `future.cancel()` on timeout to prevent coroutine leaks

### Resource Paths

- All resource references go through `app_paths.py`
- PyInstaller frozen: falls back to `sys._MEIPASS`
- User override: `%APPDATA%\AzureOpsDashboard\templates\` takes precedence

### Data Safety

- **Read-only Azure operations only** — no create/update/delete
- Requires at minimum Reader role
- Service Principal secret is never stored (entered per-session via GUI)
- No API keys or secrets are hardcoded anywhere

## Coding Conventions

- Python 3.11+, type hints throughout
- `from __future__ import annotations` in every module
- Frozen dataclasses for data models (`Node`, `Edge`, `DocReference`)
- i18n: use `t("key")` from `i18n.py` — never hardcode UI strings
- Tests: `python -m unittest tests -v` (39 tests, no Azure/SDK connectivity needed)

## Common Tasks

### Running

```powershell
uv venv && uv pip install -e ".[ai]"
uv run python main.py
```

### Testing

```powershell
uv run python -m unittest tests -v
```

### Building .exe

```powershell
pwsh .\build_exe.ps1 -Mode onedir
```

### Adding a new report template

1. Create `templates/<type>-<name>.json` following existing schema
2. The template will be auto-discovered by `list_templates()`
3. User overrides go in `%APPDATA%\AzureOpsDashboard\templates\`
