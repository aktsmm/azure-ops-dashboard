English: [README.md](README.md)

# Azure Ops Dashboard

Azure環境（既存リソース）を読み取って、Draw.io 構成図（`.drawio`）やセキュリティ／コストレポート（`.md` / `.docx` / `.pdf`）を生成する **tkinter GUIアプリ**。

**日本語 / English 切り替え対応** — UI・ログ・AIレポート出力言語をワンクリックで切替。

## 機能

### 図生成（Diagram）

- Azure Resource Graph（`az graph query`）でリソース棚卸しを取得
- `.drawio`（mxfile XML）を生成して、現状構成図（As-Is）を即出力
- `inventory`（全体構成図）/ `network`（ネットワークトポロジー）の2ビュー
- **Max Nodes 補足**: 収集は best-effort です。`Max Nodes` に 1000 を超える値を指定しても、Azure CLI / ARG の上限に合わせて 1000 にクランプされます。

### レポート生成（Report）

- **Security Report** — セキュアスコア、推奨事項、Defender状態、リスク分析
- **Cost Report** — サービス別/RG別コスト、最適化推奨、Advisor連携
- GitHub Copilot SDK（AI）によるレポート自動生成
- 参考情報補強（best-effort）: Microsoft Learn Search API（`https://learn.microsoft.com/api/search`）+ Microsoft Docs MCP（`https://learn.microsoft.com/api/mcp`）
- **モデル動的選択** — 利用可能モデルをCopilot SDKから自動取得、UIで選択可能（既定: 最新Sonnet）
- テンプレートカスタマイズ（セクション ON/OFF + カスタム指示）
- Word (.docx) / PDF / **SVG (.drawio.svg)** エクスポート対応
- **差分レポート** — 前回と今回のレポートを自動比較（diff.md 自動生成）

### GUI 機能

- **Language 切替** → 日本語 / English（UIテキスト + AIレポート出力を即時切替）
- **View 選択** → inventory / network / security-report / cost-report
- **テンプレート管理** — プリセット選択 + チェックボックスでセクション制御 + 保存
- **追加指示** — 保存済み指示をチェックで呼び出し + 自由入力欄
- **出力フォルダ** — 設定済みならダイアログなしで自動保存
- **Open with** — Auto / Draw.io / VS Code / OS default から選択
- - 補足: Draw.io で開くのは `.drawio` / `.drawio.svg` のみです。レポート（`.md` / `.json`）は VS Code で開きます（Windows は Notepad にフォールバック）。
- **自動オープン** — 生成完了後に自動でファイルを開く
- **AI レビュー** — Collect 後にリソース構成レビュー → Proceed/Cancel
- **Canvas プレビュー** — ログ下部に簡易構成図（パン/ズーム対応）

### クロスプラットフォーム

- **Windows** — フル対応（exe 配布可）
- **macOS** — GUI / az CLI / Copilot SDK / ファイルオープン(`open`) / Draw.io(.app)検出 対応
- **Linux** — GUI / az CLI / Copilot SDK / ファイルオープン(`xdg-open`) 対応

## 前提

