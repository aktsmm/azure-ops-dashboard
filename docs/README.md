# Docs

This `/docs` folder exists to satisfy the FY26 GitHub Copilot SDK Enterprise Challenge repo requirements.

## Problem → Solution

- **Problem**: Enterprise IT operations teams waste time switching between Azure Portal, CLI, and docs to visualize environments, assess security posture, and track costs.
- **Solution**: Azure Ops Dashboard generates **Draw.io diagrams** and **AI-powered security/cost reports** from a live Azure environment in one click.

## Prereqs

- Python 3.11+ (source run)
- `uv`
- Azure CLI (`az`) + Resource Graph extension (`az extension add --name resource-graph`)
- GitHub Copilot SDK + Copilot CLI login (for AI features)

See the full list in the main README: [../README.md](../README.md)

## Setup

- Create venv + install: `uv venv && uv pip install -e ".[ai]"`
- Run: `uv run python src/app.py`

This repo also includes a small entry-point shim under `/src`:

- `python src/app.py`

## Deployment / Packaging

- Build .exe (Windows): `pwsh .\build_exe.ps1 -Mode onedir`

## Architecture

- Diagram (Draw.io): [architecture.drawio](architecture.drawio)
- High-level architecture + module map: [../README.md](../README.md)

## Responsible AI (RAI) Notes

RAI notes are documented in the main README: [../README.md#responsible-ai-rai-notes](../README.md#responsible-ai-rai-notes)

## Other docs

- Media assets: [media/](media/)
