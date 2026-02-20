---
type: coding
exported_at: 2026-02-20T10:12:56
tools_used: [PyInstaller, uv, az, PowerShell, git]
outcome_status: success
---

# Step10: exe化 + テンプレート上書き + バグ修正 + Learnings

## Summary

Step10 Azure Ops Dashboard の network view クラッシュ修正、PyInstaller による Windows exe 化、テンプレートの bundled+user override 機構の実装、copilot-instructions.md の新規作成、Retrospective Learnings の記録を行った。

## Timeline

### Phase 1 - バグ修正

- `Edge(relation=...)` → `Edge(kind=...)` フィールド名不整合を修正（network view クラッシュ原因）
  - Modified: [collector.py](../collector.py)
- `env.json` の `view` / `edges` がハードコードされていた問題を修正
  - Modified: [main.py](../main.py)
- ステップ表示番号ずれ（Step 2/5 → 3/5 → 4/5 → 5/5）を修正
  - Modified: [main.py](../main.py)
- Word COM オブジェクトが例外時に孤児化する問題を try/finally で修正
  - Modified: [exporter.py](../exporter.py)

### Phase 2 - PyInstaller exe 化

- `app_paths.py` 新規作成 — `sys._MEIPASS` / `Path(__file__).parent` の抽象化
  - Created: [app_paths.py](../app_paths.py)
- `build_exe.ps1` 新規作成 — onedir / onefile 切替ビルドスクリプト
  - Created: [build_exe.ps1](../build_exe.ps1)
  - PowerShell `Resolve-Path` 末尾 `\` 問題を修正（2 attempts → `.Path` プロパティで解決）
- `main.py` / `ai_reviewer.py` のテンプレートパス参照を `app_paths` ベースに切替
  - Modified: [main.py](../main.py), [ai_reviewer.py](../ai_reviewer.py)
- onedir ビルド成功確認 → `dist/AzureOpsDashboard/AzureOpsDashboard.exe` 生成・起動確認

### Phase 3 - テンプレート bundled + user override

- `app_paths.py` に `user_templates_dir()` / `saved_instructions_path()` / `template_search_dirs()` 追加
- `ai_reviewer.py` の `list_templates()` をユーザー領域優先読み込みに変更
- `main.py` の保存済み指示読み込み・テンプレート保存先をユーザー領域に変更
- ユーザー領域: `%APPDATA%\AzureOpsDashboard\templates\`
- 再ビルドして動作確認

### Phase 4 - ドキュメント・Learnings

- README に exe 配布前提条件、配布メモ、テンプレート更新手順を追記
  - Modified: [README.md](../README.md)
- `.github/copilot-instructions.md` 新規作成（Python/Git/Azure/PyInstaller ルール）
  - Created: [../../.github/copilot-instructions.md](../../.github/copilot-instructions.md)
- AGENTS.md に共通 Learnings L1〜L3 追記
  - Modified: [../../AGENTS.md](../../AGENTS.md)
- DESIGN.md にプロジェクト固有 Learnings D1〜D7 追記
  - Modified: [DESIGN.md](../DESIGN.md)
- Agents & Instructions レビュー実施 → copilot-instructions.md 作成、ナンバリング修正

### Phase 5 - コミット

- git init → 初回コミット `d084a25`（115 files）

## Key Learnings

- **D1**: frozen dataclass のフィールド名と呼び出し側キーワード引数は `mypy --strict` で検出すべき
- **D2**: PyInstaller 前提の GUI は最初から `app_paths.py` でリソースパスを抽象化する
- **D3**: 設定/テンプレートは「bundled + user override」二段構えにすると exe 再配布なしで更新可能
- **D4**: CWD 依存の実行パターンは繰り返しミスされる → README 明記 + `-m` 実行対応を検討
- **D5**: PowerShell `Resolve-Path` の戻り値は `.Path` で取り出さないと末尾 `\` が付くケースがある

## Commands & Code

```powershell
# onedir ビルド
pwsh .\build_exe.ps1 -Mode onedir

# onefile ビルド
pwsh .\build_exe.ps1 -Mode onefile

# exe 起動
Start-Process -FilePath ".\dist\AzureOpsDashboard\AzureOpsDashboard.exe"
```

```python
# app_paths.py — リソース基点の抽象化パターン
def resource_base_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).parent

def user_app_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / f".{APP_NAME}"
```

## References

- [PyInstaller Documentation](https://pyinstaller.org/)
- [Copilot SDK Getting Started](https://github.com/github/copilot-sdk/blob/main/docs/getting-started.md)

## Next Steps

- [ ] network view のレイアウト改善（PublicIP/NIC/Subnet/VM の固定並び）
- [ ] `__main__.py` + `-m` 実行対応で CWD 依存解消
- [ ] GitHub Actions で tag → exe 自動ビルド → Release 配置
- [ ] AI レビューのオプトアウト（送信内容マスク / OFF スイッチ）
- [ ] `main.py` 分割（preview.py 等）で保守性向上
