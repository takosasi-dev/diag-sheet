# GUI に出す文字を作る関数(gui_rows)のテスト。tkinter は使わない。
# 7語が決まった順で0件も出ること、値が無い欄が「—」になり 0 や空文字で埋まらないことを見る。

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from diagsheet.__main__ import ADAPTERS, convert_file, load_checked_sheet
from diagsheet.gui_rows import (
    COLUMNS,
    MAX_ALERT_LINES,
    NO_VALUE,
    alert_text,
    clean_path_text,
    count_cells,
    detail_lines,
    info_lines,
    item_rows,
    markdown_beside,
    start_dir,
    status_text,
    tool_choices,
    version_or_none,
)
from diagsheet.model import CATEGORY_ORDER, display_words, load_bad_word
from diagsheet.render_md import render
from tests.helpers import FIXTURES, read_json, section, source_fixtures

BAD_WORD = load_bad_word()
WORDS = [display_words(BAD_WORD)[category] for category in CATEGORY_ORDER]
FORBIDDEN = ("問題なし", "合格", "大丈夫")


@pytest.fixture
def sheet() -> dict[str, Any]:
    data: dict[str, Any] = read_json(FIXTURES / "sheets" / "all_states.sheet.json")
    return data


def test_tool_choices_use_the_cli_names_with_japanese_labels() -> None:
    assert tool_choices(ADAPTERS) == [
        ("stutter", "PC遅延診断(stutter)"),
        ("netdiag", "回線診断(netdiag)"),
    ]


def test_count_cells_show_the_seven_words_in_order_including_zero(sheet: dict[str, Any]) -> None:
    assert WORDS == ["異常", "注意", "測れなかった", "未チェック", "対象外", "正常", "判定なし"]
    cells = count_cells(sheet["counts"], BAD_WORD)
    assert cells == [
        "[異常] 1件",
        "[注意] 1件",
        "[測れなかった] 1件",
        "[未チェック] 1件",
        "[対象外] 1件",
        "[正常] 1件",
        "[判定なし] 2件",
    ]
    zero = count_cells(dict.fromkeys(CATEGORY_ORDER, 0), BAD_WORD)
    assert zero == [f"[{word}] 0件" for word in WORDS]


def test_count_cells_without_a_sheet_show_a_dash_not_zero() -> None:
    cells = count_cells(None, BAD_WORD)
    assert cells == [f"[{word}] {NO_VALUE}" for word in WORDS]
    assert not any("0" in cell for cell in cells)


def test_count_cells_follow_the_bad_word_of_the_mapping() -> None:
    assert count_cells(None, "要確認")[0] == f"[要確認] {NO_VALUE}"


def test_rows_are_grouped_in_the_order_of_the_seven_words(sheet: dict[str, Any]) -> None:
    rows = item_rows(sheet, BAD_WORD)
    assert len(rows) == len(sheet["items"])
    assert [row.state for row in rows] == [
        "[異常]",
        "[注意]",
        "[測れなかった]",
        "[未チェック]",
        "[対象外]",
        "[正常]",
        "[判定なし]",
        "[判定なし]",
    ]
    assert all(len(row.cells()) == len(COLUMNS) for row in rows)
    assert sorted(row.item_id for row in rows) == sorted(item["id"] for item in sheet["items"])


def test_rows_without_a_value_show_a_dash_and_the_reason(sheet: dict[str, Any]) -> None:
    rows = {row.item_id: row for row in item_rows(sheet, BAD_WORD)}
    for item_id in ("synthetic.failed", "synthetic.unchecked", "synthetic.not_applicable"):
        row = rows[item_id]
        assert (row.value, row.confidence, row.verdict) == (NO_VALUE, NO_VALUE, NO_VALUE)
        assert row.basis not in ("", NO_VALUE)
    # 理由の改行は、一覧では1行にする(詳細の欄には元のまま出す)。
    assert rows["synthetic.failed"].basis == "合成の理由 2行目"


def test_rows_with_a_value_use_the_same_text_as_the_markdown(sheet: dict[str, Any]) -> None:
    rows = {row.item_id: row for row in item_rows(sheet, BAD_WORD)}
    warn = rows["synthetic.warn"]
    assert (warn.value, warn.confidence, warn.verdict) == ("12.5 ms", "実測", "注意(medium)")
    assert warn.basis == NO_VALUE and warn.note == NO_VALUE
    bad = rows["synthetic.bad"]
    assert (bad.value, bad.basis, bad.note) == (NO_VALUE, "合成の根拠 | 縦棒つき", "合成の注記")
    # 値が false の項目は false と出す(値が無いのとは別)。
    assert rows["synthetic.ok"].value == "false"
    markdown = render(sheet, BAD_WORD)
    assert "| 合成の項目(注意) | 12.5 ms | 実測 | 注意(medium) |" in section(markdown, "注意")


