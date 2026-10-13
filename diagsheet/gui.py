# 画面(tkinter)。窓の部品を並べ、ボタンから CLI と同じ関数(変換・描画・検査)を呼ぶ。
# 変換・対応づけ・判定はここに書かない。出す文字は gui_rows、エラーの文は CLI と同じ関数で作る。
# 状態は [異常] のような文字の印で示し、色は付けない(D-12)。

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import sys
import tempfile
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from types import TracebackType
from typing import Any, Final

# python -m diagsheet gui で開いたときは、ここで CLI のモジュールをもう一度読む(関数を借りるだけ)。
from diagsheet.__main__ import (
    ADAPTERS,
    NO_VIOLATION,
    SYNTHETIC,
    check_file,
    convert_file,
    default_out_dir,
    error_lines,
    load_checked_sheet,
    render_file,
    violation_summary,
)
from diagsheet.gui_rows import (
    COLUMNS,
    Row,
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
    tool_label,
    version_or_none,
)
from diagsheet.model import EXIT_CHECK, EXIT_IO, EXIT_OK, DiagSheetError, load_bad_word

TITLE: Final = "DiagSheet"
WINDOW_SIZE: Final = (960, 640)
WINDOW_MIN_SIZE: Final = (780, 520)
SMOKE_CLOSE_MS: Final = 500
# 一覧の列の幅(96dpi のときの px)と、窓を広げたときに伸ばすかどうか。
COLUMN_WIDTHS: Final = {
    "state": (112, False),
    "name": (190, False),
    "value": (100, False),
    "confidence": (56, False),
    "verdict": (112, False),
    "basis": (230, True),
    "note": (120, True),
}
JSON_TYPES: Final = (("JSON", "*.json"), ("すべてのファイル", "*.*"))
# --demo とスクリーンショットで画面に出すパス。実在しない作り物。
DEMO_SOURCE_NAME: Final = "sample.json"
DEMO_SOURCE: Final = "D:\\demo\\results\\sample.json"
DEMO_OUT: Final = "D:\\demo\\out"
DEMO_SHEET: Final = "D:\\demo\\out\\sample.sheet.json"
DEMO_VERSION: Final = "v1.0.0"
DETAIL_TITLE: Final = "詳細(選んだ項目・検査の結果・エラー)"
READY: Final = "結果 JSON を選んで「変換」を押す。作ったシートは「開く」で表示できる。"

Alert = Callable[[str, str], None]
Opener = Callable[[str], None]


