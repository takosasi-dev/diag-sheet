# テストが共通に使う小さな道具: 合成 fixture の一覧、JSON の読み書き、変換して結果を読む関数、
# Markdown から1つの節だけを取り出す関数。出力先はどれも pytest の一時フォルダの中にする。

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from diagsheet.__main__ import convert_file, main

FIXTURES = Path(__file__).parent / "fixtures"
# 出力に出てはいけない合成の値(プロセス名・ディスク名・公開 IP・SSID など。D-11)。
SECRETS = (
    "SYNTH-DISK-NAME",
    "SYNTH-PROCESS-NAME",
    "SYNTH-DRIVER-NAME",
    "SYNTH-PAGEFILE-NAME",
    "SYNTH-POWER-PLAN",
    "SYNTH-EVENT-DETAIL",
    "SYNTH-SSID",
    "SYNTH-ISP",
    "SYNTH-CITY",
    "SYNTH-ALIAS",
    "SYNTH-ADAPTER",
    "203.0.113.7",
    "203.0.113.20",
    "192.0.2.1",
    "2001:db8::",
)


def source_fixtures() -> list[tuple[str, Path]]:
    return [
        (tool, path)
        for tool in ("stutter", "netdiag")
        for path in sorted((FIXTURES / tool).glob("*.json"))
    ]


def sheet_fixtures() -> list[Path]:
    return sorted((FIXTURES / "sheets").glob("*.sheet.json"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return path


def convert_data(
    tool: str, data: Any, tmp_path: Path, *, name: str = "source.json", version: str | None = None
) -> tuple[dict[str, Any], str]:
    """合成の元データを一時フォルダで変換し、(シート, Markdown) を返す。"""
    source = write_json(tmp_path / "src" / name, data)
    json_path, md_path = convert_file(tool, source, tmp_path / "out", version)
    return read_json(json_path), md_path.read_text(encoding="utf-8")


def cli(*args: str) -> int:
    return main(list(args))


def files_under(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*") if p.is_file()) if path.exists() else []


def item(sheet: dict[str, Any], item_id: str) -> dict[str, Any]:
    found = [i for i in sheet["items"] if i["id"] == item_id]
    assert len(found) == 1, f"{item_id} が {len(found)} 件"
    return found[0]


def section(markdown: str, word: str) -> str:
    """`## [word]` の見出しから次の見出し(または末尾の区切り)までを返す。"""
    lines = markdown.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"## [{word}] "))
    rest = range(start + 1, len(lines))
    end = next((i for i in rest if lines[i].startswith("## ") or lines[i] == "---"), len(lines))
    return "\n".join(lines[start:end])
