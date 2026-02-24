"""Step 0: SDK Chat CLI — パス解決ユーティリティ

PyInstaller(frozen) と通常実行で、リソース/ユーザーデータの場所を共通化する。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "CopilotChat"


def resource_base_dir() -> Path:
    """同梱リソースの基点ディレクトリを返す。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).parent


def bundled_settings_path() -> Path:
    """同梱 settings.json（既定）のパス。"""
    return resource_base_dir() / "settings.json"


def user_app_dir() -> Path:
    """ユーザーデータの基点（Roaming）を返す。"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / f".{APP_NAME}"


def user_settings_path() -> Path:
    """ユーザー settings.json（上書き）のパス。"""
    return user_app_dir() / "settings.json"


def effective_settings_path() -> Path:
    """ユーザー設定を優先し、なければ同梱設定を返す。"""
    p = user_settings_path()
    if p.exists():
        return p
    return bundled_settings_path()


def bundled_icon_path() -> Path:
    """同梱トレイアイコン（任意）のパス。"""
    return resource_base_dir() / "assets" / "icon.png"
