Japanese: [README.ja.md](README.ja.md)

# Step10: Azure Ops Dashboard (GUI app)

> Created: 2026-02-20

A **tkinter GUI app** that reads an existing Azure environment and generates Draw.io diagrams (`.drawio`) plus security/cost reports (`.md` / `.docx` / `.pdf`).

Supports **Japanese / English switching** — UI text, logs, and AI report output language can be toggled with one click.

## Features

### Diagram generation

- Uses Azure Resource Graph (`az graph query`) to inventory resources
- Generates `.drawio` (mxfile XML) for an As-Is diagram
- Two views: `inventory` (overview) / `network` (network topology)
- **Max Nodes note**: collection is best-effort; values above 1000 are clamped to 1000 to match Azure CLI/ARG limits.

### Report generation

- **Security report** — secure score, recommendations, Defender status, risk analysis
- **Cost report** — cost by service/RG, optimization recommendations, Advisor integration
- AI-generated reports via GitHub Copilot SDK
- Docs enrichment (best-effort): Microsoft Learn Search API (`https://learn.microsoft.com/api/search`) + Microsoft Docs MCP (`https://learn.microsoft.com/api/mcp`)
- **Dynamic model selection** — fetches available models and lets you pick one in the UI (default: latest Sonnet)
- Template customization (section ON/OFF + custom instructions)
- Export to Word (.docx) / PDF / **SVG (.drawio.svg)**
- **Diff report** — automatically compares the previous and current report (outputs `*-diff.md`)

### GUI features

- **Language** — Japanese / English (UI text + AI report language)
- **View** — inventory / network / security-report / cost-report
- **Template management** — choose a preset, toggle sections via checkboxes, and save
- **Extra instructions** — load saved instructions + free text input
- **Output folder** — if configured, saves without prompting
- **Open with** — Auto / Draw.io / VS Code / OS default
- **Auto-open** — open the generated file after completion
- **AI review** — review the collected environment and Proceed/Cancel
- **Canvas preview** — simple diagram preview under the logs (pan/zoom)

### Cross-platform

- **Windows** — full support (packaging to .exe supported)
- **macOS** — GUI / az CLI / Copilot SDK / open files (`open`) / detects Draw.io (.app)
- **Linux** — GUI / az CLI / Copilot SDK / open files (`xdg-open`)

## Prerequisites

- Python 3.11+ (for source run; Python is not required when using a packaged .exe)
- Azure CLI (`az`) available in PATH
- Logged in via `az login` (interactive browser)
- Or logged in via Service Principal (if you want to operate with Reader-only permissions)
- ARG extension installed: `az extension add --name resource-graph`

### Prerequisites (when using a packaged .exe)

Even when packaged, **external dependencies (Azure CLI, etc.) are NOT bundled**. You still need:

- Windows 10/11 (x64)
- Azure CLI installed and `az` executable available in PATH
- `az login` completed (or Service Principal login)
- ARG extension installed: `az extension add --name resource-graph`
- At least Reader permissions on the target subscription / resource group

#### Service Principal (example)

If you want to run as a Service Principal with only Reader permissions:

```powershell
az login --service-principal -u <APP_ID> -p <CLIENT_SECRET> --tenant <TENANT_ID>
```

You can also run this from the GUI via the `🔐 SP login` button (the secret is not stored).

#### Collection script

If you want to run and audit collection as explicit Azure CLI commands, you can use:

```powershell
pwsh .\scripts\collect-azure-env.ps1 -SubscriptionId <SUB_ID> -ResourceGroup <RG> -Limit 300 -OutDir <OUTPUT_DIR>
```

Note: the script fails fast if any `az` command returns a non-zero exit code (check the referenced output file path).

- To use AI features (review/report generation):
  - Copilot CLI installed and `copilot auth login` completed (SDK uses Copilot CLI server mode)
  - Or a token set via env vars (e.g., `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`)
  - Network access (proxy/firewall environments may require extra setup)
- To export PDF: Microsoft Word or LibreOffice (must be able to run `soffice`)

### Distribution notes

