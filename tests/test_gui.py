# 画面(gui)のテスト。窓は隠したまま作って、終わりに必ず壊す。Tk が動かない環境では飛ばす。
# エラーの窓と外のアプリは差し替えて出さない。書き込みは pytest の一時フォルダの中だけにする。
# Tk は1つのプロセスで作り直すと失敗することがあるので、根の窓は1回だけ作って使い回す。

from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from diagsheet import gui
from diagsheet.__main__ import default_out_dir
from diagsheet.gui_rows import NO_VALUE
from tests.helpers import FIXTURES, files_under, read_json, write_json

WORDS = ["異常", "注意", "測れなかった", "未チェック", "対象外", "正常", "判定なし"]
SHEET_FIXTURE = FIXTURES / "sheets" / "all_states.sheet.json"


@dataclass
class Window:
    """テスト用の窓。エラーの窓と「開く」は、出さずに記録するだけにする。"""

    app: gui.App = field(init=False)
    alerts: list[str] = field(default_factory=list)
    opened: list[str] = field(default_factory=list)
    refuse_open: bool = False

    def alert(self, _title: str, message: str) -> None:
        self.alerts.append(message)

    def open(self, path: str) -> None:
        if self.refuse_open:
            raise OSError(1, "合成の拒否")
        self.opened.append(path)

    @property
    def status(self) -> str:
        return self.app.status_var.get()

    def counts(self) -> list[str]:
        return [str(label.cget("text")) for label in self.app.count_labels]

    def states(self) -> list[str]:
        tree = self.app.tree
        return [str(tree.item(row, "values")[0]) for row in tree.get_children()]

    def detail(self) -> str:
        return self.app.detail_text.get("1.0", "end-1c")

    def info(self) -> str:
        return self.app.info_text.get("1.0", "end-1c")


@pytest.fixture(scope="module")
def tk_root() -> Iterator[tk.Tk]:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk を開けない: {exc}")
    root.withdraw()
    try:
        yield root
    finally:
        root.destroy()


@pytest.fixture
def window(tk_root: tk.Tk, tmp_path: Path) -> Iterator[Window]:
    made = Window()
    made.app = gui.App(tk_root, alert=made.alert, opener=made.open)
    made.app.out_var.set(str(tmp_path / "out"))
    tk_root.update_idletasks()
    try:
        yield made
    finally:
        # 次のテストのために、窓の中身を全部壊す(根の窓は隠したまま残す)。
        for child in tk_root.winfo_children():
            child.destroy()


def test_window_builds_with_no_sheet_and_dashes_for_counts(window: Window) -> None:
    assert window.app.root.title() == "DiagSheet"
    assert window.counts() == [f"[{word}] {NO_VALUE}" for word in WORDS]
    assert window.states() == []
    assert window.info() == "表示中のシートは無い"
    assert window.alerts == []


def test_convert_writes_the_files_and_shows_the_sheet(window: Window, tmp_path: Path) -> None:
    app = window.app
    app.source_var.set(f'"{FIXTURES / "stutter" / "basic.json"}"')
    app.version_var.set("v1.0.0")
    app.convert()
    out = tmp_path / "out"
    assert [p.name for p in files_under(out)] == ["basic.sheet.json", "basic.sheet.md"]
    sheet = read_json(out / "basic.sheet.json")
    assert sheet["tool"] == "stutter" and sheet["tool_version"] == "v1.0.0"
    assert window.counts() == [
        "[異常] 1件",
        "[注意] 1件",
        "[測れなかった] 1件",
        "[未チェック] 2件",
        "[対象外] 0件",
        "[正常] 1件",
        "[判定なし] 1件",
    ]
    assert window.states() == [
        "[異常]",
        "[注意]",
        "[測れなかった]",
        "[未チェック]",
        "[未チェック]",
        "[正常]",
        "[判定なし]",
    ]
    assert window.status.startswith("変換して書いた: basic.sheet.json・basic.sheet.md")
    assert app.sheet_var.get() == str(out / "basic.sheet.json")
    assert "ツール: stutter 版 v1.0.0(出所: 指定)" in window.info()
    assert window.alerts == []

    app.select_row(2)
    assert window.detail().splitlines()[:3] == [
        "[測れなかった] SMART(消耗度)",
        "値: — / 確度: — / ツールの判定: —",
        "理由: 権限不足",
    ]
    app.open_markdown()
    app.open_out_dir()
    assert window.opened == [str(out / "basic.sheet.md"), str(out)]


