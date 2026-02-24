# FY26 GitHub Copilot SDK Enterprise Challenge — 要件メモ

> Source: https://microsoft.sharepoint.com/teams/GithubSales/SitePages/FY26SDKChallenge.aspx
> 記録日: 2026-02-24

---

## 基本情報

| 項目 | 内容 |
|---|---|
| コンテスト名 | **FY26 GitHub Copilot SDK Enterprise Challenge** |
| 対象 | **All MCAPS FTEs** (Microsoft 社内) |
| チーム | 最大3名 or ソロ |
| 提出期限 | **2026-03-07 22:00 PST** |
| 提出方法 | SharePoint 上のフォーム |

## スケジュール

| 日付 | イベント |
|---|---|
| 2/9 | Kickoff |
| **3/7 10PM PST** | **提出期限** |
| 3/9 〜 3/20 | スクリーニング |
| 3/23 〜 3/27 | ファイナルプレゼン (Top 3) |
| 4月 | コミュニティコールで順位発表 |

## Office Hours (PST)

- 2/19 — 9 AM, 5 PM
- 2/26 — 9 AM, 5 PM
- 3/5 — 9 AM, 5 PM

## 賞品

| 順位 | 内容 |
|---|---|
| 1st | GitHub Swag $250 + Credly Badge + Coaching |
| 2nd | GitHub Swag $150 + Credly Badge + Coaching |
| 3rd | GitHub Swag $100 + Credly Badge + Coaching |
| 全 | Internal & External Amplification |

---

## 提出物要件

### 必須

1. **プロジェクト概要** (150 words max)
2. **デモ動画** (3分以内)
3. **GitHub リポジトリ** (README + アーキテクチャ図 + セットアップ手順)
4. **プレゼンデック** (1-2 slides、ビジネス価値 + アーキテクチャ図、リポリンク含む)

### GitHub リポジトリ必須構成

```
/src or /app           ← 動くコード
/docs                  ← README (問題→解決策, prereqs, setup, deployment, アーキテクチャ図, RAI notes)
AGENTS.md              ← カスタム指示
mcp.json               ← MCP サーバー設定
/presentations/        ← YourSolutionName.pptx or 公開ポストリンク
```

### ボーナス (任意)

- **Product Feedback**: SDK チーム channel にフィードバック投稿 + スクリーンショット提出
- **Customer Validation**: 顧客テスティモニアルリリースフォーム提出（署名済み or 検証ドキュメント）
- **Work IQ / Fabric IQ / Foundry IQ の使用**

---

## 審査基準

### メインスコア (105 点満点)

| 基準 | 配点 |
|---|---|
| Enterprise applicability, reusability & business value | **35 pts** |
| Integration with other Azure or Microsoft solutions | **25 pts** |
| Operational readiness (deployability, observability, CI/CD) | **15 pts** |
| Security, governance & Responsible AI excellence | **15 pts** |
| Storytelling, clarity & "amplification ready" quality | **15 pts** |

### ボーナス (最大 35 pts)

| 基準 | 配点 |
|---|---|
| Use of Work IQ / Fabric IQ / Foundry IQ | **15 pts** |
| Validated with a customer | **10 pts** |
| Copilot SDK product feedback | **10 pts** |

**合計最大: 140 pts**

---

## ジャッジ (ファイナリスト審査)

- **Dan Massey** — CVP, Engineering
- **Jamie Jones** — VP, Field Services
- **Luke Hoban** — VP, Software Engineering
- **Ashley Willis** — Sr. Dir. Developer Advocacy

---

## リソース

- [Copilot CLI quick guide](TBD)
- [Copilot SDK FAQs](TBD)
- [Copilot SDK Repo](https://github.com/github/copilot-sdk)
- [GitHub Copilot Viva Engage Channel](TBD)
- [Building Context-Aware CI with GitHub Copilot SDK and Microsoft WorkIQ](TBD)
- [Build an agent into any app with the GitHub Copilot SDK](https://github.blog/news-insights/company-news/build-an-agent-into-any-app-with-the-github-copilot-sdk/)
- [Customer Evidence Creation Agreement](TBD)

---

## FAQ 要点

- 複数エントリー提出可。複数チーム参加もOK（ただし受賞は1バッジ・1コーチングセッションのみ）
- 英語推奨だが英語力は審査対象外
- 剽窃は失格
- 既存コードの利用は透明に文書化すること（何を元に何を追加したか）
