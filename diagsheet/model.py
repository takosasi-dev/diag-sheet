# シートの型と、状態の表示7語・確度4区分の定義を持つ。表示語は (status, verdict) から一意に決まる。
# bad の表示語と対応表は mappings/ の JSON から読む(読むだけ。コードに判定の閾値は置かない)。
# 終了コードつきの例外もここに置く(CLI・アダプタ・入出力が共通に使うため)。

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

SHAPE_VERSION: Final = 1
MAPPINGS_DIR: Final = Path(__file__).resolve().parent / "mappings"

EXIT_OK: Final = 0
EXIT_IO: Final = 1
EXIT_SHAPE: Final = 2
EXIT_CHECK: Final = 3
EXIT_OUT_DIR: Final = 4

STATUSES: Final = ("measured", "failed", "unchecked", "not_applicable")
VERDICTS: Final = ("ok", "warn", "bad", "none")
JUDGED_VERDICTS: Final = ("ok", "warn", "bad")
CONFIDENCE_WORDS: Final = {
    "measured": "実測",
    "reference": "参考値",
    "estimated": "推定",
    "reported": "申告",
}
TOOLS: Final = ("stutter", "netdiag", "padlab")
TOOL_TAGS: Final = {"stutter": "PC遅延診断", "netdiag": "回線診断", "padlab": "PadLab"}
VERSION_SOURCES: Final = ("元ファイル", "指定", "不明")

# 件数表と Markdown の節の順(§9.3)。measured は verdict、それ以外は status がそのまま区分になる。
CATEGORY_ORDER: Final = ("bad", "warn", "failed", "unchecked", "not_applicable", "ok", "none")
_FIXED_WORDS: Final = {
    "warn": "注意",
    "failed": "測れなかった",
    "unchecked": "未チェック",
    "not_applicable": "対象外",
    "ok": "正常",
    "none": "判定なし",
}
BAD_WORD_CHOICES: Final = ("異常", "要対処", "要確認")

Scalar = str | int | float | bool | None


class DiagSheetError(Exception):
    """終了コードを持つエラー。CLI がそのまま終了コードにする。"""

    exit_code = EXIT_IO


class InputError(DiagSheetError):
    """引数・入出力のエラー(読めない JSON、同名ファイルあり、版の食い違い)。"""

    exit_code = EXIT_IO


class ShapeError(DiagSheetError):
    """知らない形・対応表に無い判定の値(INV-9・INV-2)。"""

    exit_code = EXIT_SHAPE


class CheckError(DiagSheetError):
    """シートの形の違反・知らない形の版。"""

    exit_code = EXIT_CHECK

    def __init__(self, violations: list[str]) -> None:
        super().__init__("\n".join(violations))
        self.violations = violations


class OutDirError(DiagSheetError):
    """出力先が診断ツールのフォルダの中(FR-18)。"""

    exit_code = EXIT_OUT_DIR


def category_of(status: object, verdict: object) -> str | None:
    """(status, verdict) から区分を1つ決める。決められない組み合わせは None。"""
    if status == "measured":
        return verdict if isinstance(verdict, str) and verdict in VERDICTS else None
    if isinstance(status, str) and status in STATUSES and verdict is None:
        return status
    return None


def count_items(items: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(CATEGORY_ORDER, 0)
    for item in items:
        category = category_of(item.get("status"), item.get("verdict"))
        if category is not None:
            counts[category] += 1
    return counts


def read_mapping(name: str, mappings_dir: Path | None = None) -> dict[str, Any]:
    """mappings/ の JSON を読み取り専用で読む。壊れていれば InputError。"""
    path = (mappings_dir or MAPPINGS_DIR) / name
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise InputError(f"対応表を読めない: {path}({exc})") from exc
    if not isinstance(data, dict):
        raise InputError(f"対応表が JSON のオブジェクトでない: {path}")
    return data


def load_bad_word(mappings_dir: Path | None = None) -> str:
    """bad の表示語(§8.5 の最終行)を verdict_map.json から読む。"""
    word = read_mapping("verdict_map.json", mappings_dir).get("bad_word")
    if word not in BAD_WORD_CHOICES:
        choices = " / ".join(BAD_WORD_CHOICES)
        raise InputError(f"verdict_map.json の bad_word が {word!r}。選べるのは {choices}")
    return str(word)


def display_words(bad_word: str) -> dict[str, str]:
    """区分 → 表示語(7語)。順は CATEGORY_ORDER。"""
    words = {"bad": bad_word, **_FIXED_WORDS}
    return {category: words[category] for category in CATEGORY_ORDER}


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    status: str
    origin: str
    unit: str | None = None
    value: Scalar = None
    confidence: str | None = None
    verdict: str | None = None
    verdict_raw: Scalar = None
    verdict_label: str | None = None
    reason: str | None = None
    evidence: str | None = None
    note: str | None = None
    action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "unit": self.unit,
            "status": self.status,
            "value": self.value,
            "confidence": self.confidence,
            "verdict": self.verdict,
            "verdict_raw": self.verdict_raw,
            "verdict_label": self.verdict_label,
            "reason": self.reason,
            "evidence": self.evidence,
            "note": self.note,
            "action": self.action,
            "from": self.origin,
        }


@dataclass(frozen=True)
class Source:
    file: str
    sha256: str
    shape: str


@dataclass(frozen=True)
class Run:
    label: str
    measured_at: str
    subject: str
    conditions: dict[str, Scalar] = field(default_factory=dict)


@dataclass(frozen=True)
class Overall:
    value: str
    score: int | float | None
    used: int
    total: int
    excluded: list[str]
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "score": self.score,
            "used": self.used,
            "total": self.total,
            "excluded": list(self.excluded),
            "note": self.note,
        }


@dataclass(frozen=True)
class Sheet:
    tool: str
    tool_version: str | None
    adapter_version: str
    created_at: str
    source: Source
    run: Run
    items: list[Item]
    overall: Overall | None = None

    def to_dict(self) -> dict[str, Any]:
        items = [item.to_dict() for item in self.items]
        return {
            "diagsheet": SHAPE_VERSION,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "tool_version_from": "不明" if self.tool_version is None else "指定",
            "adapter_version": self.adapter_version,
            "created_at": self.created_at,
            "source": {
                "file": self.source.file,
                "sha256": self.source.sha256,
                "shape": self.source.shape,
            },
            "run": {
                "label": self.run.label,
                "measured_at": self.run.measured_at,
                "subject": self.run.subject,
                "conditions": dict(self.run.conditions),
            },
            "overall": None if self.overall is None else self.overall.to_dict(),
            "counts": count_items(items),
            "items": items,
        }
