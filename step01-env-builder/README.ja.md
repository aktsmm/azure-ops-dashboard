English: [README.md](README.md)

# Step 01: Azure Env Builder CLI

自然言語の要件から Bicep を生成し、`az deployment group` で **what-if（プレビュー）/ 実デプロイ** を行う CLI です。
実行ごとに `out/<timestamp>/` に成果物（Bicep/ログ/結果）を保存します。

- 設計: [DESIGN.md](DESIGN.md)

## 前提

- Python 3.11+
- `uv` が利用できること
- Azure CLI（`az`）が利用できること
- `az login` 済み
- デプロイ先サブスクリプションに権限があること

## セットアップ（共通）

ワークスペースルートで:

```powershell
uv venv
uv pip install -e .
```

## 実行

```powershell
cd .\step01-env-builder

# RG 未指定の場合、RG は自動で envb-<timestamp> が作られます
uv run python .\main.py "storageだけの検証環境" --what-if

# サブスク/RG/リージョンを明示
uv run python .\main.py "storageだけの検証環境" --subscription <SUB_ID> --resource-group <RG> --location japaneast --what-if
```

## 成果物（`out/<timestamp>/`）

- `spec.md`（入力/ターゲット/実行する az コマンド一覧）
- `main.bicep`（生成 Bicep）
- `main.parameters.json`
- `deploy.log`（実行ログ: az コマンド + stdout/stderr）
- `result.md`（結果、エラー分類、次アクション、outputs）

## 推奨: 新規RGで分離（what-if → deploy）

同じ Resource Group で `--what-if`（プレビュー）→ 実デプロイを流すと、検証と後片付けが楽です。

```powershell
cd .\step01-env-builder
$loc = 'japaneast'
$rg = 'envb-' + (Get-Date -Format yyyyMMdd-HHmmss)

az group create -n $rg -l $loc

# プレビュー（リソース作成なし）
uv run python .\main.py "storageだけの検証環境" --what-if --resource-group $rg --location $loc

# 実デプロイ
uv run python .\main.py "storageだけの検証環境" --resource-group $rg --location $loc

# 後片付け（必要なら）
az group delete -n $rg --yes --no-wait
```

※ `az group delete` は削除操作です。サブスクリプション/RG を必ず確認してください。
