"""Step 0: SDK Chat CLI — GUI 常駐アプリ

System Tray 常駐 + Alt ダブルタップでチャットウィンドウ起動。
ストリーミング表示・イベントハンドリング・エラーハンドリング・
クリーンアップ保証を備え、Step 2 統合時にそのまま再利用できる。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import sys
import threading
import time
import tkinter as tk
from typing import Optional

import keyboard

from chat_window import ChatWindow
from config import (
    HOTKEY_INTERVAL,
    HOTKEY_KEY,
    PREFIX_ERROR,
    PREFIX_SYSTEM,
)
from event_handler import EventHandler
from sdk_client import SDKClient
from session_manager import SessionManager
from tray_app import TrayApp


class App:
    """アプリケーション全体を統合するコントローラ。

    スレッド構成:
      Main Thread  → tkinter メインループ（ChatWindow）
      Thread 1     → asyncio event loop（SDK 通信）
      Thread 2     → pystray（System Tray）
      keyboard     → グローバルホットキー監視（独立）
    """

    def __init__(self) -> None:
        self._root: Optional[tk.Tk] = None
        self._chat_window: Optional[ChatWindow] = None
        self._tray: Optional[TrayApp] = None
        self._sdk_client: Optional[SDKClient] = None
        self._session_mgr: Optional[SessionManager] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._loop_ready = threading.Event()
        self._tray_thread: Optional[threading.Thread] = None
        self._last_alt_time: float = 0.0
        self._shutting_down = False
        self._reconnecting = False

    # ------------------------------------------------------------------ #
    # 起動
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """アプリケーションを起動。"""
        # 1. tkinter ルートウィンドウ
        self._root = tk.Tk()

        # 2. asyncio ループを別スレッドで起動
        self._loop = asyncio.new_event_loop()
        self._loop_ready.clear()
        self._loop_thread = threading.Thread(
            target=self._run_async_loop, daemon=True, name="asyncio-sdk"
        )
        self._loop_thread.start()

        # ループが回り始めてからスケジューリングする（競合回避）
        if not self._loop_ready.wait(timeout=5):
            msg = "内部エラー: SDK ループの起動がタイムアウトしました"
            print(f"{PREFIX_ERROR} {msg}", file=sys.stderr)
            try:
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:  # noqa: BLE001
                pass
            try:
                self._root.destroy()
            except Exception:  # noqa: BLE001
                pass
            return

        # 3. ChatWindow 作成
        self._chat_window = ChatWindow(self._root, on_submit=self._on_user_submit)
        self._chat_window.append_system("SDK 接続中...")
        self._chat_window.set_ready(False)

        # 4. SDK 初期化（asyncio スレッドで実行）
        future = asyncio.run_coroutine_threadsafe(self._init_sdk(), self._loop)
        future.add_done_callback(self._on_sdk_init_done)

        # 5. グローバルホットキー登録（Alt ダブルタップ）
        self._register_hotkey()

        # 6. System Tray を別スレッドで起動
        self._tray = TrayApp(
            on_chat=self._show_chat_threadsafe,
            on_reconnect=self._reconnect_threadsafe,
            on_quit=self._quit_threadsafe,
        )
        self._tray_thread = threading.Thread(
            target=self._tray.run, daemon=True, name="system-tray"
        )
        self._tray_thread.start()

        print(f"{PREFIX_SYSTEM} App started — Alt×2 でチャット起動")

        # 7. tkinter メインループ（ブロッキング）
        self._root.mainloop()

    # ------------------------------------------------------------------ #
    # asyncio ループ
    # ------------------------------------------------------------------ #

    def _run_async_loop(self) -> None:
        """asyncio イベントループを実行（別スレッド）。"""
        if self._loop is None:
            return
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._loop_ready.set)
        try:
            self._loop.run_forever()
        finally:
            try:
                self._loop.close()
            except Exception:  # noqa: BLE001
                pass

    async def _init_sdk(self) -> None:
        """SDK Client + Session を初期化。"""
        self._sdk_client = SDKClient()
        await self._sdk_client.start()

        chat_window = self._chat_window
        if chat_window is None:
            raise RuntimeError("ChatWindow is not initialized")

        handler = EventHandler(
            on_delta=chat_window.append_delta,
            on_message_complete=lambda _: chat_window.on_response_complete(),
            on_tool_start=chat_window.append_tool,
            on_reasoning_delta=chat_window.append_reasoning,
            on_reasoning=lambda _: None,
            on_idle=lambda: None,
        )
        self._session_mgr = SessionManager(self._sdk_client, handler)
        await self._session_mgr.create()

    def _on_sdk_init_done(self, future: concurrent.futures.Future[None]) -> None:
        """SDK 初期化完了コールバック。"""
        try:
            future.result()
            if self._chat_window:
                self._chat_window.set_ready(True)
                self._chat_window.append_system("SDK 接続完了 — Alt×2 でチャット起動")
            if self._tray:
                self._tray.notify("Copilot Chat", "SDK 接続完了。Alt×2 でチャット起動。")
        except Exception as e:  # noqa: BLE001
            msg = f"SDK 初期化失敗: {e}"
            print(f"{PREFIX_ERROR} {msg}", file=sys.stderr)
            if self._chat_window:
                self._chat_window.set_status("SDK: Error")
                self._chat_window.append_error(msg)
            if self._tray:
                self._tray.notify("Copilot Chat — Error", msg)

    # ------------------------------------------------------------------ #
    # ホットキー（Alt ダブルタップ）
    # ------------------------------------------------------------------ #

    def _register_hotkey(self) -> None:
        """Alt ダブルタップを検出するホットキーを登録。"""
        keyboard.on_release_key(HOTKEY_KEY, self._on_hotkey_release, suppress=False)

    def _on_hotkey_release(self, event: keyboard.KeyboardEvent) -> None:  # noqa: ARG001
        """Alt キーのリリースでダブルタップを検出。"""
        now = time.time()
        elapsed = now - self._last_alt_time
        self._last_alt_time = now

        if elapsed < HOTKEY_INTERVAL:
            # ダブルタップ検出 → ChatWindow をトグル
            self._last_alt_time = 0.0  # リセット（3連打防止）
            self._toggle_chat_threadsafe()

    # ------------------------------------------------------------------ #
    # スレッドセーフ操作
    # ------------------------------------------------------------------ #

    def _show_chat_threadsafe(self) -> None:
        """任意のスレッドから ChatWindow を表示。"""
        if self._root and self._chat_window:
            self._root.after(0, self._chat_window.show)

    def _toggle_chat_threadsafe(self) -> None:
        """任意のスレッドから ChatWindow をトグル。"""
        if self._root and self._chat_window:
            self._root.after(0, self._chat_window.toggle)

    def _quit_threadsafe(self) -> None:
        """任意のスレッドからアプリを終了。"""
        if self._root:
            self._root.after(0, self._shutdown)

    def _reconnect_threadsafe(self) -> None:
        """任意のスレッドから SDK 再接続を開始。"""
        if self._root:
            self._root.after(0, self._start_reconnect)

    def _start_reconnect(self) -> None:
        """tkinter スレッド上で再接続をスケジュール。"""
        if self._shutting_down or self._reconnecting:
            return
        self._reconnecting = True

        if self._chat_window:
            self._chat_window.set_ready(False)
            self._chat_window.set_status("SDK: Reconnecting...")
            self._chat_window.append_system("SDK 再接続中...")

        if self._loop is None:
            if self._chat_window:
                self._chat_window.append_error("再接続に失敗しました: SDK ループが未初期化")
            self._reconnecting = False
            return

        future: concurrent.futures.Future[None] = asyncio.run_coroutine_threadsafe(
            self._reconnect_sdk(), self._loop
        )
        future.add_done_callback(self._on_reconnect_done)

    def _on_reconnect_done(self, future: concurrent.futures.Future[None]) -> None:
        try:
            future.result()
            if self._chat_window:
                self._chat_window.set_ready(True)
                self._chat_window.append_system("SDK 再接続完了")
            if self._tray:
                self._tray.notify("Copilot Chat", "SDK 再接続完了")
        except Exception as e:  # noqa: BLE001
            msg = f"SDK 再接続失敗: {e}"
            print(f"{PREFIX_ERROR} {msg}", file=sys.stderr)
            if self._chat_window:
                self._chat_window.set_status("SDK: Error")
                self._chat_window.append_error(msg)
                self._chat_window.on_response_complete()
            if self._tray:
                self._tray.notify("Copilot Chat — Error", msg)
        finally:
            self._reconnecting = False

    # ------------------------------------------------------------------ #
    # ユーザー入力 → SDK 送信
    # ------------------------------------------------------------------ #

    def _on_user_submit(self, text: str) -> None:
        """ChatWindow からのユーザー入力を SDK に送信。"""
        if self._chat_window is None:
            return

        if self._loop is None:
            self._chat_window.append_error("内部エラー: SDK ループが初期化されていません")
            self._chat_window.on_response_complete()
            return

        if self._session_mgr is None:
            self._chat_window.append_error("SDK 接続中です。少し待ってから再送してください")
            self._chat_window.on_response_complete()
            return

        asyncio.run_coroutine_threadsafe(self._send_message(text), self._loop)

    async def _send_message(self, text: str) -> None:
        """SDK にメッセージを送信。"""
        if self._session_mgr is None:
            return

        try:
            reply = await self._session_mgr.send(text)
        except Exception as e:  # noqa: BLE001
            if self._chat_window:
                self._chat_window.append_error(f"送信に失敗しました: {e}")
                self._chat_window.on_response_complete()
            return

        if reply is None and self._chat_window:
            self._chat_window.append_error("応答を取得できませんでした")
            self._chat_window.on_response_complete()

    # ------------------------------------------------------------------ #
    # シャットダウン
    # ------------------------------------------------------------------ #

    def _shutdown(self) -> None:
        """アプリケーションを終了。"""
        if self._shutting_down:
            return
        self._shutting_down = True

        print(f"{PREFIX_SYSTEM} Shutting down...")

        # ホットキー解除
        try:
            keyboard.unhook_all()
        except Exception:  # noqa: BLE001
            pass

        # SDK クリーンアップ（asyncio スレッドで実行）
        if self._loop and self._session_mgr:
            future: concurrent.futures.Future[None] = asyncio.run_coroutine_threadsafe(
                self._cleanup_sdk(), self._loop
            )
            try:
                future.result(timeout=5)
            except Exception:  # noqa: BLE001
                pass

        # asyncio ループ停止
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

        # Tray 停止
        if self._tray:
            try:
                self._tray.stop()
            except Exception:  # noqa: BLE001
                pass

        # tkinter 終了
        if self._root:
            try:
                self._root.destroy()
            except Exception:  # noqa: BLE001
                pass

        print(f"{PREFIX_SYSTEM} Shutdown complete")

    async def _cleanup_sdk(self) -> None:
        """SDK のクリーンアップ。"""
        if self._session_mgr:
            await self._session_mgr.destroy()
        if self._sdk_client:
            await self._sdk_client.stop()

    async def _reconnect_sdk(self) -> None:
        """SDK をクリーンアップして再初期化する（asyncio スレッド）。"""
        await self._cleanup_sdk()

        # 初期化と同じ手順で作り直す
        self._sdk_client = SDKClient()
        await self._sdk_client.start()

        if self._chat_window is None:
            return

        chat_window = self._chat_window
        if chat_window is None:
            return

        handler = EventHandler(
            on_delta=chat_window.append_delta,
            on_message_complete=lambda _: chat_window.on_response_complete(),
            on_tool_start=chat_window.append_tool,
            on_reasoning_delta=chat_window.append_reasoning,
            on_reasoning=lambda _: None,
            on_idle=lambda: None,
        )
        self._session_mgr = SessionManager(self._sdk_client, handler)
        await self._session_mgr.create()


def main() -> None:
    """エントリポイント。"""
    app = App()
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n👋 Bye!")


if __name__ == "__main__":
    main()
