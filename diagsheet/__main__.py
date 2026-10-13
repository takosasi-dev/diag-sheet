# CLI(§9.1)。convert・render・check・--selftest を受け、終了コード 0〜4 を返す。
# 流れは「出力先の確認 → 読む → 写す → 検査 → 書き出す」。途中で止まれば出力を1つも残さない。
# 引数の誤りは argparse の既定の 2 ではなく 1 で終える(2 は「知らない形」に使うため)。

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn, Protocol

from diagsheet import __version__
from diagsheet.adapters import netdiag, stutter
from diagsheet.check import check_sheet
from diagsheet.io_safe import (
    SHEET_JSON_SUFFIX,
    SHEET_MD_SUFFIX,
    ensure_outside_tool_dirs,
    load_tool_dirs,
    parse_json,
    read_bytes,
    safe_name,
    sha256_hex,
    sheet_stem,
    write_files,
)
from diagsheet.model import (
    CATEGORY_ORDER,
    EXIT_CHECK,
    EXIT_IO,
    EXIT_OK,
    TOOLS,
    CheckError,
    DiagSheetError,
    InputError,
    Item,
    Run,
    Sheet,
    Source,
    display_words,
    load_bad_word,
)
from diagsheet.render_md import render


class Adapter(Protocol):
    def __call__(
        self,
        source: object,
        *,
        source_file: str,
        source_sha256: str,
        tool_version: str | None,
        created_at: str,
        mappings_dir: Path | None = None,
    ) -> Sheet: ...


ADAPTERS: dict[str, Adapter] = {"stutter": stutter.convert, "netdiag": netdiag.convert}
SYNTHETIC: dict[str, Callable[[], dict[str, Any]]] = {
    "stutter": stutter.synthetic_source,
    "netdiag": netdiag.synthetic_source,
}
# まだ無いアダプタと、その理由。
PENDING = {"padlab": "PadLab の保存形式に合わせた項目表が未確定(仕様書 §8.3・Phase 4 の確認待ち)"}


class _ArgError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _ArgError(f"{self.format_usage()}diagsheet: 引数の誤り: {message}")


