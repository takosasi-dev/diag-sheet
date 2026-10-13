# 回線診断(Network-diagnostic-software v1.0.0)の結果 JSON をシートに写す。形の名前は netdiag-1。
# 主要指標25項目の鍵の道筋は元ツールの flatten_metrics と同じ物を自分で持つ(import しない)。
# 公開 IP・ISP・SSID・ゲートウェイ・経路・NAT の外部アドレスは読まない。判定は対応表の項目だけ。

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from diagsheet.adapters import (
    VerdictMap,
    as_list,
    as_object,
    as_text,
    as_timestamp,
    is_number,
    load_verdict_map,
    non_finite_word,
    reject_duplicate_ids,
    reject_unknown_keys,
    require_keys,
)
from diagsheet.model import Item, Overall, Run, Scalar, ShapeError, Sheet, Source

TOOL = "netdiag"
SHAPE = "netdiag-1"
ADAPTER_VERSION = "0.1.0"
SUBJECT = "回線"

# 元ツールの results/ に混ざる、フル診断ではない JSON の接頭辞(元ツールの定数と同じ17個)。
NON_DIAGNOSTIC_PREFIXES = (
    "lanscan_",
    "watchdog_",
    "pathmon_",
    "report_",
    "ping_log_",
    "dnsaudit_",
    "geomap_",
    "portcheck_",
    "capture_",
    "atlas_",
    "ipv6_",
    "bandwidth_",
    "topology_",
    "services_",
    "tuning_",
    "advice_",
    "trend_",
)

_TOP_REQUIRED = ("label", "timestamp", "grade")
_TOP_KNOWN = (
    *_TOP_REQUIRED,
    "wifi",
    "ipv6",
    "gateway_ip",
    "latency",
    "traceroute",
    "public_ip_info",
    "dns",
    "path_mtu",
    "jitter",
    "link_stats",
    "nat",
    "throughput",
    "upload",
    "ip_version_compare",
    "time_sync",
    "quic",
    "dnsbl",
    "bufferbloat",
)
_GRADE_REQUIRED = ("grade", "score", "breakdown")
_GRADE_KNOWN = (*_GRADE_REQUIRED, "earned", "possible", "contract_mbps", "comment")
# 値が無いときに理由の文を探す鍵。値に近い階層から順に見る。
_REASON_KEYS = ("error", "reason", "tcp_error", "adapter_error")

REASON_NO_SECTION = "結果ファイルにこの節が無い(この結果を出した版は測っていない)"
REASON_NO_VALUE = "節はあるが値が無い"


@dataclass(frozen=True)
class _Row:
    name: str
    path: tuple[str, ...]
    unit: str | None = None
    confidence: str = "measured"
    note_key: str | None = None


# flatten_metrics の31項目から、ラベル・計測日時・総合グレード・総合スコア・公開IP・ISP を
# 除いた25項目。単位は項目名から分けて unit に入れる。
_ROWS = (
    _Row("IPv6グローバル", ("ipv6", "has_global_address")),
    _Row("IPv6疎通", ("ipv6", "egress_reachable")),
    _Row("経路MTU", ("path_mtu", "mtu")),
    _Row("接続方式(MTUから推定)", ("path_mtu", "interpretation"), confidence="estimated"),
    _Row("NATタイプ", ("nat", "nat_type")),
    _Row("遅延(GW)平均", ("latency", "gateway", "avg_ms"), "ms"),
    _Row("遅延(1.1.1.1)平均", ("latency", "1.1.1.1", "avg_ms"), "ms"),
    _Row("遅延(8.8.8.8)平均", ("latency", "8.8.8.8", "avg_ms"), "ms"),
    _Row("ジッター", ("jitter", "jitter_ms"), "ms"),
    _Row("MOS値", ("jitter", "mos")),
    _Row("通話品質", ("jitter", "quality")),
    _Row("下り単一", ("throughput", "single", "mbps"), "Mbps"),
    _Row("下り6並列", ("throughput", "parallel6", "mbps"), "Mbps"),
    _Row("上り単一", ("upload", "single", "mbps"), "Mbps"),
    _Row("上り6並列", ("upload", "parallel6", "mbps"), "Mbps"),
    _Row("TCP再送率", ("link_stats", "tcp_retransmit_pct"), "%"),
    _Row("IPv4経由", ("ip_version_compare", "ipv4", "mbps"), "Mbps"),
    _Row("IPv6経由", ("ip_version_compare", "ipv6", "mbps"), "Mbps"),
    _Row("時刻ズレ", ("time_sync", "offset_ms"), "ms"),
    _Row("QUIC利用可否", ("quic", "usable")),
    _Row("DNSBL問題あり", ("dnsbl", "has_problem")),
    _Row("バッファブロート アイドル", ("bufferbloat", "idle_latency", "avg_ms"), "ms"),
    _Row("バッファブロート 負荷時", ("bufferbloat", "loaded_latency", "avg_ms"), "ms"),
    _Row("バッファブロート 負荷時損失", ("bufferbloat", "loaded_latency", "loss_pct"), "%"),
    _Row(
        "簡易RPM近似値",
        ("bufferbloat", "rpm_approx"),
        confidence="reference",
        note_key="rpm_note",
    ),
)


