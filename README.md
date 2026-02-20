# FY26 GitHub Copilot SDK Enterprise Pattern Challenge

> 作成日: 2026-02-20  
> 提出期限: **2026-03-07 10PM PST**（日本時間 3/8 15:00）

---

## このワークスペースの目的

GitHub Copilot SDK Enterprise Challenge の **開発・提出** を行うワークスペース。  
企画・知見は `D:\03.5_GHC_Research` で蓄積済み → 本ワークスペースは **実装に集中**。

---

## 🎯 確定プラン（4段階ロードマップ）

```
Step 0:   SDK Chat CLI（素振り / 15分）
  → CopilotClient → create_session → send_and_wait の最小動作確認
  ↓
Step 0.5: ディクテーションツール（音声レイヤー先行実装 / 1時間）
  → Azure Speech STT + pyautogui で音声→テキスト入力
  → SDK は使わないが、Voice Agent の音声レイヤーの先行実装
  ↓
Step 1:   Azure Env Builder CLI（中間プロジェクト / 2〜3日）
  → 自然言語 → Bicep 生成 → デプロイ → エラー修正ループ → 結果報告
  → ★提出候補（2本目）
  ↓
Step 2:   Voice-first Enterprise Copilot（本命 / 残り期間）
  → Step 0 + Step 0.5 + Step 1 を統合
  → 音声 I/O + SDK 対話 + Env Builder スキル + スキル自動同期 + Work IQ
  → ★メイン提出
```

---

## 提出プロジェクト

| #   | プロジェクト                       | スコア   | 状態       |
| --- | ---------------------------------- | -------- | ---------- |
| 🥇  | **Voice-first Enterprise Copilot** | 131/135  | 本命       |
| 🥈  | Azure Env Builder CLI              | ~120/135 | 中間・保険 |

---

## スケジュール

| 期間       | タスク                           | SDK | 成果物                            |
| ---------- | -------------------------------- | --- | --------------------------------- |
| 2/20       | Step 0: SDK Chat CLI（素振り）   | ✅  | 最小動作確認                      |
| 2/20〜2/21 | Step 0.5: ディクテーションツール | ❌  | Azure Speech STT + pyautogui      |
| 2/21〜2/23 | Step 1: Azure Env Builder CLI    | ✅  | 提出候補2本目                     |
| 2/24〜3/5  | Step 2: Voice Agent 本開発       | ✅  | メイン提出物（Step 0+0.5+1 統合） |
| 3/6〜3/7   | デモ動画撮影 + デック + README   | -   | 提出                              |

---

## フォルダ構成

```
sdk-enterprise-challenge/
├── README.md                 # ← このファイル
├── docs/
│   ├── design.md             # Voice Agent 詳細設計
│   ├── tech-reference.md     # SDK 技術リファレンス
│   ├── idea-list.md          # アイデア一覧 & 判断記録
│   └── knowledge-summary.md  # Research WS からの知見サマリー
├── step00-chat-cli/          # Step 0: SDK 素振り
├── step01-env-builder/       # Step 1: Azure Env Builder CLI
├── step02-dictation/         # Step 2: 音声入力ツール
├── voice-agent/              # Step 3: Voice Agent（本命）
│   ├── src/                  # ソースコード
│   ├── AGENTS.md
│   ├── mcp.json
│   └── skills/               # Agent-Skills 自動同期先
├── azure-ops-dashboard/      # Azure 環境→図・レポート生成 (AzureOpsDashboard)
└── presentations/            # デモデック
```

---

## 提出要件チェックリスト

### 必須提出物

- [ ] プロジェクト概要（150 words max）
- [ ] デモ動画（3分以内）
- [ ] GitHub リポジトリ（README, アーキテクチャ図, セットアップ手順）
- [ ] プレゼンデック（1-2スライド）

### リポジトリ必須構成

- [ ] `/src` or `/app` — 動作するコード
- [ ] `/docs` — README（問題→解決策, 前提条件, セットアップ, デプロイ, アーキテクチャ図, RAI notes）
- [ ] `AGENTS.md` — カスタムインストラクション
- [ ] `mcp.json` — MCP サーバー設定
- [ ] `/presentations/` — デモデック (.pptx) or 公開ポストリンク

### ボーナス

- [ ] `/customer` — 署名済み顧客テスティモニアルリリース
- [ ] SDK チームチャネルへのプロダクトフィードバック投稿（スクリーンショット付き）

---

## 審査基準

### メインスコア（100点）

| 基準                                           | 配点       |
| ---------------------------------------------- | ---------- |
| エンタープライズ適用性・再利用性・ビジネス価値 | **35 pts** |
| Azure / Microsoft ソリューションとの統合       | **25 pts** |
| 運用準備（デプロイ可能性, 可観測性, CI/CD）    | 15 pts     |
| セキュリティ, ガバナンス, Responsible AI       | 15 pts     |
| ストーリーテリング, 明確さ, 発信品質           | 15 pts     |

### ボーナス（最大35点）

| 基準                                    | 配点       |
| --------------------------------------- | ---------- |
| Work IQ / Fabric IQ / Foundry IQ の活用 | **15 pts** |
| 顧客バリデーション                      | 10 pts     |
| Copilot SDK プロダクトフィードバック    | 10 pts     |

---

## キー日程

| マイルストーン     | 日付                    | 状態 |
| ------------------ | ----------------------- | ---- |
| キックオフ         | 2026-02-09              | ✅   |
| Office Hours #2    | 2026-02-26              | ⬜   |
| Office Hours #3    | 2026-03-05              | ⬜   |
| **提出期限**       | **2026-03-07 10PM PST** | ⬜   |
| 審査スクリーニング | 2026-03-09 〜 03-20     | -    |
| 最終プレゼン       | 2026-03-23 〜 03-27     | -    |
| 結果発表           | 4月コミュニティコール   | -    |

---

## 元ワークスペース参照（必要時のみ）

| 内容                    | パス                                                                             |
| ----------------------- | -------------------------------------------------------------------------------- |
| 調査・知見蓄積          | `D:\03.5_GHC_Research\sdk-enterprise-challenge\`                                 |
| kinfey/shinyay リポ調査 | `D:\03.5_GHC_Research\research\copilot\20260220-shinyay-kinfey-repo-research.md` |
| SDK 知見                | `D:\03.5_GHC_Research\_output-knowledge\copilot\`                                |