def default_out_dir() -> Path:
    """既定の出力先。パッケージの1つ上(リポジトリ直下)の out フォルダ。"""
    return Path(__file__).resolve().parent.parent / "out"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def dump_sheet(sheet: Mapping[str, Any]) -> str:
    return json.dumps(sheet, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _guard_out_dir(
    out_dir: Path, tool_dirs: Sequence[str] | None, mappings_dir: Path | None
) -> None:
    dirs = load_tool_dirs(mappings_dir) if tool_dirs is None else tool_dirs
    ensure_outside_tool_dirs(out_dir, dirs)


def convert_file(
    tool: str,
    source_path: Path,
    out_dir: Path,
    tool_version: str | None = None,
    *,
    mappings_dir: Path | None = None,
    tool_dirs: Sequence[str] | None = None,
) -> list[Path]:
    """元 JSON を1件変換して .sheet.json と .sheet.md を書く。書いたパスを返す。"""
    _guard_out_dir(out_dir, tool_dirs, mappings_dir)
    if tool in PENDING:
        raise InputError(f"--tool {tool} のアダプタはまだ無い(実物待ち): {PENDING[tool]}")
    if tool not in ADAPTERS:
        raise InputError(f"知らないツール: {tool}")
    if tool_version is not None and not tool_version.strip():
        raise InputError("--tool-version が空。分からないときは付けない(版は「不明」と記録する)")

    raw = read_bytes(source_path)
    data = parse_json(raw, source_path.name)
    sheet = ADAPTERS[tool](
        data,
        source_file=source_path.name,
        source_sha256=sha256_hex(raw),
        tool_version=tool_version,
        created_at=now_iso(),
        mappings_dir=mappings_dir,
    ).to_dict()
    violations = check_sheet(sheet)
    if violations:
        raise CheckError(violations)
    stem = safe_name(source_path.stem)
    files = [
        (stem + SHEET_JSON_SUFFIX, dump_sheet(sheet)),
        (stem + SHEET_MD_SUFFIX, render(sheet, load_bad_word(mappings_dir))),
    ]
    return write_files(out_dir, files)


def load_checked_sheet(sheet_path: Path) -> dict[str, Any]:
    """シートの JSON を読み、違反があれば CheckError にする。"""
    sheet = parse_json(read_bytes(sheet_path), sheet_path.name)
    violations = check_sheet(sheet)
    if violations or not isinstance(sheet, dict):
        raise CheckError(violations or ["シートが JSON のオブジェクトでない"])
    return sheet


def render_file(
    sheet_path: Path,
    out_dir: Path,
    *,
    mappings_dir: Path | None = None,
    tool_dirs: Sequence[str] | None = None,
) -> list[Path]:
    """シートの JSON から Markdown だけを作り直す。"""
    _guard_out_dir(out_dir, tool_dirs, mappings_dir)
    sheet = load_checked_sheet(sheet_path)
    name = sheet_stem(sheet_path.name) + SHEET_MD_SUFFIX
    return write_files(out_dir, [(name, render(sheet, load_bad_word(mappings_dir)))])


def heading_problems(markdown: str, bad_word: str) -> list[str]:
    """Markdown に7つの見出しが決まった順でちょうど1回ずつあるかを見る。"""
    words = display_words(bad_word)
    expected = [f"## [{words[category]}] " for category in CATEGORY_ORDER]
    found = [line for line in markdown.splitlines() if line.startswith("## ")]
    if len(found) != len(expected) or any(
        not line.startswith(head) for line, head in zip(found, expected, strict=False)
    ):
        return [f"見出しが7語の順になっていない: {found}"]
    return []


def _synthetic_sheet() -> dict[str, Any]:
    """7つの区分を1件ずつ持つ合成シート。値はすべて作り物。"""
    judged = {"confidence": "measured", "evidence": "合成の根拠"}
    items = [
        Item("synthetic.bad", "合成(異常)", "measured", "合成", verdict="bad",
             verdict_raw="x", verdict_label="合成の語", **judged),
        Item("synthetic.warn", "合成(注意)", "measured", "合成", verdict="warn",
             verdict_raw="y", verdict_label="合成の語", **judged),
        Item("synthetic.failed", "合成(測れなかった)", "failed", "合成", reason="合成の理由"),
        Item("synthetic.unchecked", "合成(未チェック)", "unchecked", "合成", reason="合成の理由"),
        Item("synthetic.na", "合成(対象外)", "not_applicable", "合成", reason="合成の理由"),
        Item("synthetic.ok", "合成(正常)", "measured", "合成", verdict="ok",
             verdict_raw="z", verdict_label="合成の語", **judged),
        Item("synthetic.none", "合成(判定なし)", "measured", "合成", value=1,
             confidence="reference", verdict="none"),
    ]
    return Sheet(
        tool="padlab",
        tool_version=None,
        adapter_version=__version__,
        created_at="2026-01-02T03:04:05+09:00",
        source=Source(file="synthetic.json", sha256="0" * 64, shape="synthetic"),
        run=Run(label="selftest", measured_at="2026-01-02T03:04:05", subject="合成"),
        items=items,
    ).to_dict()


def _selftest_sheet(bad_word: str) -> list[str]:
    sheet = _synthetic_sheet()
    problems = [f"合成シートに違反: {line}" for line in check_sheet(sheet)]
    if any(count != 1 for count in sheet["counts"].values()):
        problems.append(f"合成シートの件数が区分ごとに1件でない: {sheet['counts']}")
    problems += heading_problems(render(sheet, bad_word), bad_word)
    broken = json.loads(json.dumps(sheet))
    broken["items"][2]["value"] = 0
    if not check_sheet(broken):
        problems.append("failed の項目に value を入れたシートが check を通ってしまう")
    return problems


def _selftest_adapter(tool: str, work: Path, bad_word: str) -> list[str]:
    source_path = work / f"selftest_{tool}.json"
    source_text = json.dumps(SYNTHETIC[tool](), ensure_ascii=False, indent=2)
    source_path.write_text(source_text, encoding="utf-8", newline="\n")
    before = read_bytes(source_path)
    out_dir = work / f"out_{tool}"
    json_path, md_path = convert_file(tool, source_path, out_dir)
    sheet = load_checked_sheet(json_path)
    markdown = md_path.read_text(encoding="utf-8")
    problems = heading_problems(markdown, bad_word)
    if sheet["source"]["sha256"] != sha256_hex(before) or read_bytes(source_path) != before:
        problems.append(f"{tool}: 元ファイルのハッシュが合わない、または元ファイルが変わった")
    if any(i["status"] != "measured" and i["value"] is not None for i in sheet["items"]):
        problems.append(f"{tool}: 値が無いはずの項目に value が入っている")
    for secret in ("203.0.113.7", "SYNTHETIC-SSID", "SYNTHETIC-ISP", "192.0.2.1"):
        if secret in markdown or secret in json_path.read_text(encoding="utf-8"):
            problems.append(f"{tool}: 写さないはずの値がシートに出ている({secret})")
    try:
        convert_file(tool, source_path, out_dir)
        problems.append(f"{tool}: 同じ名前のファイルがあるのに書けてしまう")
    except InputError:
        pass
    return problems


def selftest() -> int:
    """合成データだけで、検査・描画・各アダプタを通す。問題が無ければ 0。"""
    problems: list[str] = []
    try:
        bad_word = load_bad_word()
        problems += _selftest_sheet(bad_word)
        with tempfile.TemporaryDirectory(prefix="diagsheet-selftest-") as tmp:
            for tool in SYNTHETIC:
                problems += _selftest_adapter(tool, Path(tmp), bad_word)
    except DiagSheetError as exc:
        problems.append(f"{type(exc).__name__}: {exc}")
    if problems:
        for line in problems:
            print(f"diagsheet selftest: NG: {line}", file=sys.stderr)
        return EXIT_IO
    done = "・".join(SYNTHETIC)
    pending = "・".join(PENDING)
    print(f"diagsheet selftest: OK(合成シート・{done})。まだ無いアダプタ: {pending}(実物待ち)")
    return EXIT_OK


def _build_parser() -> _Parser:
    parser = _Parser(
        prog="diagsheet",
        description="診断ツールの結果 JSON を共通の形(シート)に写す。判定は足さない。",
    )
    parser.add_argument("--version", action="version", version=f"diagsheet {__version__}")
    parser.add_argument("--selftest", action="store_true", help="合成データで自己テストをする")
    sub = parser.add_subparsers(dest="command")

    convert = sub.add_parser("convert", help="元 JSON を .sheet.json と .sheet.md にする")
    convert.add_argument("--tool", required=True, choices=TOOLS, help="元 JSON を出したツール")
    convert.add_argument("source", help="元 JSON のパス")
    convert.add_argument("--tool-version", help="ツールの版(分からなければ付けない)")
    convert.add_argument("--out", help="出力先のフォルダ(既定はリポジトリ直下の out)")

    rendering = sub.add_parser("render", help="シートの JSON から Markdown だけを作り直す")
    rendering.add_argument("sheet", help=".sheet.json のパス")
    rendering.add_argument("--out", help="出力先のフォルダ(既定はリポジトリ直下の out)")

    checking = sub.add_parser("check", help="シートの JSON の形を検査する")
    checking.add_argument("sheet", help=".sheet.json のパス")
    return parser


def _relax_streams() -> None:
    """コンソールの文字コードで出せない文字があっても落ちないようにする。"""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(errors="backslashreplace")


def _run(args: argparse.Namespace) -> int:
    if args.selftest:
        if args.command is not None:
            raise InputError("--selftest はほかのコマンドと一緒に使えない")
        return selftest()
    if args.command == "check":
        sheet = parse_json(read_bytes(Path(args.sheet)), Path(args.sheet).name)
        violations = check_sheet(sheet)
        for line in violations:
            print(line)
        if violations:
            print(f"diagsheet: 違反 {len(violations)}件", file=sys.stderr)
            return EXIT_CHECK
        print("違反なし")
        return EXIT_OK
    if args.command in ("convert", "render"):
        out_dir = Path(args.out) if args.out else default_out_dir()
        if args.command == "convert":
            written = convert_file(args.tool, Path(args.source), out_dir, args.tool_version)
        else:
            written = render_file(Path(args.sheet), out_dir)
        for path in written:
            print(path)
        return EXIT_OK
    raise InputError("コマンドが無い。convert・render・check のどれか、または --selftest を付ける")


def main(argv: Sequence[str] | None = None) -> int:
    _relax_streams()
    try:
        args = _build_parser().parse_args(argv)
    except _ArgError as exc:
        print(exc, file=sys.stderr)
        return EXIT_IO
    try:
        return _run(args)
    except CheckError as exc:
        for line in exc.violations:
            print(line, file=sys.stderr)
        summary = f"diagsheet: シートの形に違反 {len(exc.violations)}件。何も書いていない"
        print(summary, file=sys.stderr)
        return exc.exit_code
    except DiagSheetError as exc:
        print(f"diagsheet: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
