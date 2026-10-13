# PC 遅延診断アダプタのテスト(AC-4・AC-5・AC-6・AC-12・AC-14 と §10 のエッジケース)。
# 判定が severity の対応表だけで決まること、値が無い項目を「正常」に入れないこと、
# 知らない形で止まること、プロセス名などを写さないことを合成データで見る。

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from diagsheet.__main__ import convert_file
from diagsheet.adapters import stutter
from diagsheet.check import check_sheet
from diagsheet.model import ShapeError
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

STAT = {"n": 4, "p50": 1.0, "p95": 2.0, "p99": 3.0, "min": 0.5, "max": 4.0, "mean": 1.5}


@pytest.fixture
def basic() -> dict[str, Any]:
    data: dict[str, Any] = read_json(FIXTURES / "stutter" / "basic.json")
    return data


@pytest.fixture
def counters() -> dict[str, Any]:
    data: dict[str, Any] = read_json(FIXTURES / "stutter" / "counters.json")
    return data


def _verdicts(sheet: dict[str, Any]) -> list[str]:
    return [i["verdict"] for i in sheet["items"] if i["id"].startswith("stutter.finding.")]


def test_findings_are_copied_with_mapped_verdicts(basic: dict[str, Any], tmp_path: Path) -> None:
    sheet, markdown = convert_data("stutter", basic, tmp_path)
    assert check_sheet(sheet) == []
    assert sheet["tool"] == "stutter" and sheet["source"]["shape"] == "stutter-1"
    assert sheet["run"] == {
        "label": "synthetic",
        "measured_at": "2026-01-02T03:04:05",
        "subject": "PC",
        "conditions": {"duration_s": 4, "interval_s": 0.25},
    }
    assert sheet["overall"] is None
    first = item(sheet, "stutter.finding.0")
    assert first == {
        "id": "stutter.finding.0",
        "name": "合成の所見 A",
        "unit": None,
        "status": "measured",
        "value": None,
        "confidence": "measured",
        "verdict": "bad",
        "verdict_raw": "high",
        "verdict_label": "要対処",
        "reason": None,
        "evidence": "最大 200ms / 該当 1回",
        "note": "合成の説明 A",
        "action": "合成の対処 A",
        "from": "findings[0]",
    }
    assert _verdicts(sheet) == ["bad", "warn", "ok"]
    assert item(sheet, "stutter.finding.2")["note"] is None
    assert item(sheet, "stutter.finding.1")["action"] is None
    assert "合成の所見 A" in section(markdown, "異常")
    assert "要対処(high)" in section(markdown, "異常")
    assert "合成の所見 B" in section(markdown, "注意")
    assert "合成の所見 C" in section(markdown, "正常")
    assert "- 総合" not in markdown


def test_ac4_verdict_follows_severity_only(basic: dict[str, Any], tmp_path: Path) -> None:
    before, _ = convert_data("stutter", basic, tmp_path / "a")

    changed = copy.deepcopy(basic)
    changed["findings"][0]["severity"] = "ok"
    after, _ = convert_data("stutter", changed, tmp_path / "b")
    assert _verdicts(before) == ["bad", "warn", "ok"]
    assert _verdicts(after) == ["ok", "warn", "ok"]

    numbers = copy.deepcopy(basic)
    numbers["findings"][0]["evidence"] = "最大 1ms / 該当 0回"
    numbers["findings"][2]["evidence"] = "p99 99.9% / 最大 100.0%"
    for stat in numbers["stats"].values():
        for key in stat:
            stat[key] = 9999.0
    numbers["event_rate_per_min"] = 9999.0
    same, _ = convert_data("stutter", numbers, tmp_path / "c")
    assert _verdicts(same) == _verdicts(before)
    assert same["counts"] == before["counts"]


def test_ac5_smart_unavailable_is_failed_not_normal(basic: dict[str, Any], tmp_path: Path) -> None:
    sheet, markdown = convert_data("stutter", basic, tmp_path)
    smart = item(sheet, "stutter.smart")
    assert smart["name"] == "SMART(消耗度)"
    assert smart["status"] == "failed"
    assert smart["value"] is None
    assert smart["verdict"] is None
    assert smart["confidence"] is None
    assert smart["reason"] == "権限不足"
    assert "SMART(消耗度)" in section(markdown, "測れなかった")
    assert "権限不足" in section(markdown, "測れなかった")
    assert "SMART(消耗度)" not in section(markdown, "正常")
    assert "SMART(消耗度)" not in section(markdown, "判定なし")