- If you build with `onedir`, distribute the entire `dist/AzureOpsDashboard/` folder (the exe alone will not work).
- `onefile` produces a single exe, but startup is slower and it can be flagged more easily.

### Updating templates/instructions (without rebuilding the .exe)

Report templates and saved instructions can be **overridden** in the user area.
To apply updates without rebuilding, place JSON files here and restart the app:

| OS      | Path                                     |
| ------- | ---------------------------------------- |
| Windows | `%APPDATA%\AzureOpsDashboard\templates\` |
| macOS   | `~/.AzureOpsDashboard/templates/`        |
| Linux   | `~/.AzureOpsDashboard/templates/`        |

- `security-*.json` / `cost-*.json` (templates)
- `saved-instructions.json` (saved extra instructions)

If the same filename exists, **the user-area file takes precedence**.

Note: changing app behavior (code updates) requires rebuilding/updating the .exe.

## Usage

```powershell
# From the azure-ops-dashboard folder
uv run python .\main.py

# Or from the repo root
uv run python .\azure-ops-dashboard\main.py
```

When the GUI window opens:

1. Choose **Language** (Japanese / English) — you can switch anytime
2. Choose **View** (inventory / network / security-report / cost-report)
3. Enter Subscription / Resource Group (optional)
4. For reports: choose a template → toggle sections → add extra instructions
5. Click **▶ Collect** or **▶ Generate Report**
6. For diagrams: AI review → Proceed → save + auto-open
7. For reports: AI generation → save + auto-open

## Files

| File               | Description                                                        |
| ------------------ | ------------------------------------------------------------------ |
| `main.py`          | Main GUI app (tkinter)                                             |
| `gui_helpers.py`   | Shared GUI constants/utilities (split out from main.py)            |
| `collector.py`     | Azure data collection (az graph query / Security / Cost / Advisor) |
| `drawio_writer.py` | `.drawio` XML generator                                            |
| `ai_reviewer.py`   | AI review/report generation (Copilot SDK)                          |
| `exporter.py`      | Markdown → Word (.docx) / PDF export                               |
| `i18n.py`          | i18n module (JA/EN dictionaries + runtime switch)                  |
| `app_paths.py`     | Resource path abstraction (PyInstaller frozen support)             |
| `docs_enricher.py` | Microsoft Docs MCP integration (reference enrichment)              |
| `tests.py`         | Unit tests (collector / drawio_writer / exporter / gui_helpers)    |
| `templates/`       | Report templates JSON + saved instructions                         |

### Templates

| File                      | Type     | Notes                                 |
| ------------------------- | -------- | ------------------------------------- |
| `security-standard.json`  | Security | All sections enabled (standard)       |
| `security-executive.json` | Security | Executive summary + actions only      |
| `cost-standard.json`      | Cost     | All sections enabled (standard)       |
| `cost-executive.json`     | Cost     | Executive summary + savings proposals |
| `saved-instructions.json` | Common   | Saved extra instructions (5 presets)  |

## Outputs

Generated in the output folder:

- `*.drawio` (Draw.io diagram)
- `*.drawio.svg` (SVG export, optional — requires Draw.io CLI)
- `*.md` (Markdown report)
- `*-diff.md` (diff report — compares with previous run)
- `*.docx` (Word report, optional)
- `*.pdf` (PDF report, optional — requires Word/LibreOffice)
- `env.json` (nodes/edges and azureId→cellId map)
- `collect.log.json` (executed commands + stdout/stderr)

## Design / Survey

- Design (SSOT): `DESIGN.md`
- Technical survey (SSOT): `TECH-SURVEY.md`
- Session logs: `output_sessions/`

## Tests

```powershell
# From the azure-ops-dashboard folder
uv run python -m unittest tests -v
```

Tests can run without Azure CLI / Copilot SDK connectivity (20 tests).

## Packaging (Windows .exe)

You can generate an exe with PyInstaller (Azure CLI `az` must be installed separately).

```powershell
# onedir (recommended: faster startup, fewer issues)
pwsh .\build_exe.ps1 -Mode onedir

# onefile (single exe)
pwsh .\build_exe.ps1 -Mode onefile
```

- Outputs are created under `dist/` (relative to the folder you run the build from).
