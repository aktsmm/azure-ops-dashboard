---
topic: Azure環境を読み取ってDraw.io図を生成するツール技術調査（drawio-mcp-server / .drawio XML / Azure Resource Graph）
date: 2026-02-20
status: final
sources_count: 6
reflection_count: 1
---

# Azure環境を読み取ってDraw.io図を生成するツール技術調査（drawio-mcp-server / .drawio XML / Azure Resource Graph）

> 調査日: 2026-02-20
> 調査者: Deep Research Agent

## TL;DR

- drawio-mcp-server は「ローカルに .drawio を吐く」よりも、**ブラウザ拡張を介して“開いているDraw.io”を操作/検査する**タイプの MCP サーバー。Node.js v20+ と専用ブラウザ拡張が必須。[^1]
- `.drawio` は **非圧縮XML**として保存でき、最小構成は `<mxfile><diagram><mxGraphModel><root><mxCell .../></root></mxGraphModel></diagram></mxfile>` という階層。頂点は `vertex="1"`、辺は `edge="1" source/target`。[^2][^3]
- Azureの「関係（VM→NIC→PIP、NIC→Subnet など）」を組むなら、ARG の `join` + `mv-expand` + `parse` が現実的。VM/NIC/PIP を2回 `leftouter join` で結ぶサンプルが公式にある。[^6]

## 1) drawio-mcp-server（lgazo/drawio-mcp-server）の主要ツール一覧と必須前提

### 必須前提（要点）

- **Node.js v20+** が必要。[^1]
- **Draw.io MCP Browser Extension**（専用のブラウザ拡張）が必要（拡張が Draw.io と MCP サーバーを中継）。[^1]
- Draw.io（diagrams.net）の **Web版/デスクトップ版が利用可能**であること（MCPは“Draw.ioインスタンスを操作する”前提）。[^1]
- ブラウザ拡張は既定で **WebSocket 3333** に接続（`--extension-port` で変更可、変更時は拡張側も合わせる）。[^1]
- MCP 側は stdio に加え、オプションで **HTTP transport（/health と /mcp）** を有効化できる。[^1]

### ツール一覧（主要カテゴリ）

> ※ “追加/編集” は豊富だが、README上は「ファイル保存/エクスポートを直接行う専用ツール」は前面に出ていない（保存/エクスポートは通常 Draw.io 側の操作で実施する想定に見える）。[^1]

- **Inspection（検査）**
  - `get-selected-cell`（選択中セルの取得）[^1]
  - `get-shape-categories`（図形ライブラリのカテゴリ一覧）[^1]
  - `get-shapes-in-category`（カテゴリ内の図形一覧）[^1]
  - `get-shape-by-name`（名前で図形取得）[^1]
  - `list-paged-model`（セル一覧をページング/フィルタして取得）[^1]

- **Modification（追加/編集）**
  - `add-rectangle`（矩形追加）[^1]
  - `add-edge`（セル間エッジ追加）[^1]
  - `delete-cell-by-id`（セル削除）[^1]
  - `add-cell-of-shape`（ライブラリ形状を指定してセル追加）[^1]
  - `set-cell-shape`（既存セルにライブラリ形状のスタイル適用）[^1]
  - `set-cell-data`（セルへカスタム属性を保存/更新）[^1]
  - `edit-cell`（セルのtext/geometry/style等を部分更新）[^1]
  - `edit-edge`（エッジのtext/source/target/style等を部分更新）[^1]

- **Layer（レイヤ管理）**
  - `list-layers` / `create-layer` / `get-active-layer` / `set-active-layer` / `move-cell-to-layer`[^1]

## 2) Draw.ioのローカルファイル生成（.drawio XML / mxfile）方式のポイント

### 保存形式の前提

- draw.io(diagrams.net)の推奨のネイティブ保存形式は **`.drawio`** で、**非圧縮XML**として保存できる。[^2]

### 最小構造（要点）

`.drawio` の“最低限の骨格”として押さえるポイント（要約）:

- **`<mxfile>`**: ルート要素（メタ情報属性を持つことが多い）。[^3]
- **`<diagram>`**: 1ページ相当。`name` や `id` を持つことが多い。[^3]
- **`<mxGraphModel>`**: グラフモデル本体（表示設定や `root` を内包）。[^3]
- **`<root>`**: `mxCell` 群を持つ。
  - よくある初期セルとして `id="0"` と `id="1" parent="0"` が配置される例がある。[^3]

### mxCellの最小要素（vertex/edge）

