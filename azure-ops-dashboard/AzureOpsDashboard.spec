# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path


def _find_copilot_bin_dir() -> Path | None:
    # Locate `copilot/bin` under the current Python environment.
    # This avoids hard-coding machine-specific absolute paths in the tracked spec.
    venv_root = Path(sys.executable).resolve().parents[1]
    candidates = [
        venv_root / "Lib" / "site-packages" / "copilot" / "bin",  # Windows venv
        venv_root / "lib" / "python" / "site-packages" / "copilot" / "bin",  # POSIX fallback
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    return None


project_root = Path(__file__).resolve().parent
src_root = project_root / "src"
templates_dir = src_root / "azure_ops_dashboard" / "templates"

datas = [(str(templates_dir), "templates")]
copilot_bin_dir = _find_copilot_bin_dir()
if copilot_bin_dir is not None:
    # NOTE: use a non-conflicting top-level name inside the exe bundle.
    datas.append((str(copilot_bin_dir), "copilot_cli\\bin"))


a = Analysis(
    [str(project_root / "src" / "app.py")],
    pathex=[str(project_root), str(src_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AzureOpsDashboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AzureOpsDashboard",
)
