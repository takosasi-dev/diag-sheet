# 回線診断アダプタのテスト(AC-7・AC-8・AC-12 の lanscan_ と §10 のエッジケース)。
# 「節が無い = 未チェック」と「節はあるが値が無い = 測れなかった」の区別、対応表にある2項目だけの
# 判定、総合の写し方、公開 IP や SSID を写さないことを合成データで見る。

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from diagsheet.__main__ import convert_file
from diagsheet.adapters import netdiag
from diagsheet.check import check_sheet
from tests.helpers import (
    FIXTURES,
    SECRETS,
    cli,
    convert_data,
    files_under,
    item,
    read_json,
    section,
    write_json,
)

NO_SECTION = "結果ファイルにこの節が無い(この結果を出した版は測っていない)"
NO_VALUE = "節はあるが値が無い"


@pytest.fixture
def full() -> dict[str, Any]:
    data: dict[str, Any] = read_json(FIXTURES / "netdiag" / "full.json")
    return data


@pytest.fixture
def partial() -> dict[str, Any]:
    data: dict[str, Any] = read_json(FIXTURES / "netdiag" / "partial.json")
    return data


def test_full_result_gives_25_items(full: dict[str, Any], tmp_path: Path) -> None:
    sheet, markdown = convert_data("netdiag", full, tmp_path)
    assert check_sheet(sheet) == []
    assert sheet["tool"] == "netdiag" and sheet["source"]["shape"] == "netdiag-1"
    assert len(sheet["items"]) == 25
    assert len({i["id"] for i in sheet["items"]}) == 25
    assert sheet["run"] == {
        "label": "synthetic",
        "measured_at": "2026-01-02T03:04:05",
        "subject": "回線",
        "conditions": {"contract_mbps": 1000},
    }
    assert sheet["counts"] == {
        "bad": 0,
        "warn": 0,
        "failed": 0,
        "unchecked": 0,
        "not_applicable": 0,
        "ok": 2,
        "none": 23,
    }
    retransmit = item(sheet, "netdiag.link_stats.tcp_retransmit_pct")
    assert retransmit == {
        "id": "netdiag.link_stats.tcp_retransmit_pct",
        "name": "TCP再送率",
        "unit": "%",
        "status": "measured",
        "value": 0.5,
        "confidence": "measured",
        "verdict": "none",
        "verdict_raw": None,
        "verdict_label": None,
        "reason": None,
        "evidence": None,
        "note": None,
        "action": None,
        "from": "link_stats.tcp_retransmit_pct",
    }
    assert item(sheet, "netdiag.latency.1.1.1.1.avg_ms")["value"] == 10
    assert item(sheet, "netdiag.ipv6.has_global_address")["value"] is True
    assert "- 条件: contract_mbps 1000" in markdown
    assert "| 経路MTU | 1500 | 実測 |" in section(markdown, "判定なし")
    assert "| 下り単一 | 300.5 Mbps | 実測 |" in section(markdown, "判定なし")


def test_confidence_reference_and_estimated(full: dict[str, Any], tmp_path: Path) -> None:
    sheet, markdown = convert_data("netdiag", full, tmp_path)
    rpm = item(sheet, "netdiag.bufferbloat.rpm_approx")
    assert (rpm["confidence"], rpm["value"], rpm["note"]) == ("reference", 3000, "合成の RPM 注記")
    method = item(sheet, "netdiag.path_mtu.interpretation")
    assert (method["confidence"], method["name"]) == ("estimated", "接続方式(MTUから推定)")
    others = [
        i["confidence"]
        for i in sheet["items"]
        if i["id"] not in (rpm["id"], method["id"]) and i["status"] == "measured"
    ]
    assert set(others) == {"measured"}
    assert "| 簡易RPM近似値 | 3000 | 参考値 |" in section(markdown, "判定なし")
    assert "| 接続方式(MTUから推定) | 合成の接続方式 | 推定 |" in section(markdown, "判定なし")
    assert "- 注記(簡易RPM近似値): 合成の RPM 注記" in markdown
    assert "合成の MTU 注記" not in markdown and "合成の時刻の注記" not in markdown


