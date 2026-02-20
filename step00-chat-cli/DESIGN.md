# Step 0: SDK Chat CLI — 基本設計 + 詳細設計

> 作成日: 2026-02-20
> ステータス: Voice Agent 基盤品質で設計

---

## 1. 基本設計（BD）

### 1.1 目的

GitHub Copilot SDK（Python）の最小動作確認を行いつつ、Step 3（Voice-first Enterprise Copilot）の **SDK レイヤー基盤** としてそのまま再利用できるクオリティで実装する。

### 1.2 スコープ

| IN スコープ                                                                          | OUT スコープ                     |
| ------------------------------------------------------------------------------------ | -------------------------------- |
| SDK 接続・認証（CLI ログインデフォルト）                                             | 音声 I/O（Step 2 で実装）        |
| セッション作成・管理・破棄                                                           | MCP サーバー接続（Step 1 以降）  |
| ストリーミング表示（delta リアルタイム）                                             | Skills 自動同期（Step 3 で実装） |
| イベントハンドリング（推論・ツール実行表示）                                         | カスタムツール定義               |
| エラーハンドリング・リトライ                                                         | 永続セッション                   |
| クリーンアップ保証（async context manager）                                          |                                  |
| **System Tray 常駐（pystray）**                                                      |                                  |
| **グローバルホットキー（Alt ダブルタップ、settings.json で変更可）で入力ウィンドウ** |                                  |
| **tkinter チャットウィンドウ（ストリーミング表示）**                                 |                                  |
| モジュール分割（Voice Agent 統合を見据えた拡張点）                                   |                                  |

### 1.3 アーキテクチャ概要

```
┌────────────────────────────────────────────────────────────────┐
│                     main.py (エントリポイント)                  │
│                                                                │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────┐    │
│  │  TrayApp     │   │ ChatWindow   │   │ asyncio loop     │    │
│  │  (pystray)   │   │ (tkinter)    │   │ (background)     │    │
│  │              │   │              │   │                  │    │
│  │ System Tray  │   │ 入力欄       │   │ SDKClient        │    │
│  │ アイコン     │──→│ 応答表示     │──→│ SessionManager   │    │
│  │ 右クリック   │   │ ストリーミング│←──│ EventHandler     │    │
│  │ メニュー     │   │              │   │                  │    │
│  └─────────────┘   └──────────────┘   └──────────────────┘    │
│        │                   ↑                                   │
│        │                   │                                   │
│  Global Hotkey ────────────┘                                   │
│  (Alt ダブルタップ — settings.json で変更可)                   │
│  keyboard library                                              │
└────────────────────────────────────────────────────────────────┘

スレッド構成:
  Main Thread    → tkinter メインループ（ChatWindow）
  Thread 1       → asyncio event loop（SDK 通信）
  Thread 2       → pystray（System Tray）
  Global Hotkey  → keyboard ライブラリ（Alt ダブルタップ、settings.json でキー変更可）
```

### 1.4 認証方式

- **CLI ログインのデフォルト方式** を使用
- `copilot auth login` 済みであれば追加認証不要
- `CopilotClient(use_logged_in_user=True)` （デフォルト）
- PAT フォールバックは Step 0 では不要（必要になれば `GITHUB_TOKEN` 環境変数で対応）

### 1.5 制約事項

| 制約                                          | 理由                                                           |
| --------------------------------------------- | -------------------------------------------------------------- |
| Python 3.11+                                  | pyproject.toml 制約                                            |
| `github-copilot-sdk >= 0.1.25`                | `PermissionHandler` が v0.1.25 で必須化（#509）                |
| `copilot` CLI がインストール済み・PATH に存在 | SDK が内部で CLI をサーバーモードで起動する                    |
| Windows 環境                                  | 開発機が Windows。spawn 対応が必要                             |
| `on_permission_request` 必須                  | v0.1.25 で deny-by-default。未設定だとツール実行が全拒否される |

### 1.6 Voice Agent 統合時の拡張ポイント

Step 3 で Voice Agent に統合する際、以下の差し替え・注入だけで対応できる設計にする：