def _walk(section: object, row: _Row) -> tuple[object, list[dict[str, Any]]]:
    """節から道筋をたどる。(値, 通ったオブジェクトの列) を返す。途中が無ければ値は None。"""
    visited: list[dict[str, Any]] = []
    current = section
    for depth, key in enumerate(row.path[1:], start=1):
        if current is None:
            break
        if not isinstance(current, dict):
            where = ".".join(row.path[:depth])
            raise ShapeError(f"知らない形: {where} がオブジェクトでも null でもない")
        visited.append(current)
        current = current.get(key)
    return current, visited


def _failure_reason(visited: list[dict[str, Any]]) -> str:
    for node in reversed(visited):
        for key in _REASON_KEYS:
            text = node.get(key)
            if isinstance(text, str) and text:
                return text
    return REASON_NO_VALUE


def _row_item(row: _Row, top: dict[str, Any], vmap: VerdictMap) -> Item:
    field = ".".join(row.path)
    common: dict[str, Any] = {
        "id": f"netdiag.{field}",
        "name": row.name,
        "unit": row.unit,
        "origin": field,
    }
    if row.path[0] not in top:
        return Item(status="unchecked", reason=REASON_NO_SECTION, **common)

    value, visited = _walk(top[row.path[0]], row)
    if row.note_key is not None and visited:
        note = visited[0].get(row.note_key)
        if isinstance(note, str) and note:
            common["note"] = note
    if value is None:
        return Item(status="failed", reason=_failure_reason(visited), **common)
    if not isinstance(value, str | int | float | bool):
        raise ShapeError(f"知らない形: {field} が数・文字列・真偽のどれでもない")
    word = non_finite_word(value)
    if word is not None:
        return Item(status="failed", reason=f"値が数でない({word})", **common)

    if vmap.has_field(field):
        label, verdict = vmap.lookup(field, value)
        return Item(
            status="measured",
            value=value,
            confidence=row.confidence,
            verdict=verdict,
            verdict_raw=value,
            verdict_label=label,
            **common,
        )
    return Item(
        status="measured", value=value, confidence=row.confidence, verdict="none", **common
    )


def _overall(grade: dict[str, Any]) -> Overall:
    value = as_text(grade["grade"], "grade.grade")
    score = grade["score"]
    if score is not None and (not is_number(score) or non_finite_word(score) is not None):
        raise ShapeError("知らない形: grade.score が数でも null でもない")
    if not value or (value == "?") != (score is None):
        raise ShapeError("知らない形: grade.grade と grade.score の組み合わせが実物に無い")

    breakdown = as_list(grade["breakdown"], "grade.breakdown")
    used = 0
    excluded: list[str] = []
    for index, raw in enumerate(breakdown):
        where = f"grade.breakdown[{index}]"
        entry = as_object(raw, where)
        require_keys(entry, ("項目", "点"), where)
        name = as_text(entry["項目"], f"{where}.項目")
        points = entry["点"]
        if points is None:
            excluded.append(name)
        elif is_number(points) and non_finite_word(points) is None:
            used += 1
        else:
            raise ShapeError(f"知らない形: {where}.点 が数でも null でもない")

    note: str | None = None
    if value == "?":
        comment = grade.get("comment")
        note = comment if isinstance(comment, str) and comment else None
    return Overall(
        value=value, score=score, used=used, total=len(breakdown), excluded=excluded, note=note
    )


