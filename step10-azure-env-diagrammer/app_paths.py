"""Step10: パス解決ユーティリティ

- 通常実行と PyInstaller(frozen) 実行で、リソース/ユーザーデータの場所を共通化する。
- templates は「同梱(既定)」+「ユーザー上書き」を想定する。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "AzureOpsDashboard"


def resource_base_dir() -> Path:
    """同梱リソースの基点ディレクトリを返す。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).parent


def bundled_templates_dir() -> Path:
    return resource_base_dir() / "templates"


def user_app_dir() -> Path:
    """ユーザーデータの基点（Roaming）を返す。"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / f".{APP_NAME}"


def user_templates_dir() -> Path:
    return user_app_dir() / "templates"


def ensure_user_dirs() -> None:
    user_templates_dir().mkdir(parents=True, exist_ok=True)


def saved_instructions_path() -> Path:
    """保存済み指示のパス（ユーザー上書き優先）を返す。"""
    user_path = user_templates_dir() / "saved-instructions.json"
    if user_path.exists():
        return user_path
    return bundled_templates_dir() / "saved-instructions.json"


def template_search_dirs() -> list[Path]:
    """テンプレート探索ディレクトリ（ユーザー優先）を返す。"""
    return [user_templates_dir(), bundled_templates_dir()]
