# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.1] - 2026-02-24

### Fixed

- Report collection timeouts increased to 10 minutes for large subscriptions (az rest / Advisor).
- Best-effort report generation: security/cost/advisor collection failures no longer abort report generation.
- Auto-open safety: report outputs (.md/.json) are never passed to Draw.io; VS Code is preferred (Windows falls back to Notepad).
- Sanitized AI output to remove accidental tool-call/meta traces (e.g., `<tool_calls>` blocks).

## [1.0.0] - 2026-02-24

### Added

- Diagram generation — inventory / network views via Azure Resource Graph (`az graph query`)
- Security report — secure score, recommendations, Defender status, risk analysis (AI-generated)
- Cost report — cost by service/RG, optimization recommendations, Advisor integration (AI-generated)
- Diff report — automatically compares previous and current reports (`*-diff.md`)
- Microsoft Docs enrichment — best-effort reference enrichment via Microsoft Learn Search API + MCP
- Dynamic model selection — fetches available models from GitHub Copilot SDK
- Template customization — section ON/OFF, custom instructions, 4 built-in presets
- Export — Word (.docx) / PDF / SVG (.drawio.svg)
- i18n — Japanese / English runtime switching (UI + report output)
- Service Principal login — `🔐 SP login` button (secret is not stored)
- Canvas preview — simple diagram preview with pan/zoom
- PyInstaller packaging — `build_exe.ps1` for onedir / onefile builds
- User-area template override — `%APPDATA%\AzureOpsDashboard\templates\` (no rebuild needed)
- Collection script — `scripts/collect-azure-env.ps1` for auditable CLI execution
- Unit tests — can run without Azure CLI / Copilot SDK connectivity
- Cross-platform — Windows (full + exe), macOS, Linux
