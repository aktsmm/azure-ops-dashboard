# AI プロンプト構成一覧

Azure Ops Dashboard で AI レポート生成に使用されるプロンプトの全体像。

---

## 1. リソースレビュー（inventory / network ビュー）

| 層                | 内容                                                        | ソース                                                          |
| ----------------- | ----------------------------------------------------------- | --------------------------------------------------------------- |
| **System Prompt** | Azure インフラレビュー専門家。5観点で500字以内に要約        | `ai_reviewer.py` — `_system_prompt_review()`                    |
| **言語指示**      | `ai.output_language` — 末尾に「日本語/英語で出力」を追記    | `i18n.py`（キー） + `ai_reviewer.py`（`AIReviewer.generate()`） |
| **User Prompt**   | 「以下のAzureリソース一覧をレビューしてください」+ テキスト | `ai_reviewer.py` — `AIReviewer.review()`                        |

### System Prompt 概要（日本語モード）

```text
あなたは Azure インフラストラクチャのレビュー専門家です。
ユーザーから Azure Resource Graph で取得したリソース一覧が提供されます。

以下の観点でレビューし、日本語で簡潔にまとめてください:
1. 構成概要 — 何のシステムか推測し、2-3行で説明
2. リソース構成の妥当性 — 冗長性・HA構成の有無、足りないリソースの指摘
3. セキュリティ — NSG, Key Vault, Private Endpoint の有無
4. コスト最適化 — 不要に見えるリソース（NetworkWatcher の重複等）
5. 図にする際のヒント — グループ化の提案

回答は Markdown で、全体 500文字以内に収めてください。
```

---

## 2. セキュリティレポート（security-report ビュー）

| 層                       | 内容                                                               | ソース                                                          |
| ------------------------ | ------------------------------------------------------------------ | --------------------------------------------------------------- |
| **System Prompt (base)** | Azure セキュリティ監査専門家                                       | `ai_reviewer.py` — `_system_prompt_security_base()`             |
| **+ CAF ガイダンス**     | 準拠FW / 環境固有分析 / Docs検索 / 深刻度分類                      | `ai_reviewer.py` — `_caf_security_guidance()`                   |
| **+ テンプレート指示**   | セクション ON/OFF + 出力オプション                                 | `ai_reviewer.py` — `build_template_instruction()`               |
| **+ カスタム指示**       | フリーテキスト + 保存済み指示                                      | `main.py`（UI） + `ai_reviewer.py`（合成）                      |
| **+ 言語指示**           | system prompt 末尾に追記                                           | `i18n.py`（キー） + `ai_reviewer.py`（`AIReviewer.generate()`） |
| **User Prompt**          | サブスク名 → 依頼文 → セキュリティデータ → リソース一覧 → Docs参照 | `ai_reviewer.py` — `_run_report()`                              |
| **Docs 検索**            | `Azure security best practices` + タイプ別 (max 3)                 | `docs_enricher.py` — `security_search_queries()`                |

### レポートのレビューゲート（保存前）

AI レポート生成後、**Proceed / Cancel** の確認ステップを挟み、ユーザーがログ上の内容を確認してから保存に進みます。

### System Prompt 概要

```text
あなたは Azure セキュリティ監査の専門家です。
Azure Security Center / Microsoft Defender for Cloud のデータと、
実際の Azure 環境のリソース一覧が提供されます。

「この環境固有の具体的な指摘」を書いてください。
一般論ではなく、「この環境の ○○ は △△ だから □□ すべき」という具体性を最優先。
```

### CAF ガイダンス

```text
## 準拠フレームワーク
- CAF — セキュリティベースライン
- WAF — Security Pillar
- Azure Security Benchmark v3 (ASB)
- Microsoft Defender for Cloud 推奨事項

## 環境固有の分析指示
- リソース名・タイプを具体的に挙げてコメント
- NSG未設定 VM, Public IP 露出, Key Vault 未使用等を具体名で指摘

## 出力ルール
- 深刻度: Critical / High / Medium / Low
- 「根拠: [CAF Security Baseline](URL)」形式
- 環境に存在しないリソースの指摘はしない
```

---

## 3. コストレポート（cost-report ビュー）

| 層                       | 内容                                                        | ソース                                            |
| ------------------------ | ----------------------------------------------------------- | ------------------------------------------------- |
| **System Prompt (base)** | Azure コスト最適化専門家                                    | `ai_reviewer.py` — `_system_prompt_cost_base()`   |
| **+ CAF ガイダンス**     | 準拠FW / コスト上位リソース / 金額付き                      | `ai_reviewer.py` — `_caf_cost_guidance()`         |
| **+ テンプレート指示**   | セクション ON/OFF + オプション + 通貨記号                   | `ai_reviewer.py` — `build_template_instruction()` |
| **+ カスタム指示**       | 同上                                                        | `main.py`（UI） + `ai_reviewer.py`（合成）        |
| **User Prompt**          | サブスク名 → 依頼文 → コストデータ → Advisor推奨 → Docs参照 | `ai_reviewer.py` — `_run_report()`                |
| **Docs 検索**            | `Azure cost optimization best practices` + タイプ別 (max 3) | `docs_enricher.py` — `cost_search_queries()`      |

### レポートのレビューゲート（保存前）

AI レポート生成後、**Proceed / Cancel** の確認ステップを挟み、ユーザーがログ上の内容を確認してから保存に進みます。

### System Prompt 概要

