---
agent: "agent"
description: "review-code のワークスペースエイリアス（グローバル版に統合済み）"
tools: ["agent", "edit/editFiles", "execute/runInTerminal", "todo"]
---

> **このプロンプトはグローバルの `review-code.prompt.md` に統合済みです。**
> 直接 `review-code` を使ってください。
>
> このファイルが呼ばれた場合も、グローバル版と同じワークフローで実行します。

<!-- 以下は fallback: グローバル版が読み込まれなかった場合のミニマル指示 -->

## Fallback Instructions

1. `.github/copilot-instructions.md` と `AGENTS.md` の Learnings を読む
2. 対象コードをレビューし、🔴🟡🟢 テーブルで報告
3. ユーザーが `all fix` / 番号指定 / `review only` を返す
4. 選択項目を修正 → `compileall` + テスト → コミット
