"""Step 0: SDK Chat CLI — System Tray 管理

pystray ベースの System Tray アイコン。
右クリックメニューから Chat ウィンドウ表示・アプリ終了を操作。
"""

from __future__ import annotations

from typing import Callable

import pystray
from PIL import Image, ImageDraw

from app_paths import bundled_icon_path


class TrayApp:
    """pystray ベースの System Tray アイコン。

    別スレッドで run() を呼ぶ（ブロッキング）。
    メインスレッド（tkinter）から stop() で終了。
    """

    def __init__(
        self,
        on_chat: Callable[[], None],
        on_reconnect: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        """
        on_chat: Chat ウィンドウを開くコールバック
        on_reconnect: SDK 再接続コールバック
        on_quit: アプリ終了コールバック
        """
        self._on_chat = on_chat
        self._on_reconnect = on_reconnect
        self._on_quit = on_quit
        self._icon: pystray.Icon | None = None

    def run(self) -> None:
        """トレイアイコンを開始（ブロッキング — 専用スレッドで実行）。"""
        image = self._create_icon_image()
        menu = pystray.Menu(
            pystray.MenuItem("💬 Chat", self._handle_chat, default=True),
            pystray.MenuItem("🔄 Reconnect", self._handle_reconnect),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Exit", self._handle_quit),
        )
        self._icon = pystray.Icon(
            name="copilot-chat",
            icon=image,
            title="Copilot Chat (Alt×2 で起動)",
            menu=menu,
        )
        self._icon.run()

    def stop(self) -> None:
        """トレイアイコンを停止。"""
        if self._icon is not None:
            self._icon.stop()

    def notify(self, title: str, message: str) -> None:
        """トースト通知を表示。"""
        if self._icon is not None:
            try:
                self._icon.notify(message, title=title)
            except Exception:  # noqa: BLE001
                pass  # 通知失敗は致命的ではない

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #

    def _handle_chat(self) -> None:
        self._on_chat()

    def _handle_reconnect(self) -> None:
        self._on_reconnect()

    def _handle_quit(self) -> None:
        self._on_quit()

    @staticmethod
    def _create_icon_image() -> Image.Image:
        """プログラムで生成する簡易アイコン（16x16 の Copilot 風アイコン）。

        assets/icon.png が存在すればそちらを優先。
        """
        icon_path = bundled_icon_path()
        if icon_path.exists():
            with Image.open(icon_path) as img:
                return img.copy()

        # フォールバック: 青い丸に白い C
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, size - 2, size - 2], fill="#0078d4")
        # 中央に「C」を描画
        try:
            from PIL import ImageFont

            font = ImageFont.truetype("arial.ttf", size=36)
        except OSError:
            font = ImageFont.load_default()
        draw.text((size // 2, size // 2), "C", fill="white", font=font, anchor="mm")
        return img
