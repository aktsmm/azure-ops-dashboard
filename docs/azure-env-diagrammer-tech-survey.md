# Azure Env Diagrammer — 技術調査（要約）

> 作成日: 2026-02-20

このドキュメントは「Azure環境を読み取って Draw.io（diagrams.net）で開ける図を出す」ための技術的な選択肢を、MVPに必要な範囲で要約する。

詳細版（一次情報リンクと補足込み）:

- `research/20260220-azure-env-to-drawio-mvp.md`

## 1) Draw.io出力: 2つの現実解

### A. `.drawio`（mxfile XML）を直接生成（MVP推奨）

- メリット: ブラウザ不要、バッチ実行向き、CIでも生成できる
- デメリット: Azure公式アイコン等のスタイル指定は後回しになりがち

最小の構造（概念）:

- `mxfile` → `diagram` → `mxGraphModel` → `root` → `mxCell`
- ノード: `mxCell vertex="1"` + `mxGeometry(x,y,w,h)`
- エッジ: `mxCell edge="1" source="..." target="..."` + `mxGeometry relative="1"`

### B. drawio MCPで“開いているDraw.io”を操作

例: `lgazo/drawio-mcp-server`

- メリット: shape library を探索しつつ追加できる（`get-shape-*`, `add-cell-of-shape` 等）
- デメリット: Node.js v20+ とブラウザ拡張が前提になりやすく、バッチ用途は複雑化しがち

MVPでは **A（XML直生成）** を採用し、Bはオプションにするのが安全。

## 2) Azure収集: まずARG（Azure Resource Graph）

収集の優先順位（MVP）:

1. `az graph query`（ARG）: 横断的に取得しやすく、`join/mv-expand/parse` で関係も作りやすい
2. `az resource list` : 一覧は簡単だが関係抽出を後段で頑張る必要が出やすい
3. ARM REST/SDK : 詳細は強いがN+1になりやすい（MVPでの実装負担が増えがち）

ARGの例（公式サンプルがある関係）:

- VM→NIC→Public IP（`mv-expand` + `leftouter join`）
- NIC→Subnet（subnetIdを `parse kind=regex` で分解）

注意:

- ARGはKQLのサブセットで、`join` / `mv-expand` 回数など制約があるため、クエリ分割→マージが現実的

## 3) 推奨MVPアーキテクチャ（超要約）

- Collector: `az graph query` で nodes/edges を抽出（view別に2〜3本のクエリ）
- Normalizer: `nodes[]/edges[]` に正規化して `env.json` として保存
- Renderer: `.drawio` XML を生成して保存（固定グリッド配置でMVP成立）

## 参考（一次情報）

- drawio-mcp-server: https://github.com/lgazo/drawio-mcp-server
- az graph query（Azure CLI）: https://learn.microsoft.com/cli/azure/graph?view=azure-cli-latest
- Resource Graph 高度なサンプル: https://learn.microsoft.com/azure/governance/resource-graph/samples/advanced
- Resource Graph クエリ言語: https://learn.microsoft.com/azure/governance/resource-graph/concepts/query-language