def test_verdicts_only_for_the_two_mapped_items(full: dict[str, Any], tmp_path: Path) -> None:
    sheet, markdown = convert_data("netdiag", full, tmp_path)
    judged = {i["id"]: i for i in sheet["items"] if i["verdict"] != "none"}
    assert sorted(judged) == ["netdiag.dnsbl.has_problem", "netdiag.jitter.quality"]
    quality = judged["netdiag.jitter.quality"]
    assert (quality["verdict"], quality["verdict_raw"], quality["verdict_label"]) == (
        "ok",
        "優 (合成の文)",
        "優 (合成の文)",
    )
    dnsbl = judged["netdiag.dnsbl.has_problem"]
    assert (dnsbl["verdict"], dnsbl["verdict_raw"], dnsbl["verdict_label"], dnsbl["value"]) == (
        "ok",
        False,
        "問題なし",
        False,
    )
    assert item(sheet, "netdiag.quic.usable")["verdict"] == "none"
    assert item(sheet, "netdiag.bufferbloat.loaded_latency.avg_ms")["verdict"] == "none"
    normal = section(markdown, "正常")
    assert "| 通話品質 | 優 (合成の文) | 実測 | 優 (合成の文) |  |" in normal
    assert "| DNSBL問題あり | false | 実測 | 問題なし(false) |  |" in normal


@pytest.mark.parametrize(
    ("quality", "verdict"),
    [("優 (快適)", "ok"), ("良", "ok"), ("可 (やや不満)", "warn"), ("不可 (明確な問題)", "bad")],
)
def test_jitter_quality_is_mapped_by_first_character(
    quality: str, verdict: str, full: dict[str, Any], tmp_path: Path
) -> None:
    full["jitter"]["quality"] = quality
    sheet, _ = convert_data("netdiag", full, tmp_path)
    found = item(sheet, "netdiag.jitter.quality")
    assert (found["verdict"], found["verdict_raw"], found["value"]) == (verdict, quality, quality)


def test_dnsbl_problem_is_bad(full: dict[str, Any], tmp_path: Path) -> None:
    full["dnsbl"]["has_problem"] = True
    sheet, markdown = convert_data("netdiag", full, tmp_path)
    found = item(sheet, "netdiag.dnsbl.has_problem")
    assert (found["verdict"], found["verdict_label"]) == ("bad", "問題あり")
    assert "| DNSBL問題あり | true | 実測 | 問題あり(true) |  |" in section(markdown, "異常")


@pytest.mark.parametrize(
    ("section_name", "key", "value"),
    [("jitter", "quality", "最高"), ("jitter", "quality", ""), ("jitter", "quality", 5),
     ("dnsbl", "has_problem", "yes"), ("dnsbl", "has_problem", 1)],
)
def test_values_missing_from_the_verdict_map_exit_2(
    section_name: str, key: str, value: Any, full: dict[str, Any], tmp_path: Path
) -> None:
    full[section_name][key] = value
    source = write_json(tmp_path / "src" / "x.json", full)
    out = tmp_path / "out"
    assert cli("convert", "--tool", "netdiag", str(source), "--out", str(out)) == 2
    assert files_under(out) == []


def test_ac7_missing_section_is_unchecked_and_empty_link_stats_is_failed(
    full: dict[str, Any], tmp_path: Path
) -> None:
    del full["ip_version_compare"]
    full["link_stats"] = {}
    sheet, markdown = convert_data("netdiag", full, tmp_path)
    for item_id, name in (
        ("netdiag.ip_version_compare.ipv4.mbps", "IPv4経由"),
        ("netdiag.ip_version_compare.ipv6.mbps", "IPv6経由"),
    ):
        found = item(sheet, item_id)
        assert (found["name"], found["unit"]) == (name, "Mbps")
        assert (found["status"], found["value"], found["reason"]) == ("unchecked", None, NO_SECTION)
        assert f"| {name} | {NO_SECTION} |" in section(markdown, "未チェック")
    retransmit = item(sheet, "netdiag.link_stats.tcp_retransmit_pct")
    assert (retransmit["status"], retransmit["value"], retransmit["reason"]) == (
        "failed",
        None,
        NO_VALUE,
    )
    assert "TCP再送率" in section(markdown, "測れなかった")
    assert "TCP再送率" not in section(markdown, "未チェック")
    assert sheet["counts"]["unchecked"] == 2 and sheet["counts"]["failed"] == 1


def test_ac8_throughput_error_is_failed_with_the_tool_text(
    full: dict[str, Any], tmp_path: Path
) -> None:
    full["throughput"]["single"] = {"error": "HTTP 429"}
    sheet, markdown = convert_data("netdiag", full, tmp_path)
    single = item(sheet, "netdiag.throughput.single.mbps")
    assert single["name"] == "下り単一"
    assert single["status"] == "failed" and single["value"] is None
    assert "HTTP 429" in single["reason"]
    assert item(sheet, "netdiag.throughput.parallel6.mbps")["status"] == "measured"
    assert "| 下り単一 | HTTP 429 | throughput.single.mbps |" in section(markdown, "測れなかった")


