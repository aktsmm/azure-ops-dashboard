# Azure Env Diagrammer（Azure環境→Draw.io図）— 設計（MVP）

> 作成日: 2026-02-20

## 0. ねらい

Azure上の“いまある”環境（リソース/関係）を読み取り、**Draw.io（diagrams.net）で開ける図（.drawio XML）**を自動生成する。

想定ユースケース:

- 既存サブスク/RGの棚卸し（構成把握・引き継ぎ）
- 変更前後の比較用のベース図（現状As-Is）
- Voice Agent から「このRGの構成図出して」で即図化

## 前提（MVP）

- Windows / Python 3.11+
- Azure CLI（`az`）が利用可能
- `az login` 済み（MVPは対話ログイン前提）
- Azure Resource Graph 拡張（`az extension add --name resource-graph`）が利用可能

## 1. スコープ

### 1.1 IN

- Azure Resource Graph（ARG）/ Azure CLI を使った環境取得
- “ノード（リソース）”と、MVPで扱える範囲の“エッジ（関係）”生成
- `.drawio`（mxfile XML）生成（ファイルとして保存）

### 1.2 OUT（MVPでやらない）

- すべてのAzureサービスの意味的な関係解決
- 完全自動の美しいレイアウト（graphviz等の導入は後回し）
- ポータル相当の詳細設定UI
- 破壊的操作（削除/停止/変更）

## 2. 方式選定（結論）

### 2.1 Draw.io出力方式

MVPの結論: **`.drawio` XML を直接生成**する。

- 依存が軽い（ブラウザ/拡張なしで完結）
- CI/バッチで生成しやすい

補足: drawio MCP（例: `lgazo/drawio-mcp-server`）は「開いているDraw.ioを操作/検査」する方式で強力だが、
ブラウザ拡張が前提になりやすいので **“後段のオプション”**として扱う（MVP必須にしない）。

### 2.2 Azure収集方式

MVPの結論: **Azure Resource Graph（`az graph query`）を第一選択**にする。

- 1クエリで横断的に取得しやすい
- `join`/`mv-expand`/`parse` で関係を作りやすい（VM→NIC→PIP、NIC→Subnet など）

## 3. GUI I/F（tkinter / ダークテーマ）

```powershell
uv run python .\main.py
```

GUIウィンドウが起動する（VS Codeダークテーマ風）。

### 3.1 入力フォーム

- **Subscription**: `ttk.Combobox`（認証済みなら `az account list` で候補自動ロード）
- **Resource Group**: `ttk.Combobox`（Subscription選択で `az group list` から候補ロード）
- **View**: `ttk.Combobox`（`inventory` / `network`）
- **Max Nodes**: テキスト入力（既定: 300）
- いずれも取得失敗時は手入力にフォールバック
- **Refresh** ボタンで候補を再取得

### 3.2 操作フロー（Collect → Review → Generate → Preview）

1. 入力 → **Collect** ボタン → ワーカースレッドで `az graph query` 実行
2. **レビュー画面**（収集後→生成前の承認ステップ）
   - 表示: 取得件数、type別カウント、対象Sub/RG、適用したLimit、実行ARGクエリ（コピー可）
   - ボタン: **Proceed**（生成へ）/ **Cancel**（中断して入力に戻る）
   - RG未指定時は警告を強めて明示確認
3. **Generate**: .drawio XML 生成 → 保存ダイアログ
4. **プレビュー**（Canvas簡易描画）: ノード=矩形+ラベル、エッジ=線
   - パン（ドラッグ）/ ズーム（ホイール）/ フィット（ボタン）
5. **Open .drawio** ボタンで外部（diagrams.net等）で開く

### 3.3 進捗表示

- `ttk.Progressbar`（indeterminate）+ ステップ表示（`Step 1/5: Collect`）+ 経過時間（`mm:ss`、200ms更新）
- `_set_working(True/False)` でバー開始/停止・タイマー開始/停止・入力ロック/解除を統制
- ワーカー内のステップ（収集→正規化→XML生成→保存→完了）ごとにステップ文字列を更新

### 3.4 エラーハンドリング（事前チェック＋分類）

起動時に `az` 有無・`az login` 状態・`resource-graph` 拡張をバックグラウンド検査。
未整備の場合はGUI上に次アクションを固定文で表示:

| 状態              | ガイダンス                                                      |
| ----------------- | --------------------------------------------------------------- |
| `az` コマンド無し | 「Azure CLI をインストールしてください」                        |
| 未ログイン        | 「`az login` を実行してください」                               |
| ARG拡張無し       | 「`az extension add --name resource-graph` を実行してください」 |
| 権限不足          | 「Reader 以上の権限が必要です」                                 |
| タイムアウト      | 「RG を指定して範囲を絞ってください」                           |

