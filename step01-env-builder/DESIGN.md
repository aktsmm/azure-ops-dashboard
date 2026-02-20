# Step 1: Azure Env Builder CLI — 基本設計 + 詳細設計

> 作成日: 2026-02-20
> 目的: Step 3（Voice-first Enterprise Copilot）の中核スキル候補として、
> 自然言語→Bicep生成→デプロイ→失敗修復ループを CLI 単体で成立させる。

---

## 1. 基本設計（BD）

### 1.1 目的

- 自然言語入力から、検証用 Azure 環境を **自律的に構築**できる CLI を作る
- Copilot SDK を使って「失敗→原因分析→修正→再デプロイ」のループを回す
- Step 3 で Voice Agent のスキル（`azure-env-builder`）として組み込める形にする

### 1.2 スコープ

| IN スコープ                                    | OUT スコープ                           |
| ---------------------------------------------- | -------------------------------------- |
| 自然言語→要件整理→Bicep生成                    | 複雑なGUI（ポータル相当）              |
| `az` 実行によるデプロイ（RG/サブスク内）       | 本番運用の完全自動承認（Step 3で検討） |
| エラー解析→修正→再試行（数回）                 | すべてのAzureサービス対応              |
| 生成物の保存（Bicep/params/ログ/結果レポート） | IaCリポへのPR自動化（将来）            |

### 1.3 成果物（アーティファクト）

- `./out/<timestamp>/` 以下に以下を保存
  - `spec.md`（解釈した要件・前提・制約）
  - `main.bicep` / `main.parameters.json`
  - `deploy.log`（`az` 実行ログ）
  - `result.md`（作ったリソース、接続情報、次アクション）

### 1.4 主要な制約と前提

- 実行環境: Windows / Python 3.11+
- 認証: `az login` 済みを前提（Service Principal 対応は後回し）
- デプロイ単位: Resource Group（既定）
- 破壊的操作は避ける（既存 RG を上書きしない・明示指定が必要）

---

## 2. 詳細設計（DD）

### 2.1 CLI インターフェース（最小）

- 例:
  - `uv run python main.py "AI Search + Cosmos DB + Container Apps の検証環境作って"`

- 引数（設計）
  - `prompt`（必須）: ユーザーの自然言語要件
  - `--subscription`（任意）: サブスクリプションID（省略時は `az account show` の既定）
  - `--resource-group`（任意）: RG名（省略時は生成）
  - `--location`（任意）: `japaneast` など
  - `--what-if`（任意）: `az deployment group what-if` を先に実行

#### 2.1.1 デフォルト（凍結）

- `--location` 省略時: `japaneast`
- `--subscription` 省略時: `az account show` の既定サブスクリプションを使用
- `--resource-group` 省略時: `envb-<timestamp>`（衝突回避のため時刻ベースで生成）
- `out/` の配置: **実行カレントディレクトリ配下**の `./out/<timestamp>/`
  - `timestamp` 形式: `YYYYMMDD-HHMMSS`

#### 2.1.2 終了コード（凍結）

- `0`: `az` が成功（`--what-if` は what-if 成功、通常はデプロイ成功）
- `1`: 失敗（`az` 終了コード非0、タイムアウト、前提不足など）

#### 2.1.3 安全柵（凍結）

- 破壊的操作（例: `az group delete` / `az resource delete`）は **実装しない**
- 既存 RG を明示指定した場合でも、行うのは `az deployment group create/what-if` のみ
- `--resource-group` を明示指定した場合は、RG を作成せず `az group show` で存在確認のみ行う（存在しなければ失敗）
- `--what-if` 指定時は **デプロイは実施しない**（what-if の結果を保存して終了）

#### 2.1.4 生成物の詳細（凍結）

- `spec.md`
  - 入力 `prompt`
  - 実行時の `subscription` / `resource_group` / `location` / `what_if`
  - 使用した `az` コマンド（引数含む）
- `main.bicep` / `main.parameters.json`
  - Bicep/params の完全な内容（再現のため）
- `deploy.log`
  - 実行した `az` コマンド
  - `stdout` / `stderr` / `exit code`
  - タイムアウトがあれば明記
- `result.md`
  - 成功/失敗サマリ
  - 成功時: 主要な outputs / 作成リソースの手がかり（可能な範囲）
  - 失敗時: 次の修復アクション候補（カテゴリだけでも良い）

### 2.2 モジュール分割（案）

- `orchestrator.py`
  - SDKセッション管理、ループ制御（最大試行回数、バックオフ）
- `bicep_generator.py`
  - 要件→Bicep/params 生成（テンプレ+差分編集）
- `azure_cli.py`
  - `az` 呼び出し（標準出力/標準エラー、終了コード、タイムアウト）
- `artifact_store.py`
  - `out/` への保存、再現性（入力/出力/ログ）

※ Step 1 はまず単一 `main.py` でも良いが、Step 3 へ移植しやすい分割を推奨。

### 2.3 失敗修復ループ（最小ルール）

- ループ上限: 3回
- 1回の試行で行うこと
  1. Bicep生成（または前回からの修正）
  2. `az deployment group create`（または what-if）
  3. 失敗時: エラーログから原因カテゴリを特定（命名/プロバイダ登録/リージョン/クォータ/パラメータ）
  4. 修正案を生成して再試行

### 2.4 セキュリティ/ガバナンス（設計メモ）

- 実行コマンドは `az` に限定し、作業ディレクトリも固定する
- デプロイ前に「作るリソース一覧」「推定コスト」「破壊的変更の有無」を要約して確認できる形にする（自動承認は Step 3）

---

## 3. テスト計画（最小）

- `az login` 済み環境で、Resource Group へのデプロイが成功すること
- 意図的に失敗する入力（無効リージョン/無効SKU）で、修復ループが動くこと
- `out/` に生成物一式が保存され、再現可能であること
