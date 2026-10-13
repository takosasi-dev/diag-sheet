# exe にしたとき(sys.frozen)の場所の決め方と、入口の振り分けのテスト。実際の exe は作らない。
# 同梱データは展開先から読み、書き込み先は exe の隣にする。引数なしなら画面、あれば CLI。
# コンソールの無い exe と同じく stdout・stderr が None でも落ちないことも見る。

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

import diagsheet
from diagsheet import gui, resources
from diagsheet.__main__ import default_out_dir, main
from diagsheet.model import MAPPINGS_DIR, load_bad_word
from tests.helpers import FIXTURES, files_under

PACKAGE_DIR = Path(diagsheet.__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """exe として動いているふりをする。展開先は tmp/_MEI、exe は tmp/app/DiagSheet.exe。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI"), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "DiagSheet.exe"))
    return tmp_path


def test_from_source_the_paths_are_in_the_repository() -> None:
    assert not resources.is_frozen()
    assert resources.resource_path("mappings") == PACKAGE_DIR / "mappings"
    assert resources.app_dir() == REPO_DIR
    assert MAPPINGS_DIR == PACKAGE_DIR / "mappings"
    assert load_bad_word() == "異常"


def test_frozen_reads_bundled_data_and_writes_next_to_the_exe(frozen: Path) -> None:
    assert resources.is_frozen()
    bundled = resources.resource_path("mappings", "verdict_map.json")
    assert bundled == frozen / "_MEI" / "diagsheet" / "mappings" / "verdict_map.json"
    assert resources.app_dir() == (frozen / "app").resolve()
    out = default_out_dir()
    assert out == (frozen / "app").resolve() / "out"
    assert (frozen / "_MEI").resolve() not in out.parents


def test_frozen_flag_without_an_unpack_dir_is_not_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert not resources.is_frozen()
    assert resources.app_dir() == REPO_DIR


def test_frozen_without_arguments_opens_the_gui(
    frozen: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[bool, bool]] = []

    def fake_run(*, smoke: bool = False, demo: bool = False) -> int:
        calls.append((smoke, demo))
        return 0

    monkeypatch.setattr(gui, "run", fake_run)
    assert main([]) == 0
    assert calls == [(False, False)]


def test_frozen_with_arguments_runs_as_the_cli(
    frozen: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_run(*, smoke: bool = False, demo: bool = False) -> int:
        raise AssertionError("引数があるのに画面を開こうとした")

    monkeypatch.setattr(gui, "run", fail_run)
    sheet = FIXTURES / "sheets" / "all_states.sheet.json"
    assert main(["check", str(sheet)]) == 0
    assert capsys.readouterr().out.strip() == "違反なし"
    out = frozen / "work" / "out"
    source = FIXTURES / "stutter" / "basic.json"
    assert main(["convert", "--tool", "stutter", str(source), "--out", str(out)]) == 0
    assert [p.name for p in files_under(out)] == ["basic.sheet.json", "basic.sheet.md"]
    assert main(["convert"]) == 1


def test_from_source_no_arguments_is_still_an_argument_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*, smoke: bool = False, demo: bool = False) -> int:
        raise AssertionError("ソースから引数なしで動かしたのに画面を開こうとした")

    monkeypatch.setattr(gui, "run", fail_run)
    assert main([]) == 1


def test_gui_command_passes_the_hidden_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[bool, bool]] = []

    def fake_run(*, smoke: bool = False, demo: bool = False) -> int:
        calls.append((smoke, demo))
        return 0

    monkeypatch.setattr(gui, "run", fake_run)
    assert main(["gui"]) == 0
    assert main(["gui", "--smoke"]) == 0
    assert main(["gui", "--smoke", "--demo"]) == 0
    assert calls == [(False, False), (True, False), (True, True)]


def test_missing_console_streams_do_not_crash_the_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    try:
        assert main(["--selftest"]) == 0
        assert main(["check", str(tmp_path / "none.sheet.json")]) == 1
        assert main(["unknown-command"]) == 1
        assert sys.stdout is not None and sys.stderr is not None
    finally:
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                stream.close()


def test_version_is_the_same_everywhere() -> None:
    assert diagsheet.__version__ == "0.2.0"
    project = tomllib.loads((REPO_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == diagsheet.__version__
    changelog = (REPO_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## \[([^\]]+)\]", changelog, re.MULTILINE)
    assert first is not None and first.group(1) == diagsheet.__version__
    readme = (REPO_DIR / "README.md").read_text(encoding="utf-8")
    assert f"版 {diagsheet.__version__}(" in readme


def test_build_tools_keep_work_files_under_build_and_bundle_the_mappings() -> None:
    script = (REPO_DIR / "tools" / "build_exe.py").read_text(encoding="utf-8")
    for word in ("--onefile", "--windowed", "--add-data", "--specpath", "--workpath", "DiagSheet"):
        assert word in script
    ignored = (REPO_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {"build/", "dist/", "*.spec"} <= set(ignored)
    for name in ("build_exe.py", "exe_entry.py", "make_screenshots.py"):
        first = (REPO_DIR / "tools" / name).read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith("# ") and re.search(r"[぀-ヿ一-鿿]", first), name
