# Build Learnings

## Universal（汎用 — 他プロジェクトでも使える）

### U1: optional import は try/except + except 側でダミー代入して名前を常にバインドする

- **Tags**: `pylance` `optional-dependency` `type-safety`
- **Added**: 2026-02-24
- **Evidence**: `pystray` を try/except でインポートし、except 側で未代入のまま型アノテーションに使ったところ Pylance が "possibly unbound" / "型式では変数を使用できません" を多数報告した
- **Action**: `except ImportError:` ブロックで `pystray = None  # type: ignore[assignment]` のようにダミー代入し、メソッド内では `if pystray is None: raise RuntimeError(...)` ガードを冒頭に入れる。型注釈は文字列リテラル形式を避け `Any` に統一するか、`TYPE_CHECKING` ブロックで import する。

### U2: asyncio.run() で SDK 呼び出しを同期ラップするときは asyncio インポートを try ブロック外に置く

- **Tags**: `asyncio` `sdk-integration` `optional-dependency`
- **Added**: 2026-02-24
- **Evidence**: `asyncio` を `try: from copilot import ...` と同じブロックに入れると、SDK が import できない環境で asyncio まで未定義になるリスクがある
- **Action**: asyncio は標準ライブラリなので try ブロック外で通常 import する。SDK 側の optional import のみを try で囲む。

## Project-specific（このワークスペース固有）

### P1: Step1 SDK 統合は asyncio.run() による同期ラップで CLI と親和性を保つ

- **Tags**: `step01` `sdk-integration` `architecture`
- **Added**: 2026-02-24
- **Evidence**: Step1 は同期 CLI。SDK は async API。`asyncio.run()` で同期ラップし、`_SDK_AVAILABLE` フラグで SDK なし環境のフォールバック（`_bicep_stub()`）を維持した
- **Action**: SDK 呼び出し関数は `_generate_bicep_with_sdk` / `_repair_bicep_with_sdk` に分離し、main() ロジックはフォールバック込みで呼び出す。スタブは削除せずに残す。

### P2: Step3 src/app.py 骨格は AppController + AppMode Enum パターンで状態管理する

- **Tags**: `step03` `architecture` `tray-app`
- **Added**: 2026-02-24
- **Evidence**: Step0 の TrayApp は GUI 依存が強く直接移植しにくい。Step3 では appmode + controller パターンに分離し、SDK/Speech は後から attach() で注入できる設計にした
- **Action**: `attach_sdk()` / `attach_speech()` で依存を注入する形を維持し、src/sdk/ 実装完了後に呼び出し側に接続する。

## Session Log

<!-- 2026-02-24 -->

### Done

- Step1 `main.py`: `_generate_bicep_with_sdk()` 追加（`_bicep_stub()` フォールバック付き）
- Step1 `main.py`: `_repair_bicep_with_sdk()` 追加、deploy ループ内に SDK 修復ブランチ実装
- Step3 `src/app.py`: トレイ常駐 + AppMode 切替骨格を新規作成
- DASHBOARD.md: Step1 75%, Step3 15% に更新、完了タスクをチェック

### Not Done

- Step1: モジュール分割（orchestrator / bicep_generator / artifact_store）: スコープが大きく今回対象外
- Step3: src/sdk/ / src/speech/ 移植: Step1 完了を優先するため NEXT 行き

## Next Steps

### 確認（今回やったことが効いているか）

- [ ] Step1: `python main.py "Storage Account を1台" --what-if` を実行し SDK Bicep 生成ログが出ることを確認 `~3d`
- [ ] Step3: `python src/app.py` を実行し pystray インストール後にトレイアイコンが表示されることを確認 `~3d`

### 新観点（今回カバーできなかった品質改善）

- [ ] Step1: SDK 修復ループの e2e テスト（意図的に壊れた Bicep を渡してループが動くか） `~7d`
- [ ] Step3: `src/sdk/` モジュール実装（Step0 SDKClient / SessionManager 移植） `~7d`
- [ ] Step1: `asyncio.run()` は Python 3.10+ のみ対応。`pyproject.toml` の python_requires を確認 `~7d`
