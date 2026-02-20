---
type: design
exported_at: 2026-02-20T09:44:24
tools_used:
  [
    replace_string_in_file,
    multi_replace_string_in_file,
    create_file,
    run_in_terminal,
    read_file,
    grep_search,
  ]
outcome_status: success
---

# Step10 GUI UX Enhancement — Azure Ops Dashboard

## Summary

Azure Env Diagrammer の GUI を大幅改良。タイトル変更、フォーム再構成、レポートテンプレートカスタマイズ、Word/PDF エクスポート、追加指示の保存・呼び出し、自動保存・自動オープン、Draw.io/VS Code 選択機能を実装した。

## Timeline

### Phase 1 - タイトル・フォーム再構成

- ウィンドウタイトルを `Azure Env Diagrammer` → `Azure Ops Dashboard` に変更
- フォーム順序を View 先頭に変更（View → Subscription → RG → Max Nodes → Output Dir）
- View ラベルを Accent カラー + Bold で視認性向上
- Modified: [main.py](main.py#L48) — `WINDOW_TITLE` 定数変更
- Modified: [main.py](main.py#L145-L240) — フォーム配置を Row 0: View から再構成

### Phase 2 - RG/Limit 動的無効化 + 出力フォルダ

- レポート系 View 選択時に RG / Max Nodes をグレーアウト（不使用表示）
- Output Dir 欄 + `...`（参照）+ `📂`（フォルダを開く）ボタン追加
- Output Dir 設定済みなら保存ダイアログなしで自動保存
- Modified: [main.py](main.py#L464-L498) — `_on_view_changed` 拡張

### Phase 3 - テンプレートカスタマイズ

- レポート種別ごとのプリセット JSON テンプレートを作成（4種）
  - `security-standard.json` / `security-executive.json`
  - `cost-standard.json` / `cost-executive.json`
- GUI にテンプレート選択ドロップダウン + セクション ON/OFF チェックボックス（3列グリッド）
- `💾 Save as…` ボタンでカスタムテンプレート保存
- `ai_reviewer.py` に `build_template_instruction()` を追加、テンプレート設定をシステムプロンプトに反映
- Modified: [ai_reviewer.py](ai_reviewer.py#L1-L120) — テンプレート管理・プロンプト構築追加
- Modified: [main.py](main.py#L240-L330) — レポート設定パネル UI
- Created: [templates/security-standard.json](templates/security-standard.json)
- Created: [templates/security-executive.json](templates/security-executive.json)
- Created: [templates/cost-standard.json](templates/cost-standard.json)
- Created: [templates/cost-executive.json](templates/cost-executive.json)

### Phase 4 - 追加指示の保存・呼び出し

- `templates/saved-instructions.json` にプリセット 5 件を用意
  - 経営層向け要約 / 英語併記 / アクションアイテム重視 / コンプライアンス準拠 / 簡潔
- GUI にチェックボックス行（3列）で ON/OFF 可能
- チェック済み指示 + 自由入力テキストが結合されて AI に渡る
- Modified: [main.py](main.py#L275-L310) — 保存済み指示チェック UI
- Created: [templates/saved-instructions.json](templates/saved-instructions.json)

### Phase 5 - Word / PDF エクスポート

- `exporter.py` を新規作成 — Markdown → Word (.docx) 変換
  - 見出し / 表 / リスト / コードブロック / 引用 / 水平線に対応
  - PDF は Word COM（comtypes）or LibreOffice headless でフォールバック
- GUI に出力形式チェックボックス: `☑ Markdown ☐ Word (.docx) ☐ PDF`
- 依存パッケージ追加: `python-docx`, `markdown`
- Created: [exporter.py](exporter.py)
- Modified: [main.py](main.py#L310-L330) — 出力形式 UI + エクスポート連携

### Phase 6 - 自動オープン + Open App 選択

- 生成後に自動でファイルを開く機能（`☑ 生成後に自動で開く`）
- Open with 選択: `◉ Auto ○ Draw.io ○ VS Code ○ OS既定`
  - Auto: .drawio なら Draw.io → VS Code → OS既定の優先順
  - Draw.io 検出: PATH + `%LOCALAPPDATA%\Programs\draw.io\`
  - VS Code 検出: `code` / `code-insiders` / `code.cmd`
- 検出状態を表示（`✅ Draw.io 検出` / `⚠️ Draw.io 未検出`）
- Modified: [main.py](main.py#L17-L18) — `import shutil, subprocess` 追加
- Modified: [main.py](main.py#L72-L100) — `_detect_drawio_path()`, `_detect_vscode_path()` 追加
- Modified: [main.py](main.py#L237-L255) — Open with ラジオボタン行
- Modified: [main.py](main.py#L1290-L1330) — `_open_file_with()` 共通メソッド

## Key Learnings

- tkinter の動的 UI 制御（`grid`/`pack_forget` での表示/非表示切替）はレイアウト順序に注意が必要 — `before` 引数で制御
- テンプレートをシステムプロンプトにインジェクションする方式なら、セクション ON/OFF が柔軟に効く
- `shutil.which()` で Draw.io / VS Code の検出が簡潔にできる
- Word 出力は `python-docx` で十分実用的。PDF は COM 依存なので環境を問わない方法は課題

## Commands & Code

```python
# Draw.io 自動検出
import shutil
from pathlib import Path

def _detect_drawio_path() -> str | None:
    for name in ("draw.io", "drawio"):
        p = shutil.which(name)
        if p:
            return p
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "draw.io" / "draw.io.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None
```

```python
# テンプレート → AI プロンプト変換
def build_template_instruction(template, custom_instruction=""):
    sections = template.get("sections", {})
    enabled = [f"- {v['label']}" for k, v in sections.items() if v.get("enabled")]
    disabled = [f"- {v['label']}" for k, v in sections.items() if not v.get("enabled")]
    # → システムプロンプトに「含めるセクション」「含めないセクション」として注入
```

## References

- [python-docx documentation](https://python-docx.readthedocs.io/)
- [Draw.io Desktop](https://github.com/jgraph/drawio-desktop)

## Next Steps

- [ ] PDF 変換の非 COM 方式対応（weasyprint 等の検討）
- [ ] テンプレートの import/export 機能（お客様間で共有）
- [ ] 保存済み指示の GUI 上での追加/編集/削除
- [ ] レポート生成履歴の管理（比較機能の前提）
- [ ] ウィンドウサイズの記憶（設定ファイル永続化）
