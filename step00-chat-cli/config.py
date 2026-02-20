"""Step 0: SDK Chat CLI — 設定定数

Voice Agent 統合時もこのファイルをベースに拡張する。
ユーザーは settings.json でホットキー等を上書き可能。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

# --- モデル設定 ---
DEFAULT_MODEL = "gpt-4.1"
DEFAULT_TIMEOUT = 120  # seconds

# --- リトライ設定 ---
MAX_RETRY = 3
RETRY_BACKOFF = 2.0  # seconds（指数バックオフの基数）

# --- ANSI カラーコード（コンソール用） ---
BLUE = "\033[34m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"

# --- 表示プレフィックス（コンソール用） ---
PREFIX_TOOL = f"{YELLOW}[tool]{RESET}"
PREFIX_REASONING = f"{DIM}[reasoning]{RESET}"
PREFIX_SYSTEM = f"{GREEN}[system]{RESET}"
PREFIX_ERROR = f"{RED}[error]{RESET}"

# --- GUI 設定（デフォルト値） ---
HOTKEY_KEY = "alt"           # ダブルタップで検出するキー
HOTKEY_INTERVAL = 0.35       # ダブルタップ判定間隔（秒）
WINDOW_TITLE = "Copilot Chat"
WINDOW_WIDTH = 500
WINDOW_HEIGHT = 600
WINDOW_BG = "#1e1e1e"       # VS Code ダークテーマに合わせた背景
TEXT_FG = "#d4d4d4"          # 通常テキスト
INPUT_BG = "#2d2d2d"         # 入力エリア背景
ACCENT_COLOR = "#0078d4"     # Microsoft Blue
TOOL_COLOR = "#dcdcaa"       # 黄色（ツール表示）
REASONING_COLOR = "#808080"  # グレー（推論表示）
USER_COLOR = "#569cd6"       # 青（ユーザー発言）
FONT_FAMILY = "Consolas"
FONT_SIZE = 11


# --- ユーザー設定ファイル読み込み ---
_SETTINGS_PATH = Path(__file__).parent / "settings.json"


def _set_if_valid(
    user: dict[str, Any],
    json_key: str,
    var_name: str,
    cast: Callable[[Any], Any],
    predicate: Callable[[Any], bool],
) -> None:
    """settings.json の値を検証してからモジュール変数に反映する。

    失敗（キー無し/型変換失敗/範囲外）時は何もしない＝デフォルト維持。
    """
    if json_key not in user:
        return

    try:
        value = cast(user[json_key])
    except (TypeError, ValueError):
        return

    try:
        if not predicate(value):
            return
    except Exception:
        return

    globals()[var_name] = value

def _load_user_settings() -> None:
    """settings.json があれば読み込み、モジュール変数を上書きする。

    settings.json の例::

        {
            "hotkey_key": "ctrl",
            "hotkey_interval": 0.4,
            "model": "gpt-5",
            "window_width": 600,
            "font_size": 13
        }
    """
    if not _SETTINGS_PATH.exists():
        return

    try:
        with _SETTINGS_PATH.open(encoding="utf-8") as f:
            user = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    # 文字列系（空文字は無視）
    _set_if_valid(user, "hotkey_key", "HOTKEY_KEY", str, lambda v: bool(v.strip()))
    _set_if_valid(user, "model", "DEFAULT_MODEL", str, lambda v: bool(v.strip()))
    _set_if_valid(user, "window_title", "WINDOW_TITLE", str, lambda v: bool(v.strip()))
    _set_if_valid(user, "window_bg", "WINDOW_BG", str, lambda v: bool(v.strip()))
    _set_if_valid(user, "text_fg", "TEXT_FG", str, lambda v: bool(v.strip()))
    _set_if_valid(user, "input_bg", "INPUT_BG", str, lambda v: bool(v.strip()))
    _set_if_valid(user, "accent_color", "ACCENT_COLOR", str, lambda v: bool(v.strip()))
    _set_if_valid(user, "font_family", "FONT_FAMILY", str, lambda v: bool(v.strip()))

    # 数値系（現実的な範囲だけ許可）
    _set_if_valid(user, "hotkey_interval", "HOTKEY_INTERVAL", float, lambda v: 0.05 <= v <= 2.0)
    _set_if_valid(user, "timeout", "DEFAULT_TIMEOUT", int, lambda v: 5 <= v <= 3600)
    _set_if_valid(user, "window_width", "WINDOW_WIDTH", int, lambda v: 300 <= v <= 3840)
    _set_if_valid(user, "window_height", "WINDOW_HEIGHT", int, lambda v: 300 <= v <= 2160)
    _set_if_valid(user, "font_size", "FONT_SIZE", int, lambda v: 8 <= v <= 40)


_load_user_settings()
