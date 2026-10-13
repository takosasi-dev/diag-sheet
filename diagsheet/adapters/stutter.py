# PC 遅延診断(pc-stutter-diagnosis v1.0.0)の結果 JSON をシートに写す(§9.5)。形の名前は stutter-1。
# 所見の判定は severity を対応表で写すだけ。数値を比べる処理は持たない。元のコードは import しない。
# samples・events と、snapshot のプロセス名・ドライバ名・ディスク名は写さない。

from __future__ import annotations

from pathlib import Path
from typing import Any

from diagsheet.adapters import (
    VerdictMap,
    as_list,
    as_object,
    as_text,
    as_timestamp,
    is_number,
    load_not_measured,
    load_verdict_map,
    non_finite_word,
    reject_duplicate_ids,
    reject_unknown_keys,
    require_keys,
)
from diagsheet.model import Item, Run, Scalar, ShapeError, Sheet, Source

TOOL = "stutter"
SHAPE = "stutter-1"
ADAPTER_VERSION = "0.1.0"
SUBJECT = "PC"

_TOP_REQUIRED = (
    "label",
    "timestamp",
    "duration_s",
    "interval_s",
    "snapshot",
    "stats",
    "findings",
    "event_rate_per_min",
)
_TOP_KNOWN = (*_TOP_REQUIRED, "samples", "events")
_FINDING_KEYS = ("severity", "title", "evidence", "meaning", "action")
_SMART_KEYS = ("rows", "available", "reason")
# SMART の行から写す欄: (元の鍵, 単位, 項目名に付ける語)。語は元ツールのレポートの語。
_SMART_FIELDS = (
    ("Wear", "%", "消耗"),
    ("Temperature", "℃", "温度"),
    ("PowerOnHours", "時間", "通電"),
)

REASON_SMART = "SMART を取得できなかった"
REASON_SMART_NULL = "SMART の行はあるが値が無い"
REASON_NO_SAMPLE = "サンプルが1件も取れなかった"
NOT_MEASURED_ORIGIN = "README「測れないもの」"


def _not_a_number(value: object) -> str:
    return f"値が数でない({non_finite_word(value)})"


def _finding_items(findings: list[Any], vmap: VerdictMap) -> list[Item]:
    items: list[Item] = []
    for index, raw in enumerate(findings):
        where = f"findings[{index}]"
        finding = as_object(raw, where)
        require_keys(finding, _FINDING_KEYS, where)
        reject_unknown_keys(finding, _FINDING_KEYS, where)
        severity = as_text(finding["severity"], f"{where}.severity")
        label, verdict = vmap.lookup("severity", severity)
        title = as_text(finding["title"], f"{where}.title")
        evidence = as_text(finding["evidence"], f"{where}.evidence")
        if not title or not evidence:
            raise ShapeError(f"知らない形: {where} の title か evidence が空")
        items.append(
            Item(
                id=f"stutter.finding.{index}",
                name=title,
                status="measured",
                confidence="measured",
                verdict=verdict,
                verdict_raw=severity,
                verdict_label=label,
                evidence=evidence,
                note=as_text(finding["meaning"], f"{where}.meaning") or None,
                action=as_text(finding["action"], f"{where}.action") or None,
                origin=where,
            )
        )
    return items


def _smart_row_items(row: dict[str, Any], where: str) -> list[Item]:
    device = row["DeviceId"]
    if isinstance(device, bool) or not isinstance(device, str | int) or device == "":
        raise ShapeError(f"知らない形: {where}.DeviceId が文字列でも整数でもない")
    items: list[Item] = []
    for key, unit, word in _SMART_FIELDS:
        value = row[key]
        common: dict[str, Any] = {
            "id": f"stutter.smart.{device}.{key}",
            "name": f"SMART ディスク{device} {word}",
            "unit": unit,
            "origin": f"{where}.{key}",
        }
        if value is None:
            items.append(Item(status="failed", reason=REASON_SMART_NULL, **common))
        elif not is_number(value):
            raise ShapeError(f"知らない形: {where}.{key} が数でも null でもない")
        elif non_finite_word(value) is not None:
            items.append(Item(status="failed", reason=_not_a_number(value), **common))
        else:
            common.update(value=value, confidence="measured", verdict="none")
            items.append(Item(status="measured", **common))
    return items


def _smart_items(snapshot: dict[str, Any]) -> list[Item]:
    require_keys(snapshot, ("smart",), "snapshot")
    smart = as_object(snapshot["smart"], "snapshot.smart")
    require_keys(smart, _SMART_KEYS, "snapshot.smart")
    reject_unknown_keys(smart, _SMART_KEYS, "snapshot.smart")
    available = smart["available"]
    if not isinstance(available, bool):
        raise ShapeError("知らない形: snapshot.smart.available が真偽でない")
    if not available:
        reason = smart["reason"]
        if reason is not None and not isinstance(reason, str):
            raise ShapeError("知らない形: snapshot.smart.reason が文字列でも null でもない")
        return [
            Item(
                id="stutter.smart",
                name="SMART(消耗度)",
                status="failed",
                reason=reason or REASON_SMART,
                origin="snapshot.smart",
            )
        ]
    rows = as_list(smart["rows"], "snapshot.smart.rows")
    if not rows:
        raise ShapeError("知らない形: snapshot.smart.available が true なのに rows が空")
    items: list[Item] = []
    for index, raw in enumerate(rows):
        where = f"snapshot.smart.rows[{index}]"
        row = as_object(raw, where)
        require_keys(row, ("DeviceId", *(key for key, _, _ in _SMART_FIELDS)), where)
        items += _smart_row_items(row, where)
    return items


