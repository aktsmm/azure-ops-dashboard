# Step10: Azure Ops Dashboard（GUIアプリ）

> 作成日: 2026-02-20

Azure環境（既存リソース）を読み取って、Draw.io 構成図（`.drawio`）やセキュリティ／コストレポート（`.md` / `.docx` / `.pdf`）を生成する **tkinter GUIアプリ**。

**日本語 / English 切り替え対応** — UI・ログ・AIレポート出力言語をワンクリックで切替。

## 機能

### 図生成（Diagram）

- Azure Resource Graph（`az graph query`）でリソース棚卸しを取得
- `.drawio`（mxfile XML）を生成して、現状構成図（As-Is）を即出力
- `inventory`（全体構成図）/ `network`（ネットワークトポロジー）の2ビュー

### レポート生成（Report）

- **Security Report** — セキュアスコア、推奨事項、Defender状態、リスク分析
- **Cost Report** — サービス別/RG別コスト、最適化推奨、Advisor連携
- GitHub Copilot SDK（AI）によるレポート自動生成
- テンプレートカスタマイズ（セクション ON/OFF + カスタム指示）
- Word (.docx) / PDF エクスポート対応

### GUI 機能

- **Language 切替** → 日本語 / English（UIテキスト + AIレポート出力を即時切替）
- **View 選択** → inventory / network / security-report / cost-report
- **テンプレート管理** — プリセット選択 + チェックボックスでセクション制御 + 保存
- **追加指示** — 保存済み指示をチェックで呼び出し + 自由入力欄
- **出力フォルダ** — 設定済みならダイアログなしで自動保存
- **Open with** — Auto / Draw.io / VS Code / OS default から選択
- **自動オープン** — 生成完了後に自動でファイルを開く
- **AI レビュー** — Collect 後にリソース構成レビュー → Proceed/Cancel
- **Canvas プレビュー** — ログ下部に簡易構成図（パン/ズーム対応）

### クロスプラットフォーム

- **Windows** — フル対応（exe 配布可）
- **macOS** — GUI / az CLI / Copilot SDK / ファイルオープン(`open`) / Draw.io(.app)検出 対応
- **Linux** — GUI / az CLI / Copilot SDK / ファイルオープン(`xdg-open`) 対応

## 前提

- Python 3.11+（※ソース実行時。exe 配布で使う場合は Python 不要）
- Azure CLI（`az`）が利用可能
- `az login` 済み
- ARG拡張: `az extension add --name resource-graph`

### 前提（exe 配布で使う場合）

exe にしても **外部依存（Azure CLI など）は同梱されません**。そのため「exe さえあればどこでもOK」ではなく、下記が必要です。

- Windows 10/11（x64）
- Azure CLI がインストール済みで `az` が PATH から実行できること
- `az login` 済みであること
- ARG 拡張が入っていること: `az extension add --name resource-graph`
- 対象 Subscription / RG に対して最低でも Reader 相当の権限があること
- AI 機能（レビュー/レポート）を使う場合:
  - Copilot CLI がインストール済みで `copilot auth login` 済み（SDK は Copilot CLI の server mode を利用）
  - もしくは環境変数トークン（例: `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`）が設定済み
  - ネットワーク到達（社内Proxy/Firewall環境だと追加設定が必要な場合あり）
- PDF 出力を使う場合: Microsoft Word または LibreOffice（`soffice` が実行できること）

### 配布メモ

- onedir で作った場合は `dist/AzureOpsDashboard/` 配下を **フォルダごと** 配布してください（exe 単体だと動きません）。
- onefile は exe 1個になりますが、起動が遅くなる/誤検知されやすいことがあります。

### テンプレート/指示のアップデート（exe 再配布なし）

レポート用テンプレートや保存済み指示（インストラクション）は、ユーザー領域で **上書き**できます。
exe を作り直さずに反映したい場合は、以下に JSON を配置してアプリを再起動してください。

