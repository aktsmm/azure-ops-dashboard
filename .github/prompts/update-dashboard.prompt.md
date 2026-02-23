---
description: "プロジェクトの実装状態をスキャンして DASHBOARD.md を最新状態に更新する"
---

# Update Dashboard

`DASHBOARD.md` を現在の実装状態に基づいて正確に更新する。

## 判断基準

- **実際に動くコードが存在する** → ✅ / [x] / 進捗率アップ
- **ファイルはあるが TODO が残る** → 🔧 / 部分チェック
- **ソースがない / 空ディレクトリ** → ⬜ / 0%
- 根拠なく進捗率を上げない

## 手順

SSOT は dashboard-updater エージェント定義です。手順の詳細はそちらを参照してください:

- `.github/agents/dashboard-updater.agent.md`

このプロンプトは「何を達成するか（DASHBOARD 更新）」と「判断基準」のみを定義します。
実行手順・Fail Fast・Done Criteria はエージェント定義に従ってください。

## Non-Goals

- 実装コードの修正・提案
- アーキテクチャや設計の変更提案
- TODO の優先順位の独断変更