def test_smart_reason_null_uses_fixed_text(basic: dict[str, Any], tmp_path: Path) -> None:
    basic["snapshot"]["smart"]["reason"] = None
    sheet, _ = convert_data("stutter", basic, tmp_path)
    assert item(sheet, "stutter.smart")["reason"] == "SMART を取得できなかった"


def test_ac6_counter_and_null_stat_make_two_failed(
    counters: dict[str, Any], tmp_path: Path
) -> None:
    sheet, markdown = convert_data("stutter", counters, tmp_path)
    failed = [i for i in sheet["items"] if i["status"] == "failed"]
    assert [i["id"] for i in failed] == ["stutter.counter.freq_pct", "stutter.stats.hard_faults"]
    assert failed[0]["reason"] == "PDH カウンタを開けなかった(0xC0000BB8)"
    assert failed[0]["from"] == "snapshot.unavailable_counters.freq_pct"
    assert failed[1]["reason"] == "サンプルが1件も取れなかった"
    assert failed[1]["from"] == "stats.hard_faults"
    assert sheet["counts"]["failed"] == 2
    assert "## [測れなかった] 2件" in markdown


def test_same_counter_in_both_places_gives_two_items(
    counters: dict[str, Any], tmp_path: Path
) -> None:
    counters["stats"] = {"cpu_pct": dict(STAT), "freq_pct": None}
    sheet, _ = convert_data("stutter", counters, tmp_path)
    failed = [i["id"] for i in sheet["items"] if i["status"] == "failed"]
    assert failed == ["stutter.counter.freq_pct", "stutter.stats.freq_pct"]


def test_smart_rows_are_measured_without_verdict(counters: dict[str, Any], tmp_path: Path) -> None:
    sheet, markdown = convert_data("stutter", counters, tmp_path)
    wear = item(sheet, "stutter.smart.0.Wear")
    assert (wear["value"], wear["unit"], wear["verdict"], wear["confidence"]) == (
        3,
        "%",
        "none",
        "measured",
    )
    assert wear["from"] == "snapshot.smart.rows[0].Wear"
    assert item(sheet, "stutter.smart.1.Wear")["value"] == 0
    assert item(sheet, "stutter.smart.1.Temperature")["unit"] == "℃"
    assert item(sheet, "stutter.smart.0.PowerOnHours")["value"] == 1234
    assert not any(i["id"] == "stutter.smart" for i in sheet["items"])
    assert "| SMART ディスク0 消耗 | 3 % | 実測 |" in section(markdown, "判定なし")
    assert "| SMART ディスク1 消耗 | 0 % | 実測 |" in section(markdown, "判定なし")


def test_smart_null_value_is_failed_not_zero(counters: dict[str, Any], tmp_path: Path) -> None:
    counters["snapshot"]["smart"]["rows"][1]["Wear"] = None
    sheet, _ = convert_data("stutter", counters, tmp_path)
    wear = item(sheet, "stutter.smart.1.Wear")
    assert wear["status"] == "failed" and wear["value"] is None
    assert wear["reason"] == "SMART の行はあるが値が無い"


def test_event_rate_and_not_measured_items(basic: dict[str, Any], tmp_path: Path) -> None:
    sheet, markdown = convert_data("stutter", basic, tmp_path)
    rate = item(sheet, "stutter.event_rate_per_min")
    assert (rate["status"], rate["value"], rate["unit"], rate["verdict"], rate["confidence"]) == (
        "measured",
        15.0,
        "件/分",
        "none",
        "measured",
    )
    unchecked = [i for i in sheet["items"] if i["status"] == "unchecked"]
    assert [(i["id"], i["name"], i["reason"]) for i in unchecked] == [
        (
            "stutter.not_measured.0",
            "プロセス別のディスクI/O",
            "プロセス別のディスクI/O も管理者権限が必要。",
        ),
        (
            "stutter.not_measured.1",
            "GPU起因のコマ落ち",
            "GPU起因のコマ落ち。表示側の話でOSのカウンタには出ない。",
        ),
    ]
    assert "GPU起因のコマ落ち" in section(markdown, "未チェック")
    assert "GPU起因のコマ落ち" not in section(markdown, "正常")
    assert sheet["counts"] == {
        "bad": 1,
        "warn": 1,
        "failed": 1,
        "unchecked": 2,
        "not_applicable": 0,
        "ok": 1,
        "none": 1,
    }


