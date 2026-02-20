# Step 3: Voice-first Enterprise Copilot

Step 0（GUI+SDK基盤）/ Step 1（Env Builder）/ Step 2（Dictation）を統合した本命プロジェクト。

## 参照ドキュメント

- 全体設計: [../docs/design.md](../docs/design.md)
- SDK前提/セキュリティ: [../docs/tech-reference.md](../docs/tech-reference.md)

## 実装開始の前提

- Step 0 + Step 1 + Step 2 の最小動作が確認できていること

## 実装配置（予定）

（実装開始時に `src/` を作成し、ここに集約）

- `src/app.py`: 常駐（トレイ/ホットキー）とモード切替（dictation / agent）
- `src/sdk/`: Copilot SDK ラッパー（Step00の移植/統合）
- `src/speech/`: Azure Speech STT/TTS（Step02の移植/統合）
- `src/skills/`: skills 同期 + `skill_directories` 注入
- `src/tools/`: onPreToolUse（許可/拒否/確認）

## TODO

- Step 0 + Step 1 + Step 2 完了後に統合実装開始
