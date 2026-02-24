"""Step 03: Voice-first Enterprise Copilot — メインアプリ

システムトレイ常駐 + モード切替（dictation / agent）。

実装状況:
- トレイ常駐 + 右クリックメニュー: ✅
- モード切替（dictation / agent）: ✅
- SDK 統合 (src/sdk/): ✅
- 音声統合 (src/speech/): ✅
- Skills 同期 (src/skills/): ✅
- ToolApproval (src/tools/): ✅
- MCP サーバー設定 (src/mcp_config.py): ✅
"""

from __future__ import annotations

import asyncio
import queue
import sys
import threading
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    import pystray
    from PIL import Image as _PilImage

# pystray / PIL は optional
try:
    import pystray  # type: ignore[import-not-found]
    from PIL import Image, ImageDraw  # type: ignore[import-not-found]
    _TRAY_AVAILABLE = True
except ImportError:
    pystray = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    _TRAY_AVAILABLE = False
    print("[app] pystray/Pillow が見つかりません。トレイアイコンは無効化されます。", file=sys.stderr)

# ---------------------------------------------------------------------------
# optional: SDK
# ---------------------------------------------------------------------------
try:
    import sys as _sys
    _src = str(Path(__file__).parent)
    if _src not in _sys.path:
        _sys.path.insert(0, _src)
    from sdk import SDKClient, SessionManager, EventHandler  # type: ignore[import]
    _SDK_AVAILABLE = True
except ImportError:
    SDKClient = None  # type: ignore[assignment,misc]
    SessionManager = None  # type: ignore[assignment,misc]
    EventHandler = None  # type: ignore[assignment,misc]
    _SDK_AVAILABLE = False
    print("[app] SDK モジュールが見つかりません。Agent モードは無効です。", file=sys.stderr)

# ---------------------------------------------------------------------------
# optional: Speech
# ---------------------------------------------------------------------------
try:
    from speech import AzureSpeech  # type: ignore[import]
    _SPEECH_AVAILABLE = True
except ImportError:
    AzureSpeech = None  # type: ignore[assignment,misc]
    _SPEECH_AVAILABLE = False
    print("[app] Speech モジュールが見つかりません。音声機能は無効です。", file=sys.stderr)

# ---------------------------------------------------------------------------
# optional: Skills
# ---------------------------------------------------------------------------
try:
    from skills import SkillManager  # type: ignore[import]
    _SKILLS_AVAILABLE = True
except ImportError:
    SkillManager = None  # type: ignore[assignment,misc]
    _SKILLS_AVAILABLE = False

# ---------------------------------------------------------------------------
# optional: Tools
# ---------------------------------------------------------------------------
try:
    from tools import ApprovalMode, ToolApproval  # type: ignore[import]
    _TOOLS_AVAILABLE = True
except ImportError:
    ApprovalMode = None  # type: ignore[assignment,misc]
    ToolApproval = None  # type: ignore[assignment,misc]
    _TOOLS_AVAILABLE = False

# ---------------------------------------------------------------------------
# optional: MCP Config
# ---------------------------------------------------------------------------
try:
    from mcp_config import MCPConfig  # type: ignore[import]
    _MCP_AVAILABLE = True
except ImportError:
    MCPConfig = None  # type: ignore[assignment,misc]
    _MCP_AVAILABLE = False

# ---------------------------------------------------------------------------
# optional: pyautogui
# ---------------------------------------------------------------------------
try:
    import pyautogui as _pyautogui  # type: ignore[import-not-found]
    _PYAUTOGUI_AVAILABLE = True
except ImportError:
    _pyautogui = None  # type: ignore[assignment]
    _PYAUTOGUI_AVAILABLE = False


# ---------------------------------------------------------------------------
# モード定義
# ---------------------------------------------------------------------------

class AppMode(Enum):
    IDLE = auto()
    DICTATION = auto()
    AGENT = auto()


# ---------------------------------------------------------------------------
# トレイアイコン生成
# ---------------------------------------------------------------------------

def _make_icon_image(mode: AppMode, size: int = 64) -> Any:
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow が未インストールです")
    color_map = {
        AppMode.IDLE: "#555555",
        AppMode.DICTATION: "#e05c44",
        AppMode.AGENT: "#0078d4",
    }
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=color_map.get(mode, "#555555"))
    return img


# ---------------------------------------------------------------------------
# AppController
# ---------------------------------------------------------------------------