def test_failure_reasons_come_from_the_nearest_error_text(
    partial: dict[str, Any], tmp_path: Path
) -> None:
    sheet, markdown = convert_data("netdiag", partial, tmp_path)
    assert check_sheet(sheet) == []
    reasons = {i["id"].removeprefix("netdiag."): i["reason"] for i in sheet["items"]}
    assert reasons["link_stats.tcp_retransmit_pct"] == "合成の netstat エラー"
    assert reasons["upload.parallel6.mbps"] == "合成の上りエラー"
    assert reasons["throughput.single.mbps"] == "HTTP 429"
    assert reasons["latency.8.8.8.8.avg_ms"] == "合成の ping エラー"
    assert reasons["latency.1.1.1.1.avg_ms"] == NO_VALUE
    assert reasons["latency.gateway.avg_ms"] == NO_VALUE
    assert reasons["path_mtu.mtu"] == "合成の MTU エラー"
    assert reasons["path_mtu.interpretation"] == "合成の MTU エラー"
    assert reasons["jitter.quality"] == "有効なサンプルが不足"
    assert reasons["nat.nat_type"] == "合成の STUN エラー"
    assert reasons["time_sync.offset_ms"] == "合成の NTP エラー"
    assert reasons["dnsbl.has_problem"] == "合成の DNSBL エラー"
    assert reasons["ipv6.egress_reachable"] == NO_VALUE
    assert reasons["bufferbloat.loaded_latency.avg_ms"] == "合成の負荷時エラー"
    assert reasons["bufferbloat.rpm_approx"] == NO_VALUE
    assert reasons["ip_version_compare.ipv4.mbps"] == NO_SECTION
    assert reasons["upload.single.mbps"] is None

    zero = item(sheet, "netdiag.throughput.parallel6.mbps")
    assert (zero["status"], zero["value"]) == ("measured", 0.0)
    assert item(sheet, "netdiag.quic.usable")["value"] is False
    assert item(sheet, "netdiag.jitter.quality")["verdict"] is None
    assert sheet["counts"] == {
        "bad": 0,
        "warn": 0,
        "failed": 18,
        "unchecked": 2,
        "not_applicable": 0,
        "ok": 0,
        "none": 5,
    }
    assert "通話品質" in section(markdown, "測れなかった")
    assert "通話品質" not in section(markdown, "正常")


def test_overall_copies_grade_and_lists_excluded(full: dict[str, Any], tmp_path: Path) -> None:
    full["grade"]["breakdown"][6]["点"] = None
    full["grade"]["breakdown"][6]["実測"] = "測定不可"
    sheet, markdown = convert_data("netdiag", full, tmp_path)
    assert sheet["overall"] == {
        "value": "B",
        "score": 82.5,
        "used": 6,
        "total": 7,
        "excluded": ["TCP再送率"],
        "note": None,
    }
    assert (
        "- 総合(ツールの採点): B / 82.5 点(採点に使った項目 6/7。外れた項目: TCP再送率)" in markdown
    )
    assert "合成のコメント" not in markdown


def test_ungraded_result_keeps_question_mark_and_comment(
    partial: dict[str, Any], tmp_path: Path
) -> None:
    sheet, markdown = convert_data("netdiag", partial, tmp_path)
    assert sheet["overall"] == {
        "value": "?",
        "score": None,
        "used": 0,
        "total": 2,
        "excluded": ["下り速度(契約比)", "TCP再送率"],
        "note": "採点できる項目がありませんでした",
    }
    assert sheet["run"]["conditions"] == {}
    assert "- 条件: なし" in markdown
    assert (
        "- 総合(ツールの採点): ?(採点に使った項目 0/2。外れた項目: 下り速度(契約比)、TCP再送率)"
        in markdown
    )
    assert "- 注記(総合): 採点できる項目がありませんでした" in markdown


