# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


def _resolve_copilot_bin_dir(project_dir: Path) -> Path | None:
    # Prefer a local venv (public repo layout), then fallback to monorepo layout.
    candidates = [
        project_dir / ".venv" / "Lib" / "site-packages" / "copilot" / "bin",
        project_dir / ".." / ".venv" / "Lib" / "site-packages" / "copilot" / "bin",
    ]
    for path in candidates:
        resolved = path.resolve()
        if resolved.exists():
            return resolved
    return None


_project_dir = Path(__file__).resolve().parent

_datas = [(str((_project_dir / "templates").resolve()), "templates")]

_copilot_bin = _resolve_copilot_bin_dir(_project_dir)
if _copilot_bin:
    # NOTE: avoid top-level "copilot/" to prevent Python import collisions.
    _datas.append((str(_copilot_bin), "copilot_cli\\bin"))


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=_datas,
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
    name='AzureOpsDashboard',
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
    name='AzureOpsDashboard',
)
