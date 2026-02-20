"""Step10: パス解決ユーティリティ

- 通常実行と PyInstaller(frozen) 実行で、リソース/ユーザーデータの場所を共通化する。
- templates は「同梱(既定)」+「ユーザー上書き」を想定する。
- settings.json の読み書きを一元管理する。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


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


def settings_path() -> Path:
    """ユーザー設定ファイルのパスを返す（ユーザー領域）。"""
    return user_app_dir() / "settings.json"


def saved_instructions_path() -> Path:
    """保存済み指示のパス（ユーザー上書き優先）を返す。"""
    user_path = user_templates_dir() / "saved-instructions.json"
    if user_path.exists():
        return user_path
    return bundled_templates_dir() / "saved-instructions.json"


def template_search_dirs() -> list[Path]:
    """テンプレート探索ディレクトリ（ユーザー優先）を返す。"""
    return [user_templates_dir(), bundled_templates_dir()]


def copilot_cli_path() -> str | None:
    """Copilot SDK 同梱 CLI バイナリのパスを返す。

    PyInstaller frozen の場合:
      _MEIPASS/copilot/bin/copilot.exe  (--add-data で同梱)
    通常実行:
      site-packages/copilot/bin/copilot.exe  (SDK が自身で解決するので None)

    Returns:
        CLI バイナリのパス。通常実行時は None（SDK のデフォルトに任せる）。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None  # 通常実行 — SDK が自身で解決

    # frozen exe: _MEIPASS 配下に同梱した copilot CLI を探す
    if sys.platform == "win32":
        binary_name = "copilot.exe"
    else:
        binary_name = "copilot"

    candidate = Path(meipass) / "copilot" / "bin" / binary_name
    if candidate.exists():
        return str(candidate)

    return None


# ============================================================
# settings.json 読み書き（一元管理）
# ============================================================

def load_setting(key: str, default: str = "") -> str:
    """settings.json から値を読み込む。"""
    try:
        p = settings_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return str(data.get(key, default))
    except Exception:
        pass
    return default


def save_setting(key: str, value: str) -> None:
    """settings.json に値を書き込む（単一キー）。"""
    try:
        settings = load_all_settings()
        settings[key] = value
        save_all_settings(settings)
    except Exception:
        pass


def load_all_settings() -> dict[str, Any]:
    """settings.json を丸ごと読み込む。"""
    try:
        p = settings_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_all_settings(data: dict[str, Any]) -> None:
    """settings.json を丸ごと書き込む（一括保存）。"""
    try:
        ensure_user_dirs()
        p = settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