class AppController:
    """アプリ全体の状態管理とモード切替を担当。"""

    def __init__(self) -> None:
        self._mode = AppMode.IDLE
        self._mode_lock = threading.Lock()
        self._icon: Any = None

        self._sdk: Any = None
        self._speech: Any = None

        self._agent_stop = threading.Event()
        self._agent_input_queue: queue.Queue[str] = queue.Queue()
        self._agent_thread: Optional[threading.Thread] = None

        self._dictation_typewrite = _pyautogui.typewrite if _PYAUTOGUI_AVAILABLE else None

        # Skills / Tools / MCP（初期化）
        self._skill_manager: Any = None
        self._tool_approval: Any = None
        self._mcp_config: Any = None
        self._init_skills_tools_mcp()

    def _init_skills_tools_mcp(self) -> None:
        if _SKILLS_AVAILABLE and SkillManager is not None:
            try:
                self._skill_manager = SkillManager()
                dirs = self._skill_manager.skill_directories()
                print(f"[app] Skills: {len(dirs)} スキルディレクトリ", file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"[app] SkillManager 初期化失敗: {e}", file=sys.stderr)

        if _TOOLS_AVAILABLE and ToolApproval is not None and ApprovalMode is not None:
            try:
                self._tool_approval = ToolApproval(mode=ApprovalMode.SAFE)
                print("[app] ToolApproval: SAFE モード", file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"[app] ToolApproval 初期化失敗: {e}", file=sys.stderr)

        if _MCP_AVAILABLE and MCPConfig is not None:
            try:
                self._mcp_config = MCPConfig()
                print("[app] MCPConfig: 初期化完了", file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"[app] MCPConfig 初期化失敗: {e}", file=sys.stderr)

    def attach_sdk(self, sdk: object) -> None:
        self._sdk = sdk

    def attach_speech(self, speech: object) -> None:
        self._speech = speech

    @property
    def mode(self) -> AppMode:
        with self._mode_lock:
            return self._mode

    def set_mode(self, mode: AppMode) -> None:
        with self._mode_lock:
            if self._mode == mode:
                return
            old = self._mode
            self._mode = mode
        print(f"[app] mode: {old.name} → {mode.name}", file=sys.stderr)
        self._refresh_icon()
        self._on_mode_change(mode)

    def _on_mode_change(self, mode: AppMode) -> None:
        if mode == AppMode.DICTATION:
            self._stop_agent_mode()
            self._start_dictation_mode()
        elif mode == AppMode.AGENT:
            self._stop_dictation_mode()
            self._start_agent_mode()
        else:
            self._stop_dictation_mode()
            self._stop_agent_mode()
            print("[app] Idle mode.", file=sys.stderr)

    # ------------------------------------------------------------------ #
    # Dictation モード
    # ------------------------------------------------------------------ #

    def _start_dictation_mode(self) -> None:
        if self._speech is None:
            print("[app] Dictation mode: Speech モジュール未アタッチ", file=sys.stderr)
            return
        if self._speech.is_recognizing:
            return
        if self._dictation_typewrite is not None:
            def on_text(text: str) -> None:
                self._dictation_typewrite(text, interval=0.02)  # type: ignore[misc]
        else:
            def on_text(text: str) -> None:  # type: ignore[misc]
                print(f"[app] 🎤 dictation: {text}")
        try:
            self._speech.start_recognition(on_text_cb=on_text)
        except Exception as e:  # noqa: BLE001
            print(f"[app] STT 開始エラー: {e}", file=sys.stderr)

    def _stop_dictation_mode(self) -> None:
        if self._speech is not None and self._speech.is_recognizing:
            self._speech.stop_recognition()

    # ------------------------------------------------------------------ #
    # Agent モード
    # ------------------------------------------------------------------ #

    def _start_agent_mode(self) -> None:
        if self._sdk is None:
            print("[app] Agent mode: SDK 未アタッチ", file=sys.stderr)
            return
        if self._agent_thread is not None and self._agent_thread.is_alive():
            return

        self._agent_stop.clear()
        while not self._agent_input_queue.empty():
            try:
                self._agent_input_queue.get_nowait()
            except queue.Empty:
                break

        if self._speech is not None:
            def on_agent_text(text: str) -> None:
                self._agent_input_queue.put(text)
            try:
                self._speech.start_recognition(on_text_cb=on_agent_text)
            except Exception as e:  # noqa: BLE001
                print(f"[app] Agent STT 開始エラー: {e}", file=sys.stderr)

        self._agent_thread = threading.Thread(
            target=self._run_agent_loop_sync, daemon=True, name="agent-loop"
        )
        self._agent_thread.start()
        print("[app] Agent mode 開始", file=sys.stderr)

    def _stop_agent_mode(self) -> None:
        self._agent_stop.set()
        self._agent_input_queue.put("__STOP__")
        if self._agent_thread is not None:
            self._agent_thread.join(timeout=5.0)
            self._agent_thread = None
        if self._speech is not None and self._speech.is_recognizing:
            self._speech.stop_recognition()

    def _run_agent_loop_sync(self) -> None:
        try:
            asyncio.run(self._agent_async_loop())
        except Exception as e:  # noqa: BLE001
            print(f"[app] Agent ループエラー: {e}", file=sys.stderr)

    async def _agent_async_loop(self) -> None:
        """SDK セッションを維持しながら STT テキストを受信して応答する非同期ループ。"""
        if SDKClient is None:
            print("[app] SDK が利用できません", file=sys.stderr)
            return

        response_buf: list[str] = []

        def _on_delta(delta: str) -> None:
            response_buf.append(delta)
            print(delta, end="", flush=True)

        def _on_complete(content: str) -> None:  # noqa: ARG001
            print()
            full = "".join(response_buf)
            response_buf.clear()
            if self._speech is not None and full:
                self._speech.speak_async(full)

        if EventHandler is not None:
            event_handler = EventHandler(on_delta=_on_delta, on_message_complete=_on_complete)
        else:
            event_handler = None

        # セッション設定を組み立て（skills / tools / mcp を注入）
        session_config: dict[str, Any] = {
            "model": "gpt-4.1",
            "streaming": True,
        }

        if self._skill_manager is not None:
            session_config = self._skill_manager.inject_into_config(session_config)

        if self._tool_approval is not None:
            session_config = self._tool_approval.inject_into_config(session_config)
        else:
            # ToolApproval なしの場合は approve_all をフォールバックとして設定
            try:
                from copilot import PermissionHandler  # type: ignore[import-not-found]
                session_config["on_permission_request"] = PermissionHandler.approve_all
            except ImportError:
                pass

        if self._mcp_config is not None:
            session_config = self._mcp_config.inject_into_config(session_config)

        try:
            async with SDKClient() as client:
                if SessionManager is not None:
                    mgr = SessionManager(client, event_handler, session_config=session_config)
                    await mgr.create()
                else:
                    # SessionManager 非利用時は直接 create_session
                    from copilot import PermissionHandler as PH  # type: ignore[import-not-found]
                    session_config.setdefault("on_permission_request", PH.approve_all)
                    raw_session = await client.client.create_session(session_config)
                    if event_handler is not None:
                        raw_session.on(event_handler.handle)
                    class _MgrShim:
                        def __init__(self, s): self._s = s
                        async def send(self, t): await self._s.send_and_wait({"prompt": t}, timeout=120)
                        async def destroy(self): await self._s.delete()
                    mgr = _MgrShim(raw_session)  # type: ignore[assignment]

                print("[app] 🤖 Agent: 話しかけてください", file=sys.stderr)

                while not self._agent_stop.is_set():
                    try:
                        text = await asyncio.to_thread(self._agent_input_queue.get, True, 1.0)
                    except Exception:
                        continue

                    if text == "__STOP__" or self._agent_stop.is_set():
                        break

                    print(f"[app] >> {text}")
                    await mgr.send(text)

                await mgr.destroy()
        except Exception as e:  # noqa: BLE001
            print(f"[app] Agent セッションエラー: {e}", file=sys.stderr)

    # ------------------------------------------------------------------ #
    # トレイ
    # ------------------------------------------------------------------ #

    def _build_menu(self) -> Any:
        if pystray is None:
            raise RuntimeError("pystray が未インストールです")
        items = []
        if self._mode == AppMode.DICTATION:
            items.append(pystray.MenuItem("🔴 Dictation 停止", lambda: self.set_mode(AppMode.IDLE)))
        else:
            items.append(pystray.MenuItem("🎤 Dictation 開始", lambda: self.set_mode(AppMode.DICTATION)))
        if self._mode == AppMode.AGENT:
            items.append(pystray.MenuItem("🔵 Agent 停止", lambda: self.set_mode(AppMode.IDLE)))
        else:
            items.append(pystray.MenuItem("🤖 Agent 開始", lambda: self.set_mode(AppMode.AGENT)))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("❌ 終了", self._handle_quit))
        return pystray.Menu(*items)

    def _refresh_icon(self) -> None:
        if self._icon is None or not _TRAY_AVAILABLE:
            return
        self._icon.icon = _make_icon_image(self._mode)
        self._icon.menu = self._build_menu()

    def _handle_quit(self) -> None:
        print("[app] 終了します...", file=sys.stderr)
        self.set_mode(AppMode.IDLE)
        if self._icon is not None:
            self._icon.stop()

    def run_tray(self) -> None:
        if not _TRAY_AVAILABLE:
            print("[app] トレイなしモードで待機中。Ctrl+C で終了。", file=sys.stderr)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
            return
        image = _make_icon_image(AppMode.IDLE)
        assert pystray is not None
        self._icon = pystray.Icon(
            name="voice-copilot",
            icon=image,
            title="Voice Copilot (Step03)",
            menu=self._build_menu(),
        )
        self._icon.run()


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def main() -> int:
    app = AppController()
    print("[app] Voice-first Enterprise Copilot を起動します...", file=sys.stderr)

    if _SDK_AVAILABLE and SDKClient is not None:
        app.attach_sdk(SDKClient)
        print("[app] SDK: 有効", file=sys.stderr)
    else:
        print("[app] SDK: 無効（copilot SDK 未インストール）", file=sys.stderr)

    if _SPEECH_AVAILABLE and AzureSpeech is not None:
        try:
            speech = AzureSpeech()
            app.attach_speech(speech)
            print("[app] Speech: 有効", file=sys.stderr)
        except RuntimeError as e:
            print(f"[app] Speech 初期化失敗: {e}", file=sys.stderr)
    else:
        print("[app] Speech: 無効（azure-cognitiveservices-speech 未インストール）", file=sys.stderr)

    app.run_tray()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
