Japanese: [README.ja.md](README.ja.md)

# GitHub Copilot SDK Enterprise Pattern Challenge (Workspace)

This repository is a workspace that contains multiple small projects built around the GitHub Copilot SDK (Step00–Step03 + Azure Ops Dashboard).
Each project is designed to be separable (as a standalone subdirectory), and detailed usage lives in each project’s README.

## Start Here

- Progress / remaining tasks: [DASHBOARD.md](DASHBOARD.md)
- Agents / operational learnings: [AGENTS.md](AGENTS.md)
- Design & research notes: [docs/](docs/)

## Common Setup (source run)

This workspace uses `uv`.

```powershell
uv venv
uv pip install -e .
```

## Projects

| Directory              | Summary                                                                                                | README                                                         |
| ---------------------- | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- |
| `azure-ops-dashboard/` | GUI app: Azure environment → diagrams (.drawio) / reports (Security/Cost) with optional .exe packaging | [azure-ops-dashboard/README.md](azure-ops-dashboard/README.md) |
| `step00-chat-cli/`     | Copilot SDK smoke test (tray resident + Alt×2 popup)                                                   | [step00-chat-cli/README.md](step00-chat-cli/README.md)         |
| `step01-env-builder/`  | Natural language → Bicep → deploy (what-if / apply) CLI                                                | [step01-env-builder/README.md](step01-env-builder/README.md)   |
| `step02-dictation/`    | Azure Speech STT → type into the active window                                                         | [step02-dictation/README.md](step02-dictation/README.md)       |
| `step03-voice-agent/`  | Main project (integrates Step00/01/02 into a voice-first agent)                                        | [step03-voice-agent/README.md](step03-voice-agent/README.md)   |

## References (in this repo)

- Voice Agent design: [docs/design.md](docs/design.md)
- SDK / ops notes: [docs/tech-reference.md](docs/tech-reference.md)
- Research notes: [research/](research/)
- Implementation session logs: [output_sessions/](output_sessions/)
