# Step10: Azure Env Diagrammer — 設計（MVP）

> 作成日: 2026-02-20

このStepの設計SSOTは以下。

- `docs/azure-env-diagrammer-design.md`

## 方式

- **GUIアプリ**（tkinter / ダークテーマ / VS Code風）
- ワーカースレッドで `az graph query` を実行し、UIをブロックしない
- 認証済みなら **Subscription / RG をプルダウン選択**（az account list / az group list で自動取得）

## 操作フロー

**Collect → Review → Generate → Preview**

1. Sub/RG/View を選択 → **Collect** → ワーカーでARG実行
2. 収集結果をレビュー（件数/type別カウント/クエリ） → **Proceed** or **Cancel**
3. .drawio 生成 → 保存ダイアログ
4. Canvas簡易プレビュー（矩形+線 / パン / ズーム）
5. **Open .drawio** で外部表示

## 進捗・安全

- `ttk.Progressbar` + ステップ表示 + 経過時間（mm:ss）
- 事前チェック（az有無 / login / extension）→ ガイダンス
- 二重実行防止 / Cancel / ページング警告

## UX強化（A〜D）

- A: Sub/RGドロップダウン（自動ロード / フォールバック手入力 / Refresh）
- B: Copy Log / Copy Query
- C: 生成履歴（直近5件）
- D: エラー分類→次アクション固定文

## ファイル構成（予定）

```
step10-azure-env-diagrammer/
├── main.py           # エントリポイント + App クラス
├── collector.py      # az graph query ラッパ（inventory / network）
├── drawio_writer.py  # .drawio XML 生成
├── preview.py        # Canvas プレビュー
├── settings.json     # ユーザー設定（自動生成）
├── DESIGN.md
├── README.md
└── TECH-SURVEY.md
```

## 実装の進行

1. Phase 1: 進捗表示 + エラー改善 + ファイル分離 ← **現在ここ**
2. Phase 2: Sub/RGドロップダウン + レビュープロセス + View選択
3. Phase 3: Canvasプレビュー + Copy/履歴/Cancel + network view

## Learnings（2026-02-20 セッション）

### 🔴 P1

| #   | 知見                                                                             | 対処                                                                                  |
| --- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| D1  | `Edge` の `kind` フィールドを `relation=` で呼んでいた → network view クラッシュ | collector.py 修正済み。今後は `mypy --strict` で検出する                              |
| D2  | `Path(__file__).parent` は PyInstaller frozen で壊れる                           | `app_paths.py` に集約済み。リソース参照は直接 `__file__` を使わない                   |
| D3  | テンプレート更新で exe 再配布したくない                                          | `%APPDATA%\AzureOpsDashboard\templates\` からユーザー上書き優先で読む仕組みを実装済み |

### 🟡 P2

| #   | 知見                                                                                     | 対処                                                                  |
| --- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| D4  | CWD が違うと `uv run python main.py` が Exit Code 1（5回発生）                           | README に起動例を追記済み。将来は `__main__.py` + `-m` 実行対応を検討 |
| D5  | PowerShell `Resolve-Path` の戻り値に末尾 `\` が付いて `uv pip install --python` が壊れた | `build_exe.ps1` で `.Path` プロパティを使うように修正済み             |

### 🟢 P3（修正済み・記録のみ）

| #   | 知見                                              | 対処                                                   |
| --- | ------------------------------------------------- | ------------------------------------------------------ |
| D6  | `env.json` に view/edges がハードコードされていた | `main.py` で実際の値を書き出すよう修正済み             |
| D7  | Word COM が例外時に孤児化                         | `exporter.py` の `md_to_pdf()` に try/finally 追加済み |
