"""Korean desktop GUI for Vernier spectrum-file analysis."""

from __future__ import annotations

import argparse
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")
matplotlib.rcParams["font.family"] = ["Malgun Gothic"]
matplotlib.rcParams["axes.unicode_minus"] = False
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import numpy as np

from spectrum_core import (
    SpectrumFile,
    SpectrumSeries,
    absorbance_from_transmittance,
    export_series_csv,
    is_transmittance,
    load_spectrum_csv,
    nearest_point,
    summarize_region,
)
from research_window import ResearchAnalysisWindow


TARGETS_NM = (434.0, 578.0)


class SpectrumApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Vernier 스펙트럼 분석기")
        self.geometry("1320x900")
        self.minsize(1030, 680)
        self.option_add("*Font", ("Malgun Gothic", 10))

        self.dataset: SpectrumFile | None = None
        self.extra_series: list[SpectrumSeries] = []
        self.current_series: SpectrumSeries | None = None
        self.selection_artist = None
        self.selection_marker = None
        self.selection_annotation = None
        self.research_window: ResearchAnalysisWindow | None = None

        self.series_name = tk.StringVar()
        self.window_half_width = tk.DoubleVar(value=5.0)
        self.export_range = tk.StringVar(value="전체 파장")
        self.status_text = tk.StringVar(value="CSV, TXT, TSV 또는 XLSX 스펙트럼 파일을 불러오십시오.")
        self.file_text = tk.StringVar(value="불러온 파일 없음")
        self.clicked_wavelength = tk.StringVar(value="-")
        self.clicked_value = tk.StringVar(value="-")
        self._summary_vars = {
            target: {
                key: tk.StringVar(value="-")
                for key in ("nearest", "max", "min", "mean", "count")
            }
            for target in TARGETS_NM
        }

        self._configure_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f3f5f7")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#f3f5f7", foreground="#152238", font=("Malgun Gothic", 18, "bold"))
        style.configure("Subtitle.TLabel", background="#f3f5f7", foreground="#536273")
        style.configure("CardTitle.TLabel", background="#ffffff", foreground="#152238", font=("Malgun Gothic", 11, "bold"))
        style.configure("Card.TLabel", background="#ffffff", foreground="#26384d")
        style.configure("Accent.TButton", font=("Malgun Gothic", 10, "bold"), foreground="#ffffff", background="#1d64d8")
        style.map("Accent.TButton", background=[("active", "#164fae")])
        style.configure("Status.TLabel", background="#17263c", foreground="#ffffff", padding=(10, 7))

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(18, 14, 18, 8))
        header.pack(fill="x")
        ttk.Label(header, text="Vernier 스펙트럼 분석기", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="흡광 스펙트럼 · 434 nm / 578 nm 집중 분석",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(18, 0), pady=(7, 0))

        actions = ttk.Frame(self, padding=(18, 4, 18, 10))
        actions.pack(fill="x")
        ttk.Button(actions, text="CSV 불러오기", style="Accent.TButton", command=self.open_csv).pack(side="left")
        ttk.Button(actions, text="NaCl 연구 분석", command=self.open_research_window).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="그래프 초기화", command=self.reset_view).pack(side="left", padx=8)
        ttk.Label(actions, textvariable=self.file_text, style="Subtitle.TLabel").pack(side="left", padx=18)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        controls_holder = ttk.Frame(body, style="Card.TFrame", width=350)
        graph_card = ttk.Frame(body, style="Card.TFrame", padding=8)
        body.add(controls_holder, weight=0)
        body.add(graph_card, weight=1)

        controls_canvas = tk.Canvas(controls_holder, background="#ffffff", highlightthickness=0, width=330)
        controls_scrollbar = ttk.Scrollbar(controls_holder, orient="vertical", command=controls_canvas.yview)
        controls = ttk.Frame(controls_canvas, style="Card.TFrame", padding=14)
        controls_window = controls_canvas.create_window((0, 0), window=controls, anchor="nw")
        controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
        controls_canvas.pack(side="left", fill="both", expand=True)
        controls_scrollbar.pack(side="right", fill="y")
        controls.bind(
            "<Configure>",
            lambda _event: controls_canvas.configure(scrollregion=controls_canvas.bbox("all")),
        )
        controls_canvas.bind(
            "<Configure>",
            lambda event: controls_canvas.itemconfigure(controls_window, width=event.width),
        )
        controls_canvas.bind(
            "<MouseWheel>",
            lambda event: controls_canvas.yview_scroll(int(-event.delta / 120), "units"),
        )
        self._build_controls(controls)
        self._build_graph(graph_card)

        ttk.Label(self, textvariable=self.status_text, style="Status.TLabel", anchor="w").pack(fill="x")

    def _build_controls(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="데이터 선택", style="CardTitle.TLabel").pack(anchor="w")
        self.series_combo = ttk.Combobox(parent, textvariable=self.series_name, state="readonly", width=34)
        self.series_combo.pack(fill="x", pady=(6, 10))
        self.series_combo.bind("<<ComboboxSelected>>", self._on_series_selected)
        self.convert_button = ttk.Button(parent, text="투과율 → 흡광도 변환", command=self.convert_to_absorbance, state="disabled")
        self.convert_button.pack(fill="x")

        ttk.Separator(parent).pack(fill="x", pady=14)
        ttk.Label(parent, text="집중 분석 영역", style="CardTitle.TLabel").pack(anchor="w")
        width_row = ttk.Frame(parent, style="Card.TFrame")
        width_row.pack(fill="x", pady=(7, 8))
        ttk.Label(width_row, text="영역 반폭", style="Card.TLabel").pack(side="left")
        spin = ttk.Spinbox(width_row, from_=0.5, to=50, increment=0.5, textvariable=self.window_half_width, width=8, command=self.refresh_summaries)
        spin.pack(side="left", padx=8)
        ttk.Label(width_row, text="nm", style="Card.TLabel").pack(side="left")
        spin.bind("<Return>", lambda _event: self.refresh_summaries())
        spin.bind("<FocusOut>", lambda _event: self.refresh_summaries())

        for target in TARGETS_NM:
            self._build_target_card(parent, target)

        ttk.Separator(parent).pack(fill="x", pady=14)
        ttk.Label(parent, text="클릭한 지점", style="CardTitle.TLabel").pack(anchor="w")
        click_grid = ttk.Frame(parent, style="Card.TFrame")
        click_grid.pack(fill="x", pady=(6, 0))
        ttk.Label(click_grid, text="파장", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(click_grid, textvariable=self.clicked_wavelength, style="Card.TLabel").grid(row=0, column=1, sticky="e")
        ttk.Label(click_grid, text="측정값", style="Card.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Label(click_grid, textvariable=self.clicked_value, style="Card.TLabel").grid(row=1, column=1, sticky="e")
        click_grid.columnconfigure(1, weight=1)

        ttk.Separator(parent).pack(fill="x", pady=14)
        ttk.Label(parent, text="CSV 내보내기", style="CardTitle.TLabel").pack(anchor="w")
        self.export_combo = ttk.Combobox(
            parent,
            textvariable=self.export_range,
            state="readonly",
            values=("전체 파장", "434 nm 영역", "578 nm 영역", "현재 그래프 범위"),
        )
        self.export_combo.pack(fill="x", pady=(6, 7))
        ttk.Button(parent, text="선택 범위 CSV 저장", command=self.export_csv).pack(fill="x")

    def _build_target_card(self, parent: ttk.Frame, target: float) -> None:
        frame = tk.Frame(parent, background="#edf4ff", highlightbackground="#cadbf7", highlightthickness=1, padx=9, pady=7)
        frame.pack(fill="x", pady=4)
        top = tk.Frame(frame, background="#edf4ff")
        top.pack(fill="x")
        tk.Label(top, text=f"{target:g} nm", background="#edf4ff", foreground="#154c9f", font=("Malgun Gothic", 11, "bold")).pack(side="left")
        ttk.Button(top, text="확대", command=lambda value=target: self.focus_target(value)).pack(side="right")
        details = tk.Frame(frame, background="#edf4ff")
        details.pack(fill="x", pady=(4, 0))
        labels = (("최근접", "nearest"), ("최대", "max"), ("최소", "min"), ("평균", "mean"), ("표본 수", "count"))
        for row, (label, key) in enumerate(labels):
            tk.Label(details, text=label, background="#edf4ff", foreground="#52637a").grid(row=row, column=0, sticky="w", pady=1)
            tk.Label(details, textvariable=self._summary_vars[target][key], background="#edf4ff", foreground="#1b2d45").grid(row=row, column=1, sticky="e", pady=1)
        details.columnconfigure(1, weight=1)

    def _build_graph(self, parent: ttk.Frame) -> None:
        self.figure = Figure(figsize=(8.5, 6.2), dpi=100, facecolor="#ffffff")
        self.axes = self.figure.add_subplot(111)
        self.axes.set_title("CSV를 불러오면 스펙트럼이 표시됩니다.", color="#536273")
        self.axes.set_xlabel("파장 (nm)")
        self.axes.set_ylabel("측정값")
        self.axes.grid(True, alpha=0.22)
        self.canvas = FigureCanvasTkAgg(self.figure, master=parent)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        toolbar_frame = ttk.Frame(parent, style="Card.TFrame")
        toolbar_frame.pack(fill="x")
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side="left")
        ttk.Label(toolbar_frame, text="그래프를 클릭하면 가장 가까운 측정점을 표시합니다.", style="Card.TLabel").pack(side="right", padx=8)
        self.canvas.mpl_connect("button_press_event", self._on_graph_click)

    def open_csv(self, filename: str | None = None) -> None:
        if filename is None:
            filename = filedialog.askopenfilename(
                title="스펙트럼 CSV 불러오기",
                filetypes=(("CSV 및 텍스트", "*.csv *.txt *.tsv"), ("모든 파일", "*.*")),
            )
        if not filename:
            return
        try:
            dataset = load_spectrum_csv(filename)
        except Exception as exc:
            messagebox.showerror("CSV 불러오기 실패", str(exc), parent=self)
            return
        self.dataset = dataset
        self.extra_series.clear()
        names = [item.label for item in dataset.series]
        self.series_combo["values"] = names
        self.series_name.set(names[0])
        self.current_series = dataset.series[0]
        self.file_text.set(f"{dataset.source.name} · {len(dataset.series)}개 측정 열")
        self.plot_current_series()
        self.status_text.set(
            f"{dataset.source.name}을 불러왔습니다. 인코딩 {dataset.encoding}, 구분자 {repr(dataset.delimiter)}"
        )

    def open_research_window(self) -> None:
        if self.research_window is not None and self.research_window.winfo_exists():
            self.research_window.deiconify()
            self.research_window.lift()
            self.research_window.focus_force()
            return
        self.research_window = ResearchAnalysisWindow(self, lambda: self.current_series)

    def _all_series(self) -> list[SpectrumSeries]:
        base = list(self.dataset.series) if self.dataset else []
        return base + self.extra_series

    def _on_series_selected(self, _event=None) -> None:
        name = self.series_name.get()
        self.current_series = next((item for item in self._all_series() if item.label == name), None)
        self.plot_current_series()

    def plot_current_series(self) -> None:
        series = self.current_series
        if series is None:
            return
        self.axes.clear()
        self.axes.plot(series.wavelength_nm, series.values, color="#1769d2", linewidth=1.55)
        half_width = self._valid_half_width(show_error=False)
        if half_width is not None:
            colors = ("#5b8ff9", "#f6bd16")
            for target, color in zip(TARGETS_NM, colors):
                self.axes.axvspan(target - half_width, target + half_width, color=color, alpha=0.13)
                self.axes.axvline(target, color=color, linewidth=0.9, linestyle="--", alpha=0.8)
        self.axes.set_xlabel("파장 (nm)")
        ylabel = series.label
        if series.value_unit and series.value_unit.casefold() not in ylabel.casefold():
            ylabel = f"{ylabel} ({series.value_unit})"
        self.axes.set_ylabel(ylabel)
        self.axes.set_title(series.label, color="#152238", pad=10)
        self.axes.grid(True, alpha=0.22)
        self.axes.margins(x=0.015, y=0.08)
        self.figure.tight_layout()
        self.selection_artist = None
        self.selection_marker = None
        self.selection_annotation = None
        self.clicked_wavelength.set("-")
        self.clicked_value.set("-")
        self.convert_button.configure(state="normal" if is_transmittance(series) else "disabled")
        self.refresh_summaries(redraw=False)
        self.canvas.draw_idle()

    def _valid_half_width(self, show_error: bool = True) -> float | None:
        try:
            value = float(self.window_half_width.get())
            if value <= 0:
                raise ValueError
            return value
        except (tk.TclError, ValueError):
            if show_error:
                messagebox.showerror("입력 오류", "영역 반폭은 0보다 큰 숫자여야 합니다.", parent=self)
            return None

    def refresh_summaries(self, redraw: bool = True) -> None:
        series = self.current_series
        half_width = self._valid_half_width()
        if series is None or half_width is None:
            return
        for target in TARGETS_NM:
            fields = self._summary_vars[target]
            try:
                summary = summarize_region(series, target, half_width)
                fields["nearest"].set(f"{summary.nearest_wavelength_nm:.2f} nm · {summary.nearest_value:.5g}")
                fields["max"].set(f"{summary.maximum_wavelength_nm:.2f} nm · {summary.maximum_value:.5g}")
                fields["min"].set(f"{summary.minimum_wavelength_nm:.2f} nm · {summary.minimum_value:.5g}")
                fields["mean"].set(f"{summary.mean_value:.5g}")
                fields["count"].set(str(summary.count))
            except ValueError:
                for variable in fields.values():
                    variable.set("범위 밖")
        if redraw:
            self.plot_current_series()

    def focus_target(self, target: float) -> None:
        if self.current_series is None:
            messagebox.showinfo("데이터 필요", "먼저 CSV를 불러오십시오.", parent=self)
            return
        half_width = self._valid_half_width()
        if half_width is None:
            return
        display_half_width = max(10.0, half_width * 2.5)
        self.axes.set_xlim(target - display_half_width, target + display_half_width)
        mask = np.abs(self.current_series.wavelength_nm - target) <= display_half_width
        if np.any(mask):
            values = self.current_series.values[mask]
            low, high = float(np.min(values)), float(np.max(values))
            padding = max((high - low) * 0.12, 1e-9)
            self.axes.set_ylim(low - padding, high + padding)
        self.canvas.draw_idle()
        self.status_text.set(f"{target:g} nm 주변을 확대했습니다.")

    def reset_view(self) -> None:
        if self.current_series is not None:
            self.plot_current_series()

    def _on_graph_click(self, event) -> None:
        if event.inaxes is not self.axes or event.xdata is None or self.current_series is None:
            return
        wavelength, value, _ = nearest_point(self.current_series, float(event.xdata))
        self.clicked_wavelength.set(f"{wavelength:.3f} nm")
        unit = f" {self.current_series.value_unit}" if self.current_series.value_unit else ""
        self.clicked_value.set(f"{value:.7g}{unit}")
        if self.selection_artist is not None:
            self.selection_artist.remove()
        if self.selection_marker is not None:
            self.selection_marker.remove()
        if self.selection_annotation is not None:
            self.selection_annotation.remove()
        self.selection_artist = self.axes.axvline(wavelength, color="#d34242", linewidth=1.0, alpha=0.75)
        (self.selection_marker,) = self.axes.plot([wavelength], [value], marker="o", markersize=7, color="#d34242")
        self.selection_annotation = self.axes.annotate(
            f"{wavelength:.2f} nm\n{value:.5g}{unit}",
            xy=(wavelength, value),
            xytext=(12, 14),
            textcoords="offset points",
            bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "#d34242", "alpha": 0.95},
            arrowprops={"arrowstyle": "->", "color": "#d34242"},
        )
        self.canvas.draw_idle()
        self.status_text.set(f"최근접 측정점: {wavelength:.3f} nm, {value:.7g}{unit}")

    def convert_to_absorbance(self) -> None:
        if self.current_series is None:
            return
        try:
            converted = absorbance_from_transmittance(self.current_series)
        except ValueError as exc:
            messagebox.showerror("변환 실패", str(exc), parent=self)
            return
        self.extra_series.append(converted)
        names = [item.label for item in self._all_series()]
        self.series_combo["values"] = names
        self.series_name.set(converted.label)
        self.current_series = converted
        self.plot_current_series()
        self.status_text.set("투과율을 A = -log10(T)로 변환했습니다. 원본 열은 보존되어 있습니다.")

    def _export_limits(self) -> tuple[float | None, float | None, str]:
        choice = self.export_range.get()
        half_width = self._valid_half_width()
        if choice == "434 nm 영역" and half_width is not None:
            return 434.0 - half_width, 434.0 + half_width, "434nm"
        if choice == "578 nm 영역" and half_width is not None:
            return 578.0 - half_width, 578.0 + half_width, "578nm"
        if choice == "현재 그래프 범위":
            lower, upper = self.axes.get_xlim()
            return float(lower), float(upper), "view"
        return None, None, "full"

    def export_csv(self) -> None:
        if self.current_series is None or self.dataset is None:
            messagebox.showinfo("데이터 필요", "먼저 CSV를 불러오십시오.", parent=self)
            return
        lower, upper, suffix = self._export_limits()
        suggested = f"{self.dataset.source.stem}_{suffix}.csv"
        filename = filedialog.asksaveasfilename(
            title="파장별 CSV 저장",
            defaultextension=".csv",
            initialfile=suggested,
            filetypes=(("CSV", "*.csv"),),
        )
        if not filename:
            return
        try:
            count = export_series_csv(filename, self.current_series, lower, upper)
        except Exception as exc:
            messagebox.showerror("CSV 저장 실패", str(exc), parent=self)
            return
        self.status_text.set(f"{Path(filename).name}에 {count}개 파장 데이터를 저장했습니다.")
        messagebox.showinfo("저장 완료", f"{count}개 행을 UTF-8 CSV로 저장했습니다.", parent=self)

    def _on_close(self) -> None:
        self.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="Vernier spectrum CSV analyzer")
    parser.add_argument("csv", nargs="?", help="시작할 때 불러올 CSV")
    parser.add_argument("--smoke-test", action="store_true", help="GUI 생성 후 즉시 종료")
    args = parser.parse_args()
    app = SpectrumApp()
    if args.csv:
        app.after(50, lambda: app.open_csv(args.csv))
    if args.smoke_test:
        app.open_research_window()
        app.update_idletasks()
        app.update()
        app.destroy()
        return 0
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