| OS      | パス                                       |
| ------- | ------------------------------------------ |
| Windows | `%APPDATA%\AzureOpsDashboard\templates\`   |
| macOS   | `~/.AzureOpsDashboard/templates/`          |
| Linux   | `~/.AzureOpsDashboard/templates/`          |

- `security-*.json` / `cost-*.json`（テンプレート）
- `saved-instructions.json`（保存済み追加指示）

同名ファイルがある場合は **ユーザー領域の方が優先**されます。

※ アプリ本体の挙動変更（コード更新）は exe 更新が必要です。

## 使い方

```powershell
# step10-azure-env-diagrammer フォルダ内で実行
uv run python .\main.py

# リポジトリルートから実行する場合
uv run python .\step10-azure-env-diagrammer\main.py
```

GUIウィンドウが起動するので:

1. **Language** を選択（日本語 / English）— 任意のタイミングで切替可
2. **View** を選択（inventory / network / security-report / cost-report）
3. Subscription / Resource Group を入力（任意）
4. レポート系の場合: テンプレート選択 → セクション ON/OFF → 追加指示
5. **▶ Collect** or **▶ Generate Report** ボタンを押す
6. 図の場合: AI レビュー → Proceed で生成 → 自動オープン
7. レポートの場合: AI 生成 → 自動保存 → 自動オープン

## ファイル構成

| ファイル           | 説明                                                           |
| ------------------ | -------------------------------------------------------------- |
| `main.py`          | GUI アプリ本体（tkinter）                                      |
| `collector.py`     | Azure データ収集（az graph query / Security / Cost / Advisor） |
| `drawio_writer.py` | .drawio XML 生成                                               |
| `ai_reviewer.py`   | AI レビュー・レポート生成（Copilot SDK）                       |
| `exporter.py`      | Markdown → Word (.docx) / PDF 変換                             |
| `i18n.py`          | 国際化モジュール（日本語/英語 翻訳辞書 + ランタイム切替）      |
| `app_paths.py`     | リソースパス抽象化（PyInstaller frozen 対応）                   |
| `docs_enricher.py` | Microsoft Docs MCP 連携（レポート参考文献補強）                |
| `templates/`       | レポートテンプレート JSON + 保存済み指示                       |

### テンプレート

| ファイル                  | 種別     | 特徴                                |
| ------------------------- | -------- | ----------------------------------- |
| `security-standard.json`  | Security | 全セクション有効（標準）            |
| `security-executive.json` | Security | 経営層向け（サマリ+アクションのみ） |
| `cost-standard.json`      | Cost     | 全セクション有効（標準）            |
| `cost-executive.json`     | Cost     | 経営層向け（サマリ+削減提案のみ）   |
| `saved-instructions.json` | 共通     | 保存済み追加指示（5件プリセット）   |

## 出力

保存先フォルダに以下を生成:

- `*.drawio`（Draw.io 構成図）
- `*.md`（Markdown レポート）
- `*.docx`（Word レポート、オプション）
- `*.pdf`（PDF レポート、オプション — Word/LibreOffice 必要）
- `env.json`（nodes/edges と azureId→cellId マップ）
- `collect.log.json`（実行コマンドとstdout/stderr）

## 設計/調査

- 設計（SSOT）: `DESIGN.md`
- 技術調査（SSOT）: `TECH-SURVEY.md`
- セッションログ: `output_sessions/`

## 実行ファイル化（Windows .exe）

PyInstaller を使って exe を生成できます（Azure CLI `az` は別途インストールが必要です）。

```powershell
# onedir（おすすめ: 起動が速い / トラブルが少ない）
pwsh .\build_exe.ps1 -Mode onedir

# onefile（単一 exe）
pwsh .\build_exe.ps1 -Mode onefile
```

- 生成物は `step10-azure-env-diagrammer/dist/` 配下に出ます。
