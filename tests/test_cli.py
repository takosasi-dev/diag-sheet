# CLI 全体のテスト: --selftest(AC-2)、引数の誤りが終了コード 1 になること、まだ無いアダプタの扱い、
# 診断ツールのコードを import していないこと(AC-3)、既定の出力先、対応表の読み込み。

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import diagsheet
from diagsheet.__main__ import PENDING, convert_file, default_out_dir
from diagsheet.adapters import load_not_measured, load_verdict_map
from diagsheet.model import InputError, ShapeError, load_bad_word
from tests.helpers import FIXTURES, cli, files_under, read_json, source_fixtures

PACKAGE_DIR = Path(diagsheet.__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent


def test_ac2_selftest_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli("--selftest") == 0
    assert "selftest: OK" in capsys.readouterr().out


def test_selftest_as_module_exits_0() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "diagsheet", "--selftest"],
        cwd=REPO_DIR,
        capture_output=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["convert"],
        ["convert", "--tool", "stutter"],
        ["convert", "--tool", "other", "x.json"],
        ["render"],
        ["check"],
        ["unknown-command"],
        ["--selftest", "check", "x.sheet.json"],
        ["check", "x.sheet.json", "--out", "y"],
    ],
)
def test_argument_errors_exit_1_not_2(args: list[str]) -> None:
    assert cli(*args) == 1


def test_padlab_adapter_is_pending(tmp_path: Path) -> None:
    assert list(PENDING) == ["padlab"]
    source = source_fixtures()[0][1]
    out = tmp_path / "out"
    assert cli("convert", "--tool", "padlab", str(source), "--out", str(out)) == 1
    assert files_under(out) == []
    assert not out.exists()


def test_ac3_no_imports_of_the_diagnostic_tools() -> None:
    pattern = re.compile(
        r"(import|from) +(stutter_diag|stutter_gui|network_diag|report_tab|pdh)\b"
    )
    sources = sorted(PACKAGE_DIR.rglob("*.py"))
    assert len(sources) >= 8
    hits = [
        f"{path.name}:{number}"
        for path in sources
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if pattern.search(line)
    ]
    assert hits == []


def test_only_standard_library_is_imported() -> None:
    allowed = set(sys.stdlib_module_names) | {"diagsheet", "__future__"}
    pattern = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        modules = set(pattern.findall(path.read_text(encoding="utf-8")))
        assert modules <= allowed, (path.name, modules - allowed)


def test_every_source_file_starts_with_a_japanese_comment() -> None:
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith("# ") and re.search(r"[぀-ヿ一-鿿]", first), path


def test_default_out_dir_is_out_under_the_repository() -> None:
    assert default_out_dir() == REPO_DIR / "out"


def test_mappings_are_valid_and_marked_tentative() -> None:
    assert load_bad_word() == "異常"
    stutter_map = load_verdict_map("stutter")
    assert [stutter_map.lookup("severity", raw) for raw in ("high", "medium", "ok")] == [
        ("要対処", "bad"),
        ("注意", "warn"),
        ("正常", "ok"),
    ]
    with pytest.raises(ShapeError):
        stutter_map.lookup("severity", "critical")
    assert not load_verdict_map("padlab").has_field("severity")
    assert [name for name, _ in load_not_measured("stutter")] == [
        "プロセス別のディスクI/O",
        "GPU起因のコマ落ち",
    ]
    assert load_not_measured("netdiag") == []
    for name in ("verdict_map.json", "not_measured.json"):
        assert "仮決め" in read_json(PACKAGE_DIR / "mappings" / name)["_note"]


def test_bad_word_must_be_one_of_the_three(tmp_path: Path) -> None:
    mappings = tmp_path / "mappings"
    mappings.mkdir()
    for name in ("verdict_map.json", "not_measured.json", "tool_dirs.json"):
        data = read_json(PACKAGE_DIR / "mappings" / name)
        if name == "verdict_map.json":
            data["bad_word"] = "注意"
        (mappings / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(InputError):
        load_bad_word(mappings)
    source = FIXTURES / "stutter" / "basic.json"
    with pytest.raises(InputError):
        convert_file("stutter", source, tmp_path / "out", mappings_dir=mappings)
    assert files_under(tmp_path / "out") == []


def test_other_bad_word_changes_only_the_heading(tmp_path: Path) -> None:
    mappings = tmp_path / "mappings"
    mappings.mkdir()
    for name in ("verdict_map.json", "not_measured.json", "tool_dirs.json"):
        data = read_json(PACKAGE_DIR / "mappings" / name)
        if name == "verdict_map.json":
            data["bad_word"] = "要確認"
        (mappings / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    source = FIXTURES / "stutter" / "basic.json"
    _, md_path = convert_file("stutter", source, tmp_path / "out", mappings_dir=mappings)
    markdown = md_path.read_text(encoding="utf-8")
    assert "## [要確認] 1件" in markdown and "## [異常]" not in markdown
    assert "| 要確認 | 注意 | 測れなかった | 未チェック | 対象外 | 正常 | 判定なし |" in markdown


def test_repository_text_files_are_utf8_lf_without_bom() -> None:
    suffixes = {".py", ".json", ".toml", ".md", ".gitignore", ".gitattributes", ""}
    skipped = {".git", "out", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
    checked = 0
    for path in sorted(REPO_DIR.rglob("*")):
        if not path.is_file() or skipped & set(path.relative_to(REPO_DIR).parts):
            continue
        if path.suffix not in suffixes and path.name not in suffixes:
            continue
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), path
        assert b"\r" not in raw, path
        raw.decode("utf-8")
        checked += 1
    assert checked >= 20
