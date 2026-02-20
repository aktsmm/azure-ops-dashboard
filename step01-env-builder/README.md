# Step 1: Azure Env Builder CLI

自然言語 → Bicep 生成 → Azure デプロイ → 失敗修復ループを行う CLI（Step 3 で Voice Agent のスキルに昇格予定）。

- 設計: [DESIGN.md](DESIGN.md)

## 実行（予定）

```bash
uv run python main.py "AI Search + Cosmos DB + Container Apps の検証環境作って"
```

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

## 前提

- `az login` 済み
- デプロイ先サブスク/権限があること