| 拡張ポイント                      | Step 0 での実装                 | Step 3 での差し替え                                        |
| --------------------------------- | ------------------------------- | ---------------------------------------------------------- |
| `EventHandler` のコールバック     | ChatWindow にストリーミング表示 | delta → TTS キューへ送信（+ ChatWindow 表示は維持）        |
| `SessionManager` のセッション設定 | model + streaming のみ          | `skill_directories`, `mcpServers`, `system_message` を注入 |
| `SDKClient` のオプション          | デフォルト                      | `github_token`, `log_level` をカスタマイズ                 |
| `on_permission_request`           | `approve_all`                   | カスタムハンドラ（ホワイトリスト制御）                     |
| `ChatWindow` の入力               | テキスト入力のみ                | 音声入力ボタン追加 / ホットキーで音声モード切替            |
| `TrayApp` のメニュー              | Chat / Exit のみ                | Skills 更新 / 設定 / ログ表示 等追加                       |

---

## 2. 詳細設計（DD）

### 2.1 ファイル構成

```
step00-chat-cli/
├── DESIGN.md          # ← このファイル
├── README.md          # セットアップ手順・使い方
├── main.py            # エントリポイント（スレッド起動・統合）
├── config.py          # 設定定数（GUI 設定含む）
├── sdk_client.py      # CopilotClient ラッパー
├── session_manager.py # Session 作成・管理・送受信
├── event_handler.py   # イベントルーター（GUI コールバック対応）
├── chat_window.py     # tkinter チャットウィンドウ
├── tray_app.py        # pystray System Tray 管理
└── assets/ (optional)
    └── icon.png       # トレイアイコン（存在しない場合はプログラム生成）
```

### 2.2 `config.py` — 設定定数

```python
"""Step 0 設定定数"""

# --- モデル設定 ---
DEFAULT_MODEL = "gpt-4.1"
DEFAULT_TIMEOUT = 120  # seconds

# --- リトライ設定 ---
MAX_RETRY = 3
RETRY_BACKOFF = 2.0  # seconds（指数バックオフの基数）

# --- ANSI カラーコード ---
BLUE = "\033[34m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"

# --- 表示プレフィックス ---
PREFIX_TOOL = f"{YELLOW}[tool]{RESET}"
PREFIX_REASONING = f"{BLUE}[reasoning]{RESET}"
PREFIX_SYSTEM = f"{GREEN}[system]{RESET}"
PREFIX_ERROR = f"{RED}[error]{RESET}"
```

#### settings.json の上書きポリシー

- `settings.json` は「指定されたキーのみ」デフォルトを上書きする
- **型不一致/範囲外などの不正値は無視**し、デフォルトを維持する（起動不能を防ぐ）

### 2.3 `sdk_client.py` — CopilotClient ラッパー

#### クラス設計

```python
class SDKClient:
    """CopilotClient のライフサイクルを管理するラッパー。

    async context manager 対応で確実なクリーンアップを保証。
    接続失敗時は指数バックオフでリトライ（最大 MAX_RETRY 回）。
    """

    def __init__(self, **client_options):
        """client_options は CopilotClient() にそのまま渡す。

        Voice Agent 統合時に github_token, log_level 等を
        ここから注入できる。
        """

    async def start(self) -> None:
        """CopilotClient を起動。リトライロジック付き。"""

    async def stop(self) -> None:
        """CopilotClient を停止。エラーを握りつぶさない。"""

    async def __aenter__(self) -> "SDKClient":
        """async with SDKClient() as client: で使用"""

    async def __aexit__(self, *exc) -> None:
        """例外発生時も確実に stop() を呼ぶ"""

    @property
    def client(self) -> CopilotClient:
        """内部の CopilotClient インスタンスを返す"""
```

#### リトライロジック

```
attempt 1: start() → 失敗 → wait 2s
attempt 2: start() → 失敗 → wait 4s
attempt 3: start() → 失敗 → raise RuntimeError("SDK 接続に失敗しました")
```