def test_convert_with_the_other_tool_and_no_version(window: Window, tmp_path: Path) -> None:
    app = window.app
    app.tool_var.set("回線診断(netdiag)")
    app.source_var.set(str(FIXTURES / "netdiag" / "partial.json"))
    app.convert()
    sheet = read_json(tmp_path / "out" / "partial.sheet.json")
    assert sheet["tool"] == "netdiag" and sheet["tool_version"] is None
    assert "版 不明(出所: 不明)" in window.info() and "総合(ツールの採点): ?" in window.info()
    assert window.counts()[2] == "[測れなかった] 18件" and len(window.states()) == 25


def test_convert_errors_use_the_cli_wording_and_clear_the_sheet(
    window: Window, tmp_path: Path
) -> None:
    app = window.app
    source = FIXTURES / "stutter" / "basic.json"
    app.source_var.set(str(source))
    app.convert()
    assert window.states() != []

    # 同じ名前のファイルがある(終了コード 1)。前の表示は消す。
    app.convert()
    assert window.status.startswith("diagsheet: 同じ名前のファイルがある(上書きしない): ")
    assert window.status.endswith("(終了コード 1)")
    assert window.alerts[-1].startswith("diagsheet: 同じ名前のファイルがある")
    assert window.alerts[-1].endswith("終了コード 1")
    assert window.states() == [] and window.counts()[0] == f"[異常] {NO_VALUE}"
    assert len(files_under(tmp_path / "out")) == 2

    # 知らない形(終了コード 2)。何も書かない。
    app.out_var.set(str(tmp_path / "out2"))
    app.tool_var.set("回線診断(netdiag)")
    app.convert()
    assert window.status.startswith("diagsheet: フル診断の結果ではない: ")
    assert window.status.endswith("(終了コード 2)")
    assert not (tmp_path / "out2").exists()

    # 出力先が診断ツールのフォルダの中(終了コード 4)。パスの文字列だけで止まるので、何も作らない。
    app.out_var.set("L:\\PC遅延診断\\out")
    app.convert()
    assert "出力先が診断ツールのフォルダの中にある" in window.status
    assert window.status.endswith("(終了コード 4)")

    # 版の欄が空白だけ(CLI で --tool-version に空を渡したのと同じ)。
    app.out_var.set(str(tmp_path / "out3"))
    app.version_var.set(" ")
    app.convert()
    assert "--tool-version が空" in window.status and not (tmp_path / "out3").exists()


def test_empty_fields_are_rejected_before_any_call(window: Window, tmp_path: Path) -> None:
    app = window.app
    app.convert()
    assert window.status.startswith("結果 JSON の場所が空")
    for action in (app.open_sheet, app.check, app.rerender):
        action()
        assert window.status.startswith("シート JSON の場所が空")
    assert len(window.alerts) == 4 and not (tmp_path / "out").exists()
    app.open_markdown()
    assert window.status.startswith("開く Markdown がまだ無い")
    app.open_out_dir()
    assert window.status.startswith("出力先のフォルダがまだ無い") and window.opened == []


def test_empty_out_field_falls_back_to_the_default_like_the_cli(window: Window) -> None:
    window.app.out_var.set("  ")
    window.app.open_out_dir()
    assert window.app.out_var.get() == str(default_out_dir())


def test_open_sheet_shows_all_seven_states(window: Window) -> None:
    app = window.app
    app.sheet_var.set(str(SHEET_FIXTURE))
    app.open_sheet()
    assert window.status == "開いた: all_states.sheet.json(8項目)"
    assert window.states() == [*(f"[{word}]" for word in WORDS), "[判定なし]"]
    assert window.counts()[-1] == "[判定なし] 2件"
    assert window.info().splitlines()[0] == f"表示中: {SHEET_FIXTURE}"
    # 隣に Markdown が無いので、開かずにそう書く。
    app.open_markdown()
    assert window.status.startswith("Markdown が無い: ") and window.opened == []


