# SDK Enterprise Challenge — アイデア一覧 & 判断記録

> 作成日: 2026-02-20  
> 提出期限: 2026-03-07 10PM PST（日本時間 3/8 15:00）

---

## 確定プロジェクト

| #   | プロジェクト                       | スコア   | ステータス |
| --- | ---------------------------------- | -------- | ---------- |
| 🥇  | **Voice-first Enterprise Copilot** | 131/135  | 本命       |
| 🥈  | Azure Env Builder CLI              | ~120/135 | 中間・保険 |

---

## Azure Env Builder CLI（中間プロジェクト）

**コンセプト**: 自然言語で Azure 環境を自律構築する CLI ツール。

```
$ envbuilder "AI Search + Cosmos DB + Container Apps の検証環境作って"
  → SDK が要件を解釈
  → Bicep テンプレートを動的に生成
  → デプロイ実行
  → エラー → 原因分析 → 修正 → リトライ（自律ループ）
  → 完了報告 + 接続情報
```

**SDK の必然性**: 自然言語 → Bicep 生成 → デプロイ → エラー修正の自律ループはスクリプトでは不可能。

**既存資産**:

- `azure-env-builder` スキル（Agent-Skills リポ）
- `azure-autodeploy` エージェント（20260208 セッション実績: AI Search + Cosmos DB 自律デプロイ済み）
- `Iac` リポの Bicep テンプレート集

**推定スコア**:

| 基準               | 配点 | 見込   | 理由                       |
| ------------------ | ---- | ------ | -------------------------- |
| エンプラ適用性     | 35   | 30     | インフラチーム全員が使える |
| Azure 統合         | 25   | **25** | Azure そのものが対象       |
| 運用準備           | 15   | 12     | CLI ツールとして配布可能   |
| セキュリティ/RAI   | 15   | 11     | デプロイ前の確認フロー     |
| ストーリーテリング | 15   | 12     | 自然言語→環境構築のデモ    |
| IQ ボーナス        | 15   | 10     | 過去のデプロイ履歴検索     |
| SDK フィードバック | 10   | 10     | 確実に実施                 |
| 顧客バリデーション | 10   | 5      | 社内利用                   |

**Voice Agent との関係**: Agent Skills にそのまま昇格 → 「検証環境作って」で音声から全自動。

---

## 判断記録

### SDK じゃないとダメかの判定

| やりたいこと                   | スクリプトで可能？    | SDK 必要？ |
| ------------------------------ | --------------------- | ---------- |
| Azure リソース一覧取得         | ✅ `az resource list` | ❌         |
| コストデータをグラフ化         | ✅ `az cost query`    | ❌         |
| **音声 I/O**                   | ❌                    | ✅         |
| **自然言語での対話操作**       | ❌                    | ✅         |
| **複数ツール横断の自律判断**   | ❌                    | ✅         |
| **非定型の自然言語入力に対応** | ❌                    | ✅         |
| 定型レポート生成               | ✅ cron + script      | △          |
| ダッシュボード表示             | ✅ Grafana / Power BI | ❌         |

### Whisper vs Azure Speech

| 項目             | Azure Speech               | Whisper        |
| ---------------- | -------------------------- | -------------- |
| リアルタイム性   | ◎ `continuous_recognition` | △ ファイル単位 |
| レイテンシ       | ◎ 数百ms                   | △ 1〜3秒       |
| Azure スコア加点 | ✅                         | ❌             |
| 日本語精度       | ○                          | ◎              |
| オフライン       | ❌                         | ✅             |

**結論**: コンテスト用は Azure Speech 一択。将来的にはハイブリッド（`SPEECH_ENGINE=azure|whisper`）。

---

## 没にしたアイデアとその理由

| アイデア              | 没理由                                                |
| --------------------- | ----------------------------------------------------- |
| Onboarding Buddy      | Dev Box 構築が難しい                                  |
| Incident Commander    | 実装が重すぎる                                        |
| Compliance Auditor    | 特になし                                              |
| Meeting Prep Agent    | 優先度低い                                            |
| PR Review Sensei      | よくある。GitHub 純正と被る                           |
| Cost Guardian         | Work IQ 弱い                                          |
| Azure Dashboard       | **SDK じゃなくてもできる**（az CLI + Grafana で十分） |
| Knowledge Capture CLI | Azure 弱い                                            |
| Repo Onboarder        | Azure 弱い                                            |
| Teams Bot             | Bot Framework セットアップが重い                      |