### 2.4 `event_handler.py` — イベントルーター

#### クラス設計

```python
from typing import Callable, Optional

class EventHandler:
    """SDK セッションイベントを処理するルーター。

    デフォルトではコンソール出力。Voice Agent 統合時は
    on_delta コールバックを差し替えて TTS キューに送信する。
    """

    def __init__(
        self,
        on_delta: Optional[Callable[[str], None]] = None,
        on_message_complete: Optional[Callable[[str], None]] = None,
        on_tool_start: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
        on_idle: Optional[Callable[[], None]] = None,
    ):
        """コールバック注入。None の場合はデフォルト（コンソール出力）を使用。"""

    def handle(self, event) -> None:
        """session.on() に渡すメインハンドラ。

        event.type.value で分岐:
        - "assistant.message_delta" → on_delta(event.data.delta_content)
        - "assistant.message"       → on_message_complete(event.data.content)
        - "assistant.reasoning_delta" → 推論 delta（DIM 表示）
        - "assistant.reasoning"     → on_reasoning(event.data.content)
        - "tool.execution_start"    → on_tool_start(event.data.tool_name)
        - "session.idle"            → on_idle()
        """
```

#### デフォルトコールバック動作

| イベント                    | デフォルト動作                                            |
| --------------------------- | --------------------------------------------------------- |
| `assistant.message_delta`   | `print(delta, end="", flush=True)` — リアルタイム文字出力 |
| `assistant.message`         | `print()` — 改行のみ（delta で本文は出力済み）            |
| `assistant.reasoning_delta` | `print(f"{DIM}{delta}{RESET}", end="", flush=True)`       |
| `assistant.reasoning`       | `print()` — 改行                                          |
| `tool.execution_start`      | `print(f"{PREFIX_TOOL} {tool_name}")`                     |
| `session.idle`              | 何もしない（send_and_wait が idle を検知して戻る）        |

### 2.5 `session_manager.py` — Session 管理

#### クラス設計

```python
class SessionManager:
    """SDK Session のライフサイクルと送受信を管理。

    create_session 時に必ず on_permission_request を設定し、
    v0.1.25 の deny-by-default 問題を回避する。
    """

    def __init__(
        self,
        client: SDKClient,
        event_handler: EventHandler,
        model: str = DEFAULT_MODEL,
        session_config: Optional[dict] = None,
    ):
        """
        client: SDKClient インスタンス
        event_handler: イベントハンドラ
        model: 使用モデル（デフォルト: gpt-4.1）
        session_config: 追加セッション設定（skill_directories, mcpServers 等）
                        → Voice Agent 統合時の拡張点
        """

    async def create(self) -> None:
        """セッションを作成し、イベントハンドラを登録。

        create_session に渡す設定:
        {
            "model": self.model,
            "streaming": True,
            "on_permission_request": PermissionHandler.approve_all,
            **self.session_config,  # 追加設定をマージ
        }
        """

    async def send(self, prompt: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[str]:
        """プロンプトを送信し、完了を待って応答テキストを返す。

        戻り値: reply.data.content if reply else None

        send_and_wait を使用。timeout 秒で打ち切り。
        """

    async def destroy(self) -> None:
        """セッションを破棄。"""

    @property
    def session(self):
        """内部の Session インスタンスを返す（テスト・拡張用）"""
```

#### セッション設定のマージ順序

```python
base_config = {
    "model": self.model,
    "streaming": True,
    "on_permission_request": PermissionHandler.approve_all,
}
# session_config が base_config を上書き（on_permission_request のカスタマイズ等）
final_config = {**base_config, **self.session_config}
```

### 2.6 `main.py` — エントリポイント

#### フロー

