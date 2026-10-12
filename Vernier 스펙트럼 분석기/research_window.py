"""Tkinter research-analysis window for the NaCl-mCP experiment."""

from __future__ import annotations

import csv
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from research_analysis import (
    METRIC_LABELS,
    ResearchMeasurement,
    average_spectrum,
    calculate_metrics,
    fit_linear_calibration,
    infer_sample_metadata,
    summarize_groups,
)
from spectrum_core import SpectrumSeries, is_transmittance, load_spectrum_file


CONCENTRATION_CHOICES = ("미지", "0.0", "0.4", "0.6", "0.8", "1.0", "1.2", "1.4", "1.6")


class ResearchAnalysisWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        current_series_getter: Callable[[], SpectrumSeries | None],
    ) -> None:
        super().__init__(master)
        self.title("NaCl-mCP 연구 분석")
        self.geometry("1420x900")
        self.minsize(1120, 720)
        self.current_series_getter = current_series_getter
        self.measurements: list[ResearchMeasurement] = []
        self._row_to_index: dict[str, int] = {}

        self.concentration = tk.StringVar(value="0.4")
        self.replicate = tk.IntVar(value=1)
        self.sample_id = tk.StringVar(value="")
        self.half_width = tk.DoubleVar(value=5.0)
        self.metric_label = tk.StringVar(value=METRIC_LABELS["ratio"])
        self.status = tk.StringVar(
            value="표준 시료는 농도를 지정하고, 미지 시료는 '미지'로 등록하십시오."
        )
        self.fit_text = tk.StringVar(value="회귀식: 데이터 필요")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(16, 12, 16, 8))
        header.pack(fill="x")
        ttk.Label(header, text="NaCl 농도별 mCP 가시광 흡수 스펙트럼", font=("Malgun Gothic", 16, "bold")).pack(side="left")
        ttk.Label(
            header,
            text="권장 조건: 0.0, 0.4-1.6 M · 농도별 3회 반복 · 400-700 nm",
            foreground="#536273",
        ).pack(side="left", padx=18, pady=(5, 0))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        left = ttk.Frame(body, padding=10, width=420)
        right = ttk.Frame(body, padding=6)
        body.add(left, weight=0)
        body.add(right, weight=1)
        self._build_controls(left)
        self._build_plots(right)
        ttk.Label(self, textvariable=self.status, anchor="w", padding=(10, 7), background="#17263c", foreground="white").pack(fill="x")

    def _build_controls(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="시료 정보", font=("Malgun Gothic", 11, "bold")).pack(anchor="w")
        form = ttk.Frame(parent)
        form.pack(fill="x", pady=(6, 8))
        ttk.Label(form, text="NaCl 농도 (M)").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Combobox(form, textvariable=self.concentration, values=CONCENTRATION_CHOICES, width=12).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(form, text="반복 번호").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Spinbox(form, from_=1, to=99, textvariable=self.replicate, width=8).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(form, text="시료 이름").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.sample_id).grid(row=2, column=1, sticky="ew", pady=3)
        form.columnconfigure(1, weight=1)

        buttons = ttk.Frame(parent)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="현재 스펙트럼 등록", command=self.add_current_series).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(buttons, text="파일 일괄 추가", command=self.add_files).grid(row=0, column=1, sticky="ew", padx=(3, 0))
        ttk.Button(buttons, text="선택 정보 수정", command=self.update_selected).grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=(6, 0))
        ttk.Button(buttons, text="선택 삭제", command=self.remove_selected).grid(row=1, column=1, sticky="ew", padx=(3, 0), pady=(6, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)

        ttk.Separator(parent).pack(fill="x", pady=12)
        ttk.Label(parent, text="등록된 측정", font=("Malgun Gothic", 11, "bold")).pack(anchor="w")
        table_frame = ttk.Frame(parent)
        table_frame.pack(fill="both", expand=True, pady=(6, 8))
        self.table = ttk.Treeview(
            table_frame,
            columns=("sample", "concentration", "replicate", "a434", "a578", "ratio"),
            show="headings",
            height=15,
        )
        columns = {
            "sample": ("시료", 130),
            "concentration": ("M", 55),
            "replicate": ("반복", 48),
            "a434": ("A434", 70),
            "a578": ("A578", 70),
            "ratio": ("비", 70),
        }
        for name, (label, width) in columns.items():
            self.table.heading(name, text=label)
            self.table.column(name, width=width, stretch=name == "sample", anchor="center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.table.bind("<<TreeviewSelect>>", self._load_selected_metadata)

        analysis = ttk.LabelFrame(parent, text="분석 설정", padding=8)
        analysis.pack(fill="x")
        ttk.Label(analysis, text="영역 반폭 (nm)").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(analysis, from_=0.5, to=20, increment=0.5, textvariable=self.half_width, width=8).grid(row=0, column=1, sticky="e")
        ttk.Label(analysis, text="회귀 지표").grid(row=1, column=0, sticky="w", pady=(5, 0))
        metric_combo = ttk.Combobox(analysis, textvariable=self.metric_label, state="readonly", values=tuple(METRIC_LABELS.values()), width=20)
        metric_combo.grid(row=1, column=1, sticky="ew", pady=(5, 0))
        metric_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        analysis.columnconfigure(1, weight=1)
        ttk.Button(analysis, text="분석 갱신", command=self.refresh).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        ttk.Label(analysis, textvariable=self.fit_text, wraplength=360, justify="left").grid(row=3, column=0, columnspan=2, sticky="w", pady=(7, 0))

        export = ttk.Frame(parent)
        export.pack(fill="x", pady=(8, 0))
        ttk.Button(export, text="요약 CSV 저장", command=self.export_summary).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(export, text="그래프 PNG 저장", command=self.export_figure).pack(side="left", fill="x", expand=True, padx=(3, 0))

    def _build_plots(self, parent: ttk.Frame) -> None:
        self.figure = Figure(figsize=(9.0, 7.2), dpi=100, facecolor="white")
        self.spectrum_axes = self.figure.add_subplot(211)
        self.calibration_axes = self.figure.add_subplot(212)
        self._empty_axes()
        self.canvas = FigureCanvasTkAgg(self.figure, master=parent)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(self.canvas, parent, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(fill="x")

    def _empty_axes(self) -> None:
        self.spectrum_axes.clear()
        self.spectrum_axes.set_title("농도별 평균 스펙트럼")
        self.spectrum_axes.set_xlabel("파장 (nm)")
        self.spectrum_axes.set_ylabel("흡광도 (A.U.)")
        self.spectrum_axes.set_xlim(400, 700)
        self.spectrum_axes.grid(True, alpha=0.22)
        self.calibration_axes.clear()
        self.calibration_axes.set_title("NaCl 농도-스펙트럼 지표")
        self.calibration_axes.set_xlabel("NaCl 농도 (M)")
        self.calibration_axes.set_ylabel("분석 지표")
        self.calibration_axes.grid(True, alpha=0.22)
        self.figure.tight_layout()

    def _parse_form(self) -> tuple[float | None, int, str]:
        text = self.concentration.get().strip()
        concentration = None if not text or text == "미지" else float(text)
        if concentration is not None and concentration < 0:
            raise ValueError("농도는 0 이상이어야 합니다.")
        replicate = int(self.replicate.get())
        if replicate < 1:
            raise ValueError("반복 번호는 1 이상이어야 합니다.")
        sample_id = self.sample_id.get().strip()
        return concentration, replicate, sample_id

    def _normalized_series(self, series: SpectrumSeries) -> SpectrumSeries:
        if is_transmittance(series):
            raise ValueError("투과율 데이터입니다. 기본 창에서 흡광도로 변환한 뒤 등록하십시오.")
        return series

    def add_current_series(self) -> None:
        series = self.current_series_getter()
        if series is None:
            messagebox.showinfo("스펙트럼 필요", "기본 창에서 CSV를 불러오거나 분광기로 측정하십시오.", parent=self)
            return
        try:
            concentration, replicate, sample_id = self._parse_form()
            series = self._normalized_series(series)
            if not sample_id:
                sample_id = series.label
            self.measurements.append(ResearchMeasurement(sample_id, concentration, replicate, series, "현재 스펙트럼"))
        except Exception as exc:
            messagebox.showerror("등록 실패", str(exc), parent=self)
            return
        self.refresh()

    def add_files(self) -> None:
        filenames = filedialog.askopenfilenames(
            title="스펙트럼 파일 일괄 추가",
            filetypes=(("스펙트럼 파일", "*.csv *.txt *.tsv *.xlsx"), ("모든 파일", "*.*")),
            parent=self,
        )
        if not filenames:
            return
        added = 0
        failures: list[str] = []
        for filename in filenames:
            try:
                dataset = load_spectrum_file(filename)
                for number, series in enumerate(dataset.series, start=1):
                    series = self._normalized_series(series)
                    text = f"{dataset.source.stem} {series.label}"
                    concentration, replicate = infer_sample_metadata(text)
                    sample_id = dataset.source.stem if len(dataset.series) == 1 else f"{dataset.source.stem} - {series.label}"
                    if len(dataset.series) > 1 and replicate == 1:
                        replicate = number
                    self.measurements.append(ResearchMeasurement(sample_id, concentration, replicate, series, dataset.source.name))
                    added += 1
            except Exception as exc:
                failures.append(f"{Path(filename).name}: {exc}")
        self.refresh()
        if failures:
            messagebox.showwarning("일부 파일 실패", "\n".join(failures[:8]), parent=self)
        self.status.set(f"{added}개 스펙트럼을 추가했습니다. 농도가 '미지'인 행은 선택하여 수정할 수 있습니다.")

    def _selected_index(self) -> int | None:
        selected = self.table.selection()
        if not selected:
            return None
        return self._row_to_index.get(selected[0])

    def _load_selected_metadata(self, _event=None) -> None:
        index = self._selected_index()
        if index is None:
            return
        measurement = self.measurements[index]
        self.concentration.set("미지" if measurement.concentration_m is None else f"{measurement.concentration_m:g}")
        self.replicate.set(measurement.replicate)
        self.sample_id.set(measurement.sample_id)

    def update_selected(self) -> None:
        index = self._selected_index()
        if index is None:
            messagebox.showinfo("선택 필요", "수정할 행을 선택하십시오.", parent=self)
            return
        try:
            concentration, replicate, sample_id = self._parse_form()
            old = self.measurements[index]
            self.measurements[index] = ResearchMeasurement(sample_id or old.sample_id, concentration, replicate, old.series, old.source)
        except Exception as exc:
            messagebox.showerror("수정 실패", str(exc), parent=self)
            return
        self.refresh()

    def remove_selected(self) -> None:
        indices = sorted(
            (self._row_to_index[item] for item in self.table.selection() if item in self._row_to_index),
            reverse=True,
        )
        for index in indices:
            self.measurements.pop(index)
        self.refresh()

    def _metric_key(self) -> str:
        selected = self.metric_label.get()
        return next((key for key, label in METRIC_LABELS.items() if label == selected), "ratio")

    def _half_width_value(self) -> float:
        value = float(self.half_width.get())
        if value <= 0:
            raise ValueError("영역 반폭은 0보다 커야 합니다.")
        return value

    def refresh(self) -> None:
        try:
            half_width = self._half_width_value()
        except Exception as exc:
            messagebox.showerror("분석 설정 오류", str(exc), parent=self)
            return
        self.table.delete(*self.table.get_children())
        self._row_to_index.clear()
        valid_count = 0
        for index, measurement in enumerate(self.measurements):
            try:
                metrics = calculate_metrics(measurement.series, half_width)
                values = (
                    measurement.sample_id,
                    "미지" if measurement.concentration_m is None else f"{measurement.concentration_m:g}",
                    measurement.replicate,
                    f"{metrics.a434:.5f}",
                    f"{metrics.a578:.5f}",
                    f"{metrics.ratio:.5f}",
                )
                valid_count += 1
            except ValueError as exc:
                values = (measurement.sample_id, "오류", measurement.replicate, "-", "-", str(exc)[:18])
            row = self.table.insert("", "end", values=values)
            self._row_to_index[row] = index
        self._draw_analysis(half_width)
        self.status.set(f"등록 {len(self.measurements)}개 · 분석 가능 {valid_count}개 · 영역 평균 ±{half_width:g} nm")

    def _draw_analysis(self, half_width: float) -> None:
        self._empty_axes()
        known = [item for item in self.measurements if item.concentration_m is not None]
        grouped: dict[float, list[ResearchMeasurement]] = {}
        for item in known:
            grouped.setdefault(float(item.concentration_m), []).append(item)
        palette = ["#315efb", "#00a67d", "#8f5bd7", "#f08c2e", "#d34242", "#00a0c6", "#6f7f3f", "#7a5c45"]
        for color, (concentration, items) in zip(palette, sorted(grouped.items())):
            for item in items:
                self.spectrum_axes.plot(item.series.wavelength_nm, item.series.values, color=color, alpha=0.16, linewidth=0.8)
            try:
                mean_series = average_spectrum(items)
                self.spectrum_axes.plot(mean_series.wavelength_nm, mean_series.values, color=color, linewidth=1.8, label=f"{concentration:g} M (n={len(items)})")
            except ValueError:
                continue
        self.spectrum_axes.axvline(434, color="#315efb", linestyle="--", linewidth=0.8, alpha=0.7)
        self.spectrum_axes.axvline(578, color="#d34242", linestyle="--", linewidth=0.8, alpha=0.7)
        self.spectrum_axes.set_xlim(400, 700)
        if grouped:
            self.spectrum_axes.legend(fontsize=8, ncol=2)

        metric = self._metric_key()
        try:
            fit = fit_linear_calibration(self.measurements, metric, half_width)
        except ValueError as exc:
            self.fit_text.set(f"회귀식: {exc}")
            self.canvas.draw_idle()
            return
        self.calibration_axes.errorbar(
            fit.concentrations,
            fit.values,
            yerr=fit.standard_deviations,
            fmt="o",
            capsize=4,
            color="#1769d2",
            label="농도별 평균 ± 표준편차",
        )
        line_x = np.linspace(float(np.min(fit.concentrations)), float(np.max(fit.concentrations)), 200)
        self.calibration_axes.plot(line_x, fit.slope * line_x + fit.intercept, color="#d34242", label="선형 회귀")
        unknown_lines: list[str] = []
        for item in self.measurements:
            if item.concentration_m is not None:
                continue
            try:
                value = calculate_metrics(item.series, half_width).value(metric)
                predicted = fit.predict_concentration(value)
                outside = predicted < float(np.min(fit.concentrations)) or predicted > float(np.max(fit.concentrations))
                self.calibration_axes.scatter([predicted], [value], marker="*", s=120, color="#f08c2e", zorder=5)
                unknown_lines.append(f"{item.sample_id}: {predicted:.4f} M" + (" (검량 범위 밖)" if outside else ""))
            except ValueError:
                continue
        self.calibration_axes.legend(fontsize=8)
        equation = f"y = {fit.slope:.6g}x + {fit.intercept:.6g}, R² = {fit.r_squared:.4f}"
        self.fit_text.set(equation + ("\n미지 시료: " + "; ".join(unknown_lines) if unknown_lines else ""))
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def export_summary(self) -> None:
        if not self.measurements:
            messagebox.showinfo("데이터 필요", "먼저 측정 데이터를 등록하십시오.", parent=self)
            return
        filename = filedialog.asksaveasfilename(
            title="연구 분석 요약 CSV 저장",
            defaultextension=".csv",
            initialfile="NaCl_mCP_spectrum_summary.csv",
            filetypes=(("CSV", "*.csv"),),
            parent=self,
        )
        if not filename:
            return
        half_width = self._half_width_value()
        metric = self._metric_key()
        fit = None
        try:
            fit = fit_linear_calibration(self.measurements, metric, half_width)
        except ValueError:
            pass
        with Path(filename).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["sample_id", "NaCl_M", "replicate", "A434_mean", "A578_mean", "A578_A434", "lambda_max_nm", "Amax", "predicted_NaCl_M", "source"])
            for item in self.measurements:
                metrics = calculate_metrics(item.series, half_width)
                predicted = ""
                if item.concentration_m is None and fit is not None:
                    predicted = f"{fit.predict_concentration(metrics.value(metric)):.10g}"
                writer.writerow([
                    item.sample_id,
                    "" if item.concentration_m is None else f"{item.concentration_m:.10g}",
                    item.replicate,
                    f"{metrics.a434:.10g}",
                    f"{metrics.a578:.10g}",
                    f"{metrics.ratio:.10g}",
                    f"{metrics.lambda_max:.10g}",
                    f"{metrics.a_max:.10g}",
                    predicted,
                    item.source,
                ])
            writer.writerow([])
            writer.writerow(["group_summary", "NaCl_M", "n", "metric", "mean", "sample_std"])
            for summary in summarize_groups(self.measurements, half_width):
                mean, std = summary.value(metric)
                writer.writerow(["group_summary", summary.concentration_m, summary.count, metric, mean, std])
            if fit is not None:
                writer.writerow([])
                writer.writerow(["linear_fit", metric, "slope", fit.slope, "intercept", fit.intercept, "R_squared", fit.r_squared])
        self.status.set(f"요약 데이터를 {Path(filename).name}에 저장했습니다.")

    def export_figure(self) -> None:
        filename = filedialog.asksaveasfilename(
            title="분석 그래프 PNG 저장",
            defaultextension=".png",
            initialfile="NaCl_mCP_spectrum_analysis.png",
            filetypes=(("PNG", "*.png"), ("JPEG", "*.jpg")),
            parent=self,
        )
        if not filename:
            return
        self.figure.savefig(filename, dpi=180, bbox_inches="tight")
        self.status.set(f"그래프를 {Path(filename).name}에 저장했습니다.")
