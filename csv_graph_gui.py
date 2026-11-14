"""Windows GUI for plotting numeric CSV columns and overlaying multiple files."""

from __future__ import annotations

import csv
import os
import re
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")
matplotlib.rcParams["font.family"] = ["Malgun Gothic"]
matplotlib.rcParams["axes.unicode_minus"] = False
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure


CONCENTRATION_PATTERN = re.compile(
    r"(?<![\d.])(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>mM|M|mol/L|mol)(?![A-Za-z])"
)


@dataclass(frozen=True)
class CsvDataset:
    path: Path
    columns: list[str]
    rows: list[dict[str, str]]


class CsvGraphApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CSV 그래프 도구")
        self.geometry("1320x900")
        self.minsize(980, 650)
        self.option_add("*Font", ("Malgun Gothic", 10))

        self.datasets: list[CsvDataset] = []
        self.x_column = tk.StringVar()
        self.y_column = tk.StringVar()
        self.title_text = tk.StringVar(value="CSV 그래프")
        self.status_text = tk.StringVar(value="CSV 파일을 불러오십시오.")
        self._configure_style()
        self._build_ui()

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
        ttk.Label(header, text="CSV 그래프 도구", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="다중 CSV 비교 · 그래프 오버레이 · PNG 저장", style="Subtitle.TLabel").pack(side="left", padx=(18, 0), pady=(7, 0))

        actions = ttk.Frame(self, padding=(18, 4, 18, 10))
        actions.pack(fill="x")
        ttk.Button(actions, text="CSV 파일 추가", style="Accent.TButton", command=self.add_files).pack(side="left")
        ttk.Button(actions, text="선택 파일 그래프", command=self.plot_selected).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="모든 파일 겹쳐 그리기", command=self.plot_overlay).pack(side="left", padx=8)
        ttk.Button(actions, text="농도별 평균 그래프", command=self.plot_concentration_averages).pack(side="left")
        ttk.Button(actions, text="그래프 미리보기", command=self.preview_graph).pack(side="left")
        ttk.Button(actions, text="434/578 흡광도 비", command=self.show_absorbance_ratio).pack(side="left", padx=(8, 0))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        controls = ttk.Frame(body, style="Card.TFrame", padding=14, width=350)
        graph_card = ttk.Frame(body, style="Card.TFrame", padding=8)
        body.add(controls, weight=0)
        body.add(graph_card, weight=1)
        self._build_controls(controls)
        self._build_graph(graph_card)
        ttk.Label(self, textvariable=self.status_text, style="Status.TLabel", anchor="w").pack(fill="x")

    def _build_controls(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="불러온 CSV 파일", style="CardTitle.TLabel").pack(anchor="w")
        list_frame = ttk.Frame(parent, style="Card.TFrame")
        list_frame.pack(fill="both", expand=True, pady=(6, 7))
        self.file_list = tk.Listbox(list_frame, height=10, exportselection=False, activestyle="none")
        file_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=file_scrollbar.set)
        self.file_list.pack(side="left", fill="both", expand=True)
        file_scrollbar.pack(side="right", fill="y")
        self.file_list.bind("<<ListboxSelect>>", self.on_file_select)
        buttons = ttk.Frame(parent, style="Card.TFrame")
        buttons.pack(fill="x")
        ttk.Button(buttons, text="선택 파일 제거", command=self.remove_selected).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(buttons, text="전체 비우기", command=self.clear_files).pack(side="left", fill="x", expand=True, padx=(3, 0))

        ttk.Separator(parent).pack(fill="x", pady=14)
        ttk.Label(parent, text="축과 제목", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(parent, text="X축 열", style="Card.TLabel").pack(anchor="w", pady=(7, 2))
        self.x_combo = ttk.Combobox(parent, textvariable=self.x_column, state="readonly")
        self.x_combo.pack(fill="x")
        ttk.Label(parent, text="Y축 열", style="Card.TLabel").pack(anchor="w", pady=(8, 2))
        self.y_combo = ttk.Combobox(parent, textvariable=self.y_column, state="readonly")
        self.y_combo.pack(fill="x")
        ttk.Label(parent, text="그래프 제목", style="Card.TLabel").pack(anchor="w", pady=(8, 2))
        ttk.Entry(parent, textvariable=self.title_text).pack(fill="x")

        ttk.Separator(parent).pack(fill="x", pady=14)
        ttk.Label(parent, text="내보내기", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Button(parent, text="현재 그래프 PNG 저장", command=self.save_png).pack(fill="x", pady=(7, 0))
        ttk.Label(parent, text="오버레이는 같은 열 이름을 우선 사용하고, 없으면 선택한 파일의 열 순서로 대체합니다. 평균은 파일명 속 0.4M_rep1, 400mM_2 형식의 농도를 인식합니다.", style="Card.TLabel", wraplength=290, justify="left").pack(anchor="w", pady=(10, 0))

    def _build_graph(self, parent: ttk.Frame) -> None:
        self.figure = Figure(figsize=(8.5, 6.2), dpi=100, facecolor="#ffffff")
        self.axis = self.figure.add_subplot(111)
        self.axis.set_title("CSV를 불러오면 그래프가 표시됩니다.", color="#536273")
        self.axis.set_xlabel("X")
        self.axis.set_ylabel("Y")
        self.axis.grid(True, alpha=0.25)
        self.canvas = FigureCanvasTkAgg(self.figure, master=parent)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        toolbar_frame = ttk.Frame(parent, style="Card.TFrame")
        toolbar_frame.pack(fill="x")
        toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side="left")

    @staticmethod
    def _read_csv(path: str) -> CsvDataset:
        decoding_errors: list[str] = []
        for encoding in ("utf-8-sig", "cp949", "utf-8"):
            try:
                with open(path, "r", encoding=encoding, newline="") as source:
                    sample = source.read(4096)
                    source.seek(0)
                    try:
                        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                    except csv.Error:
                        dialect = csv.excel
                    reader = csv.DictReader(source, dialect=dialect)
                    rows = [dict(row) for row in reader if row]
                    columns = list(reader.fieldnames or [])
                if not columns or any(not column.strip() for column in columns):
                    raise ValueError("CSV 첫 행에 유효한 열 이름이 필요합니다.")
                if not rows:
                    raise ValueError("헤더 다음에 데이터 행이 없습니다.")
                return CsvDataset(Path(path), columns, rows)
            except UnicodeDecodeError as exc:
                decoding_errors.append(str(exc))
        raise ValueError("지원 인코딩(UTF-8, CP949)으로 CSV를 읽지 못했습니다. " + " / ".join(decoding_errors))

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(title="CSV 파일 선택", filetypes=(("CSV 파일", "*.csv"), ("모든 파일", "*.*")))
        errors: list[str] = []
        added = 0
        for path in paths:
            if any(dataset.path == Path(path) for dataset in self.datasets):
                continue
            try:
                dataset = self._read_csv(path)
            except (OSError, ValueError, csv.Error) as exc:
                errors.append(f"{Path(path).name}: {exc}")
                continue
            self.datasets.append(dataset)
            self.file_list.insert(tk.END, dataset.path.name)
            added += 1
        if added and not self.file_list.curselection():
            self.file_list.selection_set(0)
            self.on_file_select()
        self.status_text.set(f"{added}개 파일을 추가했습니다. 총 {len(self.datasets)}개 파일")
        if errors:
            messagebox.showwarning("일부 파일을 읽지 못함", "\n".join(errors), parent=self)

    def on_file_select(self, _event=None) -> None:
        selection = self.file_list.curselection()
        if not selection:
            return
        dataset = self.datasets[selection[0]]
        self.x_combo["values"] = dataset.columns
        self.y_combo["values"] = dataset.columns
        self.x_column.set(dataset.columns[0])
        numeric = self._numeric_columns(dataset)
        y_candidates = [column for column in numeric if column != dataset.columns[0]]
        self.y_column.set(y_candidates[0] if y_candidates else (dataset.columns[1] if len(dataset.columns) > 1 else dataset.columns[0]))
        self.status_text.set(f"{dataset.path.name}: {len(dataset.rows)}개 행, {len(dataset.columns)}개 열")

    @staticmethod
    def _numeric_columns(dataset: CsvDataset) -> list[str]:
        columns: list[str] = []
        for column in dataset.columns:
            values = [row.get(column, "").strip() for row in dataset.rows]
            values = [value for value in values if value]
            if not values:
                continue
            try:
                [float(value) for value in values]
            except ValueError:
                continue
            columns.append(column)
        return columns

    def remove_selected(self) -> None:
        selection = self.file_list.curselection()
        if not selection:
            return
        index = selection[0]
        self.file_list.delete(index)
        del self.datasets[index]
        if self.datasets:
            self.file_list.selection_set(min(index, len(self.datasets) - 1))
            self.on_file_select()
        else:
            self.x_combo["values"] = []
            self.y_combo["values"] = []
            self.x_column.set("")
            self.y_column.set("")
        self.status_text.set(f"총 {len(self.datasets)}개 파일")

    def clear_files(self) -> None:
        self.datasets.clear()
        self.file_list.delete(0, tk.END)
        self.x_combo["values"] = []
        self.y_combo["values"] = []
        self.x_column.set("")
        self.y_column.set("")
        self.status_text.set("CSV 파일을 불러오십시오.")

    @staticmethod
    def _series(dataset: CsvDataset, x_name: str, y_name: str) -> tuple[list[float], list[float]]:
        x_values: list[float] = []
        y_values: list[float] = []
        for row in dataset.rows:
            try:
                x_values.append(float(row.get(x_name, "")))
                y_values.append(float(row.get(y_name, "")))
            except (TypeError, ValueError):
                continue
        return x_values, y_values

    def _selected_column_indexes(self) -> tuple[int, int] | None:
        columns = list(self.x_combo["values"])
        try:
            return columns.index(self.x_column.get()), columns.index(self.y_column.get())
        except ValueError:
            return None

    def _series_for_dataset(self, dataset: CsvDataset) -> tuple[list[float], list[float], bool]:
        """Use matching headers first, then fall back to the selected column positions."""
        x_name = self.x_column.get()
        y_name = self.y_column.get()
        if x_name in dataset.columns and y_name in dataset.columns:
            x_values, y_values = self._series(dataset, x_name, y_name)
            return x_values, y_values, False
        indexes = self._selected_column_indexes()
        if indexes is None:
            return [], [], False
        x_index, y_index = indexes
        if x_index >= len(dataset.columns) or y_index >= len(dataset.columns):
            return [], [], False
        x_values, y_values = self._series(dataset, dataset.columns[x_index], dataset.columns[y_index])
        return x_values, y_values, True

    @staticmethod
    def _concentration_from_path(path: Path) -> tuple[float, str] | None:
        match = CONCENTRATION_PATTERN.search(path.stem)
        if match is None:
            return None
        value = float(match.group("value").replace(",", "."))
        concentration_m = value / 1000 if match.group("unit") == "mM" else value
        return concentration_m, f"{concentration_m:g} M"

    def _prepare_plot(self) -> None:
        self.axis.clear()
        self.axis.grid(True, alpha=0.25)

    def _set_labels(self, overlay: bool = False) -> None:
        title = self.title_text.get().strip() or "CSV 그래프"
        self.axis.set_title(f"{title} - Overlay" if overlay else title)
        self.axis.set_xlabel(self.x_column.get())
        self.axis.set_ylabel(self.y_column.get())

    def plot_selected(self) -> None:
        selection = self.file_list.curselection()
        if not selection or not self.x_column.get() or not self.y_column.get():
            messagebox.showinfo("안내", "파일과 X/Y축 열을 선택하세요.", parent=self)
            return
        dataset = self.datasets[selection[0]]
        x_values, y_values = self._series(dataset, self.x_column.get(), self.y_column.get())
        if not x_values:
            messagebox.showerror("그래프 오류", "선택한 열에서 숫자 데이터를 찾지 못했습니다.", parent=self)
            return
        self._prepare_plot()
        self.axis.plot(x_values, y_values, marker="o", markersize=3, linewidth=1.2, label=dataset.path.name)
        self._set_labels()
        self.axis.legend()
        self.figure.tight_layout()
        self.canvas.draw()
        self.status_text.set(f"{dataset.path.name}: {len(x_values)}개 데이터 점을 표시했습니다.")

    def show_absorbance_ratio(self) -> None:
        """Show A578/A434 using the points nearest to 434 nm and 578 nm."""
        selection = self.file_list.curselection()
        if not selection or not self.x_column.get() or not self.y_column.get():
            messagebox.showinfo("안내", "파일과 파장(X축)·흡광도(Y축) 열을 선택하세요.", parent=self)
            return
        dataset = self.datasets[selection[0]]
        x_values, y_values = self._series(dataset, self.x_column.get(), self.y_column.get())
        if not x_values:
            messagebox.showerror("비율 계산 오류", "선택한 열에서 숫자 데이터를 찾지 못했습니다.", parent=self)
            return

        index_434 = min(range(len(x_values)), key=lambda index: abs(x_values[index] - 434.0))
        index_578 = min(range(len(x_values)), key=lambda index: abs(x_values[index] - 578.0))
        wavelength_434, absorbance_434 = x_values[index_434], y_values[index_434]
        wavelength_578, absorbance_578 = x_values[index_578], y_values[index_578]
        if absorbance_434 == 0:
            messagebox.showerror("비율 계산 오류", "434 nm 부근의 흡광도가 0이어서 비율을 계산할 수 없습니다.", parent=self)
            return

        ratio = absorbance_578 / absorbance_434
        messagebox.showinfo(
            "434/578 흡광도 비",
            f"파일: {dataset.path.name}\n\n"
            f"434 nm 부근: {wavelength_434:.3f} nm, 흡광도 {absorbance_434:.6g}\n"
            f"578 nm 부근: {wavelength_578:.3f} nm, 흡광도 {absorbance_578:.6g}\n\n"
            f"A578 / A434 = {ratio:.6g}",
            parent=self,
        )
        self.status_text.set(f"{dataset.path.name}: A578/A434 = {ratio:.6g}")

    def plot_overlay(self) -> None:
        if not self.datasets or not self.x_column.get() or not self.y_column.get():
            messagebox.showinfo("안내", "파일을 추가하고 X/Y축 열을 선택하세요.", parent=self)
            return
        self._prepare_plot()
        plotted = 0
        position_fallback_count = 0
        skipped: list[str] = []
        for dataset in self.datasets:
            x_values, y_values, used_position_fallback = self._series_for_dataset(dataset)
            if not x_values:
                skipped.append(dataset.path.name)
                continue
            self.axis.plot(x_values, y_values, marker="o", markersize=2.5, linewidth=1.2, label=dataset.path.name)
            plotted += 1
            position_fallback_count += used_position_fallback
        if not plotted:
            messagebox.showerror("그래프 오류", "겹쳐 그릴 수 있는 숫자 데이터를 찾지 못했습니다.", parent=self)
            return
        self._set_labels(overlay=True)
        self.axis.legend()
        self.figure.tight_layout()
        self.canvas.draw()
        fallback_text = f" {position_fallback_count}개 파일은 열 순서로 매칭했습니다." if position_fallback_count else ""
        skipped_text = f" 제외: {', '.join(skipped)}" if skipped else ""
        self.status_text.set(f"{plotted}개 파일을 하나의 그래프에 표시했습니다.{fallback_text}{skipped_text}")

    def plot_concentration_averages(self) -> None:
        if not self.datasets or not self.x_column.get() or not self.y_column.get():
            messagebox.showinfo("안내", "파일을 추가하고 X/Y축 열을 선택하세요.", parent=self)
            return
        grouped: dict[float, dict[float, list[float]]] = {}
        labels: dict[float, str] = {}
        file_counts: dict[float, int] = {}
        skipped: list[str] = []
        for dataset in self.datasets:
            concentration = self._concentration_from_path(dataset.path)
            x_values, y_values, _ = self._series_for_dataset(dataset)
            if concentration is None or not x_values:
                skipped.append(dataset.path.name)
                continue
            concentration_m, label = concentration
            per_file: dict[float, list[float]] = {}
            for x_value, y_value in zip(x_values, y_values):
                per_file.setdefault(round(x_value, 10), []).append(y_value)
            grouped.setdefault(concentration_m, {})
            labels[concentration_m] = label
            file_counts[concentration_m] = file_counts.get(concentration_m, 0) + 1
            for x_value, values in per_file.items():
                grouped[concentration_m].setdefault(x_value, []).append(sum(values) / len(values))

        self._prepare_plot()
        plotted = 0
        insufficient: list[str] = []
        for concentration_m in sorted(grouped):
            file_count = file_counts[concentration_m]
            common_points = [
                (x_value, values)
                for x_value, values in grouped[concentration_m].items()
                if file_count >= 2 and len(values) == file_count
            ]
            if not common_points:
                insufficient.append(labels[concentration_m])
                continue
            common_points.sort(key=lambda point: point[0])
            x_values = [point[0] for point in common_points]
            y_values = [sum(point[1]) / file_count for point in common_points]
            self.axis.plot(x_values, y_values, marker="o", markersize=2.5, linewidth=1.4, label=f"{labels[concentration_m]} 평균 (n={file_count})")
            plotted += 1
        if not plotted:
            messagebox.showerror("평균 그래프 오류", "같은 농도에서 2개 이상이며 공통 X값을 가진 파일을 찾지 못했습니다. 파일명에 예: 0.4M_rep1 형식으로 농도를 넣으세요.", parent=self)
            return
        self._set_labels(overlay=True)
        self.axis.set_title((self.title_text.get().strip() or "CSV 그래프") + " - 농도별 평균")
        self.axis.legend()
        self.figure.tight_layout()
        self.canvas.draw()
        details: list[str] = []
        if skipped:
            details.append(f"농도/숫자 데이터 미인식: {', '.join(skipped)}")
        if insufficient:
            details.append(f"반복 또는 공통 X값 부족: {', '.join(insufficient)}")
        self.status_text.set(f"{plotted}개 농도의 평균 그래프를 표시했습니다." + (" " + " | ".join(details) if details else ""))

    def preview_graph(self) -> None:
        if not self.axis.lines:
            messagebox.showinfo("안내", "먼저 그래프를 그려 주세요.", parent=self)
            return
        preview = tk.Toplevel(self)
        preview.title("그래프 미리보기")
        preview.geometry("1050x720")
        preview.minsize(700, 500)
        preview.rowconfigure(1, weight=1)
        preview.columnconfigure(0, weight=1)
        ttk.Label(preview, text="현재 그래프 미리보기", padding=(10, 8)).grid(row=0, column=0, sticky="w")
        figure = Figure(figsize=(9, 6), dpi=100)
        axis = figure.add_subplot(111)
        for line in self.axis.lines:
            axis.plot(line.get_xdata(), line.get_ydata(), label=line.get_label(), color=line.get_color(), marker=line.get_marker(), markersize=line.get_markersize(), linewidth=line.get_linewidth(), linestyle=line.get_linestyle())
        axis.set_title(self.axis.get_title())
        axis.set_xlabel(self.axis.get_xlabel())
        axis.set_ylabel(self.axis.get_ylabel())
        axis.grid(True, alpha=0.25)
        axis.legend()
        figure.tight_layout()
        canvas = FigureCanvasTkAgg(figure, master=preview)
        canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        toolbar = NavigationToolbar2Tk(canvas, preview, pack_toolbar=False)
        toolbar.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        canvas.draw()

    def save_png(self) -> None:
        if not self.axis.lines:
            messagebox.showinfo("안내", "저장할 그래프가 없습니다.", parent=self)
            return
        filename = filedialog.asksaveasfilename(title="그래프 PNG 저장", defaultextension=".png", filetypes=(("PNG 이미지", "*.png"),))
        if not filename:
            return
        try:
            self.figure.savefig(filename, dpi=180, bbox_inches="tight")
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc), parent=self)
            return
        self.status_text.set(f"그래프를 저장했습니다: {os.path.basename(filename)}")


def main() -> int:
    CsvGraphApp().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