### 3.5 その他UX

- **Copy Log / Copy Query** ボタン: ログ・実行クエリをクリップボードへ
- **生成履歴**: 直近5件（日時/件数/パス）をリスト表示、クリックでOpen
- **二重実行防止**: 実行中は入力/ボタンをすべてロック
- **Cancel**: ワーカーにキャンセル要求 → UI復帰
- **ページング警告**: Limitで結果が欠けた場合に注意表示

### 3.6 成果物

- `*.drawio`（指定パス）
- `env.json`（正規化済みの nodes/edges。デバッグと差分比較用）
- `collect.log.json`（実行した `az ...` と stdout/stderr）

## 4. データモデル（内部）

### 4.1 正規化モデル

```text
Node:
  id: string            # Azure resourceId（小文字化して安定化）
  name: string
  type: string          # microsoft.*/*
  resourceGroup: string
  location?: string
  props?: dict          # MVPは最小（後で拡張）

Edge:
  source: string        # Node.id
  target: string        # Node.id
  kind: string          # e.g. "attachedTo", "uses", "memberOf"
```

### 4.2 View別の最低限ノード/エッジ

- `inventory` view
  - ノード: RG配下の全リソース（上限あり）
  - エッジ: なし（MVPでは“棚卸し図”として成立させる）
- `network` view
  - ノード: VNet / Subnet / NIC / VM / Public IP（まずここだけ）
  - エッジ: VM→NIC、NIC→Subnet、NIC→Public IP

## 5. 収集クエリ（ARG）

### 5.1 Inventory（RG配下の一覧）

概念:

- `Resources` から `resourceGroup` で絞り、必要列だけ `project`

### 5.2 Network（関係抽出）

公式サンプルをベースに段階的に取る（MVPは「2〜3本のクエリ」を想定）:

- VM→NIC→PIP
- NIC→Subnet（subnetIdからvnet/subnet名を `parse` で抽出してもよい）

※ `join`/`mv-expand` の上限があるので、クエリは分割して nodes/edges をマージする。

## 6. Draw.io（.drawio XML）生成

### 6.1 最小構造

- `<mxfile><diagram><mxGraphModel><root>...` の骨格を生成
- ノードは `mxCell vertex="1"` + `mxGeometry(x,y,w,h)`
- エッジは `mxCell edge="1" source="..." target="..."` + `mxGeometry relative="1"`

### 6.2 ID方針

- Draw.ioの `mxCell id` は、Azure resourceId をそのまま使うと長すぎるので、
  `n<hash>`（例: sha1の先頭12桁）に変換して安定化
- `env.json` 側に `azureId -> cellId` のマップを保存して追跡可能にする

### 6.3 レイアウト（MVP）

- `inventory`: typeごとに列を分け、行方向に詰める（固定グリッド）
- `network`: 左→右に PublicIP / NIC / Subnet / VM の順で配置（固定）

## 7. セキュリティ/ガバナンス

- 読み取り専用コマンドに限定（`az graph query`、必要なら `az account show` など）
- 取得結果はローカルに保存されるため、`env.json` には秘密（キー/接続文字列等）を入れない
  - 出力前に `properties` をホワイトリスト方式で絞る（MVPは props最小）

## 8. Voice Agent / Skills への組み込み想定（将来）

- スキル名案: `azure-env-diagrammer`
- 入力: 「このRGの構成図をdrawioで出して」
- 出力: `out/<timestamp>/env.drawio` を生成し、結果パスを返す

## 9. 実装タスク分割

### Phase 1: 進捗表示 + エラー改善 + ファイル分離

1. `main.py` からロジックを分離 → `collector.py` / `drawio_writer.py` / `preview.py`
2. `ttk.Progressbar`（indeterminate）+ ステップ表示 + 経過時間
3. 事前チェック（az有無 / login / extension）→ ガイダンス表示
4. エラー分類（未ログイン / 権限不足 / タイムアウト）→ 次アクション固定文

### Phase 2: Sub/RGドロップダウン + レビュープロセス

5. 起動時に `az account list` → Subscription候補ロード（非同期 / 失敗時フォールバック）
6. Subscription選択で `az group list` → RG候補ロード（同上）
7. 収集後→生成前のレビュー画面（件数/type別カウント/クエリ表示 + Proceed/Cancel）
8. View選択（inventory / network）ドロップダウン

### Phase 3: Canvasプレビュー + UX仕上げ

9. `tk.Canvas` 簡易描画（矩形+ラベル+線 / パン / ズーム / フィット）
10. Copy Log / Copy Query ボタン
11. 生成履歴（直近5件）リスト
12. Cancel（ワーカー中断）
13. network view の収集クエリ実装（VM→NIC→Subnet→PIP）