def test_nan_becomes_failed(basic: dict[str, Any], tmp_path: Path) -> None:
    text = json.dumps(basic, ensure_ascii=False).replace(
        '"event_rate_per_min": 15.0', '"event_rate_per_min": NaN'
    )
    assert "NaN" in text
    source = tmp_path / "nan.json"
    source.write_text(text, encoding="utf-8")
    json_path, _ = convert_file("stutter", source, tmp_path / "out")
    sheet = read_json(json_path)
    rate = item(sheet, "stutter.event_rate_per_min")
    assert rate["status"] == "failed" and rate["value"] is None
    assert rate["reason"] == "値が数でない(NaN)"
    assert "NaN" not in json_path.read_text(encoding="utf-8").replace("値が数でない(NaN)", "")


def test_ac12_missing_label_and_timestamp_exit_2(basic: dict[str, Any], tmp_path: Path) -> None:
    del basic["label"]
    del basic["timestamp"]
    source = write_json(tmp_path / "src" / "nolabel.json", basic)
    out = tmp_path / "out"
    assert cli("convert", "--tool", "stutter", str(source), "--out", str(out)) == 2
    assert files_under(out) == []


def test_ac12_unknown_severity_exit_2(basic: dict[str, Any], tmp_path: Path) -> None:
    basic["findings"][1]["severity"] = "critical"
    source = write_json(tmp_path / "src" / "critical.json", basic)
    out = tmp_path / "out"
    assert cli("convert", "--tool", "stutter", str(source), "--out", str(out)) == 2
    assert files_under(out) == []


def _mutate(data: dict[str, Any], name: str) -> None:
    if name == "legacy_stats":
        data["stats"] = {"cpu_pct": dict(STAT), "disk_read_s": dict(STAT)}
    elif name == "unknown_top_key":
        data["app_version"] = "9.9.9"
    elif name == "unknown_finding_key":
        data["findings"][0]["kind"] = "disk"
    elif name == "missing_finding_key":
        del data["findings"][0]["meaning"]
    elif name == "severity_not_text":
        data["findings"][0]["severity"] = None
    elif name == "empty_evidence":
        data["findings"][0]["evidence"] = ""
    elif name == "no_smart":
        del data["snapshot"]["smart"]
    elif name == "smart_available_not_bool":
        data["snapshot"]["smart"]["available"] = "no"
    elif name == "smart_true_without_rows":
        data["snapshot"]["smart"]["available"] = True
    elif name == "stat_not_object":
        data["stats"]["cpu_pct"] = 5
    elif name == "event_rate_missing":
        del data["event_rate_per_min"]
    elif name == "event_rate_null":
        data["event_rate_per_min"] = None
    elif name == "event_rate_bool":
        data["event_rate_per_min"] = True
    elif name == "duration_text":
        data["duration_s"] = "120"
    elif name == "timestamp_not_iso":
        data["timestamp"] = "きのう"
    elif name == "findings_not_list":
        data["findings"] = {}
    elif name == "counters_not_object":
        data["snapshot"]["unavailable_counters"] = ["cpu_pct"]
    else:
        raise AssertionError(name)


UNKNOWN_SHAPES = [
    "legacy_stats",
    "unknown_top_key",
    "unknown_finding_key",
    "missing_finding_key",
    "severity_not_text",
    "empty_evidence",
    "no_smart",
    "smart_available_not_bool",
    "smart_true_without_rows",
    "stat_not_object",
    "event_rate_missing",
    "event_rate_null",
    "event_rate_bool",
    "duration_text",
    "timestamp_not_iso",
    "findings_not_list",
    "counters_not_object",
]


@pytest.mark.parametrize("name", UNKNOWN_SHAPES)
def test_unknown_shapes_exit_2_and_write_nothing(
    name: str, basic: dict[str, Any], tmp_path: Path
) -> None:
    _mutate(basic, name)
    source = write_json(tmp_path / "src" / "x.json", basic)
    out = tmp_path / "out"
    assert cli("convert", "--tool", "stutter", str(source), "--out", str(out)) == 2
    assert files_under(out) == []


