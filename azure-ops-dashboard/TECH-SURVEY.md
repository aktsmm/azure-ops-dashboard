# Step10: Azure Ops Dashboard（GUI）— 技術調査（要約）

> 作成日: 2026-02-20

技術調査SSOTは以下。

- `docs/azure-env-diagrammer-tech-survey.md`

要点（MVP結論）:

- Azure収集: `az graph query`（Azure Resource Graph）優先
- 図生成: `.drawio`（mxfile XML）直生成を優先（依存が軽い）
- drawio MCP: ブラウザ拡張前提になりやすいので、後段のオプション
