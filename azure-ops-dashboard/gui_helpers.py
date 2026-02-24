"""GUI ヘルパー — 定数・ユーティリティ関数

main.py から分離したモジュールレベルの共通定数とファイル操作。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast


# ============================================================
# GUI 定数
# ============================================================

WINDOW_TITLE = "Azure Ops Dashboard"
WINDOW_WIDTH = 720
WINDOW_HEIGHT = 640
WINDOW_BG = "#1e1e1e"
PANEL_BG = "#252526"
TEXT_FG = "#d4d4d4"
MUTED_FG = "#808080"
INPUT_BG = "#2d2d2d"
ACCENT_COLOR = "#0078d4"
SUCCESS_COLOR = "#4ec9b0"
WARNING_COLOR = "#dcdcaa"
ERROR_COLOR = "#f44747"
BUTTON_BG = "#3C3C3C"
BUTTON_FG = "white"
FONT_FAMILY = "Consolas" if sys.platform == "win32" else "Menlo" if sys.platform == "darwin" else "Monospace"
FONT_SIZE = 11


# ============================================================
# ファイル操作
# ============================================================


def write_text(path: Path, content: str) -> None:
    """テキストファイルを書き出す（ディレクトリ自動作成）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    """JSON ファイルを書き出す（ディレクトリ自動作成）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def open_native(path: str | Path) -> None:
    """OS ごとの既定アプリでファイル/フォルダを開く。"""
    p = str(path)
    if sys.platform == "win32":
        os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


# ============================================================
# Draw.io / VS Code パス検出
# ============================================================


def detect_drawio_path() -> str | None:
    """Draw.io デスクトップアプリのパスを探す。"""
    for name in ("draw.io", "drawio"):
        p = shutil.which(name)
        if p:
            return p

    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "draw.io" / "draw.io.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "draw.io" / "draw.io.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "draw.io" / "draw.io.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            Path("/Applications/draw.io.app/Contents/MacOS/draw.io"),
            Path.home() / "Applications" / "draw.io.app" / "Contents" / "MacOS" / "draw.io",
        ]
    else:
        candidates = [
            Path("/snap/drawio/current/opt/draw.io/drawio"),
            Path("/opt/draw.io/drawio"),
        ]

    for c in candidates:
        if c.exists():
            return str(c)
    return None


def detect_vscode_path() -> str | None:
    """VS Code のパスを探す。"""
    for name in ("code", "code-insiders", "code.cmd"):
        p = shutil.which(name)
        if p:
            return p

    # Windows: PATH に無い場合が多いので、代表的なインストール先も見る
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code Insiders" / "Code - Insiders.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft VS Code" / "Code.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft VS Code" / "Code.exe",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
    return None


# ---------- パス検出キャッシュ ----------
_CACHE_UNSET = object()
_drawio_path_cache: str | None | object = _CACHE_UNSET
_vscode_path_cache: str | None | object = _CACHE_UNSET


def cached_drawio_path() -> str | None:
    """detect_drawio_path() の結果をキャッシュして返す。"""
    global _drawio_path_cache
    if _drawio_path_cache is _CACHE_UNSET:
        _drawio_path_cache = detect_drawio_path()
    return cast(str | None, _drawio_path_cache)


def cached_vscode_path() -> str | None:
    """detect_vscode_path() の結果をキャッシュして返す。"""
    global _vscode_path_cache
    if _vscode_path_cache is _CACHE_UNSET:
        _vscode_path_cache = detect_vscode_path()
    return cast(str | None, _vscode_path_cache)


# Windows でサブプロセスのコンソール窓を非表示にするヘルパー
def _subprocess_no_window() -> dict:
    """Windows 環境で CMD 窓を出さない subprocess 用 kwargs を返す。"""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def export_drawio_svg(drawio_path: Path, drawio_exe: str | None = None) -> Path | None:
    """Draw.io CLI で .drawio → .drawio.svg に変換する。

    NOTE:
      生成された SVG を draw.io で再編集できるよう、ダイアグラムを埋め込む。
    """
    exe = drawio_exe or cached_drawio_path()
    if not exe:
        return None
    svg_path = drawio_path.with_suffix(".drawio.svg")
    try:
        result = subprocess.run(
            [exe, "--export", "--format", "svg", "--embed-diagram",
             "--output", str(svg_path), str(drawio_path)],
            capture_output=True, text=True, timeout=60,
            **_subprocess_no_window(),
        )
        if result.returncode == 0 and svg_path.exists():
            return svg_path
    except Exception:
        pass
    return None
