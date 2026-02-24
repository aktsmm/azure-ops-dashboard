Japanese: [README.ja.md](README.ja.md)

# Azure Ops Dashboard

[![GitHub](https://img.shields.io/badge/repo-aktsmm%2Fazure--ops--dashboard-blue?logo=github)](https://github.com/aktsmm/azure-ops-dashboard)

> **Problem**: Enterprise IT operations teams waste hours switching between Azure Portal, CLI, and documentation tools to visualize environments, assess security posture, and track costs. Architecture diagrams go stale, and manual report creation is error-prone.
>
> **Solution**: Azure Ops Dashboard reads a live Azure environment and produces **architecture diagrams + AI-powered security/cost reports** in one click — powered by the **GitHub Copilot SDK**.

A **tkinter GUI desktop app** that connects to Azure Resource Graph, generates Draw.io diagrams (`.drawio`), and streams AI analysis reports (`.md` / `.docx` / `.pdf`) enriched with Microsoft Learn documentation.

Supports **Japanese / English runtime switching** — UI text, logs, and AI report output language can be toggled with one click.

## Demo

| GUI                                              | Cost Report                                           |
| ------------------------------------------------ | ----------------------------------------------------- |
| ![GUI Screenshot](docs/media/screenshot-gui.png) | ![Cost Report](docs/media/screenshot-cost-report.png) |

**Demo video** (3 min): provided separately (not stored in this repository)

## Download

| Artifact                                    | Link                                                                          |
| ------------------------------------------- | ----------------------------------------------------------------------------- |
| Windows x64 — pre-built `.exe` (onedir zip) | [**Releases page →**](https://github.com/aktsmm/azure-ops-dashboard/releases) |

> **Quick start (no Python required)**
>
> 1. Download `AzureOpsDashboard-vX.X.X-win-x64.zip` from the Releases page.
> 2. Unzip the archive — keep the folder structure intact.
> 3. Double-click **`AzureOpsDashboard.exe`** inside the unzipped folder.
>
> External tools (Azure CLI, etc.) are NOT bundled — see [Prerequisites (exe)](#prerequisites-when-using-a-packaged-exe).

### Architecture

See the full architecture diagram: [docs/architecture.drawio](docs/architecture.drawio)

```
User → tkinter GUI (src/azure_ops_dashboard/main.py)
         ├─→ collector.py ──→ Azure CLI (Resource Graph / Security / Cost / Advisor)
         ├─→ ai_reviewer.py ──→ GitHub Copilot SDK (streaming report generation)
         │     └─ docs_enricher.py ──→ Microsoft Learn Search API / MCP
         ├─→ drawio_writer.py ──→ .drawio (inventory / network diagrams)
         └─→ exporter.py ──→ .docx / .pdf / -diff.md
```

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
- - Note: Draw.io is used only for `.drawio` / `.drawio.svg`. Reports (`.md` / `.json`) open in VS Code (Windows falls back to Notepad).
- **Auto-open** — open the generated file after completion
- **AI review** — review the collected environment and Proceed/Cancel
- **Canvas preview** — simple diagram preview under the logs (pan/zoom)

### Cross-platform

- **Windows** — full support (packaging to .exe supported)
- **macOS** — GUI / az CLI / Copilot SDK / open files (`open`) / detects Draw.io (.app)
- **Linux** — GUI / az CLI / Copilot SDK / open files (`xdg-open`)

## Prerequisites

- Python 3.11+ (for source run; Python is not required when using a packaged .exe)
- [uv](https://docs.astral.sh/uv/) (for dependency management / running from source)
- Azure CLI (`az`) available in PATH
- Logged in via `az login` (interactive browser)
- Or logged in via Service Principal (if you want to operate with Reader-only permissions)
- ARG extension installed: `az extension add --name resource-graph`

### AI features (review / report generation)

- GitHub Copilot SDK (`uv pip install github-copilot-sdk` or `uv pip install -e ".[ai]"`)
- Copilot CLI installed and `copilot auth login` completed (SDK uses Copilot CLI server mode)
- Or a token set via env vars (e.g., `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`)
- Network access (proxy/firewall environments may require extra setup)

### Export (optional)

- **Word (.docx)**: included via `python-docx` (installed automatically)
- **PDF**: Microsoft Word (Windows, via COM/comtypes) or LibreOffice (`soffice` command, any OS)
  - Windows PDF also needs `uv pip install comtypes` if not already installed
- **SVG (.drawio.svg)**: Draw.io desktop app installed (used as CLI for SVG export)

### Permissions

- At least **Reader** on the target subscription / resource group (for diagram generation)
- **Security Reader** for Security Center data (secure score, recommendations)
- **Cost Management Reader** for cost/billing data
- **Advisor Reader** (or Reader) for Azure Advisor recommendations

### Prerequisites (when using a packaged .exe)

Even when packaged, **external dependencies (Azure CLI, etc.) are NOT bundled**. You still need:

- Windows 10/11 (x64)
- Azure CLI installed and `az` executable available in PATH
- `az login` completed (or Service Principal login)
- ARG extension installed: `az extension add --name resource-graph`
- At least Reader permissions on the target subscription / resource group (see [Permissions](#permissions) above for Security/Cost)

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

## Deployment

### Option A — Pre-built .exe (Windows, no Python required)

1. Download `AzureOpsDashboard-vX.X.X-win-x64.zip` from the [Releases page](https://github.com/aktsmm/azure-ops-dashboard/releases).
2. Unzip the archive — keep the folder structure intact.
3. Install [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) and ensure `az` is in your PATH.
4. Install the Resource Graph extension: `az extension add --name resource-graph`
5. Log in: `az login` (interactive) or `az login --service-principal` (see [Service Principal](#service-principal-example)).
6. Double-click **`AzureOpsDashboard.exe`** inside the unzipped folder.

### Option B — Run from source (any OS)

```powershell
# 1. Clone the repo
git clone https://github.com/aktsmm/azure-ops-dashboard.git
cd azure-ops-dashboard

# 2. Create a virtual environment and install dependencies
uv venv
uv pip install -e .

# 3. (Optional) Install AI features — review / report generation
uv pip install -e ".[ai]"

# 4. Authenticate with Azure CLI
az login
az extension add --name resource-graph

# 5. Authenticate with GitHub Copilot (for AI features)
copilot auth login

# 6. Run
uv run python src/app.py
```

Alternative entry point (exists under `/src` for submission requirements):

```powershell
python src/app.py
```

> **⚠ Windows PATH note**: If `uv` has installed a global Python in `~/.local/bin/`, that binary may take priority over `.venv\Scripts\python.exe` even after running `Activate.ps1`. In that case, use an **explicit path** to the venv Python:
>
> ```powershell
> .venv\Scripts\python.exe src\app.py
> ```
>
> You can verify which Python is active with `python -c "import sys; print(sys.executable)"`.
> If it does NOT point to `.venv\Scripts\python.exe`, the Copilot SDK and other venv-installed packages will not be found.

### Option C — Build your own .exe

```powershell
uv venv
uv pip install -e ".[ai]"
pwsh .\build_exe.ps1            # onedir (default)
# or: pwsh .\build_exe.ps1 -Mode onefile
```

Output is created under `dist/`. Distribute the entire `dist/AzureOpsDashboard/` folder (for onedir) or the single exe (for onefile).

---

## Usage

When the GUI window opens:

1. Choose **Language** (Japanese / English) — you can switch anytime
2. Choose **View** (inventory / network / security-report / cost-report)
3. Enter Subscription / Resource Group (optional)
4. For reports: choose a template → toggle sections → add extra instructions
5. Click **▶ Collect** or **▶ Generate Report**
6. For diagrams: AI review → Proceed → save + auto-open
7. For reports: AI generation → save + auto-open

## Files

| File                                         | Description                                                            |
| -------------------------------------------- | ---------------------------------------------------------------------- |
| `src/app.py`                                 | Entry point under `/src` (submission requirement)                      |
| `src/azure_ops_dashboard/main.py`            | Main GUI app (tkinter)                                                 |
| `src/azure_ops_dashboard/gui_helpers.py`     | Shared GUI constants/utilities                                         |
| `src/azure_ops_dashboard/collector.py`       | Azure data collection (az graph query / Security / Cost / Advisor)     |
| `src/azure_ops_dashboard/drawio_writer.py`   | `.drawio` XML generator (deterministic layout)                         |
| `src/azure_ops_dashboard/drawio_validate.py` | Draw.io XML validator (checks structure, icons, node coverage)         |
| `src/azure_ops_dashboard/ai_reviewer.py`     | AI review/report generation (Copilot SDK + MCP)                        |
| `src/azure_ops_dashboard/docs_enricher.py`   | Microsoft Docs enrichment (Learn Search API + static reference map)    |
| `src/azure_ops_dashboard/exporter.py`        | Markdown → Word (.docx) / PDF export + diff report generation          |
| `src/azure_ops_dashboard/i18n.py`            | i18n module (JA/EN dictionaries + runtime switch)                      |
| `src/azure_ops_dashboard/app_paths.py`       | Resource path abstraction (PyInstaller frozen + user override support) |
| `tests.py`                                   | Unit tests (runs without Azure CLI / SDK connectivity)                 |
| `src/azure_ops_dashboard/templates/`         | Report templates JSON + saved instructions                             |
| `scripts/`                                   | Utility scripts (Azure collection, MCP smoke test, drawio validation)  |
| `CHANGELOG.md`                               | Release changelog                                                      |
| `build_exe.ps1`                              | PyInstaller build script (onedir / onefile)                            |

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
- `*-env.json` (nodes/edges and azureId→cellId map — same base name as `.drawio`)
- `*-collect-log.json` (executed commands + stdout/stderr — same base name as `.drawio`)

## Design / Survey

- Design: [DESIGN.md](DESIGN.md)
- Technical survey: [TECH-SURVEY.md](TECH-SURVEY.md)

## Tests

```powershell
# From the azure-ops-dashboard folder
uv run python -m unittest tests -v
```

Tests can run without Azure CLI / Copilot SDK connectivity (39 tests).

## Packaging (Windows .exe)

> **Pre-built binaries are available on the [Releases page](https://github.com/aktsmm/azure-ops-dashboard/releases).**
> Build from source only if you need to customize or are on a different Python version.

You can generate an exe with PyInstaller (Azure CLI `az` must be installed separately).

```powershell
# onedir (recommended: faster startup, fewer issues)
pwsh .\build_exe.ps1 -Mode onedir

# onefile (single exe)
pwsh .\build_exe.ps1 -Mode onefile
```

- Outputs are created under `dist/` (relative to the folder you run the build from).

## Responsible AI (RAI) Notes

### What this tool does

Azure Ops Dashboard uses the **GitHub Copilot SDK** to generate AI-powered analysis reports (security and cost) based on Azure environment data collected via Azure CLI / Resource Graph. The AI reviews factual resource data and produces structured Markdown reports.

### Limitations & risks

- **AI-generated content**: Reports are AI-generated analysis, not authoritative audits. Always verify recommendations against official Azure documentation and your organization's policies before acting on them.
- **Hallucination mitigation**: Reports are enriched with Microsoft Learn documentation references to ground AI output in official sources. However, AI may still produce inaccurate or incomplete analysis.
- **No write operations**: The tool only reads Azure data (Reader role). It never creates, modifies, or deletes Azure resources.
- **No data exfiltration**: Collected Azure data is sent to the Copilot SDK for analysis but is not stored or transmitted elsewhere. The Copilot SDK processes data under GitHub's data protection policies.
- **Secrets handling**: Service Principal credentials entered via the GUI are used for `az login` only and are never stored to disk or logs.

### Human oversight

- **AI Review gate**: Before generating diagrams, the tool presents an AI review summary and requires explicit user confirmation (Proceed/Cancel).
- **Template control**: Users can enable/disable report sections and add custom instructions to guide AI output.
- **Diff reports**: Automatic comparison with previous runs helps users verify changes over time rather than relying solely on a single AI output.

### Permissions principle of least privilege

| Role                   | Required for                           |
| ---------------------- | -------------------------------------- |
| Reader                 | Resource inventory, diagram generation |
| Security Reader        | Secure score, Defender recommendations |
| Cost Management Reader | Cost/billing data                      |
| Advisor Reader         | Azure Advisor recommendations          |

No write or admin permissions are ever needed or requested.
