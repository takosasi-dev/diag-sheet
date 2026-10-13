# 入出力の安全を受け持つ: 元ファイルの読み取り専用の読み込み、SHA-256、出力名の置き換え、
# 出力先が診断ツールのフォルダの中かの判定(FR-18)、上書きしない原子的な書き出し(FR-19)。
# 失敗したときは書きかけを消し、出力ファイルを1つも残さない。

from __future__ import annotations

import contextlib
import hashlib
import json
import ntpath
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from diagsheet.model import InputError, OutDirError, read_mapping

_BAD_NAME_CHARS = frozenset('<>:"/\\|?*')
SHEET_JSON_SUFFIX = ".sheet.json"
SHEET_MD_SUFFIX = ".sheet.md"


def read_bytes(path: Path) -> bytes:
    """読み取り専用で開いて全部読む(INV-5)。"""
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise InputError(f"ファイルを読めない: {path}({exc.strerror or exc})") from exc


def parse_json(raw: bytes, name: str) -> Any:
    """UTF-8(BOM 付きも可)の JSON を読む。壊れていれば InputError。"""
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise InputError(f"JSON として読めない: {name}({exc})") from exc


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_name(name: str) -> str:
    """ファイル名に使えない文字を _ に置き換える。末尾の空白とピリオドも置き換える。"""
    out = "".join("_" if ch in _BAD_NAME_CHARS or ord(ch) < 32 else ch for ch in name)
    stripped = out.rstrip(" .")
    out = stripped + "_" * (len(out) - len(stripped))
    return out or "_"


def sheet_stem(file_name: str) -> str:
    """シートの JSON のファイル名から、出力名の幹(.sheet.json を除いた物)を得る。"""
    if file_name.lower().endswith(SHEET_JSON_SUFFIX):
        return safe_name(file_name[: -len(SHEET_JSON_SUFFIX)])
    return safe_name(Path(file_name).stem)


def load_tool_dirs(mappings_dir: Path | None = None) -> list[str]:
    dirs = read_mapping("tool_dirs.json", mappings_dir).get("dirs")
    if not isinstance(dirs, list) or not all(isinstance(d, str) and d for d in dirs):
        raise InputError("tool_dirs.json の dirs が文字列の配列でない")
    return list(dirs)


def _lexical(path: str) -> str:
    """大文字小文字・区切り文字の向き・末尾の区切り・先頭の \\\\?\\ の違いをならす。"""
    norm = ntpath.normcase(ntpath.normpath(path))
    if norm.startswith("\\\\?\\") and not norm.startswith("\\\\?\\unc\\"):
        norm = norm[4:]
    return norm.rstrip("\\")


def _forms(path: str) -> set[str]:
    """比べるための形。文字列としての形と、実在する部分をたどった実パスの形の両方。"""
    rooted = ntpath.isabs(path) and bool(ntpath.splitdrive(path)[0])
    absolute = path if rooted else os.path.abspath(path)
    forms = {_lexical(absolute)}
    with contextlib.suppress(OSError, ValueError):
        forms.add(_lexical(os.path.realpath(absolute)))
    return forms


def ensure_outside_tool_dirs(out_dir: Path, tool_dirs: Sequence[str]) -> None:
    """出力先が診断ツールのフォルダそのものか、その中なら OutDirError(終了コード 4)。"""
    out_forms = _forms(str(out_dir))
    for tool_dir in tool_dirs:
        for base in _forms(tool_dir):
            if any(out == base or out.startswith(base + "\\") for out in out_forms):
                raise OutDirError(
                    f"出力先が診断ツールのフォルダの中にある: {out_dir}({tool_dir})。何も書かない"
                )


def write_files(out_dir: Path, files: Sequence[tuple[str, str]]) -> list[Path]:
    """files(名前, 本文)を全部書くか、1つも書かないかのどちらかにする。上書きはしない。"""
    targets = [out_dir / name for name, _ in files]
    for target in targets:
        if os.path.lexists(target):
            raise InputError(f"同じ名前のファイルがある(上書きしない): {target}")

    made_dir = False
    temps: list[Path] = []
    done: list[Path] = []
    try:
        if not out_dir.is_dir():
            out_dir.mkdir(parents=True)
            made_dir = True
        for _, text in files:
            fd, temp_name = tempfile.mkstemp(dir=out_dir, prefix=".diagsheet-", suffix=".tmp")
            temps.append(Path(temp_name))
            with open(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        for temp, target in zip(temps, targets, strict=True):
            if os.path.lexists(target):
                raise FileExistsError(f"同じ名前のファイルがある: {target}")
            os.rename(temp, target)
            done.append(target)
    except (OSError, UnicodeError) as exc:
        for leftover in (*temps, *done):
            with contextlib.suppress(OSError):
                leftover.unlink()
        if made_dir:
            with contextlib.suppress(OSError):
                out_dir.rmdir()
        raise InputError(f"書き出しに失敗した(何も残していない): {out_dir}({exc})") from exc
    return targets