def _counter_items(snapshot: dict[str, Any]) -> list[Item]:
    if "unavailable_counters" not in snapshot:
        return []
    counters = as_object(snapshot["unavailable_counters"], "snapshot.unavailable_counters")
    items: list[Item] = []
    for name, code in counters.items():
        where = f"snapshot.unavailable_counters.{name}"
        if not as_text(code, where):
            raise ShapeError(f"知らない形: {where} が空")
        items.append(
            Item(
                id=f"stutter.counter.{name}",
                name=f"PDH カウンタ {name}",
                status="failed",
                reason=f"PDH カウンタを開けなかった({code})",
                origin=where,
            )
        )
    return items


def _stats_items(stats: dict[str, Any]) -> list[Item]:
    items: list[Item] = []
    for key, value in stats.items():
        if value is None:
            items.append(
                Item(
                    id=f"stutter.stats.{key}",
                    name=f"統計 {key}",
                    status="failed",
                    reason=REASON_NO_SAMPLE,
                    origin=f"stats.{key}",
                )
            )
        elif not isinstance(value, dict):
            raise ShapeError(f"知らない形: stats.{key} がオブジェクトでも null でもない")
    return items


def _event_rate_item(value: object) -> Item:
    common: dict[str, Any] = {
        "id": "stutter.event_rate_per_min",
        "name": "イベント頻度",
        "unit": "件/分",
        "origin": "event_rate_per_min",
    }
    if not is_number(value):
        raise ShapeError("知らない形: event_rate_per_min が数でない")
    if non_finite_word(value) is not None:
        return Item(status="failed", reason=_not_a_number(value), **common)
    return Item(status="measured", value=value, confidence="measured", verdict="none", **common)


def _conditions(top: dict[str, Any]) -> dict[str, Scalar]:
    conditions: dict[str, Scalar] = {}
    for key in ("duration_s", "interval_s"):
        value = top[key]
        if not is_number(value) or non_finite_word(value) is not None:
            raise ShapeError(f"知らない形: {key} が数でない")
        conditions[key] = value
    return conditions


def convert(
    source: object,
    *,
    source_file: str,
    source_sha256: str,
    tool_version: str | None,
    created_at: str,
    mappings_dir: Path | None = None,
) -> Sheet:
    """元 JSON(読み込み済みの値)をシートにする。知らない形なら ShapeError。"""
    top = as_object(source, "最上位")
    require_keys(top, _TOP_REQUIRED, "最上位")
    reject_unknown_keys(top, _TOP_KNOWN, "最上位")
    label = as_text(top["label"], "label")
    timestamp = as_timestamp(top["timestamp"], "timestamp")
    snapshot = as_object(top["snapshot"], "snapshot")
    stats = as_object(top["stats"], "stats")
    findings = as_list(top["findings"], "findings")
    if "disk_read_s" in stats:
        raise ShapeError(
            "知らない形: stats に disk_read_s がある(ドライブ別対応前の旧形式)。"
            "旧形式の実物が無いので変換しない"
        )

    items = [
        *_finding_items(findings, load_verdict_map(TOOL, mappings_dir)),
        *_smart_items(snapshot),
        *_counter_items(snapshot),
        *_stats_items(stats),
        _event_rate_item(top["event_rate_per_min"]),
    ]
    for index, (name, reason) in enumerate(load_not_measured(TOOL, mappings_dir)):
        items.append(
            Item(
                id=f"stutter.not_measured.{index}",
                name=name,
                status="unchecked",
                reason=reason,
                origin=NOT_MEASURED_ORIGIN,
            )
        )
    reject_duplicate_ids(item.id for item in items)
    return Sheet(
        tool=TOOL,
        tool_version=tool_version,
        adapter_version=ADAPTER_VERSION,
        created_at=created_at,
        source=Source(file=source_file, sha256=source_sha256, shape=SHAPE),
        run=Run(
            label=label, measured_at=timestamp, subject=SUBJECT, conditions=_conditions(top)
        ),
        items=items,
    )


def synthetic_source() -> dict[str, Any]:
    """--selftest 用の合成の元 JSON。値はすべて作り物で、実測ではない。"""
    stat = {"n": 8, "p50": 1.0, "p95": 2.0, "p99": 3.0, "min": 0.5, "max": 4.0, "mean": 1.5}
    return {
        "label": "selftest",
        "timestamp": "2026-01-02T03:04:05",
        "duration_s": 2,
        "interval_s": 0.25,
        "snapshot": {
            "smart": {"rows": [], "available": False, "reason": "合成の理由"},
            "unavailable_counters": {"cpu_queue": "0xC0000BB8"},
        },
        "samples": [],
        "stats": {"cpu_pct": dict(stat), "cpu_queue": None, "disk_read_s_C": dict(stat)},
        "events": [],
        "findings": [
            {
                "severity": severity,
                "title": f"合成の所見({severity})",
                "evidence": "合成の根拠 1.0",
                "meaning": "合成の説明",
                "action": "",
            }
            for severity in ("high", "medium", "ok")
        ],
        "event_rate_per_min": 0.0,
    }
