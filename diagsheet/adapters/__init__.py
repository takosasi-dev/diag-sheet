# アダプタが共通に使う部品: 判定の対応表(verdict_map.json)と「測らない物」の表
# (not_measured.json)の読み込み、元 JSON の形を確かめる小さな関数。
# 判定は対応表から引くだけ。表に無い値は ShapeError(終了コード 2)にして、判定なしへ逃がさない。

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypeGuard

from diagsheet.model import JUDGED_VERDICTS, InputError, Scalar, ShapeError, read_mapping

_MATCHES = ("exact", "first_char")
_ENTRY_KEYS = frozenset({"field", "match", "raw", "label", "verdict"})


@dataclass(frozen=True)
class _Entry:
    field: str
    match: str
    raw: str | bool | int | float
    label: str | None
    verdict: str

    def hits(self, value: object) -> bool:
        if self.match == "first_char":
            return isinstance(value, str) and value[:1] == self.raw
        return type(value) is type(self.raw) and value == self.raw


class VerdictMap:
    """1つのツールの対応表。field は元 JSON の鍵の道筋、raw は元の値。"""

    def __init__(self, entries: Iterable[_Entry]) -> None:
        self._entries = tuple(entries)

    def has_field(self, field: str) -> bool:
        return any(entry.field == field for entry in self._entries)

    def lookup(self, field: str, value: Scalar) -> tuple[str, str]:
        """(ツールの表示語, 共通の判定) を返す。表に無ければ ShapeError。"""
        for entry in self._entries:
            if entry.field == field and entry.hits(value):
                label = entry.label if entry.label is not None else str(value)
                return label, entry.verdict
        raise ShapeError(f"対応表(verdict_map.json)に無い判定の値: {field} = {value!r}")


def load_verdict_map(tool: str, mappings_dir: Path | None = None) -> VerdictMap:
    tools = read_mapping("verdict_map.json", mappings_dir).get("tools")
    rows = tools.get(tool, []) if isinstance(tools, dict) else None
    if not isinstance(rows, list):
        raise InputError("verdict_map.json の tools の形が違う")
    entries: list[_Entry] = []
    for row in rows:
        ok = (
            isinstance(row, dict)
            and set(row) == _ENTRY_KEYS
            and isinstance(row["field"], str)
            and row["match"] in _MATCHES
            and isinstance(row["raw"], str | bool | int | float)
            and (row["label"] is None or isinstance(row["label"], str))
            and row["verdict"] in JUDGED_VERDICTS
        )
        if not ok:
            raise InputError(f"verdict_map.json の {tool} の行の形が違う: {row!r}")
        entries.append(_Entry(row["field"], row["match"], row["raw"], row["label"], row["verdict"]))
    return VerdictMap(entries)


def load_not_measured(tool: str, mappings_dir: Path | None = None) -> list[tuple[str, str]]:
    """ツールが「測らない」と書いている物のうち、未チェックとして出す物の (項目名, 理由)。"""
    rows = read_mapping("not_measured.json", mappings_dir).get(tool, [])
    if not isinstance(rows, list):
        raise InputError("not_measured.json の形が違う")
    out: list[tuple[str, str]] = []
    for row in rows:
        name = row.get("name") if isinstance(row, dict) else None
        reason = row.get("reason") if isinstance(row, dict) else None
        if not (isinstance(name, str) and name and isinstance(reason, str) and reason):
            raise InputError(f"not_measured.json の {tool} の行の形が違う: {row!r}")
        out.append((name, reason))
    return out


def as_object(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ShapeError(f"知らない形: {where} がオブジェクトでない")
    return value


def as_list(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ShapeError(f"知らない形: {where} が配列でない")
    return value


def as_text(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise ShapeError(f"知らない形: {where} が文字列でない")
    return value


def as_timestamp(value: object, where: str) -> str:
    text = as_text(value, where)
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise ShapeError(f"知らない形: {where} が ISO 8601 の日時でない") from exc
    return text


def is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def non_finite_word(value: object) -> str | None:
    """NaN・Infinity ならその呼び名を返す。ふつうの値なら None。"""
    if not isinstance(value, float) or math.isfinite(value):
        return None
    if math.isnan(value):
        return "NaN"
    return "Infinity" if value > 0 else "-Infinity"


def require_keys(obj: dict[str, Any], required: Iterable[str], where: str) -> None:
    missing = [key for key in required if key not in obj]
    if missing:
        raise ShapeError(f"知らない形: {where} に鍵 {'・'.join(missing)} が無い")


def reject_unknown_keys(obj: dict[str, Any], known: Iterable[str], where: str) -> None:
    known_set = set(known)
    unknown = [key for key in obj if key not in known_set]
    if unknown:
        raise ShapeError(f"知らない形: {where} に知らない鍵 {'・'.join(unknown)} がある")


def reject_duplicate_ids(ids: Iterable[str]) -> None:
    seen: set[str] = set()
    for item_id in ids:
        if item_id in seen:
            raise ShapeError(f"知らない形: 項目の id が重なる({item_id})")
        seen.add(item_id)