- **頂点（ノード）**: `mxCell` に `vertex="1"` を付け、内部に `mxGeometry`（x/y/width/height）を置く。[^3]
  - 例: `value` がラベル、`style` が見た目（図形/色/フォント等）を表す。[^3]
- **辺（エッジ）**: `mxCell` に `edge="1"` を付け、`source` と `target` に接続先セルIDを入れる。内部に `mxGeometry relative="1"` を置く例がある。[^3]

### 生成戦略（実務の観点）

- まずは **IDの安定化**（ノードIDをAzureのresourceId等に紐づける/ハッシュ化する等）→ エッジ `source/target` が作りやすい。
- “図形カタログ/テーマ”より先に、**ノード種別（VM/VNet/Subnet/NIC/PIP）と関係線**を先に埋めるのがMVP向き。

## 3) Azure環境収集の選択肢比較（az resource list vs ARG vs ARM REST/SDK）

### ざっくり比較（関係生成を主目的にした観点）

- `az resource list`
  - 長所: 入口が簡単（まず全リソースを取るのに向く）
  - 注意: **リソース間の関係**（例: VM→NIC→Subnet→PIP）を組むには、追加で詳細取得やID解決の処理が増えがち（“一覧”は関係を直接返さないケースが多い）

- Azure Resource Graph（`az graph query` / ARG）
  - 長所: `Resources` テーブルを中心に、**`join` と `mv-expand` で関係を組み立てやすい**。VM→NIC→PIP のように複数種別を結合する公式サンプルがある。[^6]
  - 長所: `parse kind=regex` で resourceId 文字列から名前抽出（例: NICのsubnetIdから vnet/subnet 名）もできる。[^6]
  - 注意: Resource Graph は KQLのサブセットで、`join` / `mv-expand` の回数などに既定制限がある（SDKクエリで `join` と `mv-expand` がそれぞれ3回まで等）。[^5]

- ARM REST / SDK
  - 長所: リソース種別ごとの **完全なプロパティ**や、状況に応じた **最新/詳細**を取りやすい（特に個別リソースの深掘り）
  - 注意: 関係抽出は “APIをいくつ叩いて、どう正規化するか” が実装負担になりやすい（N+1になりがち）

### `az graph query` の現実的な前提

- `az graph query` を使うには **Azure CLI拡張（resource-graph）** が必要で、CLIバージョン要件もある。[^4]

### 関係（VM-NIC-Subnet-PIP等）を作るARGサンプル/テクニック（要点）

- **テクニックA: `mv-expand` で配列（NIC一覧 / ipConfigurations）を展開し、primary を絞る**
  - VM側: `properties.networkProfile.networkInterfaces` を `mv-expand` し、NICが複数なら `primary` を選ぶ（公式サンプルは `array_length` と `primary` 条件を併用）。[^6]
  - NIC側: `properties.ipConfigurations` を `mv-expand` し、同様に primary を選ぶ。[^6]

- **テクニックB: `leftouter join` を段階的に積む（VM→NIC、結果→PIP）**
  - 公式サンプルでは `Resources (VM)` を `Resources (NIC)` に `leftouter join`、さらに `Resources (PIP)` に `leftouter join` している。[^6]

- **テクニックC: `parse kind=regex` で subnetId から VNet/Subnet を抽出**
  - NICの `ipConfigurations[].properties.subnet.id` を文字列化し、`/virtualNetworks/<vnet>/subnets/<subnet>` を正規表現で分解するサンプルがある。[^6]

- **テクニックD: `project` と `project-away` で join 後の列衝突を整理**
  - `join` 後は同名列に `1` が付くので、不要列を落として整形する（サンプルで `project-away ...1` が多用される）。[^6]
  - なお、`project` で絞る場合は **joinキーを project に残す必要**がある（公式注記）。[^5]

#### 擬似KQL例（MVP用の“関係エッジ”抽出イメージ）

- VM→NIC→PIP（公式サンプルの構造を踏襲）[^6]

```kusto
Resources
| where type =~ 'microsoft.compute/virtualmachines'
| mv-expand nic = properties.networkProfile.networkInterfaces
| project vmId=id, vmName=name, nicId=tostring(nic.id)
| join kind=leftouter (
    Resources
    | where type =~ 'microsoft.network/networkinterfaces'
    | mv-expand ipconfig=properties.ipConfigurations
    | project nicId=id, publicIpId=tostring(ipconfig.properties.publicIPAddress.id)
) on nicId
| join kind=leftouter (
    Resources
    | where type =~ 'microsoft.network/publicipaddresses'
    | project publicIpId=id, publicIpAddress=properties.ipAddress
) on publicIpId
```

