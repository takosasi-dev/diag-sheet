# DiagSheet.exe を作る(開発用。PyInstaller が要る)。1ファイル・コンソール無しで dist/ に出す。
# 対応表(diagsheet/mappings/*.json)を同梱する。作業ファイルと .spec は build/ の下に置く。
# 使い方: python tools/build_exe.py

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "DiagSheet"
ENTRY = ROOT / "tools" / "exe_entry.py"
MAPPINGS = ROOT / "diagsheet" / "mappings"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"


def command() -> list[str]:
    """PyInstaller の引数。パスは全部絶対パスにする(.spec を build/ に置くので相対だとずれる)。"""
    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        NAME,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
        "--paths",
        str(ROOT),
        "--add-data",
        f"{MAPPINGS}{os.pathsep}diagsheet/mappings",
        str(ENTRY),
    ]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")
    done = subprocess.run(command(), cwd=ROOT, check=False)
    exe = DIST_DIR / f"{NAME}.exe"
    if done.returncode != 0 or not exe.is_file():
        code = done.returncode or 1
        print(f"build_exe: 作れなかった(PyInstaller の終了コード {code})", file=sys.stderr)
        return code
    print(f"build_exe: {exe}({exe.stat().st_size} バイト)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