def test_open_sheet_refuses_a_broken_sheet_like_render(window: Window, tmp_path: Path) -> None:
    app = window.app
    app.sheet_var.set(str(SHEET_FIXTURE))
    app.open_sheet()
    broken = read_json(SHEET_FIXTURE)
    broken["items"][2]["value"] = 0
    path = write_json(tmp_path / "src" / "broken.sheet.json", broken)
    app.sheet_var.set(str(path))
    app.open_sheet()
    assert window.status == "diagsheet: シートの形に違反 1件。何も書いていない(終了コード 3)"
    assert window.states() == []
    assert "status が failed なのに value が null でない" in window.detail()
    assert window.alerts[-1].endswith("終了コード 3")


def test_check_reports_like_the_cli(window: Window, tmp_path: Path) -> None:
    app = window.app
    app.sheet_var.set(str(SHEET_FIXTURE))
    app.check()
    assert window.status == "検査: 違反なし(all_states.sheet.json)"
    assert window.detail().splitlines() == [f"検査: {SHEET_FIXTURE}", "違反なし"]

    broken = read_json(SHEET_FIXTURE)
    broken["items"][2]["value"] = 0
    broken["counts"]["ok"] += 1
    path = write_json(tmp_path / "src" / "broken.sheet.json", broken)
    app.sheet_var.set(str(path))
    app.check()
    assert window.status == "diagsheet: 違反 3件(終了コード 3)"
    lines = window.detail().splitlines()
    assert lines[0] == f"検査: {path}" and lines[-1] == "diagsheet: 違反 3件" and len(lines) == 5

    app.sheet_var.set(str(tmp_path / "none.sheet.json"))
    app.check()
    assert window.status.startswith("diagsheet: ファイルを読めない: ")
    assert window.status.endswith("(終了コード 1)")
    # 違反の一覧は窓を出さない。読めないときだけ窓を出す。
    assert len(window.alerts) == 1


def test_rerender_writes_only_the_markdown(window: Window, tmp_path: Path) -> None:
    app = window.app
    app.sheet_var.set(str(SHEET_FIXTURE))
    app.rerender()
    out = tmp_path / "out"
    assert [p.name for p in files_under(out)] == ["all_states.sheet.md"]
    assert window.status == f"Markdown を書いた: {out / 'all_states.sheet.md'}"
    app.open_markdown()
    assert window.opened == [str(out / "all_states.sheet.md")]
    app.rerender()
    assert "同じ名前のファイルがある" in window.status and len(files_under(out)) == 1


@pytest.mark.parametrize("tool", ["stutter", "netdiag"])
def test_demo_shows_synthetic_data_with_made_up_paths(
    window: Window, tool: str, tmp_path: Path
) -> None:
    app = window.app
    app.show_demo(tool)
    assert app.source_var.get() == "D:\\demo\\results\\sample.json"
    assert app.out_var.get() == "D:\\demo\\out"
    assert app.sheet_var.get() == "D:\\demo\\out\\sample.sheet.json"
    assert window.states() != [] and window.alerts == []
    shown = "\n".join([window.info(), window.detail(), window.status, *window.counts()])
    for word in ("Users", "AppData", str(tmp_path), str(Path.home())):
        assert word not in shown
    assert not files_under(tmp_path)


def test_unexpected_errors_in_a_button_reach_the_status_bar(window: Window) -> None:
    handler = window.app.root.report_callback_exception
    handler(ValueError, ValueError("合成の失敗"), None)
    assert window.status == "diagsheet: 想定外のエラー: ValueError: 合成の失敗"
    assert window.alerts == [window.status]


def test_opener_failures_are_shown_not_raised(window: Window, tmp_path: Path) -> None:
    window.refuse_open = True
    window.app.out_var.set(str(tmp_path))
    window.app.open_out_dir()
    assert window.status == f"開けない: {tmp_path}(合成の拒否)"
    assert window.opened == []
