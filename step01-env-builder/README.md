Japanese: [README.ja.md](README.ja.md)

# Step 01: Azure Env Builder CLI

A CLI that generates Bicep from a natural language spec and runs `az deployment group` for **what-if (preview) / apply (deploy)**.
Each run saves artifacts (Bicep/logs/results) under `out/<timestamp>/`.

- Design: [DESIGN.md](DESIGN.md)

## Prerequisites

- Python 3.11+
- `uv` available
- Azure CLI (`az`) available
- Logged in via `az login`
- Permissions on the target subscription

## Setup (common)

From the workspace root:

```powershell
uv venv
uv pip install -e .
```

## Run

```powershell
cd .\step01-env-builder

# If Resource Group is omitted, it auto-creates envb-<timestamp>
uv run python .\main.py "validation environment (storage only)" --what-if

# Explicit subscription / RG / location
uv run python .\main.py "validation environment (storage only)" --subscription <SUB_ID> --resource-group <RG> --location japaneast --what-if
```

## Artifacts (`out/<timestamp>/`)

- `spec.md` (input/targets/list of az commands)
- `main.bicep` (generated Bicep)
- `main.parameters.json`
- `deploy.log` (execution log: az commands + stdout/stderr)
- `result.md` (results, error classification, next actions, outputs)

## Recommended: isolate in a new RG (what-if → deploy)

Using the same Resource Group for `--what-if` (preview) → deploy makes validation and cleanup easier.

```powershell
cd .\step01-env-builder
$loc = 'japaneast'
$rg = 'envb-' + (Get-Date -Format yyyyMMdd-HHmmss)

az group create -n $rg -l $loc

# Preview (no resource creation)
uv run python .\main.py "validation environment (storage only)" --what-if --resource-group $rg --location $loc

# Deploy
uv run python .\main.py "validation environment (storage only)" --resource-group $rg --location $loc

# Cleanup (if needed)
az group delete -n $rg --yes --no-wait
```

Note: `az group delete` is destructive. Double-check the subscription/RG before running.
