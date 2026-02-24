# FY26 GitHub Copilot SDK Enterprise Challenge — Submission Draft

> **Contest**: FY26 GitHub Copilot SDK Enterprise Challenge (MCAPS internal)
> **Deadline**: 2026-03-07 22:00 PST
> **Submit**: SharePoint form (https://microsoft.sharepoint.com/teams/GithubSales/SitePages/FY26SDKChallenge.aspx)
> **Requirements**: [docs/sdk-challenge-requirements.md](../../docs/sdk-challenge-requirements.md)

---

## 1. Project Summary (150 words max)

**Azure Ops Dashboard** is a desktop application that reads a live Azure environment and generates architecture diagrams plus AI-powered security and cost reports — all from one click.

The tool connects to Azure Resource Graph to inventory resources, then produces Draw.io diagrams (inventory and network topology views) with Azure-official icons and deterministic layout. Security and cost reports are generated via the **GitHub Copilot SDK**, streaming AI analysis enriched with Microsoft Learn documentation. Diff reports automatically compare with previous runs to track environment drift.

Key capabilities: template customization (section ON/OFF, custom instructions), Japanese/English runtime switching, Word/PDF/SVG export, and PyInstaller single-exe packaging. The solution targets enterprise IT operations teams who need quick Azure environment visualization and actionable insights without juggling multiple portals, CLI commands, and manual documentation.

32 unit tests run without Azure CLI or SDK connectivity. Cross-platform: Windows (full + exe), macOS, Linux.

---

## 2. Demo Video (3 min max)

<!-- TODO: 撮影後にリンクを貼る -->

- [ ] YouTube or Stream link: (TBD)

### デモシナリオ案 (3分)

| 時間      | 内容                                                                                    |
| --------- | --------------------------------------------------------------------------------------- |
| 0:00–0:20 | 問題提起: Azure 環境の可視化・レポート作成が手作業で大変                                |
| 0:20–0:50 | GUI 起動、サブスクリプション選択、inventory ビューで Collect → Draw.io 図が生成される   |
| 0:50–1:20 | network ビューに切替 → VNet/Subnet 階層の図が生成される                                 |
| 1:20–2:00 | security-report 選択 → テンプレートカスタマイズ → AI レポート生成（ストリーミング表示） |
| 2:00–2:30 | レポートの中身を見せる（セキュアスコア、推奨事項、Learn ドキュメントリンク）            |
| 2:30–2:50 | 言語切替 (EN↔JA)、差分レポート、Word エクスポート                                       |
| 2:50–3:00 | まとめ: Copilot SDK で Azure 運用をワンクリック化                                       |

---

## 3. GitHub Repository

**URL**: https://github.com/aktsmm/azure-ops-dashboard

### 必須ディレクトリ構成 — ギャップ分析

| 要件                                      | 現状                            | 対応                                         |
| ----------------------------------------- | ------------------------------- | -------------------------------------------- |
| `/src` or `/app` (working code)           | ルート直下に `.py` ファイル配置 | ルートを `/app` 扱いとする or README で説明  |
| `/docs` (README, arch diagram, RAI notes) | `README.md` + `DESIGN.md` あり  | **アーキテクチャ図** と **RAI notes** を追加 |
| `AGENTS.md`                               | なし（親リポにはある）          | **新規作成**                                 |
| `mcp.json`                                | なし                            | **新規作成**（Microsoft Learn MCP 設定）     |
| `/presentations/AzureOpsDashboard.pptx`   | なし                            | **新規作成**                                 |

---

## 4. Presentation Deck (1-2 slides)

`/presentations/AzureOpsDashboard.pptx`

### Slide 1: Business Value Proposition

- **Problem**: IT Ops チームは Azure 環境の全体像把握に複数ポータル・CLI を横断。ドキュメント更新は後回しになりがち。
- **Solution**: ワンクリックで As-Is 構成図 + AI セキュリティ/コスト分析レポート生成
- **Value**: 環境把握の工数削減 / セキュリティリスクの早期発見 / コスト最適化の提案 / 変更追跡 (diff)
- **SDK Usage**: Copilot SDK のストリーミング API でリアルタイムレポート生成、動的モデル選択
- **Repo link**: https://github.com/aktsmm/azure-ops-dashboard

### Slide 2: Architecture Diagram

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  tkinter    │     │  Azure CLI       │     │  GitHub Copilot  │
│  GUI        │────▶│  Resource Graph   │     │  SDK             │
│  (main.py)  │     │  Security Center  │     │  (CopilotClient) │
│             │     │  Cost Management  │     │                  │
└──────┬──────┘     │  Advisor          │     └────────┬─────────┘
       │            └──────────────────┘              │
       │                                              │
       ▼                                              ▼
┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐
│ drawio_writer│  │  exporter    │  │  ai_reviewer            │
│ (.drawio XML)│  │ (.docx/.pdf) │  │  (streaming report gen) │
└──────────────┘  └──────────────┘  │  + docs_enricher        │
                                    │    (Learn Search API)   │
                                    └─────────────────────────┘
```

---

## 5. Scoring Self-Assessment

### メインスコア (105 pts)

| 基準                                                   | 配点    | 見込   | 根拠                                                                 |
| ------------------------------------------------------ | ------- | ------ | -------------------------------------------------------------------- |
| Enterprise applicability, reusability & business value | 35      | **30** | Azure 環境可視化は全エンタープライズ共通課題。テンプレート再利用可能 |
| Integration with Azure/MS solutions                    | 25      | **22** | Resource Graph, Security Center, Cost Management, Advisor, Learn API |
| Operational readiness                                  | 15      | **12** | PyInstaller exe / README / 32 tests / CI 未整備                      |
| Security, governance & RAI                             | 15      | **11** | Reader 権限のみ / SP login / secret 非保存 / RAI notes 追加予定      |
| Storytelling & clarity                                 | 15      | **12** | README 充実 / デモ動画 + デック作成予定                              |
| **小計**                                               | **105** | **87** |                                                                      |

### ボーナス (35 pts)

| 基準                             | 配点   | 見込   | 根拠                         |
| -------------------------------- | ------ | ------ | ---------------------------- |
| Work IQ / Fabric IQ / Foundry IQ | 15     | **0**  | 未統合 (検討中)              |
| Customer validation              | 10     | **5**  | 社内利用ドキュメント作成可能 |
| SDK product feedback             | 10     | **10** | 提出予定                     |
| **小計**                         | **35** | **15** |                              |

**合計見込: 約 102 / 140**

---

## 6. TODO — 残タスク

### 必須 (提出に必要)

- [ ] GitHub に `aktsmm/azure-ops-dashboard` リポジトリを作成 & push
- [ ] **デモ動画** (3分以内) を撮影 → YouTube / Stream にアップ
- [ ] **プレゼンデック** (1-2 slides) `/presentations/AzureOpsDashboard.pptx` 作成
- [ ] **AGENTS.md** を azure-ops-dashboard に新規作成
- [ ] **mcp.json** を作成（Microsoft Learn MCP 設定）
- [ ] **アーキテクチャ図** (.drawio or .png) を /docs に追加
- [ ] **RAI notes** を /docs/README に追加
- [ ] SharePoint フォームで提出

### ボーナス

- [ ] SDK product feedback を SDK チーム channel に投稿 + スクリーンショット
- [ ] 社内利用検証ドキュメント作成
- [ ] Work IQ 統合検討

### その他

- [ ] リポジトリ構成を要件に合わせて調整 (`/src` or `/app` 問題)
- [ ] README の英語版をエンハンス (problem → solution, deployment, RAI)

---

## 7. SDK Product Feedback Draft (+10 pts bonus)

**Post to**: SDK チーム Teams channel

**Title**: Feedback from Azure Ops Dashboard — GitHub Copilot SDK (Python)

**Feedback**:

I built **Azure Ops Dashboard**, a tkinter desktop app that generates architecture diagrams and AI-powered security/cost reports from live Azure environments using the Copilot SDK.

**What worked well:**

- `CopilotClient` streaming API (`turn.stream()`) was easy to integrate for real-time report generation in a GUI. Async streaming → tkinter `after()` batching pattern worked cleanly.
- `await client.get_models()` made dynamic model selection straightforward (users can pick from available models in a dropdown).
- The SDK's authentication via Copilot CLI (`copilot auth login`) is simple for internal tools.

**Pain points / Feature requests:**

1. **Model listing latency**: `get_models()` can take 3-5s on first call. A cached/local model list option would help GUI responsiveness.
2. **Error messages on auth failure**: When `copilot auth login` hasn't been run, the error message from `CopilotClient.start()` is generic. A specific "not authenticated — run `copilot auth login`" message would save debugging time.
3. **Timeout control**: No built-in per-request timeout on `turn.stream()`. We had to wrap with `asyncio.wait_for()` + manual cancellation (see L7 learning). A `timeout_s` parameter on send/stream would be welcome.
4. **MCP tool integration**: We used Microsoft Learn MCP for docs enrichment alongside the SDK. Native MCP tool registration in `CopilotClient` (like `onPreToolUse` callback) would simplify the integration.
5. **Windows spawn compatibility**: SDK's async internals occasionally conflict with `multiprocessing.spawn` on Windows. Documentation on threading best practices (event loop in worker thread) would help.

**Environment**: Python 3.11, Windows 11, Copilot CLI, tkinter GUI with background threading.
