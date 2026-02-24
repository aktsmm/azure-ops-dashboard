# Azure Ops Dashboard — 技術調査（要約）

要点（MVP結論）:

- Azure収集: `az graph query`（Azure Resource Graph）優先
- 図生成: `.drawio`（mxfile XML）直生成を優先（依存が軽い）
- drawio MCP: ブラウザ拡張前提になりやすいので、後段のオプション