```text
あなたは Azure コスト最適化の専門家です。
Azure Cost Management のデータ（サービス別・RG別コスト）と、
実際の Azure 環境のリソース一覧が提供されます。

「この環境固有の具体的な指摘」を書いてください。
一般論ではなく、「この環境の ○○ は △△ だから □□ すべき」という具体性を最優先。
```

### CAF ガイダンス

```text
## 準拠フレームワーク
- CAF — コスト管理ベストプラクティス
- WAF — Cost Optimization Pillar
- FinOps Framework
- Azure Advisor — コスト推奨事項

## 環境固有の分析指示
- コスト上位リソースを具体名 + SKU ダウングレード / 予約購入を言及
- 「○○ は 月額 X円 → △△ すれば Y 円 削減可能」
- 未使用・低稼働リソースは具体名で停止・削除を推奨
- タグ未設定 → FinOps「コスト配分」観点で指摘

## 出力ルール
- 「根拠: [WAF Cost Optimization](URL)」形式
- 金額は通貨記号付き、表で読みやすく
- 環境に存在しないリソースの指摘はしない
```

---

## 4. テンプレート指示（system prompt に追加）

`build_template_instruction()` がテンプレート JSON からAI向け指示を生成。

### 出力例

```text
## レポート構成指示

### 含めるセクション（必ず出力すること）:
- 構成概要: システム構成の推測と2-3行の概要説明
- セキュアスコア: 現在のスコアと評価
- 推奨事項 (High): 重要度Highの詳細と修復手順
- 推奨アクション: 優先度付きアクションプラン

### 含めないセクション（出力しないこと）:
- 推奨事項 (Medium)
- 推奨事項 (Low)
- セキュリティアラート ...

### 出力オプション:
- リソースID省略、名前のみ表示
- Mermaid チャートなし
- 詳細項目は最大 5 件
- サブスクリプションIDマスク
```

### テンプレート一覧

| ファイル                  | 名前      | タイプ   | 概要                              |
| ------------------------- | --------- | -------- | --------------------------------- |
| `security-executive.json` | Executive | security | 経営層向け (4セクションON)        |
| `security-standard.json`  | Standard  | security | 全セクション有効 (10セクションON) |
| `cost-executive.json`     | Executive | cost     | 経営層向け (4セクションON)        |
| `cost-standard.json`      | Standard  | cost     | 全セクション有効 (8セクションON)  |

---

## 5. 保存済み指示（カスタム指示として選択可）

`templates/saved-instructions.json` で管理。チェックボックスで複数選択可能。

| 指示名                 | 内容                                |
| ---------------------- | ----------------------------------- |
| 経営層向け要約         | 技術用語を避け、3-5点に箇条書き     |
| 英語併記               | タイトルと要約を日英併記            |
| アクションアイテム重視 | 担当者・期限付きの次アクション      |
| コンプライアンス準拠   | ISO 27001 / SOC 2 の観点を追加      |
| 簡潔（500字以内）      | 最重要ポイントだけ                  |
| CAF 深掘り             | CAF 各フェーズに対応付け + Docs検索 |
| WAF 5 Pillars 評価     | 5つの柱で環境を評価 + Docs検索      |
| リソース別の改善提案   | 1リソースずつ具体名で改善提案       |
| Docs 引用を強化        | 全推奨事項に Learn URL必須          |

---

## 6. MCP ツール（AI が自律利用）

| ツール                  | エンドポイント                        | 用途                               |
| ----------------------- | ------------------------------------- | ---------------------------------- |
| `microsoft_docs_search` | `https://learn.microsoft.com/api/mcp` | Microsoft Learn 検索 → 引用URL付与 |

補足:

- セキュリティ/コストのレポート生成では、プロンプトに **WAF / CAF の静的参照** と **検索クエリ** も含め、Well-Architected / Cloud Adoption Framework の根拠URLを付けやすくしています。

---

## 7. プロンプト合成フロー

```
+---------------------------------------------------+
|  System Prompt                                    |
|  +----------------------------------------------+ |
|  | base: 専門家ロール定義                        | |
|  |  + CAF ガイダンス                             | |
|  |    (フレームワーク/環境固有指示/出力ルール)    | |
|  +----------------------------------------------+ |
|  | テンプレート指示                              | |
|  |  (セクション ON/OFF + オプション)             | |
|  +----------------------------------------------+ |
|  | カスタム指示                                  | |
|  |  (保存済み + フリーテキスト)                  | |
|  +----------------------------------------------+ |
|  | 言語指示 (JA/EN)                              | |
|  +----------------------------------------------+ |
+---------------------------------------------------+
|  User Prompt                                      |
|  +----------------------------------------------+ |
|  | 対象サブスクリプション名                      | |
|  | レポート生成依頼文                            | |
|  | データセクション (JSON)                       | |
|  |  - セキュリティデータ or コストデータ         | |
|  |  - Advisor推奨事項 (cost のみ)                | |
|  | リソース一覧 (security のみ)                  | |
|  | Microsoft Docs 参照ブロック                   | |
|  +----------------------------------------------+ |
+---------------------------------------------------+
|  MCP Tools                                        |
|  +- microsoft_docs_search (AI が自律呼び出し)     |
+---------------------------------------------------+
```

---

## 8. 言語切替

`get_language()` の戻り値 (`"ja"` / `"en"`) に応じて:

- System Prompt 全体が日本語版/英語版に切替
- CAF ガイダンスも日英対応
- User Prompt の依頼文も日英対応
- 末尾に `ai.output_language` 指示を追記
