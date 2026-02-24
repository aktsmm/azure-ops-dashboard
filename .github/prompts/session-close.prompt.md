---
description: "セッション終了時の成果物チェック・コミット・公開リポ同期・DASHBOARD更新"
---

<!-- author: aktsmm
     license: CC BY-NC-SA 4.0 -->

# Session Close

セッション作業の成果物を確認し、コミット・同期・ダッシュボード更新を漏れなく実行する。

## When to Use

- セッション終了時（作業区切り）
- 「閉じる」「まとめて」「コミットして」と言われたとき

## Procedure (Prompt Chaining)

### Step 1: 変更確認

```powershell
git status --short
git diff --stat
```

変更ファイルの一覧をユーザーに提示する。

### Step 2: 構文チェック（Python 変更がある場合）

> Python 実行パスは `copilot-instructions.md` の Python セクション参照（`.venv\Scripts\python.exe` を絶対パスで呼ぶ）

```powershell
<venv-python> -m compileall -q <changed-dirs>
```

- 失敗 → **STOP** — 構文エラーを報告して修正を優先

### Step 3: テスト（テスト対象の変更がある場合）

```powershell
cd <app-dir>
<venv-python> tests.py
```

- 失敗 → **STOP** — テスト失敗を報告

### Step 4: コミット

- Conventional Commits 形式でメッセージを提案
- ユーザー承認後にコミット
- `git push` は **明示的な指示がある場合のみ**

### Step 5: 公開リポ同期（subtree push が必要な場合）

以下の条件を確認：

| 条件                                    | チェック                                              |
| --------------------------------------- | ----------------------------------------------------- |
| `azure-ops-dashboard/` 配下に変更がある | `git diff --name-only HEAD~1 -- azure-ops-dashboard/` |
| remote `dashboard` が設定されている     | `git remote -v`                                       |

条件を満たす場合 → ユーザーに `subtree push` を提案（**自動実行しない**）

```powershell
git subtree push --prefix=azure-ops-dashboard dashboard master
```

### Step 6: DASHBOARD.md 更新

`@dashboard-updater` を呼ぶか、手動で以下を更新：

- `Last Updated` の日付と残り日数
- 変更があったステップの進捗率・チェックボックス
- NOW / NEXT の更新

### Step 7: 完了レポート

```markdown
## Session Close Report

- **Commit**: `<hash>` — `<message>`
- **Push**: ✅ / ⏭️ skipped
- **Subtree**: ✅ / ⏭️ N/A
- **Dashboard**: ✅ updated / ⏭️ no changes
- **Pending**: <残タスクがあれば>
```

## Non-Goals

- 新機能の実装やリファクタリング
- セッションログ（output_sessions/）の自動生成（手動エクスポート）

## Fail Fast

- 構文エラー → STOP
- テスト失敗 → STOP
- コミット対象なし → Step 6 へスキップ
