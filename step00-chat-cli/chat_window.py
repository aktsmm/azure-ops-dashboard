"""Step 0: SDK Chat CLI — tkinter チャットウィンドウ

ホットキーまたはトレイメニューから呼び出されるポップアップ。
ストリーミング表示・ツール実行表示に対応。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext
from typing import Callable, Optional

from config import (
    ACCENT_COLOR,
    FONT_FAMILY,
    FONT_SIZE,
    INPUT_BG,
    REASONING_COLOR,
    TEXT_FG,
    TOOL_COLOR,
    USER_COLOR,
    WINDOW_BG,
    WINDOW_HEIGHT,
    WINDOW_TITLE,
    WINDOW_WIDTH,
)


class ChatWindow:
    """tkinter ベースのチャットウィンドウ。

    ホットキーまたはトレイメニューから show() で表示し、
    Escape で hide()（非表示）する。ウィンドウは破棄しない。

    Voice Agent 統合時は on_submit を差し替えて
    音声入力と統合する。
    """

    def __init__(
        self,
        root: tk.Tk,
        on_submit: Callable[[str], None],
    ) -> None:
        """
        root: tkinter のルートウィンドウ
        on_submit: 入力テキストを受け取るコールバック
                   （asyncio loop 経由で SessionManager.send() を呼ぶ）
        """
        self._root = root
        self._on_submit = on_submit
        self._is_sending = False
        self._is_ready = False
        self._status_var = tk.StringVar(value="SDK: Connecting...")

        self._setup_window()
        self._setup_widgets()
        self._setup_bindings()
        self._setup_tags()

        # SDK 接続完了までは入力不可
        self.set_ready(False)

        # 初期状態は非表示
        self._root.withdraw()

    def _after(self, func: Callable[..., None], *args: object) -> None:
        """root.after の薄いラッパー。

        シャットダウン中に root が破棄済みでも SDK 側イベントが飛ぶことがあるため、
        TclError は無視して落とさない。
        """
        try:
            self._root.after(0, func, *args)
        except tk.TclError:
            return

    # ------------------------------------------------------------------ #
    # ウィンドウ設定
    # ------------------------------------------------------------------ #

    def _setup_window(self) -> None:
        self._root.title(WINDOW_TITLE)
        self._root.configure(bg=WINDOW_BG)
        self._root.attributes("-topmost", True)
        self._root.protocol("WM_DELETE_WINDOW", self.hide)

        # 画面中央に配置
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        x = (screen_w - WINDOW_WIDTH) // 2
        y = (screen_h - WINDOW_HEIGHT) // 2
        self._root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")

        # 最小サイズ
        self._root.minsize(350, 400)

    def _setup_widgets(self) -> None:
        # --- 応答エリア（上部） ---
        self._chat_area = scrolledtext.ScrolledText(
            self._root,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg=WINDOW_BG,
            fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE),
            insertbackground=TEXT_FG,
            relief=tk.FLAT,
            padx=12,
            pady=8,
            borderwidth=0,
        )
        self._chat_area.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))

        # --- 入力フレーム（下部） ---
        input_frame = tk.Frame(self._root, bg=WINDOW_BG)
        input_frame.pack(fill=tk.X, padx=4, pady=4)

        self._status_label = tk.Label(
            input_frame,
            textvariable=self._status_var,
            bg=WINDOW_BG,
            fg=ACCENT_COLOR,
            font=(FONT_FAMILY, FONT_SIZE - 2),
            anchor="w",
        )
        self._status_label.pack(side=tk.TOP, fill=tk.X, padx=2, pady=(0, 4))

        self._input_box = tk.Text(
            input_frame,
            height=3,
            wrap=tk.WORD,
            bg=INPUT_BG,
            fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE),
            insertbackground=TEXT_FG,
            relief=tk.FLAT,
            padx=8,
            pady=6,
            borderwidth=0,
        )
        self._input_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._send_btn = tk.Button(
            input_frame,
            text="Send",
            command=self._handle_send,
            bg=ACCENT_COLOR,
            fg="white",
            font=(FONT_FAMILY, FONT_SIZE - 1, "bold"),
            relief=tk.FLAT,
            padx=16,
            pady=6,
            cursor="hand2",
            activebackground="#005a9e",
            activeforeground="white",
        )
        self._send_btn.pack(side=tk.RIGHT, padx=(4, 0), fill=tk.Y)

    def set_status(self, text: str) -> None:
        """接続状態などのステータス表示を更新（スレッドセーフ）。"""
        self._after(self._status_var.set, text)

    def set_ready(self, ready: bool) -> None:
        """SDK 接続完了フラグを更新し、入力可否を切り替える。"""
        def _apply() -> None:
            self._is_ready = ready
            if not ready:
                self._status_var.set("SDK: Connecting...")
                self._input_box.configure(state=tk.DISABLED)
                self._send_btn.configure(state=tk.DISABLED)
                return

            self._status_var.set("SDK: Connected")
            if not self._is_sending:
                self._input_box.configure(state=tk.NORMAL)
                self._send_btn.configure(state=tk.NORMAL)
                self._input_box.focus_set()

        self._after(_apply)

    def _setup_bindings(self) -> None:
        self._root.bind("<Escape>", lambda _: self.hide())
        self._input_box.bind("<Return>", self._on_enter)
        self._input_box.bind("<Shift-Return>", lambda _: None)  # 改行を許可

    def _setup_tags(self) -> None:
        """テキストタグ（色分け用）を定義。"""
        self._chat_area.tag_configure("user", foreground=USER_COLOR)
        self._chat_area.tag_configure("assistant", foreground=TEXT_FG)
        self._chat_area.tag_configure("tool", foreground=TOOL_COLOR)
        self._chat_area.tag_configure("reasoning", foreground=REASONING_COLOR)
        self._chat_area.tag_configure("error", foreground="#f44747")
        self._chat_area.tag_configure("system", foreground=ACCENT_COLOR)

    # ------------------------------------------------------------------ #
    # 表示制御
    # ------------------------------------------------------------------ #

    def show(self) -> None:
        """ウィンドウを表示してフォーカスを当てる。"""
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()
        self._input_box.focus_set()

    def hide(self) -> None:
        """ウィンドウを非表示にする（破棄はしない）。"""
        self._root.withdraw()

    @property
    def is_visible(self) -> bool:
        return self._root.state() != "withdrawn"

    def toggle(self) -> None:
        """表示/非表示をトグル。"""
        if self.is_visible:
            self.hide()
        else:
            self.show()

    # ------------------------------------------------------------------ #
    # メッセージ表示（スレッドセーフ — root.after 経由で呼ぶ）
    # ------------------------------------------------------------------ #

    def _append_text(self, text: str, tag: str = "assistant") -> None:
        """チャットエリアにテキストを追加（内部用）。"""
        self._chat_area.configure(state=tk.NORMAL)
        self._chat_area.insert(tk.END, text, tag)
        self._chat_area.see(tk.END)
        self._chat_area.configure(state=tk.DISABLED)

    def append_user_message(self, text: str) -> None:
        """ユーザー発言を表示。"""
        self._after(self._append_text, f"\nYou: {text}\n\n", "user")

    def append_delta(self, delta: str) -> None:
        """ストリーミング delta を追記。スレッドセーフ。"""
        self._after(self._append_text, delta, "assistant")

    def append_tool(self, tool_name: str) -> None:
        """ツール実行開始を表示。"""
        self._after(self._append_text, f"[tool: {tool_name}]\n", "tool")

    def append_reasoning(self, delta: str) -> None:
        """推論 delta を表示。"""
        self._after(self._append_text, delta, "reasoning")

    def append_system(self, text: str) -> None:
        """システムメッセージを表示。"""
        self._after(self._append_text, f"[system] {text}\n", "system")

    def append_error(self, text: str) -> None:
        """エラーメッセージを表示。"""
        self._after(self._append_text, f"[error] {text}\n", "error")

    def on_response_complete(self) -> None:
        """応答完了時の後処理。"""
        def _complete() -> None:
            self._append_text("\n", "assistant")
            self._is_sending = False
            if self._is_ready:
                self._input_box.configure(state=tk.NORMAL)
                self._send_btn.configure(state=tk.NORMAL)
                self._input_box.focus_set()
        self._after(_complete)

    # ------------------------------------------------------------------ #
    # 入力処理
    # ------------------------------------------------------------------ #

    def _on_enter(self, event: tk.Event) -> str:
        """Enter キーで送信（Shift+Enter は改行）。"""
        if not event.state & 0x1:  # Shift が押されていなければ
            self._handle_send()
            return "break"  # デフォルト改行を抑制
        return ""

    def _handle_send(self) -> None:
        """入力テキストを取得して on_submit コールバックに渡す。"""
        if not self._is_ready:
            return
        text = self._input_box.get("1.0", tk.END).strip()
        if not text or self._is_sending:
            return

        self._is_sending = True
        self._input_box.delete("1.0", tk.END)
        self._input_box.configure(state=tk.DISABLED)
        self._send_btn.configure(state=tk.DISABLED)

        self.append_user_message(text)
        self._on_submit(text)
