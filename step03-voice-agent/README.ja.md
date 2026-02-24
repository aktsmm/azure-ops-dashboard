English: [README.md](README.md)

# Step 03: Voice-first Enterprise Copilot（本命）

Step00（SDK Chat + トレイ常駐）/ Step01（Env Builder）/ Step02（Dictation）を統合する本命プロジェクトです。

## 参照

- 全体設計: [../docs/design.md](../docs/design.md)
- SDK前提/セキュリティ: [../docs/tech-reference.md](../docs/tech-reference.md)
- 進捗/残タスク: [../DASHBOARD.md](../DASHBOARD.md)

## 現状

- `src/` はまだ骨格段階（統合はこれから）
- 実装が進むまでは Step00/01/02 を単体で動かして検証します

## セットアップ（共通）

ワークスペースルートで:

```powershell
uv venv
uv pip install -e .
```

## 実装配置（予定）

- `src/app.py`: 常駐（トレイ/ホットキー）とモード切替（dictation / agent）
- `src/sdk/`: Copilot SDK ラッパー（Step00の移植/統合）
- `src/speech/`: Azure Speech STT/TTS（Step02の移植/統合）
- `src/skills/`: skills 同期 + `skill_directories` 注入
- `src/tools/`: onPreToolUse（許可/拒否/確認）
