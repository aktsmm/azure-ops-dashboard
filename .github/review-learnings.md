# Review Learnings

## Universal（汎用 — 他プロジェクトでも使える）

### U1: SDK のコンストラクタ引数は実体で検証する

- **Tags**: `<外部連携>` `<バグ>` `<互換性>`
- **Added**: 2026-02-23
- **Evidence**: Copilot SDK の `CopilotClient` は `CopilotClient(options=...)` シグネチャで、`CopilotClient(**opts)` は `TypeError` になった。
- **Action**: 依存バージョン（pyproject/lock）を確認し、`inspect.signature()` 等で実体シグネチャを検証してから呼び出し形式を決める。Options/TypedDict 系は `options=` で渡す。

### U2: Windows で `shell=True` + `list2cmdline` はクォート規則不整合になりやすい

- **Tags**: `<セキュリティ>` `<外部連携>` `<Windows>`
- **Added**: 2026-02-23
- **Evidence**: `list2cmdline` は CreateProcess 向けで、`cmd.exe` の解釈とズレやすい。`shell=True` は注入リスクも上げる。
- **Action**: 可能な限り `shell=False` に統一する。`.cmd/.bat` shim を起動する必要がある場合は `cmd.exe /d /s /c` を argv で呼び、文字列連結を避ける。

### U3: Pillow の `Image.open()` はファイルハンドルを保持し得る

- **Tags**: `<非機能>` `<バグ>` `<Windows>`
- **Added**: 2026-02-23
- **Evidence**: `Image.open(path)` の戻りをそのまま保持すると、Windows でファイルがロックされたり、ハンドルが保持されたままになることがある。
- **Action**: `with Image.open(path) as img: return img.copy()` のように `with` で確実にクローズし、必要なら `copy()` でデータをメモリに展開する。

### U4: `subprocess.TimeoutExpired` の stdout/stderr は bytes/None を含む

- **Tags**: `<バグ>` `<コード品質>`
- **Added**: 2026-02-23
- **Evidence**: `TimeoutExpired.stdout/stderr` は `str | bytes | None` になり得るため、文字列連結やログ整形で型/実行時エラーの原因になる。
- **Action**: `isinstance(x, str)` を前提に `str` に正規化してから扱う（例: `stderr: str = (exc.stderr or "") if isinstance(exc.stderr, str) else ""`）。

### U5: `run_coroutine_threadsafe` の Future 型を取り違えない

- **Tags**: `<バグ>` `<型>` `<並行処理>`
- **Added**: 2026-02-23
- **Evidence**: `asyncio.run_coroutine_threadsafe()` は `asyncio.Future` ではなく `concurrent.futures.Future` を返す。done_callback の型注釈や Optional 属性参照が崩れると、静的解析エラーや実装の意図誤認につながる。
- **Action**: 返り値は `concurrent.futures.Future[T]` として扱い、callback も同型を受け取るシグネチャにする。Optional 参照はローカル変数に束縛してから使い、必要なら fail-fast で落とす。

### U6: バックグラウンドイベントループ起動待ちの成否は必ず検証する

- **Tags**: `<バグ>` `<並行処理>` `<回復性>`
- **Added**: 2026-02-23
- **Evidence**: `thread.start()` 後の `loop_ready.wait(timeout=...)` の戻り値を未チェックだと、以降の `run_coroutine_threadsafe()` が永久待ち/ハングする可能性がある。
- **Action**: wait の戻り値を検証し、起動失敗時は fail-fast で例外/ログを出す。必要なら loop/thread の停止処理もベストエフォートで行う。

### U7: 永続化 JSON は形状（list/dict）を必ず検証する

- **Tags**: `<バグ>` `<回復性>` `<コード品質>`
- **Added**: 2026-02-23
- **Evidence**: `json.loads()` 結果を `list[dict]` 前提で `for item in data: item.get(...)` のように扱うと、ファイル破損や手編集で dict/list が崩れた瞬間に `AttributeError` でアプリが落ちる。
- **Action**: 読み込み直後に `isinstance(data, dict|list)` を検証し、想定外の形状は空データへフォールバックする。ループ内要素も `dict` か確認してから `.get()` を使う。

