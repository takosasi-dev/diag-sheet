# README に載せる画面の画像を作る(開発用。Pillow が要る)。合成データだけを表示して保存する。
# 窓のハンドルを指定して撮るので、ほかの窓は写らない。画面に出すパスは作り物(D:\demo)。
# 使い方: python tools/make_screenshots.py [保存先のフォルダ]

from __future__ import annotations

import copy
import ctypes
import json
import sys
import time
import tkinter as tk
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageGrab  # noqa: E402

from diagsheet import gui  # noqa: E402
from diagsheet.check import check_sheet  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
DEFAULT_OUT = ROOT / "docs" / "images"
DEMO_BROKEN_SHEET = "D:\\demo\\out\\broken.sheet.json"
SETTLE_S = 0.4


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _settle(root: tk.Tk) -> None:
    """描画が終わるのを待つ。"""
    for _ in range(3):
        root.update_idletasks()
        root.update()
        time.sleep(SETTLE_S / 3)
    root.update()


def _grab(root: tk.Tk) -> Image.Image:
    """窓のハンドルで撮る。使えない Pillow では、窓を最前面にして窓の範囲だけを撮る。"""
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    try:
        return ImageGrab.grab(window=hwnd)
    except (TypeError, OSError):
        root.attributes("-topmost", True)
        _settle(root)
        left, top = root.winfo_rootx(), root.winfo_rooty()
        box = (left, top, left + root.winfo_width(), top + root.winfo_height())
        return ImageGrab.grab(bbox=box)


def _save(root: tk.Tk, path: Path) -> None:
    _settle(root)
    image = _grab(root).convert("RGB")
    image.save(path, format="PNG", optimize=True)
    print(f"{path.name}: {image.width}x{image.height} {path.stat().st_size} バイト")


def _broken_sheet() -> dict[str, Any]:
    """検査に通らない合成シート。値が無いはずの項目に値を入れ、件数をずらす。"""
    sheet: dict[str, Any] = copy.deepcopy(_read(FIXTURES / "sheets" / "all_states.sheet.json"))
    failed = next(item for item in sheet["items"] if item["status"] == "failed")
    failed["value"] = 0
    failed["reason"] = None
    sheet["counts"]["ok"] += 1
    return sheet


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)

    def no_alert(_title: str, _message: str) -> None:
        return None

    gui.enable_dpi_awareness()
    root = tk.Tk()
    app = gui.App(root, alert=no_alert, opener=lambda _path: None)

    # 1枚目: PC 遅延診断の合成の結果を変換したところ。1行選んで詳細を出す。
    app.show_demo("stutter", _read(FIXTURES / "stutter" / "basic.json"))
    app.select_row(0)
    _save(root, out_dir / "gui-main.png")

    # 2枚目: 回線診断の合成の結果(測れなかった項目が多い回)。
    app.show_demo("netdiag", _read(FIXTURES / "netdiag" / "partial.json"))
    app.select_row(0)
    _save(root, out_dir / "gui-netdiag.png")

    # 3枚目: 形の違反があるシートを検査したところ。表示中のシートは無い(件数は「—」)。
    app.clear_sheet()
    app.sheet_var.set(DEMO_BROKEN_SHEET)
    app.show_violations(DEMO_BROKEN_SHEET, check_sheet(_broken_sheet()))
    _save(root, out_dir / "gui-check.png")

    root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
