# GUI に出す文字を作る関数だけを置く(tkinter は使わない): 件数の欄、一覧の行、詳細の文、欄のパス。
# 値を比べたり判定を決めたりはしない。区分と値・判定の書き方は model と render_md の関数を使う。
# 値が無い欄は「—」と書く。0・空文字・ほかの値では埋めない(INV-1)。

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from diagsheet.io_safe import SHEET_MD_SUFFIX, sheet_stem
from diagsheet.model import CATEGORY_ORDER, CONFIDENCE_WORDS, TOOL_TAGS, display_words
from diagsheet.render_md import group_items, scalar_text, summary_lines, value_text, verdict_text

NO_VALUE: Final = "—"
# 一覧の列(鍵, 見出し)。順はこのまま画面に出す。
COLUMNS: Final = (
    ("state", "状態"),
    ("name", "項目"),
    ("value", "値"),
    ("confidence", "確度"),
    ("verdict", "ツールの判定"),
    ("basis", "理由・根拠"),
    ("note", "注記"),
)
MAX_ALERT_LINES: Final = 12


@dataclass(frozen=True)
class Row:
    """一覧の1行。item_id で元の項目を引ける。"""

    item_id: str
    state: str
    name: str
    value: str
    confidence: str
    verdict: str
    basis: str
    note: str

    def cells(self) -> tuple[str, ...]:
        return tuple(str(getattr(self, key)) for key, _ in COLUMNS)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _or_dash(text: str) -> str:
    return text if text else NO_VALUE


def state_mark(word: str) -> str:
    """状態は色ではなく、[異常] のような文字の印で示す(D-12)。"""
    return f"[{word}]"


def tool_label(tool: str) -> str:
    return f"{TOOL_TAGS[tool]}({tool})"


def tool_choices(tools: Iterable[str]) -> list[tuple[str, str]]:
    """選べるツールの (CLI の名前, 画面に出す名前)。"""
    return [(tool, tool_label(tool)) for tool in tools]


def version_or_none(text: str) -> str | None:
    """版の欄が空なら「付けない」(CLI で --tool-version を付けないのと同じ)。"""
    return text if text else None


def count_cells(counts: Mapping[str, Any] | None, bad_word: str) -> list[str]:
    """7語を決まった順で並べる。0件の語も出す。シートが無いときは件数を「—」にする(0 にしない)。"""
    words = display_words(bad_word)
    return [
        f"{state_mark(words[category])} "
        + (NO_VALUE if counts is None else f"{counts[category]}件")
        for category in CATEGORY_ORDER
    ]


def _confidence_text(item: Mapping[str, Any]) -> str:
    confidence = item.get("confidence")
    return CONFIDENCE_WORDS[confidence] if isinstance(confidence, str) else NO_VALUE


def _verdict_cell(item: Mapping[str, Any]) -> str:
    return verdict_text(item) if item.get("verdict_label") is not None else NO_VALUE


def _basis(item: Mapping[str, Any]) -> str:
    """値が無い項目は理由、値がある項目は根拠。どちらも無ければ空。"""
    reason = scalar_text(item.get("reason"))
    return reason if reason else scalar_text(item.get("evidence"))


def item_rows(sheet: Mapping[str, Any], bad_word: str) -> list[Row]:
    """検査を通ったシートから一覧の行を作る。並びは Markdown の節と同じ(7語の順)。"""
    words = display_words(bad_word)
    rows: list[Row] = []
    for category, items in group_items(list(sheet["items"])).items():
        for item in items:
            rows.append(
                Row(
                    item_id=str(item["id"]),
                    state=state_mark(words[category]),
                    name=_one_line(str(item["name"])),
                    value=_or_dash(_one_line(value_text(item))),
                    confidence=_confidence_text(item),
                    verdict=_or_dash(_one_line(_verdict_cell(item))),
                    basis=_or_dash(_one_line(_basis(item))),
                    note=_or_dash(_one_line(scalar_text(item.get("note")))),
                )
            )
    return rows


def detail_lines(item: Mapping[str, Any], row: Row) -> list[str]:
    """選んだ項目の全部の欄。無い欄も「—」と書いて出す。"""
    return [
        f"{row.state} {item['name']}",
        f"値: {_or_dash(value_text(item))} / 確度: {row.confidence} / ツールの判定: {row.verdict}",
        f"理由: {_or_dash(scalar_text(item.get('reason')))}",
        f"根拠: {_or_dash(scalar_text(item.get('evidence')))}",
        f"注記: {_or_dash(scalar_text(item.get('note')))}",
        f"対処: {_or_dash(scalar_text(item.get('action')))}",
        f"元の場所: {item['from']}(id: {item['id']})",
    ]


def info_lines(sheet: Mapping[str, Any], shown_path: str) -> list[str]:
    """シートの情報の欄。2行目からは Markdown の題名の下と同じ文。"""
    return [f"表示中: {shown_path}", *summary_lines(sheet)]


def alert_text(lines: list[str], exit_code: int) -> str:
    """エラーの窓に出す文。行が多いときは先頭だけを出し、要約(最後の行)は必ず出す。"""
    body = lines
    if len(lines) > MAX_ALERT_LINES:
        hidden = len(lines) - MAX_ALERT_LINES
        more = f"(ほか {hidden}行は詳細の欄に出している)"
        body = [*lines[: MAX_ALERT_LINES - 1], more, lines[-1]]
    return "\n".join([*body, "", f"終了コード {exit_code}"])


def status_text(lines: list[str], exit_code: int) -> str:
    """ステータスバーに出す1行。エラーの要約(最後の行)と終了コード。"""
    return f"{_one_line(lines[-1])}(終了コード {exit_code})"


def markdown_beside(sheet_path: Path) -> Path:
    """シートの JSON と同じフォルダにあるはずの Markdown の名前。あるかどうかは見ない。"""
    return sheet_path.with_name(sheet_stem(sheet_path.name) + SHEET_MD_SUFFIX)


def clean_path_text(text: str) -> str:
    """欄に貼ったパスの前後の空白と、「パスのコピー」が付ける二重引用符を取る。"""
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] == '"':
        stripped = stripped[1:-1].strip()
    return stripped


def start_dir(text: str, fallback: Path) -> str:
    """参照の窓を最初に開く場所。欄のパス(またはその親)が実在すればそこ、無ければ fallback。"""
    if text:
        path = Path(text)
        for candidate in (path, path.parent):
            if candidate.is_dir():
                return str(candidate)
    return str(fallback) if fallback.is_dir() else ""
