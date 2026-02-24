# Fix Learnings

## Universal（汎用 — 他プロジェクトでも使える）

### U1: AI生成物は「形式」だけでなく「最低品質」でゲートする

- **Tags**: `ai` `quality-gate` `fallback`
- **Added**: 2026-02-24
- **Evidence**: Integrated Report が `# Integrated Report` + 1文（"I'll generate...") のようなプレースホルダで保存され、見出しがあるために「成功扱い」になっていた。
- **Action**: 見出し有無だけで成功判定せず、長さ・構造（`##` セクションや箇条書き）・プレースホルダ文言を用いた最低品質ゲートを入れ、失敗時はフォールバックに切り替える。

## Project-specific（このワークスペース固有）

### P1: Integrated Report は短文を無効扱いにしてフォールバックへ

- **Tags**: `azure-ops-dashboard` `integrated-report` `copilot-sdk`
- **Added**: 2026-02-24
- **Evidence**: run_integrated_report() が「見出しを付けて救済」することで短文でも valid 扱いになり、ユーザーに空の統合レポートが出力された。
- **Action**: `placeholder/too_short/no_structure` を理由に None を返し、GUI 側の deterministic fallback を必ず発火させる。

## Session Log

<!-- 毎回上書き -->
<!-- 2026-02-24 -->

### Done

- Integrated Report の AI 出力が短文/プレースホルダの場合に無効扱いにしてフォールバックへ切替（品質ゲート追加）
- ユニットテスト 39件で回帰なしを確認
- **本番動作確認済み**: 142行の構造化された統合レポートが正常出力された（2026-02-24 22:44）

### Not Done

- なし

## Next Steps

### 確認（今回の修正が効いているか）

- [x] Integrated Report: AI が十分な内容を返した場合はそのまま採用される ✅ 2026-02-24 本番確認済み
- [ ] Integrated Report: AI が短文を返した場合にフォールバック統合レポートが生成される `~7d`

### 新観点（今回カバーできなかった品質改善）

- [ ] Integrated Report: `*-input.json` と同様に統合レポートでも ai_debug を保存して調査容易性を上げる `~7d`
