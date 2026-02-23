# GitHub Copilot SDK Enterprise Pattern Challenge（Workspace）

このリポジトリは、GitHub Copilot SDK を使った複数の小プロジェクト（Step00〜03 + Azure Ops Dashboard）をまとめたワークスペースです。
各プロジェクトは切り出し（サブディレクトリ単体）を前提に、詳細はそれぞれの README に集約します。

## まず見る

- 進捗/残タスク: [DASHBOARD.md](DASHBOARD.md)
- エージェント/運用知見: [AGENTS.md](AGENTS.md)
- 設計/調査: [docs/](docs/)

## 共通セットアップ（ソース実行）

このワークスペースは `uv` 前提です。

```powershell
uv venv
uv pip install -e .
```

## プロジェクト一覧（詳細は各 README）

| ディレクトリ | 概要 | README |
| --- | --- | --- |
| `azure-ops-dashboard/` | Azure 環境→図（.drawio）/レポート（Security/Cost）生成 GUI（exe化対応） | [azure-ops-dashboard/README.md](azure-ops-dashboard/README.md) |
| `step00-chat-cli/` | Copilot SDK 素振り（トレイ常駐 + Alt×2 ポップアップ） | [step00-chat-cli/README.md](step00-chat-cli/README.md) |
| `step01-env-builder/` | 自然言語→Bicep→デプロイ（what-if/実デプロイ）CLI | [step01-env-builder/README.md](step01-env-builder/README.md) |
| `step02-dictation/` | Azure Speech STT → アクティブウィンドウへテキスト入力 | [step02-dictation/README.md](step02-dictation/README.md) |
| `step03-voice-agent/` | 本命（Step00/01/02 統合の Voice-first Agent） | [step03-voice-agent/README.md](step03-voice-agent/README.md) |

## 参考（このリポジトリ内）

- Voice Agent 設計: [docs/design.md](docs/design.md)
- SDK/運用メモ: [docs/tech-reference.md](docs/tech-reference.md)
- 調査メモ: [research/](research/)
- 実装セッションログ: [output_sessions/](output_sessions/)
