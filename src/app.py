"""Entry point shim under /src to satisfy challenge repo structure requirements.

Run from the repository root:
  python src/app.py

This keeps the existing flat layout intact (main.py at repo root) while ensuring
there is working code under /src.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_repo_root_on_sys_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


def main() -> None:
    _ensure_repo_root_on_sys_path()

    from main import main as root_main

    root_main()


if __name__ == "__main__":
    main()