def _conditions(grade: dict[str, Any]) -> dict[str, Scalar]:
    if "contract_mbps" not in grade:
        return {}
    contract = grade["contract_mbps"]
    if not is_number(contract) or non_finite_word(contract) is not None:
        raise ShapeError("知らない形: grade.contract_mbps が数でない")
    return {"contract_mbps": contract}


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
    for prefix in NON_DIAGNOSTIC_PREFIXES:
        if source_file.startswith(prefix):
            raise ShapeError(
                f"フル診断の結果ではない: ファイル名が {prefix} で始まる(回線診断の各タブの JSON)"
            )
    top = as_object(source, "最上位")
    missing = [key for key in _TOP_REQUIRED if key not in top]
    if missing:
        raise ShapeError(f"フル診断の結果ではない: 最上位に鍵 {'・'.join(missing)} が無い")
    reject_unknown_keys(top, _TOP_KNOWN, "最上位")
    label = as_text(top["label"], "label")
    timestamp = as_timestamp(top["timestamp"], "timestamp")
    grade = as_object(top["grade"], "grade")
    require_keys(grade, _GRADE_REQUIRED, "grade")
    reject_unknown_keys(grade, _GRADE_KNOWN, "grade")

    vmap = load_verdict_map(TOOL, mappings_dir)
    items = [_row_item(row, top, vmap) for row in _ROWS]
    reject_duplicate_ids(item.id for item in items)
    return Sheet(
        tool=TOOL,
        tool_version=tool_version,
        adapter_version=ADAPTER_VERSION,
        created_at=created_at,
        source=Source(file=source_file, sha256=source_sha256, shape=SHAPE),
        run=Run(
            label=label, measured_at=timestamp, subject=SUBJECT, conditions=_conditions(grade)
        ),
        items=items,
        overall=_overall(grade),
    )


def synthetic_source() -> dict[str, Any]:
    """--selftest 用の合成の元 JSON。値はすべて作り物で、実測ではない。

    アドレスは文書用の範囲(203.0.113.0/24)、SSID は作り物。シートに出ないことの確認に使う。
    """
    ping = {"loss_pct": 0, "min_ms": 1, "max_ms": 3, "avg_ms": 2}
    return {
        "label": "selftest",
        "timestamp": "2026-01-02T03:04:05",
        "wifi": {"available": True, "ssid": "SYNTHETIC-SSID"},
        "ipv6": {"has_global_address": True, "egress_reachable": False},
        "gateway_ip": "192.0.2.1",
        "latency": {"gateway": dict(ping), "1.1.1.1": dict(ping), "8.8.8.8": dict(ping)},
        "public_ip_info": {"ip": "203.0.113.7", "org": "SYNTHETIC-ISP"},
        "path_mtu": {"mtu": 1500, "max_payload": 1472, "interpretation": "合成の接続方式"},
        "jitter": {"jitter_ms": 1.5, "mos": 4.2, "quality": "可 (合成の文)"},
        "link_stats": {},
        "nat": {"nat_type": "合成の NAT タイプ", "external_ip": "203.0.113.7"},
        "throughput": {"single": {"error": "HTTP 429"}, "parallel6": {"mbps": 200.5}},
        "upload": {"single": {"mbps": 50.25}, "parallel6": {"mbps": 100.0}},
        "time_sync": {"offset_ms": 12.3},
        "quic": {"usable": True},
        "dnsbl": {"ip": "203.0.113.7", "has_problem": False},
        "bufferbloat": {
            "idle_latency": dict(ping),
            "loaded_latency": dict(ping),
            "rpm_approx": 30000,
            "rpm_note": "合成の注記",
        },
        "grade": {
            "grade": "B",
            "score": 81.5,
            "contract_mbps": 1000,
            "breakdown": [
                {"項目": "下り速度(契約比)", "実測": "合成", "点": 11, "満点": 25},
                {"項目": "TCP再送率", "実測": "測定不可", "点": None, "満点": 5},
            ],
            "comment": "合成のコメント",
        },
    }
