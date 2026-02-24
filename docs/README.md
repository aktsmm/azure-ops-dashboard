# Docs — Azure Ops Dashboard

This `/docs` folder contains supplementary documentation for the Azure Ops Dashboard.
Full README: [../README.md](../README.md) | 日本語: [../README.ja.md](../README.ja.md)

---

## Problem → Solution

| | |
|---|---|
| **Problem** | Enterprise IT operations teams waste hours switching between Azure Portal, CLI, and documentation tools to visualize environments, assess security posture, and track costs. Architecture diagrams go stale; manual report creation is error-prone. |
| **Solution** | Azure Ops Dashboard reads a live Azure environment and produces **Draw.io architecture diagrams** + **AI-powered security/cost reports** in one click — powered by the **GitHub Copilot SDK**. |

---

## Download (pre-built .exe)

> **No Python required for the exe build.**

| Artifact | Link |
| -------- | ---- |
| Windows x64 — pre-built `.exe` (onedir zip) | [**Releases page →**](https://github.com/aktsmm/azure-ops-dashboard/releases) |

**Quick start with the exe:**

1. Go to the [Releases page](https://github.com/aktsmm/azure-ops-dashboard/releases) and download `AzureOpsDashboard-vX.X.X-win-x64.zip`.
2. Unzip the archive — keep the entire folder structure intact (`AzureOpsDashboard.exe` won't run alone without its `_internal/` folder).
3. Double-click **`AzureOpsDashboard.exe`**.

**What is NOT bundled (you still need to install these):**

| Dependency | Why needed | How to install |
|---|---|---|
| Azure CLI (`az`) | Collects Azure resource data | [Install Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) |
| ARG extension | Resource Graph queries | `az extension add --name resource-graph` |
| `az login` | Authentication | `az login` (browser) or SP login via GUI button |

No Python runtime, virtual environment, or `uv` is needed when running the pre-built exe.

---

## Quick Start (from source)

```powershell
# 1. Clone
git clone https://github.com/aktsmm/azure-ops-dashboard.git
cd azure-ops-dashboard

# 2. Create venv + install
uv venv
uv pip install -e ".[ai]"

# 3. Run
uv run python src/app.py
```

> **Windows PATH note**: If `.venv\Scripts\python.exe` is not the active interpreter, run explicitly:
> ```powershell
> .venv\Scripts\python.exe src\app.py
> ```

---

## Prerequisites

| Requirement | Source run | exe |
|---|---|---|
| Python 3.11+ | ✅ required | ❌ not needed |
| `uv` | ✅ required | ❌ not needed |
| Azure CLI (`az`) | ✅ required | ✅ required |
| ARG extension | ✅ required | ✅ required |
| GitHub Copilot SDK | ✅ for AI features | ✅ bundled |
| `copilot auth login` | ✅ for AI features | ✅ for AI features |

Full details: [../README.md#prerequisites](../README.md#prerequisites)

---

## Architecture

```
User → tkinter GUI (src/azure_ops_dashboard/main.py)
         ├─→ collector.py ──→ Azure CLI (Resource Graph / Security / Cost / Advisor)
         ├─→ ai_reviewer.py ──→ GitHub Copilot SDK (streaming report generation)
         │     └─ docs_enricher.py ──→ Microsoft Learn Search API / MCP
         ├─→ drawio_writer.py ──→ .drawio (inventory / network diagrams)
         └─→ exporter.py ──→ .docx / .pdf / -diff.md
```

- Architecture diagram (Draw.io): [architecture.drawio](architecture.drawio)
- Full module map: [../README.md](../README.md)

---

## Permissions Required

| Azure Role | Used for |
|---|---|
| Reader | Resource inventory, diagram generation |
| Security Reader | Secure score, Defender recommendations |
| Cost Management Reader | Cost / billing data |
| Advisor Reader | Azure Advisor recommendations |

No write or admin permissions are needed.

---

## Responsible AI (RAI) Notes

- Reports are AI-generated analysis, not authoritative audits. Verify recommendations before acting.
- The tool only **reads** Azure data — it never creates, modifies, or deletes resources.
- An **AI Review gate** requires explicit user confirmation before generating diagrams.

Full RAI notes: [../README.md#responsible-ai-rai-notes](../README.md#responsible-ai-rai-notes)

---

## Other Assets

- Screenshots / demo media: [media/](media/)
- Architecture diagram: [architecture.drawio](architecture.drawio)
