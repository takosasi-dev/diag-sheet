# 同梱データ(mappings/)の場所と、書き込み先の基準になるフォルダを決める。
# ソースから動かすときと PyInstaller の exe のときで場所が変わるので、ここ1か所で吸収する。
# exe のときも書き込み先は exe の隣にし、展開先の一時フォルダ(sys._MEIPASS)には書かない。

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_NAME = "diagsheet"


def _unpack_dir() -> Path | None:
    """exe として動いているときの展開先。ソースから動かしているときは None。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and isinstance(meipass, str) and meipass:
        return Path(meipass)
    return None


def is_frozen() -> bool:
    return _unpack_dir() is not None


def resource_path(*parts: str) -> Path:
    """同梱データのパス。読むだけに使う。exe では展開先の diagsheet フォルダの下を指す。"""
    unpacked = _unpack_dir()
    base = Path(__file__).resolve().parent if unpacked is None else unpacked / PACKAGE_NAME
    return base.joinpath(*parts)


def app_dir() -> Path:
    """書き込み先の基準。exe なら exe のあるフォルダ、ソースからならパッケージの1つ上。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