def enable_dpi_awareness() -> None:
    """文字がぼやけないよう、窓を作る前に DPI 対応を宣言する。できない環境では何もしない。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


def _show_error(title: str, message: str) -> None:
    messagebox.showerror(title, message)


def _open_path(path: str) -> None:
    """既定のアプリ(フォルダならエクスプローラー)で開く。"""
    if sys.platform != "win32":
        raise OSError("Windows でだけ開ける")
    os.startfile(path)


class App:
    """1枚の窓。alert と opener は、テストで窓や外のアプリを出さないために差し替えられる。"""

    def __init__(
        self, root: tk.Tk, *, alert: Alert | None = None, opener: Opener | None = None
    ) -> None:
        self.root = root
        self._alert = alert or _show_error
        self._opener = opener or _open_path
        self._bad_word = load_bad_word()
        self._tools = tool_choices(ADAPTERS)
        self._shown: list[tuple[Mapping[str, Any], Row]] = []
        self._markdown: Path | None = None
        self._scale = root.winfo_fpixels("1i") / 96

        self.tool_var = tk.StringVar(master=root, value=self._tools[0][1])
        self.version_var = tk.StringVar(master=root)
        self.source_var = tk.StringVar(master=root)
        self.out_var = tk.StringVar(master=root, value=str(default_out_dir()))
        self.sheet_var = tk.StringVar(master=root)
        self.status_var = tk.StringVar(master=root, value=READY)

        root.title(TITLE)
        root.geometry(f"{self._px(WINDOW_SIZE[0])}x{self._px(WINDOW_SIZE[1])}")
        root.minsize(self._px(WINDOW_MIN_SIZE[0]), self._px(WINDOW_MIN_SIZE[1]))
        root.report_callback_exception = self._on_callback_error

        # ステータスバーを先に置く。窓を縮めたときに削られるのは一覧の側にする。
        status = ttk.Label(root, textvariable=self.status_var, relief="sunken", anchor="w")
        status.configure(padding=(self._px(6), self._px(2)))
        status.pack(fill="x", side="bottom")
        pad = self._px(8)
        body = ttk.Frame(root, padding=(pad, pad, pad, self._px(6)))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)
        self._build_convert(body).grid(row=0, column=0, sticky="ew")
        self._build_sheet(body).grid(row=1, column=0, sticky="ew", pady=(self._px(6), 0))
        self._build_counts(body).grid(row=2, column=0, sticky="ew", pady=(self._px(8), 0))
        self._build_tree(body).grid(row=3, column=0, sticky="nsew", pady=(self._px(4), 0))
        self._build_panes(body).grid(row=4, column=0, sticky="ew", pady=(self._px(6), 0))
        self._build_buttons(body).grid(row=5, column=0, sticky="ew", pady=(self._px(6), 0))
        self.clear_sheet()

    # ---- 部品 ----

    def _px(self, value: int) -> int:
        return round(value * self._scale)

    def _build_convert(self, parent: ttk.Frame) -> ttk.LabelFrame:
        gap = self._px(4)
        frame = ttk.LabelFrame(parent, text="結果 JSON をシートにする", padding=self._px(6))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="ツール").grid(row=0, column=0, sticky="w")
        line = ttk.Frame(frame)
        line.grid(row=0, column=1, columnspan=3, sticky="w", padx=(gap, 0))
        labels = [label for _, label in self._tools]
        ttk.Combobox(
            line, textvariable=self.tool_var, values=labels, state="readonly", width=24
        ).pack(side="left")
        ttk.Label(line, text="ツールの版(任意)").pack(side="left", padx=(self._px(16), gap))
        ttk.Entry(line, textvariable=self.version_var, width=14).pack(side="left")
        hint = ttk.Label(line, text="空のままなら、版は「不明」と記録する")
        hint.pack(side="left", padx=(gap, 0))

        ttk.Label(frame, text="結果 JSON の場所").grid(row=1, column=0, sticky="w", pady=(gap, 0))
        ttk.Entry(frame, textvariable=self.source_var).grid(
            row=1, column=1, sticky="ew", padx=gap, pady=(gap, 0)
        )
        ttk.Button(frame, text="参照…", command=self.browse_source).grid(
            row=1, column=2, pady=(gap, 0)
        )

        ttk.Label(frame, text="出力先").grid(row=2, column=0, sticky="w", pady=(gap, 0))
        ttk.Entry(frame, textvariable=self.out_var).grid(
            row=2, column=1, sticky="ew", padx=gap, pady=(gap, 0)
        )
        ttk.Button(frame, text="参照…", command=self.browse_out).grid(
            row=2, column=2, pady=(gap, 0)
        )
        ttk.Button(frame, text="変換", command=self.convert).grid(
            row=2, column=3, padx=(gap, 0), pady=(gap, 0)
        )
        return frame

    def _build_sheet(self, parent: ttk.Frame) -> ttk.LabelFrame:
        gap = self._px(4)
        frame = ttk.LabelFrame(parent, text="作ってあるシートを開く・検査する", padding=self._px(6))
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="シート JSON の場所").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.sheet_var).grid(row=0, column=1, sticky="ew", padx=gap)
        buttons = (
            ("参照…", self.browse_sheet),
            ("開く", self.open_sheet),
            ("検査", self.check),
            ("Markdown を作り直す", self.rerender),
        )
        for column, (text, command) in enumerate(buttons, start=2):
            ttk.Button(frame, text=text, command=command).grid(
                row=0, column=column, padx=(0 if column == 2 else gap, 0)
            )
        return frame

    def _build_counts(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        self.count_labels: list[ttk.Label] = []
        for column in range(len(count_cells(None, self._bad_word))):
            frame.columnconfigure(column, weight=1, uniform="count")
            label = ttk.Label(frame, anchor="center", relief="sunken", padding=self._px(3))
            label.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 2, 0))
            self.count_labels.append(label)
        return frame

    def _build_tree(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        ttk.Style(self.root).configure("Treeview", rowheight=line + self._px(5))
        keys = [key for key, _ in COLUMNS]
        self.tree = ttk.Treeview(frame, columns=keys, show="headings", selectmode="browse")
        for key, heading in COLUMNS:
            width, stretch = COLUMN_WIDTHS[key]
            self.tree.heading(key, text=heading, anchor="w")
            self.tree.column(key, width=self._px(width), stretch=stretch, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        return frame

    def _build_panes(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1, uniform="pane")
        frame.columnconfigure(1, weight=1, uniform="pane")
        info = ttk.LabelFrame(frame, text="シートの情報", padding=self._px(4))
        info.grid(row=0, column=0, sticky="nsew", padx=(0, self._px(3)))
        self.info_text = self._read_only_text(info, scrollbar=False)
        detail = ttk.LabelFrame(frame, text=DETAIL_TITLE, padding=self._px(4))
        detail.grid(row=0, column=1, sticky="nsew", padx=(self._px(3), 0))
        self.detail_text = self._read_only_text(detail, scrollbar=True)
        return frame

    def _read_only_text(self, parent: ttk.LabelFrame, *, scrollbar: bool) -> tk.Text:
        parent.columnconfigure(0, weight=1)
        text = tk.Text(parent, height=7, width=10, wrap="char", font="TkDefaultFont")
        text.configure(state="disabled", borderwidth=1, relief="solid")
        text.grid(row=0, column=0, sticky="nsew")
        # 書き換えはできないが、選んでコピーはできるようにする。
        text.bind("<1>", lambda _event: text.focus_set())
        if scrollbar:
            scroll = ttk.Scrollbar(parent, orient="vertical", command=text.yview)
            text.configure(yscrollcommand=scroll.set)
            scroll.grid(row=0, column=1, sticky="ns")
        return text

    def _build_buttons(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        ttk.Button(frame, text="Markdown を開く", command=self.open_markdown).pack(side="left")
        ttk.Button(frame, text="出力フォルダを開く", command=self.open_out_dir).pack(
            side="left", padx=(self._px(6), 0)
        )
        return frame

    # ---- 表示 ----

    def _set_text(self, widget: tk.Text, lines: Sequence[str]) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", "\n".join(lines))
        widget.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _set_counts(self, counts: Mapping[str, Any] | None) -> None:
        for label, text in zip(self.count_labels, count_cells(counts, self._bad_word), strict=True):
            label.configure(text=text)

    def clear_sheet(self) -> None:
        """表示中のシートを消す。件数は「—」に戻す(0 とは書かない)。"""
        self._shown = []
        self._markdown = None
        self.tree.delete(*self.tree.get_children())
        self._set_counts(None)
        self._set_text(self.info_text, ["表示中のシートは無い"])
        self._set_text(self.detail_text, [])

    def show_sheet(self, sheet: Mapping[str, Any], shown_path: str) -> None:
        """検査を通ったシートを表示する。shown_path は「表示中」に出す文字。"""
        self.clear_sheet()
        rows = item_rows(sheet, self._bad_word)
        by_id = {str(item["id"]): item for item in sheet["items"]}
        self._shown = [(by_id[row.item_id], row) for row in rows]
        for index, row in enumerate(rows):
            self.tree.insert("", "end", iid=str(index), values=row.cells())
        self._set_counts(sheet["counts"])
        self._set_text(self.info_text, info_lines(sheet, shown_path))
        self._set_text(self.detail_text, ["一覧の行を選ぶと、その項目の全部の欄をここに出す"])

    def select_row(self, index: int) -> None:
        self.tree.selection_set(str(index))
        self.tree.see(str(index))
        self._show_detail(index)

    def _show_detail(self, index: int) -> None:
        item, row = self._shown[index]
        self._set_text(self.detail_text, detail_lines(item, row))

    def _deselect(self) -> None:
        """詳細の欄に項目以外の物を出すときは、一覧の選択を外す。"""
        self.tree.selection_set(())

    def _on_select(self, _event: object) -> None:
        selected = self.tree.selection()
        if selected:
            self._show_detail(int(selected[0]))

    def show_violations(self, shown_path: str, violations: Sequence[str]) -> None:
        """検査の結果を詳細の欄とステータスバーに出す。文は CLI の check と同じ。"""
        self._deselect()
        if violations:
            lines = [*violations, violation_summary(len(violations))]
            self._set_text(self.detail_text, [f"検査: {shown_path}", *lines])
            self._set_status(status_text(lines, EXIT_CHECK))
        else:
            self._set_text(self.detail_text, [f"検査: {shown_path}", NO_VIOLATION])
            self._set_status(f"検査: {NO_VIOLATION}({Path(shown_path).name})")

    def _fail(self, exc: DiagSheetError) -> None:
        """CLI が終了コードつきで出すエラーを、同じ文でステータスバー・詳細の欄・窓に出す。"""
        lines = error_lines(exc)
        self._deselect()
        self._set_text(self.detail_text, [*lines, f"終了コード {exc.exit_code}"])
        self._set_status(status_text(lines, exc.exit_code))
        self._alert(TITLE, alert_text(lines, exc.exit_code))

    def _reject(self, message: str) -> None:
        """入力欄が空のときなど、関数を呼ぶ前に止めるとき。"""
        self._set_status(message)
        self._alert(TITLE, message)

    def _on_callback_error(
        self, kind: type[BaseException], exc: BaseException, _trace: TracebackType | None
    ) -> None:
        message = f"diagsheet: 想定外のエラー: {kind.__name__}: {exc}"
        self._set_status(message)
        self._alert(TITLE, message)

    # ---- 入力欄 ----

    def _tool(self) -> str:
        label = self.tool_var.get()
        return next(tool for tool, shown in self._tools if shown == label)

    def _out_dir(self) -> Path:
        """出力先の欄。空なら CLI で --out を付けないときと同じ既定の場所にして、欄にも書く。"""
        text = clean_path_text(self.out_var.get())
        if not text:
            text = str(default_out_dir())
        self.out_var.set(text)
        return Path(text)

    def _sheet_path(self) -> Path | None:
        text = clean_path_text(self.sheet_var.get())
        if not text:
            self._reject("シート JSON の場所が空。「参照…」で選ぶか、パスを入れる")
            return None
        self.sheet_var.set(text)
        return Path(text)

    def browse_source(self) -> None:
        chosen = filedialog.askopenfilename(
            parent=self.root,
            title="結果 JSON を選ぶ",
            filetypes=JSON_TYPES,
            initialdir=start_dir(self.source_var.get(), Path.home()),
        )
        if chosen:
            self.source_var.set(str(Path(chosen)))

    def browse_out(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self.root,
            title="出力先のフォルダを選ぶ",
            initialdir=start_dir(self.out_var.get(), Path.home()),
        )
        if chosen:
            self.out_var.set(str(Path(chosen)))

    def browse_sheet(self) -> None:
        current = self.sheet_var.get() or self.out_var.get()
        chosen = filedialog.askopenfilename(
            parent=self.root,
            title="シートの JSON を選ぶ",
            filetypes=(("シートの JSON", "*.sheet.json"), *JSON_TYPES),
            initialdir=start_dir(current, Path.home()),
        )
        if chosen:
            self.sheet_var.set(str(Path(chosen)))

    # ---- ボタン ----

    def convert(self) -> None:
        """CLI の convert と同じ。書けたら、書いたシートを読み直して表示する。"""
        source = clean_path_text(self.source_var.get())
        if not source:
            self._reject("結果 JSON の場所が空。「参照…」で選ぶか、パスを入れる")
            return
        self.source_var.set(source)
        out_dir = self._out_dir()
        self.clear_sheet()
        try:
            json_path, md_path = convert_file(
                self._tool(), Path(source), out_dir, version_or_none(self.version_var.get())
            )
            sheet = load_checked_sheet(json_path)
        except DiagSheetError as exc:
            self._fail(exc)
            return
        self.show_sheet(sheet, str(json_path))
        self._markdown = md_path
        self.sheet_var.set(str(json_path))
        self._set_status(f"変換して書いた: {json_path.name}・{md_path.name}(出力先 {out_dir})")

    def open_sheet(self) -> None:
        """シートの JSON を読んで表示する。CLI の render と同じく、検査を通った物だけを出す。"""
        path = self._sheet_path()
        if path is None:
            return
        self.clear_sheet()
        try:
            sheet = load_checked_sheet(path)
        except DiagSheetError as exc:
            self._fail(exc)
            return
        self.show_sheet(sheet, str(path))
        self._markdown = markdown_beside(path)
        self._set_status(f"開いた: {path.name}({len(self._shown)}項目)")

    def check(self) -> None:
        """CLI の check と同じ。違反を1行ずつ詳細の欄に出す。"""
        path = self._sheet_path()
        if path is None:
            return
        try:
            violations = check_file(path)
        except DiagSheetError as exc:
            self._fail(exc)
            return
        self.show_violations(str(path), violations)

    def rerender(self) -> None:
        """CLI の render と同じ。シートの JSON から Markdown だけを出力先に書く。"""
        path = self._sheet_path()
        if path is None:
            return
        try:
            written = render_file(path, self._out_dir())
        except DiagSheetError as exc:
            self._fail(exc)
            return
        self._markdown = written[0]
        self._set_status(f"Markdown を書いた: {written[0]}")

    def open_markdown(self) -> None:
        if self._markdown is None:
            self._set_status("開く Markdown がまだ無い。変換するか、シートを開いてから押す")
        elif not self._markdown.is_file():
            self._set_status(f"Markdown が無い: {self._markdown}(「Markdown を作り直す」で作れる)")
        else:
            self._open(self._markdown)

    def open_out_dir(self) -> None:
        out_dir = self._out_dir()
        if out_dir.is_dir():
            self._open(out_dir)
        else:
            self._set_status(f"出力先のフォルダがまだ無い: {out_dir}(変換すると作られる)")

    def _open(self, path: Path) -> None:
        try:
            self._opener(str(path))
        except OSError as exc:
            self._set_status(f"開けない: {path}({exc.strerror or exc})")
        else:
            self._set_status(f"開いた: {path}")

    # ---- 合成データ ----

    def show_demo(self, tool: str = "stutter", source: Mapping[str, Any] | None = None) -> None:
        """合成データを一時フォルダで変換して表示する。画面に出すパスは作り物にする。"""
        data = SYNTHETIC[tool]() if source is None else source
        with tempfile.TemporaryDirectory(prefix="diagsheet-demo-") as tmp:
            source_path = Path(tmp) / DEMO_SOURCE_NAME
            source_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
            )
            json_path, md_path = convert_file(tool, source_path, Path(tmp) / "out", DEMO_VERSION)
            sheet = load_checked_sheet(json_path)
        self.tool_var.set(tool_label(tool))
        self.version_var.set(DEMO_VERSION)
        self.source_var.set(DEMO_SOURCE)
        self.out_var.set(DEMO_OUT)
        self.sheet_var.set(DEMO_SHEET)
        self.show_sheet(sheet, DEMO_SHEET)
        self._set_status(f"変換して書いた: {json_path.name}・{md_path.name}(出力先 {DEMO_OUT})")


def run(*, smoke: bool = False, demo: bool = False) -> int:
    """窓を開く。smoke なら窓を作って少し待ってから閉じ、途中でエラーが出ていれば 1 を返す。"""
    enable_dpi_awareness()
    problems: list[str] = []

    def record(_title: str, message: str) -> None:
        problems.append(message)

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"diagsheet: 画面を開けない: {exc}", file=sys.stderr)
        return EXIT_IO
    try:
        app = App(root, alert=record if smoke else None)
        if demo:
            app.show_demo()
    except DiagSheetError as exc:
        lines = error_lines(exc)
        for line in lines:
            print(line, file=sys.stderr)
        if not smoke:
            _show_error(TITLE, alert_text(lines, exc.exit_code))
        root.destroy()
        return exc.exit_code
    if smoke:
        root.after(SMOKE_CLOSE_MS, root.destroy)
    root.mainloop()
    for line in problems:
        print(line, file=sys.stderr)
    return EXIT_IO if problems else EXIT_OK
