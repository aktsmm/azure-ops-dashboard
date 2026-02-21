---
type: coding
exported_at: 2026-02-21T09:01:40
tools_used: [run_in_terminal, apply_patch, manage_todo_list, runSubagent, multi_tool_use.parallel]
outcome_status: partial
---

# Azure Ops Dashboard: レポート改善 + SPログイン + フォルダリネーム

## Summary

AIレポートのレビューゲート追加・WAF/CAFの根拠参照強化・Service Principalログイン対応・Azure CLI収集スクリプト追加まで実装した。プロジェクトフォルダは `azure-ops-dashboard/` へ移行したが、旧フォルダのローカル残骸（ロック等の影響）は残る可能性がある。

## Timeline

### Phase 1 - プロンプト把握

- AIプロンプトの組み立て箇所（system/user prompt、テンプレ、Docs参照）を洗い出し
- まとめドキュメント作成
- Modified: [azure-ops-dashboard/docs/prompt-map.md](azure-ops-dashboard/docs/prompt-map.md)

### Phase 2 - レポート生成フローの改善（レビュー工程）

- inventory/network に存在していた Proceed/Cancel を、security/cost レポートにも追加（保存前確認）
- Modified: [azure-ops-dashboard/main.py](azure-ops-dashboard/main.py)

### Phase 3 - Docs参照強化（WAF/CAF）+ 顧客に寄り添うトーン

- Docs参照（静的参照＋検索クエリ）に WAF/CAF を追加して根拠URLが付けやすい状態へ
- レポート用 system prompt に「できている点の承認」「建設的」「Quick win/Strategic」などのトーン規約を追加
- テンプレ指示（`build_template_instruction`）を日英対応
- Modified: [azure-ops-dashboard/docs_enricher.py](azure-ops-dashboard/docs_enricher.py)
- Modified: [azure-ops-dashboard/ai_reviewer.py](azure-ops-dashboard/ai_reviewer.py)
- Modified: [azure-ops-dashboard/i18n.py](azure-ops-dashboard/i18n.py)

### Phase 4 - Service Principalログイン対応 + 収集スクリプト化

- GUIに `🔐 SP login` を追加（Secretは保存せず、Client/Tenantのみ永続化）
- Azure CLI の収集を PowerShell スクリプトとして提供（監査・再実行が容易）
- レポート生成時の入力（収集データ/テンプレ/指示）を `*-input.json` として保存
- Modified: [azure-ops-dashboard/main.py](azure-ops-dashboard/main.py)
- Modified: [azure-ops-dashboard/i18n.py](azure-ops-dashboard/i18n.py)
- Added: [azure-ops-dashboard/scripts/collect-azure-env.ps1](azure-ops-dashboard/scripts/collect-azure-env.ps1)

### Phase 5 - 収集ロジックの拡張足場（ディスパッチ）

- diagram view の分岐を `collector.collect_diagram_view()` に寄せて、今後の追加を容易に
- Modified: [azure-ops-dashboard/collector.py](azure-ops-dashboard/collector.py)
- Modified: [azure-ops-dashboard/main.py](azure-ops-dashboard/main.py)

### Phase 6 - C-2: フォルダリネーム（step10-azure-env-diagrammer → azure-ops-dashboard）

- Windows のロックでディレクトリ丸ごとの `git mv` が失敗するケースがあり、追跡ファイルを一括移動する方式で対応
- ドキュメントやセッションログのリンク参照を新パスへ更新
- Modified: [README.md](README.md)
- Modified: [output_sessions/20260220-05--step10-i18n-support.md](output_sessions/20260220-05--step10-i18n-support.md)

## Key Learnings

- Windows では `dist/` 配下の exe 生成物がロックされ、ディレクトリリネームが失敗しやすい（プロセス/Explorer/カレントディレクトリが原因になり得る）。
- 収集を「AIにやらせる」より「CLIスクリプトとして固定化」すると、監査性と再現性が上がり、結果的に運用コストが下がる。
- Service Principal（Reader）運用を想定するなら、Secretを永続化しない方針が安全（保存は Client/Tenant のみに限定）。

## Commands & Code

```powershell
# Service Principal login（例）
az login --service-principal -u <APP_ID> -p <CLIENT_SECRET> --tenant <TENANT_ID>

# 収集スクリプト（例）
pwsh .\azure-ops-dashboard\scripts\collect-azure-env.ps1 -SubscriptionId <SUB_ID> -ResourceGroup <RG> -Limit 300 -OutDir <OUTPUT_DIR>

# テスト
cd .\azure-ops-dashboard
uv run python -m unittest tests -v
```

## References

- https://learn.microsoft.com/cli/azure/reference-index
- https://learn.microsoft.com/cli/azure/authenticate-azure-cli#sign-in-with-a-service-principal

## Next Steps

- [ ] 旧フォルダ（ローカル残骸）が残っていれば、ロック解除後に削除する（カレントディレクトリ/Explorer/実行中exeに注意）
- [ ] `azure-ops-dashboard/README.md` の未コミット変更がある場合、意図した内容か確認してコミットする
- [ ] `.spec` を追跡したい場合は `.gitignore` の `*.spec` を見直す（必要なら例外指定）

---

## Timeline (Append)

### Phase 7 - セッションログ再エクスポート

- `exported_at` を更新し、同日ファイルへ追記
- `azure-ops-dashboard/README.md` の差分は PowerShell 表示上は文字化けして見えるが、UTF-8 としては正常に読めることを確認
- 旧フォルダ `step10-azure-env-diagrammer` は空だが、別プロセスが掴んでおり削除できない状態（CWD が残っている可能性が高い）