### U8: ロック保持中に任意コールバックを呼ばない

- **Tags**: `<並行処理>` `<回復性>` `<設計>`
- **Added**: 2026-02-23
- **Evidence**: `threading.Lock` 保持中に `on_status`（GUIログ等の任意実装）を呼ぶと、ログ側が別ロックやUIスレッド待ちを含む場合にデッドロック/待ち時間増大の原因になり得る。
- **Action**: ロック内は状態のスナップショット取得のみに限定し、コールバック/ログ出力はロック外で行う（例: cached をローカル変数へ退避してから log）。

### U9: GUI で扱う Secret は保持時間を最小化する

- **Tags**: `<セキュリティ>` `<UI>` `<回復性>`
- **Added**: 2026-02-23
- **Evidence**: 入力フォームの secret をクロージャにキャプチャすると、処理完了まで参照が残りやすい。入力欄にも文字列が残り続ける。
- **Action**: 入力欄は即クリアし、secret はスレッド関数の引数として渡す等で保持範囲を狭める。ログ出力に含めない（可能なら環境変数/標準入力で渡す方式も検討）。

### U10: バックグラウンドスレッドの `except Exception: return` は禁止

- **Tags**: `<バグ>` `<回復性>` `<コード品質>`
- **Added**: 2026-02-23
- **Evidence**: `_bg_load_models` で SDK 接続失敗時の例外を `except Exception: return` で握りつぶしていたため、exe ビルドでモデル一覧が空になっても原因が一切表示されず、診断に時間がかかった。
- **Action**: バックグラウンドスレッドでも最低限 `self._log(f"エラー: {exc}")` + `traceback.print_exc()` でエラーを可視化する。特に frozen exe ではソース実行と挙動が変わりやすいため、「ベストエフォート」処理でもエラーログは必須。

### U11: PyInstaller(frozen) で同梱ディレクトリ名が Python モジュール名と衝突しないようにする

- **Tags**: `<バグ>` `<回復性>` `<PyInstaller>`
- **Added**: 2026-02-23
- **Evidence**: exe 同梱の CLI を `_MEIPASS/copilot/bin/...` に置いた結果、`import copilot` が SDK ではなく同梱ディレクトリ（namespace package）を拾い、`CopilotClient not found` で SDK が使えなかった。
- **Action**: `--add-data` の配置先は top-level パッケージ名（例: `copilot/`）と被せない。`copilot_cli/` のように別名へ退避し、参照側もそのパスを見に行く。

### U12: 長時間 AI 処理はタイムアウトとハートビートを設計する

- **Tags**: `<非機能>` `<回復性>` `<UX>`
- **Added**: 2026-02-23
- **Evidence**: draw.io 図生成のような出力が大きいAI処理では、デフォルトの短いタイムアウト（例: 180秒）だとタイムアウト→再試行になりやすく、ユーザーも「止まっているのか？」と不安になる。
- **Action**: 図生成など長時間タスクはタイムアウトを十分長く（例: 60分）設定し、5分おき等で「処理中」ハートビートログを出す。タイムアウトは処理ごとに指定可能にして、短時間タスクへ影響を最小化する。

### U13: draw.io SVG は `--embed-diagram` なしだと再編集できない

- **Tags**: `<互換性>` `<ツール>` `<Windows>`
- **Added**: 2026-02-24
- **Evidence**: draw.io CLI で `.drawio` → `.svg` を通常エクスポートした SVG を draw.io で開くと、「Invalid file data」になり得た（図データが SVG に埋め込まれていない）。
- **Action**: SVG を draw.io で再オープン（再編集）させたい場合は、エクスポート時に `--embed-diagram` を付ける。埋め込み不要なら「SVG は配布用・一次ソースは `.drawio`」と明示する。

### U14: Markdown 変換は「未閉じブロック」でも欠落させない