def test_ac12_tab_json_name_exit_2(full: dict[str, Any], tmp_path: Path) -> None:
    out = tmp_path / "out"
    for name in ("lanscan_20260102_030405.json", "trend_x.json", "ping_log_1.json"):
        source = write_json(tmp_path / "src" / name, full)
        assert cli("convert", "--tool", "netdiag", str(source), "--out", str(out)) == 2
    lanscan = write_json(tmp_path / "src" / "lanscan_real_shape.json", {"hosts": []})
    assert cli("convert", "--tool", "netdiag", str(lanscan), "--out", str(out)) == 2
    assert files_under(out) == []
    assert len(netdiag.NON_DIAGNOSTIC_PREFIXES) == 17


def _mutate(data: dict[str, Any], name: str) -> None:
    if name == "no_grade":
        del data["grade"]
    elif name == "no_label":
        del data["label"]
    elif name == "unknown_top_key":
        data["app_version"] = "9.9.9"
    elif name == "unknown_grade_key":
        data["grade"]["rank"] = 1
    elif name == "section_is_text":
        data["link_stats"] = "error"
    elif name == "subsection_is_text":
        data["throughput"]["single"] = "error"
    elif name == "value_is_object":
        data["path_mtu"]["mtu"] = {"value": 1500}
    elif name == "value_is_list":
        data["nat"]["nat_type"] = ["a"]
    elif name == "grade_without_score":
        data["grade"]["score"] = None
    elif name == "question_with_score":
        data["grade"]["grade"] = "?"
    elif name == "points_is_text":
        data["grade"]["breakdown"][0]["点"] = "25"
    elif name == "breakdown_not_list":
        data["grade"]["breakdown"] = {}
    elif name == "contract_is_text":
        data["grade"]["contract_mbps"] = "1000"
    elif name == "timestamp_not_iso":
        data["timestamp"] = "2026/01/02 3時"
    else:
        raise AssertionError(name)


UNKNOWN_SHAPES = [
    "no_grade",
    "no_label",
    "unknown_top_key",
    "unknown_grade_key",
    "section_is_text",
    "subsection_is_text",
    "value_is_object",
    "value_is_list",
    "grade_without_score",
    "question_with_score",
    "points_is_text",
    "breakdown_not_list",
    "contract_is_text",
    "timestamp_not_iso",
]


@pytest.mark.parametrize("name", UNKNOWN_SHAPES)
def test_unknown_shapes_exit_2_and_write_nothing(
    name: str, full: dict[str, Any], tmp_path: Path
) -> None:
    _mutate(full, name)
    source = write_json(tmp_path / "src" / "x.json", full)
    out = tmp_path / "out"
    assert cli("convert", "--tool", "netdiag", str(source), "--out", str(out)) == 2
    assert files_under(out) == []


def test_null_section_is_failed_not_unchecked(full: dict[str, Any], tmp_path: Path) -> None:
    full["time_sync"] = None
    sheet, _ = convert_data("netdiag", full, tmp_path)
    found = item(sheet, "netdiag.time_sync.offset_ms")
    assert (found["status"], found["reason"]) == ("failed", NO_VALUE)


def test_nan_value_is_failed(full: dict[str, Any], tmp_path: Path) -> None:
    text = json.dumps(full, ensure_ascii=False).replace('"mos": 4.3', '"mos": NaN')
    assert "NaN" in text
    source = tmp_path / "nan.json"
    source.write_text(text, encoding="utf-8")
    json_path, _ = convert_file("netdiag", source, tmp_path / "out")
    mos = item(read_json(json_path), "netdiag.jitter.mos")
    assert (mos["status"], mos["value"], mos["reason"]) == ("failed", None, "値が数でない(NaN)")


def test_private_details_are_not_copied(tmp_path: Path) -> None:
    for path in sorted((FIXTURES / "netdiag").glob("*.json")):
        assert any(secret in path.read_text(encoding="utf-8") for secret in SECRETS)
        json_path, md_path = convert_file("netdiag", path, tmp_path / path.stem)
        text = json_path.read_text(encoding="utf-8") + md_path.read_text(encoding="utf-8")
        for secret in SECRETS:
            assert secret not in text, (path.name, secret)


def test_tool_version_given_or_unknown(full: dict[str, Any], tmp_path: Path) -> None:
    unknown, md_unknown = convert_data("netdiag", full, tmp_path / "a")
    assert (unknown["tool_version"], unknown["tool_version_from"]) == (None, "不明")
    assert "netdiag 版 不明(出所: 不明)" in md_unknown
    stated, md_stated = convert_data("netdiag", full, tmp_path / "b", version="v1.0.0")
    assert (stated["tool_version"], stated["tool_version_from"]) == ("v1.0.0", "指定")
    assert "netdiag 版 v1.0.0(出所: 指定)" in md_stated
