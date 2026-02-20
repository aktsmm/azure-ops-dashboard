---
type: coding
exported_at: 2026-02-20T06:52:06
tools_used:
  [
    read_file,
    apply_patch,
    create_file,
    list_dir,
    run_in_terminal,
    get_errors,
    manage_todo_list,
  ]
outcome_status: success
---

# Step01 Env Builder — 設計凍結追記 + main.py 骨格実装

## Summary

Step01 の手戻り源（CLI契約/成果物/安全柵）を DESIGN に凍結追記し、`out/<timestamp>/` 保存と `az` 実行ログ採取まで動く `main.py` の骨格を実装しました。

## Timeline

### Phase 1 - Step01 設計の凍結（最小）

- CLI デフォルト（location/RG/out 配置）、終了コード、安全柵、成果物詳細を DESIGN に追記して凍結
- Modified: [step01-env-builder/DESIGN.md](../step01-env-builder/DESIGN.md)

### Phase 2 - Step01 main.py 骨格作成

- `argparse` で `prompt/--subscription/--resource-group/--location/--what-if` を実装
- `out/<timestamp>/` を作り、`spec.md` / `main.bicep` / `main.parameters.json` / `deploy.log` / `result.md` を保存
- `az` 実行ラッパ（stdout/stderr/exit code/timeout）を実装し、`deploy.log` に追記
- `--what-if` 時は `az deployment group what-if` の結果を保存して終了
- Modified: [step01-env-builder/main.py](../step01-env-builder/main.py)

### Phase 3 - バグ修正 + 最小検証

- `az_plan` 参照のタイプミス修正（実行時クラッシュ回避）
- `--parameters` を `@<file>` 形式に修正（az がパラメータファイルとして解釈できる形）
- `spec.md` を実行中に更新し、実際に叩いた `az` コマンド列が欠けないように修正
- `py_compile` と `--help` で最小の健全性チェック
- Modified: [step01-env-builder/main.py](../step01-env-builder/main.py)

## Key Learnings

- 手戻りが起きやすいのは「CLI契約」「成果物」「安全柵」「ログ形式」なので、先に DESIGN 側で凍結すると実装が安定する。
- az の `--parameters` は `@file.json` 指定が安全（文字列として扱われる事故を避けやすい）。

## Commands & Code

```powershell
# exported_at 取得
Get-Date -Format "yyyy-MM-ddTHH:mm:ss"

# 構文チェック
python -m py_compile .\step01-env-builder\main.py

# CLI 引数確認
cd .\step01-env-builder
python .\main.py --help
```

## References

- [Step01 設計](../step01-env-builder/DESIGN.md)

## Next Steps

- [ ] `az login` / `az account show` を確認して、`--what-if` で最小実行を通す
- [ ] `--what-if` を外して最小デプロイ成功（stub Bicep）を通す
- [ ] 失敗修復ループの中身（エラー分類→Bicep/params 修正）を実装する
- [ ] 自然言語→Bicep生成（Copilot SDK）を `main.py` から分離してモジュール化する