- NIC→Subnet（サンプルの parse を踏襲）[^6]

```kusto
Resources
| where type =~ 'microsoft.network/networkinterfaces'
| mv-expand ipConfigurations = properties.ipConfigurations
| project nicId=id, subnetId=tostring(ipConfigurations.properties.subnet.id)
| parse kind=regex subnetId with '/virtualNetworks/' vnet '/subnets/' subnet
| project nicId, subnetId, vnet, subnet
```

## 4) 推奨アーキテクチャ案（MVP、3-6項目）

1. **収集（Inventory + Relations）**: `az graph query` を第一選択にして「ノード（Resources）」と「エッジ（VM→NIC→PIP、NIC→Subnetなど）」をKQLで抽出（足りないところだけ後段で補完）。[^4][^6]
2. **正規化（Graph Model）**: 出力を `nodes[]`（id/type/name/props）と `edges[]`（source/target/type）に正規化し、IDを安定化（resourceId基準）。
3. **レイアウト（最小）**: MVPは自動レイアウトを割り切り、種別ごとに列/行を固定配置（例: VNet/Subnet列、Compute列、Public列）。
4. **出力（.drawio生成）**: `.drawio`（非圧縮XML）で `mxfile/diagram/mxGraphModel/mxCell` を直接生成して保存 → diagrams.net で開く。[^2][^3]
5. **（任意）インタラクティブ編集**: 生成後の微調整/情報付与は drawio-mcp-server を使って既存図面へ `set-cell-data` 等で属性を埋める（人手の編集を減らす）。[^1]

## 出典

| #   | ソース                                                | URL                                                                                 | Tier   | 確認日     |
| --- | ----------------------------------------------------- | ----------------------------------------------------------------------------------- | ------ | ---------- |
| 1   | lgazo/drawio-mcp-server (README)                      | https://github.com/lgazo/drawio-mcp-server                                          | Tier 1 | 2026-02-20 |
| 2   | Save a diagram in various formats                     | https://www.drawio.com/doc/faq/save-file-formats                                    | Tier 1 | 2026-02-20 |
| 3   | DRAWIO - Diagram.net Diagram File Format              | https://docs.fileformat.com/web/drawio/                                             | Tier 2 | 2026-02-20 |
| 4   | Quickstart: Run Resource Graph query using Azure CLI  | https://learn.microsoft.com/azure/governance/resource-graph/first-query-azurecli    | Tier 1 | 2026-02-20 |
| 5   | Understanding the Azure Resource Graph query language | https://learn.microsoft.com/azure/governance/resource-graph/concepts/query-language | Tier 1 | 2026-02-20 |
| 6   | Advanced Resource Graph query samples                 | https://learn.microsoft.com/azure/governance/resource-graph/samples/advanced        | Tier 1 | 2026-02-20 |

[^1]: https://github.com/lgazo/drawio-mcp-server - Requirements（Node.js v20+ / browser extension）、設定（WebSocket port / HTTP transport）、および提供ツール一覧。

[^2]: https://www.drawio.com/doc/faq/save-file-formats - `.drawio` が XML（非圧縮）である点、保存形式の説明。

[^3]: https://docs.fileformat.com/web/drawio/ - `.drawio` のXML例として `mxfile/diagram/mxGraphModel/root/mxCell`、`vertex="1"`/`edge="1"` などの構造を提示。

[^4]: https://learn.microsoft.com/azure/governance/resource-graph/first-query-azurecli - Azure CLI から `az graph query` を実行する前提（拡張導入等）。

[^5]: https://learn.microsoft.com/azure/governance/resource-graph/concepts/query-language - Resource Graph のKQLサブセット、`join`/`mv-expand` 制限、`project` と joinキー等の注意。

[^6]: https://learn.microsoft.com/azure/governance/resource-graph/samples/advanced - VM↔NIC↔PIP の `join` + `mv-expand` サンプル、NIC→Subnet の `parse kind=regex` サンプル等。

## 制限事項

- 引用URLを最大6本に制限したため、ARM REST/SDK や `az resource list` の細かな挙動差（スロットリング、APIバージョン差、個別リソースのプロパティ網羅性など）は一次情報での裏付けを省略。
- drawio-mcp-server は「ファイルを生成して保存する」用途というより「開いているDraw.ioを操作/検査する」色が強く、完全自動のバッチ生成には `.drawio` 直生成の方が単純になりやすい（要検証）。
