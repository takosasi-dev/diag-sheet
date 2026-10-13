# 形の検査(check)と Markdown の描画(render)のテスト。受け入れ基準 AC-10・AC-11 を含む。
# 壊したシートがどれも終了コード 3 で止まることと、7つの見出しが決まった順で1回ずつ出ることを見る。

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from diagsheet.__main__ import convert_file, heading_problems
from diagsheet.check import check_sheet
from diagsheet.model import CATEGORY_ORDER, display_words, load_bad_word
from diagsheet.render_md import FOOTER_LINE, render
from tests.helpers import (
    FIXTURES,
    cli,
    files_under,
    read_json,
    section,
    sheet_fixtures,
    source_fixtures,
    write_json,
)

BAD_WORD = load_bad_word()
WORDS = [display_words(BAD_WORD)[category] for category in CATEGORY_ORDER]


@pytest.fixture
def sheet() -> dict[str, Any]:
    data: dict[str, Any] = read_json(FIXTURES / "sheets" / "all_states.sheet.json")
    return data


def _by_id(sheet: dict[str, Any], item_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(i for i in sheet["items"] if i["id"] == item_id)
    return found


def test_seven_words_are_distinct() -> None:
    assert WORDS == ["異常", "注意", "測れなかった", "未チェック", "対象外", "正常", "判定なし"]
    assert len(set(WORDS)) == 7


@pytest.mark.parametrize("path", sheet_fixtures(), ids=lambda p: p.name)
def test_sheet_fixtures_pass_check(path: Path) -> None:
    assert check_sheet(read_json(path)) == []


def _break_failed_with_value(s: dict[str, Any]) -> None:
    _by_id(s, "synthetic.failed")["value"] = 0


def _break_confidence_on_unmeasured(s: dict[str, Any]) -> None:
    _by_id(s, "synthetic.unchecked")["confidence"] = "measured"


def _break_unchecked_without_reason(s: dict[str, Any]) -> None:
    _by_id(s, "synthetic.unchecked")["reason"] = None


def _break_shape_version(s: dict[str, Any]) -> None:
    s["diagsheet"] = 2


def _break_duplicate_id(s: dict[str, Any]) -> None:
    _by_id(s, "synthetic.ok")["id"] = "synthetic.warn"


AC11_BREAKERS = [
    _break_failed_with_value,
    _break_confidence_on_unmeasured,
    _break_unchecked_without_reason,
    _break_shape_version,
    _break_duplicate_id,
]


@pytest.mark.parametrize("breaker", AC11_BREAKERS, ids=lambda f: f.__name__)
def test_ac11_broken_sheets_exit_3(
    breaker: Any, sheet: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    breaker(sheet)
    path = write_json(tmp_path / "broken.sheet.json", sheet)
    assert cli("check", str(path)) == 3
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) >= 1


@pytest.mark.parametrize("breaker", AC11_BREAKERS, ids=lambda f: f.__name__)
def test_render_refuses_broken_sheets(
    breaker: Any, sheet: dict[str, Any], tmp_path: Path
) -> None:
    breaker(sheet)
    path = write_json(tmp_path / "broken.sheet.json", sheet)
    out = tmp_path / "out"
    assert cli("render", str(path), "--out", str(out)) == 3
    assert files_under(out) == []


def _mutations() -> dict[str, Any]:
    def unknown_top(s: dict[str, Any]) -> None:
        s["extra"] = 1

    def unknown_item_key(s: dict[str, Any]) -> None:
        s["items"][0]["extra"] = 1

    def missing_item_key(s: dict[str, Any]) -> None:
        del s["items"][0]["note"]

    def wrong_count(s: dict[str, Any]) -> None:
        s["counts"]["ok"] += 1

    def nan_value(s: dict[str, Any]) -> None:
        _by_id(s, "synthetic.warn")["value"] = float("nan")

    def infinity_value(s: dict[str, Any]) -> None:
        _by_id(s, "synthetic.warn")["value"] = float("inf")

    def list_value(s: dict[str, Any]) -> None:
        _by_id(s, "synthetic.warn")["value"] = [1]

    def unknown_status(s: dict[str, Any]) -> None:
        _by_id(s, "synthetic.failed")["status"] = "skipped"

    def unknown_verdict(s: dict[str, Any]) -> None:
        _by_id(s, "synthetic.ok")["verdict"] = "critical"

    def verdict_without_raw(s: dict[str, Any]) -> None:
        _by_id(s, "synthetic.bad")["verdict_raw"] = None

    def raw_on_unjudged(s: dict[str, Any]) -> None:
        _by_id(s, "synthetic.none.reference")["verdict_label"] = "正常"

    def measured_without_value(s: dict[str, Any]) -> None:
        _by_id(s, "synthetic.none.reference")["value"] = None

    def measured_with_reason(s: dict[str, Any]) -> None:
        _by_id(s, "synthetic.ok")["reason"] = "理由"

    def verdict_on_failed(s: dict[str, Any]) -> None:
        _by_id(s, "synthetic.failed")["verdict"] = "ok"

    def unknown_version_with_value(s: dict[str, Any]) -> None:
        s["tool_version_from"] = "不明"

    def stated_version_without_value(s: dict[str, Any]) -> None:
        s["tool_version"] = None

    def guessed_version_source(s: dict[str, Any]) -> None:
        s["tool_version_from"] = "推定"

    def unknown_tool(s: dict[str, Any]) -> None:
        s["tool"] = "other"

    def bad_sha(s: dict[str, Any]) -> None:
        s["source"]["sha256"] = "abc"

    def shape_version_as_text(s: dict[str, Any]) -> None:
        s["diagsheet"] = "1"

    def shape_version_as_bool(s: dict[str, Any]) -> None:
        s["diagsheet"] = True

    return {name: func for name, func in locals().items() if callable(func)}


MUTATIONS = _mutations()


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_check_reports_each_rule(name: str, sheet: dict[str, Any]) -> None:
    MUTATIONS[name](sheet)
    assert check_sheet(sheet), name


def test_check_rejects_non_object() -> None:
    assert check_sheet([1, 2]) != []
    assert check_sheet(None) != []


def test_check_cli_passes_valid_sheet(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli("check", str(sheet_fixtures()[0])) == 0
    assert "違反なし" in capsys.readouterr().out


def test_check_cli_unreadable_json_exits_1(tmp_path: Path) -> None:
    path = tmp_path / "broken.sheet.json"
    path.write_text("{ not json", encoding="utf-8")
    assert cli("check", str(path)) == 1
    assert cli("check", str(tmp_path / "missing.sheet.json")) == 1


def _all_markdown(tmp_path: Path) -> list[tuple[str, dict[str, Any], str]]:
    """全 fixture の (名前, シート, Markdown)。元データは変換し、シートは描画する。"""
    out: list[tuple[str, dict[str, Any], str]] = []
    for tool, path in source_fixtures():
        json_path, md_path = convert_file(tool, path, tmp_path / f"out_{tool}")
        out.append((f"{tool}/{path.name}", read_json(json_path), md_path.read_text("utf-8")))
    for path in sheet_fixtures():
        data = read_json(path)
        out.append((path.name, data, render(data, BAD_WORD)))
    return out


def test_ac10_headings_and_count_table(tmp_path: Path) -> None:
    results = _all_markdown(tmp_path)
    assert len(results) >= 5
    for name, data, markdown in results:
        headings = [line for line in markdown.splitlines() if line.startswith("## ")]
        assert len(headings) == 7, name
        for heading, word, category in zip(headings, WORDS, CATEGORY_ORDER, strict=True):
            assert heading == f"## [{word}] {data['counts'][category]}件", name
            assert markdown.count(f"\n## [{word}] ") == 1, name
        assert heading_problems(markdown, BAD_WORD) == [], name

        lines = markdown.splitlines()
        header = lines.index("| " + " | ".join(WORDS) + " |")
        numbers = [int(cell) for cell in lines[header + 2].strip("|").split("|")]
        assert len(numbers) == 7, name
        assert sum(numbers) == len(data["items"]), name
        assert numbers == [data["counts"][category] for category in CATEGORY_ORDER], name


def test_ac9_no_substitute_values_in_any_fixture(tmp_path: Path) -> None:
    seen = 0
    for name, data, _ in _all_markdown(tmp_path):
        for entry in data["items"]:
            if entry["status"] != "measured":
                seen += 1
                assert entry["value"] is None, f"{name} {entry['id']}"
                assert entry["confidence"] is None, f"{name} {entry['id']}"
                assert entry["verdict"] is None, f"{name} {entry['id']}"
                assert entry["reason"], f"{name} {entry['id']}"
    assert seen > 10


def test_render_puts_each_item_in_its_own_section(sheet: dict[str, Any]) -> None:
    markdown = render(sheet, BAD_WORD)
    expected = {
        "異常": "合成の項目(異常)",
        "注意": "合成の項目(注意)",
        "測れなかった": "合成の項目(測れなかった)",
        "未チェック": "合成の項目(未チェック)",
        "対象外": "合成の項目(対象外)",
        "正常": "合成の項目(正常)",
        "判定なし": "合成の項目(判定なし・参考値)",
    }
    for word, name in expected.items():
        for other in WORDS:
            assert (name in section(markdown, other)) == (other == word), (word, other)


def test_render_table_shapes_and_escaping(sheet: dict[str, Any]) -> None:
    markdown = render(sheet, BAD_WORD)
    bad = section(markdown, "異常")
    assert "| 項目 | 値 | 確度 | ツールの判定 | 根拠 |" in bad
    assert "要対処(high)" in bad
    assert "合成の根拠 \\| 縦棒つき" in bad
    failed = section(markdown, "測れなかった")
    assert "| 項目 | 理由 | 元の場所 |" in failed
    assert "合成の理由<br>2行目" in failed
    assert "| 合成の項目(注意) | 12.5 ms | 実測 | 注意(medium) |  |" in section(markdown, "注意")
    assert "| 合成の項目(正常) | false | 実測 | 問題なし(false) |  |" in section(markdown, "正常")
    none = section(markdown, "判定なし")
    assert "| 項目 | 値 | 確度 |" in none
    assert "| 合成の項目(判定なし・参考値) | 3000 | 参考値 |" in none
    assert "| 合成の項目(判定なし・申告) | 合成の答え | 申告 |" in none


def test_render_writes_nashi_for_empty_sections(sheet: dict[str, Any]) -> None:
    sheet["items"] = [i for i in sheet["items"] if i["id"] == "synthetic.ok"]
    sheet["counts"] = dict.fromkeys(CATEGORY_ORDER, 0) | {"ok": 1}
    assert check_sheet(sheet) == []
    markdown = render(sheet, BAD_WORD)
    for word in WORDS:
        body = section(markdown, word).splitlines()
        if word == "正常":
            assert body[0] == "## [正常] 1件"
        else:
            assert body == [f"## [{word}] 0件", "なし"]


def test_render_header_footer_and_frontmatter(sheet: dict[str, Any]) -> None:
    markdown = render(sheet, BAD_WORD)
    lines = markdown.splitlines()
    assert lines[:10] == [
        "---",
        "title: 診断シート 合成 all states",
        "created: 2026-01-02 03:04",
        "measured: 2026-01-02 03:04:05",
        "tags:",
        "  - 診断シート",
        "  - PadLab",
        "diagsheet: 1",
        "---",
        "# 診断シート 合成 all states",
    ]
    assert "- 計測日時: 2026-01-02 03:04:05" in lines
    assert "- ツール: padlab 版 v0.0.0-synthetic(出所: 指定) / アダプタ 0.1.0 / 形の版 1" in lines
    assert "- 元ファイル: synthetic.json(SHA-256 先頭12桁 000000000000)" in lines
    assert "- 条件: mode synthetic / count 3" in lines
    assert not any(line.startswith("- 総合") for line in lines)
    tail = lines[lines.index("---", 9) :]
    assert tail[1] == f"- {FOOTER_LINE}"
    assert "- 注記(合成の項目(異常)): 合成の注記" in tail
    assert markdown.endswith("\n") and "\r" not in markdown


def test_render_unknown_version_and_overall(sheet: dict[str, Any]) -> None:
    sheet["tool_version"] = None
    sheet["tool_version_from"] = "不明"
    sheet["overall"] = {
        "value": "D",
        "score": 56.8,
        "used": 6,
        "total": 7,
        "excluded": ["TCP再送率"],
    }
    assert check_sheet(sheet) == []
    markdown = render(sheet, BAD_WORD)
    assert "版 不明(出所: 不明)" in markdown
    assert (
        "- 総合(ツールの採点): D / 56.8 点(採点に使った項目 6/7。外れた項目: TCP再送率)" in markdown
    )


def test_render_quotes_risky_title(sheet: dict[str, Any]) -> None:
    sheet["run"]["label"] = 'a: b #c "d"\n## [正常] 9件'
    markdown = render(sheet, BAD_WORD)
    title_line = markdown.splitlines()[1]
    assert title_line.startswith('title: "') and title_line.endswith('"')
    title = json.loads(title_line.removeprefix("title: "))
    assert title == '診断シート 合成 a: b #c "d" ## [正常] 9件'
    assert heading_problems(markdown, BAD_WORD) == []


def test_render_cli_writes_only_markdown_and_never_overwrites(tmp_path: Path) -> None:
    source = sheet_fixtures()[0]
    out = tmp_path / "out"
    assert cli("render", str(source), "--out", str(out)) == 0
    written = files_under(out)
    assert [p.name for p in written] == ["all_states.sheet.md"]
    first = written[0].read_bytes()
    assert b"\r" not in first and not first.startswith(b"\xef\xbb\xbf")
    assert cli("render", str(source), "--out", str(out)) == 1
    assert files_under(out) == written and written[0].read_bytes() == first


def test_convert_and_render_give_same_markdown(tmp_path: Path) -> None:
    tool, path = source_fixtures()[0]
    json_path, md_path = convert_file(tool, path, tmp_path / "a")
    assert cli("render", str(json_path), "--out", str(tmp_path / "b")) == 0
    assert (tmp_path / "b" / md_path.name).read_bytes() == md_path.read_bytes()


def test_sheet_json_is_strict_json_utf8_lf(tmp_path: Path) -> None:
    for tool, path in source_fixtures():
        json_path, _ = convert_file(tool, path, tmp_path / tool)
        raw = json_path.read_bytes()
        assert b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf")
        assert not re.search(r"\bNaN\b|\bInfinity\b", raw.decode("utf-8"))
        assert copy.deepcopy(json.loads(raw))["diagsheet"] == 1