```
1. tkinter root 作成（Main Thread）
2. asyncio event loop を別スレッドで起動（SDK 通信用）
3. ChatWindow 作成（初期状態は非表示）
    - SDK 接続完了まで入力欄/Send を無効化（Ready=false）
    - ステータス表示: "SDK: Connecting..." / "Connected" / "Error"
4. SDK 初期化を asyncio スレッドで開始
    - SDKClient.start() → SessionManager.create()
    - EventHandler の出力先は ChatWindow に注入
5. グローバルホットキー登録（Alt ダブルタップ）
6. System Tray を別スレッドで起動
    - Chat / Reconnect / Exit
7. tkinter mainloop 開始

終了時:
  - hotkey unhook
  - session.destroy() → client.stop()
  - asyncio loop stop
  - tray stop
  - tkinter destroy
```

#### エラーハンドリング

- SDK 初期化失敗時はウィンドウ内にエラー表示し、トレイ通知も出す
- SDK 接続前は入力 UI を無効化し、誤送信で UI が固まらないようにする
- 再接続はトレイメニューの "Reconnect" から実行（既存 session/client を破棄して再初期化）

### 2.7 エラーハンドリング方針

| エラー種別           | 発生箇所                   | 対処                                                              |
| -------------------- | -------------------------- | ----------------------------------------------------------------- |
| SDK 接続失敗         | `SDKClient.start()`        | 指数バックオフで MAX_RETRY 回リトライ → 失敗で `RuntimeError`     |
| セッション作成失敗   | `SessionManager.create()`  | 例外をそのまま伝播（main でキャッチ）                             |
| 送信タイムアウト     | `SessionManager.send()`    | `send_and_wait` の timeout で制御。タイムアウト時は `None` を返す |
| `Ctrl+C`             | `input()` / イベントループ | `KeyboardInterrupt` をキャッチして graceful shutdown              |
| `EOF`                | `input()`                  | `EOFError` をキャッチして終了                                     |
| `client.stop()` 失敗 | `SDKClient.__aexit__`      | ログ出力のみ、例外は握りつぶさない                                |

### 2.8 GUI モジュール詳細設計

#### 2.8.1 `chat_window.py` — チャットウィンドウ

```python
class ChatWindow:
    """tkinter ベースのチャットウィンドウ。

    ホットキーまたはトレイメニューから呼び出され、
    画面中央にポップアップする。
    """

    def __init__(self, on_submit: Callable[[str], None]) -> None:
        """on_submit: 入力テキストを受け取るコールバック
           （asyncio loop 経由で SessionManager.send() を呼ぶ）"""

    def show(self) -> None:
        """ウィンドウを表示してフォーカスを当てる。
        既に表示中なら前面に移動するだけ。"""

    def hide(self) -> None:
        """ウィンドウを非表示にする（破棄はしない）。"""

    def append_delta(self, delta: str) -> None:
        """ストリーミング delta を応答エリアに追記。
        スレッドセーフ（root.after() 経由）。"""

    def append_tool(self, tool_name: str) -> None:
        """ツール実行開始を表示。"""

    def on_response_complete(self) -> None:
        """応答完了時の後処理（入力欄を再アクティブ化）。"""
```

**ウィンドウ仕様**:

- サイズ: 500x600px
- 位置: 画面中央
- 常に最前面 (`topmost=True`)
- Escape キーで非表示（閉じるのではなく hide）
- Enter キーで送信（Shift+Enter で改行）
- 応答エリア: スクロール可能な Text ウィジェット
- 入力エリア: 下部の Text ウィジェット + Send ボタン
- ステータス表示: 入力エリア上部に "SDK: ..." を表示
- 入力制御: SDK 接続完了まで入力欄/Send を無効化

#### 2.8.2 `tray_app.py` — System Tray

```python
class TrayApp:
    """pystray ベースの System Tray アイコン。"""

    def __init__(
        self,
        on_chat: Callable[[], None],
        on_reconnect: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        """on_chat: Chat ウィンドウを開くコールバック
           on_reconnect: SDK 再接続コールバック
           on_quit: アプリ終了コールバック"""

    def run(self) -> None:
        """トレイアイコンを開始（ブロッキング — 専用スレッドで実行）。"""

    def stop(self) -> None:
        """トレイアイコンを停止。"""

    def notify(self, title: str, message: str) -> None:
        """トースト通知を表示。"""
```

**トレイメニュー**:

- 「💬 Chat」→ ChatWindow.show()
- 「🔄 Reconnect」→ SDK 再接続（session/client を作り直す）
- 「❌ Exit」→ アプリ終了

#### 2.8.3 `main.py` — スレッド統合

```python
async def run_sdk(send_queue, gui_callbacks):
    """asyncio スレッドで実行。SDK 接続・セッション管理・メッセージ送受信。"""

def main():
    # 1. asyncio loop を別スレッドで起動
    # 2. EventHandler に GUI コールバックを注入
    # 3. SDKClient + SessionManager を asyncio loop 内で初期化
    # 4. Global Hotkey 登録 (Alt ダブルタップ)
    # 5. TrayApp を別スレッドで起動
    # 6. ChatWindow（tkinter mainloop）をメインスレッドで実行
    # 7. 終了時: SDK shutdown → tray stop → tkinter destroy
```

**スレッド間通信**:

| 方向         | 仕組み                               | 内容                                 |
| ------------ | ------------------------------------ | ------------------------------------ |
| GUI → SDK    | `asyncio.run_coroutine_threadsafe()` | ユーザー入力をセッションに送信       |
| SDK → GUI    | `root.after()` (tkinter thread-safe) | delta/ツール表示を ChatWindow に反映 |
| Hotkey → GUI | `root.after()`                       | ChatWindow.show() を呼ぶ             |
| Tray → GUI   | `root.after()`                       | ChatWindow.show() / アプリ終了       |

### 2.9 依存関係

```toml
# pyproject.toml
[project]
dependencies = [
    "github-copilot-sdk>=0.1.25",
    "pystray>=0.19",
    "Pillow>=10.0",
    "keyboard>=0.13",
]
```

| パッケージ | 用途                                                  |
| ---------- | ----------------------------------------------------- |
| `pystray`  | System Tray アイコン・メニュー                        |
| `Pillow`   | pystray のアイコン画像処理                            |
| `keyboard` | グローバルホットキー監視（Windows で管理者権限不要）  |
| `tkinter`  | チャットウィンドウ（Python 標準ライブラリ、追加不要） |

---

## 3. テスト計画

### 3.1 手動テストケース

| #   | テスト                               | 期待結果                                              |
| --- | ------------------------------------ | ----------------------------------------------------- |
| 1   | `uv run python main.py` で起動       | System Tray にアイコン表示 + SDK 接続完了通知         |
| 2   | `Alt` を素早く2回押す（Alt×2）       | チャットウィンドウが画面中央にポップアップ            |
| 3   | 「Hello」送信                        | ウィンドウ内にストリーミングで文字が流れる            |
| 4   | `Escape` キー                        | チャットウィンドウが非表示になる                      |
| 5   | 再度 `Alt` を素早く2回押す（Alt×2）  | 同じウィンドウが再表示される（会話履歴が残っている）  |
| 6   | トレイアイコン右クリック → 「Chat」  | チャットウィンドウ表示                                |
| 7   | トレイアイコン右クリック → 「Exit」  | SDK クリーンアップ → アプリ終了                       |
| 8   | 空入力で Enter                       | スキップされる                                        |
| 9   | copilot CLI 未インストール状態で起動 | トースト通知でエラー表示                              |
| 10  | 起動直後（SDK 接続前）               | 入力欄/Send が無効、ステータスが "SDK: Connecting..." |
| 11  | トレイ右クリック → 「Reconnect」     | SDK を再初期化し、成功すれば "SDK: Connected" に戻る  |

---

## 4. 備考

- Step 0 は `PermissionHandler.approve_all`（全許可）で問題ない。Step 3 で顧客向けには `onPreToolUse` フックでホワイトリスト制御に切り替える
- `event.type.value` で文字列比較するのは SDK の現在の仕様。`SessionEventType` enum との比較は将来変更される可能性あり。両方対応できるよう `event_handler.py` で吸収する
- README の「素振り / 15分」は実際の位置づけを更新する必要があるが、ルートの README は Step 0 完了後にまとめて整合する