- Python 3.11+（※ソース実行時。exe 配布で使う場合は Python 不要）
- [uv](https://docs.astral.sh/uv/)（依存管理・ソース実行時）
- Azure CLI（`az`）が利用可能
- `az login` 済み（ブラウザ対話）
- または Service Principal でログイン済み（Reader 権限で運用したい場合）
- ARG拡張: `az extension add --name resource-graph`

### AI 機能（レビュー / レポート生成）

- GitHub Copilot SDK（`pip install github-copilot-sdk` または `uv pip install -e ".[ai]"`）
- Copilot CLI がインストール済みで `copilot auth login` 済み（SDK は Copilot CLI の server mode を利用）
- もしくは環境変数トークン（例: `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`）が設定済み
- ネットワーク到達（社内 Proxy/Firewall 環境だと追加設定が必要な場合あり）

### エクスポート（オプション）

- **Word (.docx)**: `python-docx` 同梱（自動インストール）
- **PDF**: Microsoft Word（Windows、COM/comtypes 経由）または LibreOffice（`soffice` コマンド、全 OS）
  - Windows での PDF 変換には `pip install comtypes` も必要
- **SVG (.drawio.svg)**: Draw.io デスクトップアプリ（CLI として SVG エクスポートに使用）

### 権限

- 対象 Subscription / RG に対して最低でも **Reader**（図生成用）
- **Security Reader**（Security Center データ: セキュアスコア、推奨事項）
- **Cost Management Reader**（コスト/課金データ）
- **Advisor Reader**（または Reader）（Azure Advisor 推奨事項）

### 前提（exe 配布で使う場合）

exe にしても **外部依存（Azure CLI など）は同梱されません**。そのため「exe さえあればどこでもOK」ではなく、下記が必要です。

- Windows 10/11（x64）
- Azure CLI がインストール済みで `az` が PATH から実行できること
- `az login` 済みであること（または Service Principal ログイン）
- ARG 拡張が入っていること: `az extension add --name resource-graph`
- 対象 Subscription / RG に対して最低でも Reader 相当の権限があること（Security/Cost は上記 [権限](#権限) 参照）

#### Service Principal（例）

Reader 権限のみ付与した Service Principal で実行したい場合は、以下のようにログインできます。

```powershell
az login --service-principal -u <APP_ID> -p <CLIENT_SECRET> --tenant <TENANT_ID>
```

GUI からは `🔐 SP login` ボタンでも実行できます（Secret は保存しません）。

#### 収集コマンド（スクリプト）

収集処理を明示的な Azure CLI コマンドとして実行・監査したい場合は、以下のスクリプトを利用できます。

```powershell
pwsh .\scripts\collect-azure-env.ps1 -SubscriptionId <SUB_ID> -ResourceGroup <RG> -Limit 300 -OutDir <OUTPUT_DIR>
```

補足: スクリプトは `az` コマンドが非0終了した時点で停止します（エラー時は例外メッセージに出力ファイルパスが表示されます）。

### 配布メモ

- onedir で作った場合は `dist/AzureOpsDashboard/` 配下を **フォルダごと** 配布してください（exe 単体だと動きません）。
- onefile は exe 1個になりますが、起動が遅くなる/誤検知されやすいことがあります。

### テンプレート/指示のアップデート（exe 再配布なし）

レポート用テンプレートや保存済み指示（インストラクション）は、ユーザー領域で **上書き**できます。
exe を作り直さずに反映したい場合は、以下に JSON を配置してアプリを再起動してください。

| OS      | パス                                     |
| ------- | ---------------------------------------- |
| Windows | `%APPDATA%\AzureOpsDashboard\templates\` |
| macOS   | `~/.AzureOpsDashboard/templates/`        |
| Linux   | `~/.AzureOpsDashboard/templates/`        |

- `security-*.json` / `cost-*.json`（テンプレート）
- `saved-instructions.json`（保存済み追加指示）

同名ファイルがある場合は **ユーザー領域の方が優先**されます。

※ アプリ本体の挙動変更（コード更新）は exe 更新が必要です。

## 使い方

```powershell
# 依存関係インストール
uv venv
uv pip install -e .

# AI 機能も使う場合
uv pip install -e ".[ai]"

# 起動
uv run python main.py
```

> **⚠ Windows PATH に関する注意**: `uv` がグローバル Python を `~/.local/bin/` にインストールしている場合、`Activate.ps1` を実行しても `.venv\Scripts\python.exe` より先にグローバル Python が使われることがあります。その場合は **venv の Python を明示的に指定**してください:
>
> ```powershell
> .venv\Scripts\python.exe main.py
> ```
>
> `python -c "import sys; print(sys.executable)"` で `.venv\Scripts\python.exe` を指していなければ、Copilot SDK 等の venv パッケージが見つからずエラーになります。

GUIウィンドウが起動するので:

1. **Language** を選択（日本語 / English）— 任意のタイミングで切替可
2. **View** を選択（inventory / network / security-report / cost-report）
3. Subscription / Resource Group を入力（任意）
4. レポート系の場合: テンプレート選択 → セクション ON/OFF → 追加指示
5. **▶ Collect** or **▶ Generate Report** ボタンを押す
6. 図の場合: AI レビュー → Proceed で生成 → 自動オープン
7. レポートの場合: AI 生成 → 自動保存 → 自動オープン

## ファイル構成

| ファイル             | 説明                                                                 |
| -------------------- | -------------------------------------------------------------------- |
| `main.py`            | GUI アプリ本体（tkinter）                                            |
| `gui_helpers.py`     | GUI 共通定数・ユーティリティ（main.py から分離）                     |
| `collector.py`       | Azure データ収集（az graph query / Security / Cost / Advisor）       |
| `drawio_writer.py`   | .drawio XML 生成（決定的レイアウト）                                 |
| `drawio_validate.py` | Draw.io XML バリデータ（構造・アイコン・ノード網羅率検査）           |
| `ai_reviewer.py`     | AI レビュー・レポート生成（Copilot SDK + MCP）                       |
| `docs_enricher.py`   | Microsoft Docs 補強（Learn Search API + 静的リファレンスマップ）     |
| `exporter.py`        | Markdown → Word (.docx) / PDF 変換 + 差分レポート生成                |
| `i18n.py`            | 国際化モジュール（日本語/英語 翻訳辞書 + ランタイム切替）            |
| `app_paths.py`       | リソースパス抽象化（PyInstaller frozen + ユーザー上書き対応）        |
| `tests.py`           | ユニットテスト（collector / drawio_writer / exporter / gui_helpers） |
| `templates/`         | レポートテンプレート JSON + 保存済み指示                             |
| `scripts/`           | ユーティリティスクリプト（Azure 収集、MCP テスト、drawio 検証）      |
| `CHANGELOG.md`       | リリース変更履歴                                                     |
| `build_exe.ps1`      | PyInstaller ビルドスクリプト（onedir / onefile）                     |

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
- `*.drawio.svg`（SVG エクスポート、オプション — Draw.io CLI 必要）
- `*.md`（Markdown レポート）
- `*-diff.md`（差分レポート — 前回レポートとの比較）
- `*.docx`（Word レポート、オプション）
- `*.pdf`（PDF レポート、オプション — Word/LibreOffice 必要）
- `*-env.json`（nodes/edges と azureId→cellId マップ — `.drawio` と同名ベース）
- `*-collect-log.json`（実行コマンドとstdout/stderr — `.drawio` と同名ベース）

## 設計/調査

- 設計: [DESIGN.md](DESIGN.md)
- 技術調査: [TECH-SURVEY.md](TECH-SURVEY.md)

## テスト

```powershell
# azure-ops-dashboard フォルダ内で実行
uv run python -m unittest tests -v
```

Azure CLI / Copilot SDK 接続なしでテスト可能（36件）。

## 実行ファイル化（Windows .exe）

PyInstaller を使って exe を生成できます（Azure CLI `az` は別途インストールが必要です）。

```powershell
# onedir（おすすめ: 起動が速い / トラブルが少ない）
pwsh .\build_exe.ps1 -Mode onedir

# onefile（単一 exe）
pwsh .\build_exe.ps1 -Mode onefile
```

- 生成物は `dist/` 配下に出ます（実行したフォルダの直下）。
