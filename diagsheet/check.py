# シートの JSON が §9.2 の規則に合っているかを調べ、違反を1行ずつの文字列で返す。
# 値の中身は評価しない(判定をしない)。形・組み合わせ・件数の整合だけを見る。
# 形の版が 1 でなければ、ほかの規則は見ずにその1行だけを返す。

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from diagsheet.model import (
    CATEGORY_ORDER,
    CONFIDENCE_WORDS,
    JUDGED_VERDICTS,
    SHAPE_VERSION,
    STATUSES,
    TOOLS,
    VERDICTS,
    VERSION_SOURCES,
    count_items,
)

TOP_KEYS = (
    "diagsheet",
    "tool",
    "tool_version",
    "tool_version_from",
    "adapter_version",
    "created_at",
    "source",
    "run",
    "overall",
    "counts",
    "items",
)
SOURCE_KEYS = ("file", "sha256", "shape")
RUN_KEYS = ("label", "measured_at", "subject", "conditions")
OVERALL_REQUIRED = ("value", "score", "used", "total", "excluded")
OVERALL_OPTIONAL = ("note",)
ITEM_KEYS = (
    "id",
    "name",
    "unit",
    "status",
    "value",
    "confidence",
    "verdict",
    "verdict_raw",
    "verdict_label",
    "reason",
    "evidence",
    "note",
    "action",
    "from",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _non_finite(value: object, where: str) -> Iterable[str]:
    """NaN・Infinity をシートのどこにあっても違反にする。"""
    if isinstance(value, float) and not math.isfinite(value):
        yield f"{where}: 数でない値(NaN・Infinity)がある"
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _non_finite(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _non_finite(child, f"{where}[{index}]")


def _keys(
    obj: dict[str, Any], required: Iterable[str], where: str, optional: Iterable[str] = ()
) -> list[str]:
    required = tuple(required)
    allowed = {*required, *optional}
    out = [f"{where}: 鍵 {key} が無い" for key in required if key not in obj]
    out += [f"{where}: 未知の鍵 {key} がある" for key in obj if key not in allowed]
    return out


def _check_header(sheet: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if "tool" in sheet and sheet["tool"] not in TOOLS:
        out.append(f"tool が {sheet['tool']!r}。{' / '.join(TOOLS)} のどれかにする")
    version_from = sheet.get("tool_version_from")
    version = sheet.get("tool_version")
    if "tool_version_from" in sheet and version_from not in VERSION_SOURCES:
        choices = " / ".join(VERSION_SOURCES)
        out.append(f"tool_version_from が {version_from!r}。{choices} のどれかにする")
    elif version_from == "不明" and version is not None:
        out.append("tool_version_from が 不明 なのに tool_version が null でない")
    elif version_from in ("元ファイル", "指定") and not _is_text(version):
        out.append(f"tool_version_from が {version_from} なのに tool_version が空")
    if "adapter_version" in sheet and not _is_text(sheet["adapter_version"]):
        out.append("adapter_version が空でない文字列でない")
    if "created_at" in sheet:
        created = sheet["created_at"]
        try:
            if not isinstance(created, str):
                raise ValueError
            datetime.fromisoformat(created)
        except ValueError:
            out.append("created_at が ISO 8601 の日時でない")
    return out


def _check_source(source: object) -> list[str]:
    if not isinstance(source, dict):
        return ["source がオブジェクトでない"]
    out = _keys(source, SOURCE_KEYS, "source")
    for key in ("file", "shape"):
        if key in source and not _is_text(source[key]):
            out.append(f"source.{key} が空でない文字列でない")
    sha = source.get("sha256")
    if "sha256" in source and not (isinstance(sha, str) and _SHA256.fullmatch(sha)):
        out.append("source.sha256 が小文字16進64桁でない")
    return out


def _check_run(run: object) -> list[str]:
    if not isinstance(run, dict):
        return ["run がオブジェクトでない"]
    out = _keys(run, RUN_KEYS, "run")
    if "label" in run and not isinstance(run["label"], str):
        out.append("run.label が文字列でない")
    for key in ("measured_at", "subject"):
        if key in run and not _is_text(run[key]):
            out.append(f"run.{key} が空でない文字列でない")
    conditions = run.get("conditions")
    if "conditions" in run:
        if not isinstance(conditions, dict):
            out.append("run.conditions がオブジェクトでない")
        else:
            out += [
                f"run.conditions.{key} が数・文字列・真偽・null のどれでもない"
                for key, value in conditions.items()
                if not _is_scalar(value)
            ]
    return out


def _check_overall(overall: object) -> list[str]:
    if overall is None:
        return []
    if not isinstance(overall, dict):
        return ["overall が null でもオブジェクトでもない"]
    out = _keys(overall, OVERALL_REQUIRED, "overall", OVERALL_OPTIONAL)
    if "value" in overall and not _is_text(overall["value"]):
        out.append("overall.value が空でない文字列でない")
    score = overall.get("score")
    if score is not None and not _is_number(score):
        out.append("overall.score が数でも null でもない")
    for key in ("used", "total"):
        if key in overall and not _is_int(overall[key]):
            out.append(f"overall.{key} が整数でない")
    excluded = overall.get("excluded")
    if "excluded" in overall and not (
        isinstance(excluded, list) and all(_is_text(name) for name in excluded)
    ):
        out.append("overall.excluded が文字列の配列でない")
    note = overall.get("note")
    if note is not None and not isinstance(note, str):
        out.append("overall.note が文字列でも null でもない")
    return out


def _check_item(item: object, where: str) -> list[str]:
    if not isinstance(item, dict):
        return [f"{where}: オブジェクトでない"]
    out = _keys(item, ITEM_KEYS, where)
    for key in ("id", "name", "from"):
        if key in item and not _is_text(item[key]):
            out.append(f"{where}: {key} が空でない文字列でない")
    for key in ("unit", "evidence", "note", "action", "verdict_label", "reason"):
        if item.get(key) is not None and not isinstance(item[key], str):
            out.append(f"{where}: {key} が文字列でも null でもない")
    for key in ("value", "verdict_raw"):
        if not _is_scalar(item.get(key)):
            out.append(f"{where}: {key} が数・文字列・真偽・null のどれでもない")

    status = item.get("status")
    verdict = item.get("verdict")
    if status not in STATUSES:
        out.append(f"{where}: status が {status!r}。{' / '.join(STATUSES)} のどれかにする")
        return out

    if status == "measured":
        if item.get("value") is None and not _is_text(item.get("evidence")):
            out.append(f"{where}: status が measured なのに value も evidence も無い")
        confidence = item.get("confidence")
        if confidence not in CONFIDENCE_WORDS:
            choices = " / ".join(CONFIDENCE_WORDS)
            out.append(f"{where}: confidence が {confidence!r}。{choices} のどれかにする")
        if verdict not in VERDICTS:
            out.append(f"{where}: verdict が {verdict!r}。{' / '.join(VERDICTS)} のどれかにする")
        if item.get("reason") is not None:
            out.append(f"{where}: status が measured なのに reason が null でない")
    else:
        for key in ("value", "confidence", "verdict"):
            if item.get(key) is not None:
                out.append(f"{where}: status が {status} なのに {key} が null でない")
        if not _is_text(item.get("reason")):
            out.append(f"{where}: status が {status} なのに reason が空")

    if verdict in JUDGED_VERDICTS:
        if item.get("verdict_raw") is None or not _is_text(item.get("verdict_label")):
            out.append(f"{where}: verdict が {verdict} なのに verdict_raw か verdict_label が無い")
    elif item.get("verdict_raw") is not None or item.get("verdict_label") is not None:
        out.append(f"{where}: 判定が無いのに verdict_raw か verdict_label が null でない")
    return out


def _check_counts(counts: object, items: list[Any]) -> list[str]:
    if not isinstance(counts, dict):
        return ["counts がオブジェクトでない"]
    out = _keys(counts, CATEGORY_ORDER, "counts")
    if out:
        return out
    if not all(_is_int(counts[key]) for key in CATEGORY_ORDER):
        return ["counts に整数でない値がある"]
    actual = count_items(item for item in items if isinstance(item, dict))
    for key in CATEGORY_ORDER:
        if counts[key] != actual[key]:
            out.append(f"counts.{key} が {counts[key]}。items から数えると {actual[key]}")
    total = sum(counts[key] for key in CATEGORY_ORDER)
    if total != len(items):
        out.append(f"counts の和が {total}。items の数は {len(items)}")
    return out


def check_sheet(sheet: object) -> list[str]:
    """違反の一覧を返す。空なら違反なし。"""
    if not isinstance(sheet, dict):
        return ["シートが JSON のオブジェクトでない"]
    version = sheet.get("diagsheet")
    if not _is_int(version) or version != SHAPE_VERSION:
        return [f"diagsheet(形の版)が {version!r}。この版が読めるのは {SHAPE_VERSION} だけ"]

    out = _keys(sheet, TOP_KEYS, "シート")
    out += list(_non_finite(sheet, "シート"))
    out += _check_header(sheet)
    if "source" in sheet:
        out += _check_source(sheet["source"])
    if "run" in sheet:
        out += _check_run(sheet["run"])
    if "overall" in sheet:
        out += _check_overall(sheet["overall"])

    items = sheet.get("items")
    if not isinstance(items, list):
        if "items" in sheet:
            out.append("items が配列でない")
        return out
    seen: set[str] = set()
    for index, item in enumerate(items):
        item_id = item.get("id") if isinstance(item, dict) else None
        where = f"items[{index}]({item_id})" if isinstance(item_id, str) else f"items[{index}]"
        out += _check_item(item, where)
        if isinstance(item_id, str):
            if item_id in seen:
                out.append(f"{where}: id が重複している")
            seen.add(item_id)
    if "counts" in sheet:
        out += _check_counts(sheet["counts"], items)
    return out
