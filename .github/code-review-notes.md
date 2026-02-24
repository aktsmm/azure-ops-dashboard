# Review Learnings

## Universal（汎用 — 他プロジェクトでも使える）

### U1: mock で非同期コルーチンを差し替える際は `_run_async` 層でブロックする

- **Tags**: `testing` `asyncio` `mock`
- **Added**: 2026-02-24
- **Evidence**: `run_integrated_report` の品質ゲートテストに `patch.object(mod, "_run_async", return_value=...)` を使ったところ、コルーチン (`AIReviewer.generate`) が await されず RuntimeWarning が出た。テスト自体は通過するが、深い asyncio スタックを mock するより外側の同期ラッパー (`_run_async`) を差し替える方が安全かつシンプル。
- **Action**: asyncio を使う関数のユニットテストは、コルーチンではなく **同期ラッパー（`_run_async` 相当）を `return_value` で差し替える**。コルーチンを直接 mock したい場合は `AsyncMock` を使う。

## Project-specific（このワークスペース固有）

### P1: テスト内で再 import するより、モジュールスコープの import を再利用する

- **Tags**: `azure-ops-dashboard` `tests` `code-quality`
- **Added**: 2026-02-24
- **Evidence**: `test_layout_order_publicip_before_vnet` / `test_layout_order_subnet_before_vnet` の各メソッド内で `from ... import LAYOUT_ORDER as LO` を重複してインポートしていた。モジュール冒頭で既に `LAYOUT_ORDER` としてインポート済みだった。
- **Action**: テストメソッド内でのアドホック import は、モジュールスコープに同じシンボルが既にある場合は除去する。

### P2: 定数を直接ハードコードするテストは定数変更で無音破綻する

- **Tags**: `azure-ops-dashboard` `tests` `fragile-test`
- **Added**: 2026-02-24
- **Evidence**: `test_choose_default_empty` が `"gpt-4.1"` をハードコードしており、`MODEL` 定数が変わるとテストが無音でパスし続けるか突然落ちる。
- **Action**: モデル名 / デフォルト値を検証するテストは、実装側の定数 (`MODEL`) を import して `self.assertEqual(result, MODEL)` で比較する。

## Session Log

<!-- 2026-02-24 -->
### Done
- `TestIntegratedReportQualityGate` クラスを新規追加（4テスト: placeholder/too_short/None/valid）
- 重複 `LAYOUT_ORDER` インポート除去（2箇所 → モジュールスコープのシンボルを直接利用）
- 未使用 import `cached_drawio_path`, `cached_vscode_path` を削除
- `test_choose_default_empty` の `"gpt-4.1"` ハードコードを `MODEL` 定数に変更
- `_collector_module` を `collector_module` にリネーム（慣例整合）
- 39 tests → 43 tests, 全件 OK

### Not Done
- `RuntimeWarning: coroutine 'AIReviewer.generate' was never awaited` の根本抑制: 現時点では `_run_async` 差し替えで機能的に問題ないためスコープ外

## Next Steps

### 確認（今回やったことが効いているか）

- [ ] `python -m unittest tests -v` で 43 tests OK が継続して確認できる `~3d`

### 新観点（今回カバーできなかった品質改善）

- [ ] `AsyncMock` を使った `AIReviewer.generate` のコルーチン直接テストに切替え（RuntimeWarning 完全排除） `~7d`
- [ ] `run_summary_report` / `run_drawio_generation` にも同様の品質ゲートテストを追加 `~7d`