- **Tags**: `<回復性>` `<バグ>` `<コード品質>`
- **Added**: 2026-02-24
- **Evidence**: Markdown が未閉じのコードフェンス（``` が閉じていない）で終わると、変換（例: Markdown→docx）でコードブロックが欠落し得る。
- **Action**: 解析ループ終了時にバッファ（コード行など）をフラッシュし、入力が多少不正でも「欠落せず出力」するベストエフォート挙動にする。

### U15: GUI の外部アプリ起動はフォールバック必須（例外で落とさない）

- **Tags**: `<UI>` `<回復性>` `<外部連携>`
- **Added**: 2026-02-24
- **Evidence**: GUI から `subprocess.Popen()` で Draw.io / VS Code 等を起動する処理が、パス不整合・権限・環境差分で例外を投げるとアプリがクラッシュし得る。
- **Action**: 外部アプリ起動は try/except で保護し、失敗時はログを残して OS 既定のオープンへフォールバックする（ユーザー操作の継続を最優先）。

### U16: グルーピング用ハッシュIDは全ての識別軸を含める

- **Tags**: `<バグ>` `<設計>` `<データ整合性>`
- **Added**: 2026-02-24
- **Evidence**: `preprocess_nodes` のサマリノード ID が `hashlib.sha1(prefix)` のみで算出されており、同一プレフィックスで異なるリソース type のグループが同じ ID を持つ衝突バグが発生した。
- **Action**: ハッシュ ID の生成には全ての識別軸（prefix + type、必要なら location も）を含める。`f"{prefix}|{rtype}"` のように結合してからハッシュする。

### U17: 複数成果物の補助ファイル名は衝突させない

- **Tags**: `<バグ>` `<UX>` `<設計>`
- **Added**: 2026-02-24
- **Evidence**: 単一出力前提で固定名（例: `env.json` / `collect.log.json`）を書き出していたが、複数ビューを一括生成する機能追加で補助ファイルが上書きされ、どの成果物に対応するか追跡しづらくなった。
- **Action**: 補助ファイルは「主成果物と同名ベース」（例: `*.drawio` → `*-env.json`）や、view/type/timestamp など識別軸を含む命名にして衝突を防ぐ。ユーザー向けドキュメントの成果物一覧も同時に更新する。

### U18: AI プロンプトは「出力構造テンプレート + ドメイン横断パターン」で品質を安定させる

- **Tags**: `<AI>` `<プロンプト>` `<品質>`
- **Added**: 2026-02-24
- **Evidence**: 統合レポートの system prompt が 4 行の抽象指示だけだとセクション構成・詳細度がばらつき品質が低かった。7 セクション構造 + Security×Cost 等のクロスドメイン分析パターンを明示して品質が大幅向上。
- **Action**: 長文 AI 出力のプロンプトには (1) 必須セクション構造をテンプレとして提示、(2) 具体的なクロスリファレンス観点（○○×△△: チェックすべきパターン）を列挙する。抽象的な「横断分析して」は避ける。

### U19: AI 出力のサニタイズは「コードフェンス内」と「フェンス外」を分離して処理する

- **Tags**: `<AI>` `<回復性>` `<バグ>`
- **Added**: 2026-02-24
- **Evidence**: 統合レポートで AI がPython ソースコード、ディレクトリリスト、Jinja テンプレートをそのまま「レポート」として出力。`_sanitize_ai_markdown` がコードフェンス内の内容を無条件に通していたため除去できなかった。
- **Action**: コードフェンスの内容も検査し、Python import 3行以上→除去 / Jinja `{{ }}` + `{% %}`→除去 / `├──` 2行以上→除去というルールでフィルタする。正規の `bash` 例示ブロックは保持する。

### U20: AI リトライ時はデルタストリーミングを抑制してログ化けを防ぐ

- **Tags**: `<AI>` `<UI>` `<バグ>`
- **Added**: 2026-02-24
- **Evidence**: `_run_report` のリトライが同じ `on_delta` コールバックで2回目のストリーミングを行うと、1回目の不正出力デルタと2回目の正常デルタがログに混在して文字化けした。
- **Action**: リトライ時は `on_delta=lambda _d: None` で新しい `AIReviewer` を作り、ストリーミングを抑制する。最終結果は `_sanitize_ai_markdown` 経由で返せば十分。

### U21: AI が tool_input に本文を入れたら救出する

- **Tags**: `<AI>` `<回復性>` `<バグ>`
- **Added**: 2026-02-24
- **Evidence**: 統合レポート生成で AI が `<tool_call>` 形式を模倣し、Markdown 本文を `<tool_input>` の JSON (`{"content": "..."}`) に入れて返すことがある。この場合ツール痕跡をブロック削除すると本文も消えて統合が失敗する。
- **Action**: `<tool_input>` をパースし `content` を抽出してサニタイズ対象に切り替える（抽出できない場合のみ従来のブロック除去）。

### U22: 汎用タグはブロック扱いにしない（全文飲み込み防止）

- **Tags**: `<AI>` `<回復性>` `<バグ>`
- **Added**: 2026-02-24
- **Evidence**: `_sanitize_ai_markdown` が `<result>` / `<parameters>` のような汎用タグをツール痕跡として multi-line block 扱いすると、閉じタグが欠けた出力で残りの全文を破棄し、統合レポートが `no_heading` で失敗する。
- **Action**: ブロック除去（skip モード）は `tool_call` 等の確実なタグのみに限定し、汎用タグは「行単位で削除」に留める。閉じタグ欠落でも本文が残るベストエフォートを優先する。

### U23: tool_input 抽出には品質ゲート（最小長+見出し数）を設ける

- **Tags**: `<AI>` `<回復性>` `<バグ>`
- **Added**: 2026-02-24
- **Evidence**: AI が `<tool_input>` に「Let me examine...」程度の思考テキストだけを content に入れ、ツールブロック除去後に採用される結果、統合レポートが 3 行になった。スコアリング上、ツール痕跡ペナルティ(-50)が大きく短い抽出が勝ってしまう。
- **Action**: 抽出コンテンツの採用に品質ゲートを追加（300 文字以上 AND 見出し 2 以上）。ゲート不通過でも line-by-line 結果が短ければ「抽出の方が長い場合のみ」reconsider する二段構え。

## Project-specific（プロジェクト固有）

### P1: PyInstaller / exe 配布のリソース参照は `app_paths.py` に集約する

- **Tags**: `<PyInstaller>` `<設計>` `<回復性>`
- **Added**: 2026-02-24
- **Evidence**: Step0 などで `Path(__file__).parent` を散発的に使うと、PyInstaller(frozen) 化やユーザー上書き導線（AppData）追加時に修正が波及しやすい。
- **Action**: 各 Step に最小の `app_paths.py` を置き、リソース/設定の探索（`_MEIPASS` + user override）を集約する。

### P2: ハイフン入りディレクトリは unittest discovery の start_dir にならない

- **Tags**: `<テスト>` `<Python>`
- **Added**: 2026-02-23
- **Evidence**: `python -m unittest discover -s azure-ops-dashboard` は「importable でない」として失敗する（ディレクトリ名に `-` が含まれるため）。
- **Action**: `cd azure-ops-dashboard; uv run python tests.py` のようにスクリプト実行でテストを回す（またはディレクトリ名/パッケージ構成を見直す）。

## Session Log

<!-- 毎回上書き。前回の記録は残さない。 -->
<!-- 2026-02-24 -->

### Done

- i18n: `ai_reviewer.py` (12箇所) + `docs_enricher.py` (5箇所) のハードコード日本語ログを `get_language()` EN/JA 分岐に変更
  - 「検索中」「件取得」「キャッシュ済みクライアントを再利用」「MCP を接続中」「AI 思考中」「処理実行中」等
- 前回: サニタイザー強化 + system prompt 強化 + 進捗バー完了表示（同日）

### Not Done

- なし

## Next Steps

<!-- 毎回上書き。前回推奨の残骸を残さない。 -->

### 確認（今回の修正が効いているか）

- [ ] English モードで Collect → ログに日本語が混在しないこと `~3d`
- [ ] 統合レポートを再実行し、レポート本文が Markdown として完成しているか確認 `~3d`

### 新観点（今回カバーできなかった品質改善）

- [ ] `collector.py` にも同様のハードコード日本語ログがないか確認する `~7d`
- [ ] i18n キーを使わず直接文字列で EN/JA 分岐している箇所を `i18n.py` のキーに統一する `~30d`
