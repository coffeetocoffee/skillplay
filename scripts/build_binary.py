"""Build a single-binary distribution for skillplay (P10).

Evaluates PyInstaller (preferred for a Python TUI) and falls back to `shiv`
(a zipapp) if PyInstaller isn't installed. Both keep the offline, dependency-free
spirit: the result is one file you can drop on a machine with no Python.

Usage:
    python scripts/build_binary.py            # PyInstaller if available, else shiv
    python scripts/build_binary.py --method pyinstaller
    python scripts/build_binary.py --method shiv

Requires one of: `pip install pyinstaller` or `pip install shiv`.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"


def _pyinstaller() -> int:
    if shutil.which("pyinstaller") is None:
        print("PyInstaller not found. Install with: pip install pyinstaller")
        return 1
    DIST.mkdir(parents=True, exist_ok=True)
    cmd = [
        "pyinstaller",
        "--onefile",
        "--name",
        "skillplay",
        "--paths",
        str(REPO),
        str(REPO / "skillplay" / "__main__.py"),
    ]
    return subprocess.call(cmd)


def _shiv() -> int:
    if shutil.which("shiv") is None:
        print("shiv not found. Install with: pip install shiv")
        return 1
    DIST.mkdir(parents=True, exist_ok=True)
    out = DIST / "skillplay.pyz"
    cmd = [
        "shiv",
        "--entry-point",
        "skillplay.__main__:main",
        "-o",
        str(out),
        str(REPO),
    ]
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build a single-binary skillplay.")
    p.add_argument("--method", choices=["pyinstaller", "shiv"], default=None)
    args = p.parse_args(argv)
    method = args.method or ("pyinstaller" if shutil.which("pyinstaller") else "shiv")
    print(f"Building with {method} ...")
    rc = _pyinstaller() if method == "pyinstaller" else _shiv()
    if rc == 0:
        print(f"Build succeeded -> {DIST}")
    else:
        print("Build failed.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
