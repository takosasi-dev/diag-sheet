# 検査を通ったシート(dict)から §9.6 の Markdown を作る。件数表と7つの節を固定の順で必ず出す。
# 0件の節は「なし」と書く。状態は [異常] のような文字の印で示し、色と絵文字は使わない。
# ここでは値を比べない。区分は model.category_of が (status, verdict) から決めた物だけを使う。

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from diagsheet.model import (
    CATEGORY_ORDER,
    CONFIDENCE_WORDS,
    TOOL_TAGS,
    category_of,
    display_words,
)

FOOTER_LINE = "判定はすべて元のツールが結果ファイルに書いた物。DiagSheet は判定を足していない。"
_JUDGED = ("bad", "warn", "ok")
_NO_VALUE = ("failed", "unchecked", "not_applicable")
_WORD = r"0-9A-Za-z぀-ヿ㐀-鿿_"
_PLAIN_YAML = re.compile(rf"[{_WORD}][{_WORD} .()/-]*")


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _yaml_scalar(text: str) -> str:
    """frontmatter の値。素のまま書けない文字があれば二重引用符で囲む。"""
    if _PLAIN_YAML.fullmatch(text) and not text.endswith(" "):
        return text
    return json.dumps(text, ensure_ascii=False)


def _cell(text: str) -> str:
    """表のセル。バックスラッシュ・縦棒・改行をエスケープする。"""
    escaped = text.replace("\\", "\\\\").replace("|", "\\|")
    return re.sub(r"\r\n|\r|\n", "<br>", escaped)


def _scalar_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _value_text(item: Mapping[str, Any]) -> str:
    text = _scalar_text(item.get("value"))
    unit = item.get("unit")
    return f"{text} {unit}" if text and isinstance(unit, str) and unit else text


def _verdict_text(item: Mapping[str, Any]) -> str:
    label = _scalar_text(item.get("verdict_label"))
    raw = _scalar_text(item.get("verdict_raw"))
    return label if label == raw else f"{label}({raw})"


def _moment(text: str, fmt: str) -> tuple[str, bool]:
    """ISO 8601 の日時を fmt に直す。直せなければ元の文字列と False を返す。"""
    try:
        return datetime.fromisoformat(text).strftime(fmt), True
    except ValueError:
        return _one_line(text), False


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return lines


def _section(category: str, word: str, items: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = [f"## [{word}] {len(items)}件"]
    if not items:
        return [*lines, "なし"]
    if category in _NO_VALUE:
        rows = [[str(i["name"]), _scalar_text(i.get("reason")), str(i["from"])] for i in items]
        return lines + _table(("項目", "理由", "元の場所"), rows)
    if category in _JUDGED:
        rows = [
            [
                str(i["name"]),
                _value_text(i),
                CONFIDENCE_WORDS[i["confidence"]],
                _verdict_text(i),
                _scalar_text(i.get("evidence")),
            ]
            for i in items
        ]
        return lines + _table(("項目", "値", "確度", "ツールの判定", "根拠"), rows)
    rows = [[str(i["name"]), _value_text(i), CONFIDENCE_WORDS[i["confidence"]]] for i in items]
    return lines + _table(("項目", "値", "確度"), rows)


def _overall_line(overall: Mapping[str, Any]) -> str:
    head = str(overall["value"])
    if overall.get("score") is not None:
        head += f" / {_scalar_text(overall['score'])} 点"
    excluded = "、".join(str(name) for name in overall["excluded"]) or "なし"
    used = f"{overall['used']}/{overall['total']}"
    return f"- 総合(ツールの採点): {head}(採点に使った項目 {used}。外れた項目: {excluded})"


def render(sheet: Mapping[str, Any], bad_word: str) -> str:
    """シートを Markdown にする。sheet は check_sheet で違反なしを確かめた物を渡す。"""
    words = display_words(bad_word)
    items: list[Mapping[str, Any]] = list(sheet["items"])
    grouped: dict[str, list[Mapping[str, Any]]] = {category: [] for category in CATEGORY_ORDER}
    for item in items:
        category = category_of(item["status"], item["verdict"])
        if category is None:
            raise ValueError(f"区分を決められない項目: {item.get('id')}")
        grouped[category].append(item)

    run = sheet["run"]
    source = sheet["source"]
    tool = str(sheet["tool"])
    title = _one_line(f"診断シート {run['subject']} {run['label']}")
    measured, measured_ok = _moment(str(run["measured_at"]), "%Y-%m-%d %H:%M:%S")
    created, _ = _moment(str(sheet["created_at"]), "%Y-%m-%d %H:%M")
    version = "不明" if sheet["tool_version"] is None else _one_line(str(sheet["tool_version"]))
    conditions = " / ".join(
        f"{key} {_one_line(_scalar_text(value))}" for key, value in run["conditions"].items()
    )

    lines = [
        "---",
        f"title: {_yaml_scalar(title)}",
        f"created: {created}",
        f"measured: {measured if measured_ok else _yaml_scalar(measured)}",
        "tags:",
        "  - 診断シート",
        f"  - {TOOL_TAGS[tool]}",
        f"diagsheet: {sheet['diagsheet']}",
        "---",
        f"# {title}",
        "",
        f"- 計測日時: {measured}",
        f"- ツール: {tool} 版 {version}(出所: {sheet['tool_version_from']})"
        f" / アダプタ {sheet['adapter_version']} / 形の版 {sheet['diagsheet']}",
        f"- 元ファイル: {_one_line(str(source['file']))}"
        f"(SHA-256 先頭12桁 {str(source['sha256'])[:12]})",
        f"- 条件: {conditions or 'なし'}",
    ]
    overall = sheet.get("overall")
    if overall is not None:
        lines.append(_overall_line(overall))
    lines += [
        "",
        "| " + " | ".join(words[category] for category in CATEGORY_ORDER) + " |",
        "|" + "---|" * len(CATEGORY_ORDER),
        "| " + " | ".join(str(len(grouped[category])) for category in CATEGORY_ORDER) + " |",
        "",
    ]
    for category in CATEGORY_ORDER:
        lines += _section(category, words[category], grouped[category])

    lines += ["", "---", f"- {FOOTER_LINE}"]
    if overall is not None and overall.get("note"):
        lines.append(f"- 注記(総合): {_one_line(str(overall['note']))}")
    lines += [
        f"- 注記({_one_line(str(item['name']))}): {_one_line(str(item['note']))}"
        for item in items
        if item.get("note")
    ]
    return "\n".join(lines) + "\n"
