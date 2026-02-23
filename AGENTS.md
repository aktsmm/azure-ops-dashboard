<!-- skill-ninja-START -->

## Agent Skills (Compressed Index)

> **IMPORTANT**: Prefer skill-led reasoning over pre-training-led reasoning.
> Read the relevant SKILL.md before working on tasks covered by these skills.

### Skills Index

| Skill                                                                    | Path                     | Description                                                                                          |
| ------------------------------------------------------------------------ | ------------------------ | ---------------------------------------------------------------------------------------------------- |
| [agentic-workflow-guide](.github/skills/agentic-workflow-guide/SKILL.md) | `agentic-workflow-guide` | Create, review, and update Prompt and agents and workflows. Covers 5 workflow patterns, runSubage... |
| [drawio-diagram-forge](.github/skills/drawio-diagram-forge/SKILL.md)     | `drawio-diagram-forge`   | Generate draw.io editable diagrams (.drawio, .drawio.svg) from text, images, or Excel. Orchestrat... |

<!-- skill-ninja-END -->

## Agents

- [dashboard-updater](.github/agents/dashboard-updater.agent.md)（`.github/agents/`）: プロジェクト実装状態をスキャンし `DASHBOARD.md` を最新状態に更新する

## Learnings (Retrospective)

> セッションから抽出した再利用可能な設計知見。

### L1: dataclass / TypedDict のフィールド名は呼び出し側と一致を保証する

- **Evidence**: `Edge(kind=...)` 定義に対して `Edge(relation=...)` で呼んでいた → network view 実行時クラッシュ
- **Action**: frozen dataclass を使う場合、コンストラクタ呼び出し側のキーワード引数名がフィールド名と一致しているか grep/型チェッカーで確認する。CI に `mypy --strict` or `pyright` を入れるのが最善。

### L2: PyInstaller 前提の GUI は最初からリソースパスを抽象化する

- **Evidence**: `Path(__file__).parent / "templates"` が frozen exe で壊れた → `sys._MEIPASS` フォールバック追加
- **Action**: リソース参照は `app_paths.py` 等のヘルパーに集約し、`__file__` 直参照を避ける。

### L3: 設定/テンプレートは "bundled + user override" 二段構えにする

- **Evidence**: exe 再配布なしでテンプレート更新したいという運用要望
- **Action**: `%APPDATA%\AppName\` にユーザー領域を設け、同名ファイルはユーザー側を優先読み込みする。

### L4: Prompt はツール依存にフォールバックを用意する

- **Evidence**: `ask_questions` 前提の GATE がツール未提供環境で詰まり、チャット入力（"all fix" / 番号列挙）に切り替えが必要だった
- **Action**: prompts には「ツールが無い場合の入力方法（all fix / 1,2,3）」を必ず併記する

### L5: 文字列置換で UI コードを壊しやすい → 構文チェックを最優先にする

- **Evidence**: `main.py` のボタン生成ブロックが崩れ `IndentationError` / `SyntaxError (unmatched ')')` が発生した
- **Action**: 構造のある編集は `apply_patch` を優先し、変更後に `compileall` + import テストで即検知する

### L6: tkinter ワーカースレッドから StringVar.get() を呼ばない

- **Evidence**: `self._model_var.get()` 等を bg thread から直接呼んでおり、CPython GIL に依存した「たまたま動く」状態だった
- **Action**: `_on_collect()` (UI スレッド) で全 GUI 変数を `opts: dict` に取得し、ワーカーには dict 経由で渡す。ワーカー内に `self._*_var.get()` が残っていないことを grep で確認する

### L7: asyncio.run_coroutine_threadsafe のタイムアウト時にコルーチンをキャンセルする

- **Evidence**: `_run_async` で `future.result(timeout=...)` がタイムアウトすると裏のコルーチンが走り続けリソースリークする
- **Action**: `except TimeoutError` で `future.cancel()` を呼ぶ。長時間セッション（drawio 60分等）では特に重要