@pytest.mark.parametrize(("tool", "source"), source_fixtures(), ids=lambda v: getattr(v, "stem", v))
def test_rows_of_converted_fixtures_never_invent_a_value(
    tool: str, source: Path, tmp_path: Path
) -> None:
    json_path, _ = convert_file(tool, source, tmp_path / "out")
    sheet = load_checked_sheet(json_path)
    rows = {row.item_id: row for row in item_rows(sheet, BAD_WORD)}
    assert len(rows) == len(sheet["items"]) == sum(sheet["counts"].values())
    for item in sheet["items"]:
        row = rows[item["id"]]
        if item["value"] is None:
            assert row.value == NO_VALUE, item["id"]
        if item["status"] != "measured":
            assert (row.confidence, row.verdict) == (NO_VALUE, NO_VALUE), item["id"]
            assert row.state in ("[測れなかった]", "[未チェック]", "[対象外]"), item["id"]
            assert row.basis == " ".join(item["reason"].split()), item["id"]
        lines = detail_lines(item, row)
        assert lines[0].startswith(row.state) and len(lines) == 7


def test_detail_lines_show_every_field_and_a_dash_for_missing_ones(sheet: dict[str, Any]) -> None:
    rows = {row.item_id: row for row in item_rows(sheet, BAD_WORD)}
    items = {item["id"]: item for item in sheet["items"]}
    bad = detail_lines(items["synthetic.bad"], rows["synthetic.bad"])
    assert bad == [
        "[異常] 合成の項目(異常)",
        "値: — / 確度: 実測 / ツールの判定: 要対処(high)",
        "理由: —",
        "根拠: 合成の根拠 | 縦棒つき",
        "注記: 合成の注記",
        "対処: 合成の対処",
        "元の場所: synthetic[0](id: synthetic.bad)",
    ]
    failed = detail_lines(items["synthetic.failed"], rows["synthetic.failed"])
    assert failed[1] == "値: — / 確度: — / ツールの判定: —"
    assert failed[2] == "理由: 合成の理由\n2行目"


def test_info_lines_are_the_markdown_summary_lines(sheet: dict[str, Any]) -> None:
    lines = info_lines(sheet, "D:\\demo\\out\\sample.sheet.json")
    assert lines[0] == "表示中: D:\\demo\\out\\sample.sheet.json"
    markdown = render(sheet, BAD_WORD).splitlines()
    assert all(f"- {line}" in markdown for line in lines[1:])
    assert lines[1].startswith("計測日時: ") and lines[2].startswith("ツール: padlab 版 ")


def test_no_forbidden_words_are_added_by_the_gui_text() -> None:
    texts = [*count_cells(None, BAD_WORD), *(heading for _, heading in COLUMNS)]
    texts += [status_text(["diagsheet: x"], 1), alert_text(["diagsheet: x"], 1)]
    assert not any(word in text for word in FORBIDDEN for text in texts)


def test_alert_text_keeps_the_summary_and_the_exit_code() -> None:
    short = alert_text(["a", "diagsheet: 要約"], 3)
    assert short == "a\ndiagsheet: 要約\n\n終了コード 3"
    many = [f"違反 {n}" for n in range(30)] + ["diagsheet: 要約"]
    long = alert_text(many, 3).splitlines()
    assert long[0] == "違反 0" and long[MAX_ALERT_LINES - 1].startswith("(ほか 19行")
    assert long[MAX_ALERT_LINES] == "diagsheet: 要約" and long[-1] == "終了コード 3"
    assert status_text(many, 3) == "diagsheet: 要約(終了コード 3)"


def test_path_text_helpers(tmp_path: Path) -> None:
    pasted = '  "D:\\demo\\results\\sample.json"  '
    assert clean_path_text(pasted) == "D:\\demo\\results\\sample.json"
    assert clean_path_text("D:\\demo\\out") == "D:\\demo\\out"
    assert clean_path_text("   ") == "" and clean_path_text('"') == '"'
    assert version_or_none("") is None and version_or_none("v1.0.0") == "v1.0.0"
    assert version_or_none(" ") == " "
    sheet_path = Path("D:\\demo\\out\\sample.sheet.json")
    assert markdown_beside(sheet_path) == Path("D:\\demo\\out\\sample.sheet.md")
    assert markdown_beside(Path("x") / "other.json") == Path("x") / "other.sheet.md"
    file_path = tmp_path / "a.json"
    file_path.write_text("{}", encoding="utf-8")
    assert start_dir(str(file_path), tmp_path / "none") == str(tmp_path)
    assert start_dir(str(tmp_path), tmp_path / "none") == str(tmp_path)
    assert start_dir("", tmp_path) == str(tmp_path)
    assert start_dir(str(tmp_path / "no" / "x.json"), tmp_path / "none") == ""
