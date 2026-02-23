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

| Agent | Path | Description |
|-------|------|-------------|
| [dashboard-updater](.github/agents/dashboard-updater.agent.md) | `.github/agents/` | プロジェクト実装状態をスキャンし `DASHBOARD.md` を最新状態に更新する。セッション開始時・終了時に `@dashboard-updater` で呼び出す。 |

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
