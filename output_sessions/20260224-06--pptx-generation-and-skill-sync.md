---
type: coding
exported_at: 2026-02-24T15:29:43
tools_used: [python-pptx, lxml, zipfile, PIL, PowerShell, git]
outcome_status: success
---

# PPTX Generation, Template Recovery & Skill Sync

## Summary

破損したテンプレート PPTX の修復、16:9 中央揃え問題の解決、デモ動画の ZIP 直接埋め込みを含む PPTX デッキの作成を行い、得られた知見 (L9-L11) をスキルリポジトリに反映・公開同期した。

## Timeline

### Phase 1 - テンプレート PPTX 破損診断と修復

- テンプレート `template.pptx` が `BadZipFile: Bad offset for central directory` で開けない問題を調査
- ZIP ヘッダ (PK) は正常だが、EOCD の Central Directory offset が 3.2GB を指しており完全に異常
- UTF-8 replacement character (`EF BF BD`) が **12,778 箇所** 検出 → Git のテキスト変換による破損と判明
- 原因: `.gitignore` の `skills/` で Git 管理外だったが、skill-ninja インストール時にエンコーディング変換が発生
- `python-pptx` で 16:9 空テンプレートを新規生成して復旧
- Modified: [.github/skills/powerpoint-automation/assets/template.pptx](.github/skills/powerpoint-automation/assets/template.pptx)

### Phase 2 - PPTX デッキ初期生成 (v1-v3)

- `content.json` を作成し、スキルの `create_from_template.py` で 11 スライド生成 → テンプレート修復後に成功
- フォント 14pt が小さすぎ、情報量も削減していた問題を指摘される
- v3: Blank レイアウト + カスタム描画で中央揃え対応、スクショ用スライド 2 枚追加 (13 枚)
- Modified: [azure-ops-dashboard/presentations/content.json](azure-ops-dashboard/presentations/content.json)

### Phase 3 - フォント拡大 + 情報量復元 (v4)

- フォント 28pt/24pt に拡大、元の全情報量を復元
- 1 スライド 3-4 項目に制限し、スライド分割で対応 → 21 枚構成
- 標準テンプレートレイアウト (Title Slide / Title+Content / Section Header / Title Only) を使用
- Modified: [azure-ops-dashboard/presentations/AzureOpsDashboard.pptx](azure-ops-dashboard/presentations/AzureOpsDashboard.pptx)

### Phase 4 - 16:9 中央揃え問題の解決 (v6)

- `Presentation()` デフォルトプレースホルダが **25.4cm (4:3)** 基準であることを特定
- `slide_width = Cm(33.867)` (16:9) に変更してもプレースホルダ位置は不変 → 左寄り
- 全スライドを Blank レイアウト + `add_textbox()` の手動中央配置に統一
- Azure Blue タイトルバー + 対称マージン構成で正確な中央揃えを実現

### Phase 5 - スクリーンショット・デモ動画の追加 (v5-v7)

- `screenshot-gui.png`, `screenshot-cost-report.png` を配置・リネーム
- v5: PIL で画像アスペクト比を計算し、スクショをスライドに自動挿入
- v7: `lxml` + `zipfile` で PPTX の ZIP 構造を直接操作し、**デモ動画 (MP4)** をスライド 10 に埋め込み
  - `p:pic` + `a:videoFile` + `p14:media` の XML パターン
  - Content_Types に mp4 拡張子を追加
  - ポスター画像 (screenshot-gui.png) をサムネイルとして設定
- Modified: [azure-ops-dashboard/docs/media/](azure-ops-dashboard/docs/media/)

### Phase 6 - 知見反映 & スキル同期

- L9 (16:9 中央揃え), L10 (バイナリ破損防止), L11 (動画埋め込み) を抽出
- powerpoint-automation SKILL.md に 3 セクション追加 (125 行)
- ローカル AGENTS.md に L9-L11 追記
- Ag-SkillBuilder → push → `Sync-AndPush.ps1` → Agent-Skills push 完了

## Key Learnings

- **L9**: `Presentation()` のデフォルトプレースホルダは 4:3 (25.4cm) 基準。16:9 では Blank + `add_textbox()` で `SW` 基準の対称マージン配置が必須
- **L10**: `.gitattributes` の `*.pptx binary` は最初の git add 前に設定する。破損時は `python-pptx` で空テンプレートを再生成して復旧
- **L11**: python-pptx で動画埋め込みは ZIP 直接操作 (`lxml` + `zipfile`) で実現可能。`p:pic` + `a:videoFile` + `p14:media` + rels + Content_Types の 4 箇所を編集

## Commands & Code

```python
# 16:9 中央揃えパターン
prs = Presentation()
prs.slide_width = Cm(33.867)
prs.slide_height = Cm(19.05)
SW = prs.slide_width

slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank
margin = Cm(3)
tb = slide.shapes.add_textbox(margin, Cm(5), SW - margin * 2, Cm(3))
p = tb.text_frame.paragraphs[0]
p.alignment = PP_ALIGN.CENTER
```

```python
# テンプレート破損診断
with open('template.pptx', 'rb') as f:
    data = f.read()
count = data.count(b'\xef\xbf\xbd')
print(f'UTF-8 replacement chars: {count}')  # 0 以外なら破損
```

```powershell
# スキル同期
cd D:\03_github\00_VSC_tools\00_Ag-SkillBuilder
.\scripts\Sync-AndPush.ps1 -Message "sync: powerpoint-automation L9-L11" -SkipDevPush
```

## References

- [python-pptx documentation](https://python-pptx.readthedocs.io/)
- [OOXML Video Embed](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/1fb0ee96-bc34-4a3b-b903-93cfca3e66e7)

## Next Steps

- [ ] v7 PPTX の動画再生を PowerPoint で確認 → 正式版にリネーム＆コミット
- [ ] 提出用に YouTube/Stream にデモ動画をアップロード
- [ ] SharePoint フォームで提出 (期限: 2026-03-07 PST)
