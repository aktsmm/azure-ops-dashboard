<!-- skill-ninja-START -->

## Agent Skills (Compressed Index)

> **IMPORTANT**: Prefer skill-led reasoning over pre-training-led reasoning.
> Read the relevant SKILL.md before working on tasks covered by these skills.

### Skills Index

| Skill                                                                    | Path                     | Description                                                                                          |
| ------------------------------------------------------------------------ | ------------------------ | ---------------------------------------------------------------------------------------------------- |
| [agentic-workflow-guide](.github/skills/agentic-workflow-guide/SKILL.md) | `agentic-workflow-guide` | Create, review, and update Prompt and agents and workflows. Covers 5 workflow patterns, runSubage... |
| [drawio-diagram-forge](.github/skills/drawio-diagram-forge/SKILL.md)     | `drawio-diagram-forge`   | Generate draw.io editable diagrams (.drawio, .drawio.svg) from text, images, or Excel. Orchestrat... |
| [powerpoint-automation](.github/skills/powerpoint-automation/SKILL.md)   | `powerpoint-automation`  | Create professional PowerPoint presentations from various sources including web articles, blog po... |

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

### L8: tkinter の after キューを高頻度で積まない + マルチスレッドバッファはアトミックスワップ

- **Evidence**: AI ストリーミング中に `root.after(0, ...)` を毎デルタで積んだ結果、200ms 周期のタイマーが遅延してフリーズ。バッファの `join`+`clear` 間にワーカーが `append()` してデルタ消失。
- **Action**: ストリーミング UI は 100ms 等でバッチ化する。マルチスレッドのバッファ回収は `self.buf = []`（属性再バインド）でアトミックにスワップし、`join`+`clear` の非原子性を回避する。

### L9: python-pptx の Presentation() は 4:3 プレースホルダを生成する — 16:9 では Blank + 手動配置

- **Evidence**: `slide_width = Cm(33.867)` で 16:9 に設定してもプレースホルダは 25.4cm (4:3) 基準のまま → 全スライドが左寄りに表示された
- **Action**: 16:9 プレゼンでは Blank レイアウト + `add_textbox()` で `SW` 基準の対称マージン配置を行う。テンプレート PPTX 自体が 16:9 なら Layout 0-5 も使用可。

### L10: binary ファイルの Git 管理は .gitattributes を add 前に設定する

- **Evidence**: skill-ninja でインストールした `template.pptx` が UTF-8 変換で 12,778 箇所破損 (`.gitignore` の `skills/` で除外されていたため気づかず)
- **Action**: `.gitattributes` の `*.pptx binary` は最初のコミット前に設定。破損した場合は `python-pptx` で空テンプレートを再生成して復旧可能。

### L11: python-pptx で動画埋め込みは ZIP 直接操作で可能

- **Evidence**: python-pptx は公式に MP4 埋め込み非対応。しかし PPTX は ZIP なので `lxml` + `zipfile` で slide XML に `p:pic` + `a:videoFile` + `p14:media` を注入し、rels と Content_Types を追加すれば埋め込み可能
- **Action**: ポスター画像（サムネイル）は必須。PowerPoint が軽微な修復を求める場合があるが動作する。Git 管理には LFS 推奨。

### L12: 提出物のスペック（枚数・サイズ上限・ファイル命名規則）は実装前に確認する

- **Evidence**: 21 スライド・19MB の PPTX を作成した後、フォームが「1-2 slides / 10MB / submitter name in filename」を要求していると判明し全面再作成が発生した
- **Action**: 提出先フォームの制約（スライド数・ファイルサイズ上限・命名規則・許可ファイル形式）を最初に確認してから成果物を作成する。名前・メール等の確定情報も事前に収集する。
