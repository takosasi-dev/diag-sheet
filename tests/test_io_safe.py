# 入出力の安全のテスト: 出力先が診断ツールのフォルダの中なら終了コード 4(AC-13・FR-18)、
# 上書きしない(FR-19)、失敗したら何も残さない、ファイル名の置き換え、SHA-256。
# 診断ツールのフォルダが無い PC でも、パスの文字列だけで判定が働くことを見る。

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

from diagsheet import io_safe
from diagsheet.io_safe import (
    ensure_outside_tool_dirs,
    load_tool_dirs,
    safe_name,
    sha256_hex,
    sheet_stem,
    write_files,
)
from diagsheet.model import InputError, OutDirError
from tests.helpers import cli, files_under, sheet_fixtures, source_fixtures

AC13_PATHS = ["L:\\PC遅延診断\\x", "l:/pc遅延診断/x", "L:\\PC遅延診断\\"]


def test_tool_dirs_mapping_has_the_three_folders() -> None:
    assert load_tool_dirs() == ["L:\\ネットワーク診断", "L:\\PC遅延診断", "L:\\PadLab"]


@pytest.mark.parametrize("out", AC13_PATHS)
def test_ac13_tool_dir_paths_are_refused(out: str) -> None:
    with pytest.raises(OutDirError):
        ensure_outside_tool_dirs(Path(out), load_tool_dirs())


@pytest.mark.parametrize("out", AC13_PATHS)
def test_ac13_render_and_convert_exit_4(out: str) -> None:
    existed = os.path.lexists(out)
    assert cli("render", str(sheet_fixtures()[0]), "--out", out) == 4
    for tool, source in source_fixtures():
        assert cli("convert", "--tool", tool, str(source), "--out", out) == 4
    assert os.path.lexists(out) == existed


@pytest.mark.parametrize(
    "out",
    [
        "L:\\ネットワーク診断",
        "L:/ネットワーク診断/results/sheets",
        "l:\\padlab\\out\\",
        "L:\\PadLab\\..\\PadLab\\x",
        "\\\\?\\L:\\PadLab\\x",
    ],
)
def test_other_forms_inside_tool_dirs_are_refused(out: str) -> None:
    with pytest.raises(OutDirError):
        ensure_outside_tool_dirs(Path(out), load_tool_dirs())


@pytest.mark.parametrize(
    "out", ["L:\\PC遅延診断2\\x", "L:\\diag-sheet\\out", "L:\\", "L:\\PadLab\\..\\other"]
)
def test_paths_outside_tool_dirs_are_allowed(out: str) -> None:
    ensure_outside_tool_dirs(Path(out), load_tool_dirs())


def test_relative_and_existing_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool_dir = tmp_path / "Tool"
    (tool_dir / "results").mkdir(parents=True)
    monkeypatch.chdir(tool_dir)
    for out in (Path("results"), Path("."), Path("new") / "deep", tool_dir):
        with pytest.raises(OutDirError):
            ensure_outside_tool_dirs(out, [str(tool_dir)])
    ensure_outside_tool_dirs(Path(".."), [str(tool_dir)])
    ensure_outside_tool_dirs(tmp_path / "Tool-other", [str(tool_dir)])


@pytest.mark.skipif(sys.platform != "win32", reason="ジャンクションは Windows だけ")
def test_junction_into_tool_dir_is_refused(tmp_path: Path) -> None:
    import _winapi

    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    link = tmp_path / "link"
    _winapi.CreateJunction(str(tool_dir), str(link))
    try:
        with pytest.raises(OutDirError):
            ensure_outside_tool_dirs(link / "x", [str(tool_dir)])
        with pytest.raises(OutDirError):
            ensure_outside_tool_dirs(tool_dir / "x", [str(link)])
    finally:
        os.rmdir(link)


def test_safe_name_and_sheet_stem() -> None:
    assert safe_name("test_20260102_030405") == "test_20260102_030405"
    assert safe_name('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"
    assert safe_name("夜 の測定") == "夜 の測定"
    assert safe_name("tab\there") == "tab_here"
    assert safe_name("end. ") == "end__"
    assert safe_name("") == "_"
    assert sheet_stem("x.sheet.json") == "x"
    assert sheet_stem("a.b.SHEET.JSON") == "a.b"
    assert sheet_stem("plain.json") == "plain"


def test_sha256_matches_hashlib(tmp_path: Path) -> None:
    raw = "合成\n".encode()
    assert sha256_hex(raw) == hashlib.sha256(raw).hexdigest()
    assert len(sha256_hex(b"")) == 64


def test_write_files_refuses_existing_and_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "b.txt").write_text("old", encoding="utf-8")
    with pytest.raises(InputError):
        write_files(out, [("a.txt", "new a"), ("b.txt", "new b")])
    assert [p.name for p in files_under(out)] == ["b.txt"]
    assert (out / "b.txt").read_text(encoding="utf-8") == "old"


def test_write_files_writes_utf8_lf_and_creates_dir(tmp_path: Path) -> None:
    out = tmp_path / "new" / "out"
    written = write_files(out, [("a.txt", "1行目\n2行目\n"), ("b.txt", "x\n")])
    assert [p.name for p in written] == ["a.txt", "b.txt"]
    assert (out / "a.txt").read_bytes() == "1行目\n2行目\n".encode()
    assert [p.name for p in files_under(out)] == ["a.txt", "b.txt"]


def test_write_files_leaves_nothing_when_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    real_rename = os.rename
    calls: list[str] = []

    def failing_rename(src: object, dst: object) -> None:
        calls.append(str(dst))
        if len(calls) == 2:
            raise PermissionError("合成の失敗")
        real_rename(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(io_safe.os, "rename", failing_rename)
    with pytest.raises(InputError):
        write_files(out, [("a.txt", "a"), ("b.txt", "b")])
    assert len(calls) == 2
    assert files_under(out) == []
    assert not out.exists()


def test_write_files_leaves_nothing_when_text_cannot_be_encoded(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(InputError):
        write_files(out, [("a.txt", "ok"), ("b.txt", "\ud800")])
    assert files_under(out) == []