def test_top_level_list_is_unknown_shape() -> None:
    with pytest.raises(ShapeError):
        stutter.convert(
            [1], source_file="x.json", source_sha256="0" * 64, tool_version=None, created_at="x"
        )


def test_ac14_tool_version(basic: dict[str, Any], tmp_path: Path) -> None:
    unknown, md_unknown = convert_data("stutter", basic, tmp_path / "a")
    assert unknown["tool_version"] is None
    assert unknown["tool_version_from"] == "不明"
    assert "版 不明" in md_unknown

    stated, md_stated = convert_data("stutter", basic, tmp_path / "b", version="v1.0.0")
    assert stated["tool_version"] == "v1.0.0"
    assert stated["tool_version_from"] == "指定"
    assert "stutter 版 v1.0.0(出所: 指定)" in md_stated
    assert unknown["adapter_version"] == "0.1.0" and unknown["diagsheet"] == 1


def test_empty_tool_version_is_an_argument_error(basic: dict[str, Any], tmp_path: Path) -> None:
    source = write_json(tmp_path / "src" / "x.json", basic)
    out = tmp_path / "out"
    args = ["convert", "--tool", "stutter", str(source), "--tool-version", " ", "--out", str(out)]
    assert cli(*args) == 1
    assert files_under(out) == []


def test_source_is_not_modified_and_hash_matches(basic: dict[str, Any], tmp_path: Path) -> None:
    import hashlib

    source = write_json(tmp_path / "src" / "x y.json", basic)
    before = source.read_bytes()
    stat_before = source.stat()
    json_path, md_path = convert_file("stutter", source, tmp_path / "out")
    assert source.read_bytes() == before
    assert source.stat().st_mtime_ns == stat_before.st_mtime_ns
    assert [p.name for p in files_under(tmp_path / "src")] == ["x y.json"]
    sheet = read_json(json_path)
    assert sheet["source"] == {
        "file": "x y.json",
        "sha256": hashlib.sha256(before).hexdigest(),
        "shape": "stutter-1",
    }
    assert (json_path.name, md_path.name) == ("x y.sheet.json", "x y.sheet.md")


def test_bom_source_is_read_and_hash_covers_the_bom(basic: dict[str, Any], tmp_path: Path) -> None:
    import hashlib

    raw = b"\xef\xbb\xbf" + json.dumps(basic, ensure_ascii=False).encode("utf-8")
    source = tmp_path / "bom.json"
    source.write_bytes(raw)
    json_path, _ = convert_file("stutter", source, tmp_path / "out")
    assert read_json(json_path)["source"]["sha256"] == hashlib.sha256(raw).hexdigest()


def test_broken_or_missing_source_exits_1(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"label": ', encoding="utf-8")
    out = tmp_path / "out"
    assert cli("convert", "--tool", "stutter", str(broken), "--out", str(out)) == 1
    assert cli("convert", "--tool", "stutter", str(tmp_path / "none.json"), "--out", str(out)) == 1
    not_utf8 = tmp_path / "sjis.json"
    not_utf8.write_bytes('{"label": "夜"}'.encode("cp932"))
    assert cli("convert", "--tool", "stutter", str(not_utf8), "--out", str(out)) == 1
    assert files_under(out) == []


def test_convert_never_overwrites(basic: dict[str, Any], tmp_path: Path) -> None:
    source = write_json(tmp_path / "src" / "x.json", basic)
    out = tmp_path / "out"
    assert cli("convert", "--tool", "stutter", str(source), "--out", str(out)) == 0
    first = {p.name: p.read_bytes() for p in files_under(out)}
    assert sorted(first) == ["x.sheet.json", "x.sheet.md"]
    assert cli("convert", "--tool", "stutter", str(source), "--out", str(out)) == 1
    assert {p.name: p.read_bytes() for p in files_under(out)} == first

    (out / "x.sheet.json").unlink()
    assert cli("convert", "--tool", "stutter", str(source), "--out", str(out)) == 1
    assert [p.name for p in files_under(out)] == ["x.sheet.md"]


def test_private_details_are_not_copied(tmp_path: Path) -> None:
    for path in sorted((FIXTURES / "stutter").glob("*.json")):
        json_path, md_path = convert_file("stutter", path, tmp_path / path.stem)
        text = json_path.read_text(encoding="utf-8") + md_path.read_text(encoding="utf-8")
        for secret in SECRETS:
            assert secret not in text, (path.name, secret)
