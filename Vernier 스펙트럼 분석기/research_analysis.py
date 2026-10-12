"""Analysis helpers for the NaCl-m-cresol-purple spectrum experiment."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable

import numpy as np

from spectrum_core import SpectrumSeries


TARGET_434_NM = 434.0
TARGET_578_NM = 578.0
METRIC_LABELS = {
    "a434": "A434 영역 평균",
    "a578": "A578 영역 평균",
    "ratio": "A578 / A434",
    "lambda_max": "최대 흡수 파장 λmax",
    "a_max": "최대 흡광도 Amax",
}


@dataclass(frozen=True)
class ResearchMeasurement:
    sample_id: str
    concentration_m: float | None
    replicate: int
    series: SpectrumSeries
    source: str = ""


@dataclass(frozen=True)
class MeasurementMetrics:
    a434: float
    a578: float
    ratio: float
    lambda_max: float
    a_max: float

    def value(self, metric: str) -> float:
        if metric not in METRIC_LABELS:
            raise ValueError(f"지원하지 않는 분석 지표입니다: {metric}")
        return float(getattr(self, metric))


@dataclass(frozen=True)
class GroupSummary:
    concentration_m: float
    count: int
    mean: MeasurementMetrics
    std: MeasurementMetrics

    def value(self, metric: str) -> tuple[float, float]:
        return self.mean.value(metric), self.std.value(metric)


@dataclass(frozen=True)
class LinearFit:
    metric: str
    slope: float
    intercept: float
    r_squared: float
    concentrations: np.ndarray
    values: np.ndarray
    standard_deviations: np.ndarray

    def predict_concentration(self, value: float) -> float:
        if abs(self.slope) < 1e-15:
            raise ValueError("회귀선의 기울기가 0에 가까워 농도를 예측할 수 없습니다.")
        return float((value - self.intercept) / self.slope)


def _window_mean(series: SpectrumSeries, center_nm: float, half_width_nm: float) -> float:
    if half_width_nm <= 0:
        raise ValueError("분석 영역 반폭은 0보다 커야 합니다.")
    mask = np.abs(series.wavelength_nm - center_nm) <= half_width_nm
    values = series.values[mask]
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError(f"{center_nm:g} nm 주변에 유효한 데이터가 없습니다.")
    return float(np.mean(values))


def calculate_metrics(
    series: SpectrumSeries,
    half_width_nm: float = 5.0,
    visible_min_nm: float = 400.0,
    visible_max_nm: float = 700.0,
) -> MeasurementMetrics:
    """Calculate robust mCP metrics from one absorbance spectrum.

    The target absorbances are window means rather than single pixels.  This is
    deliberate because the referenced SpectroVis Plus has about 5 nm FWHM
    optical resolution and about +/-4 nm wavelength accuracy.
    """

    a434 = _window_mean(series, TARGET_434_NM, half_width_nm)
    a578 = _window_mean(series, TARGET_578_NM, half_width_nm)
    ratio = float(a578 / a434) if abs(a434) > 1e-15 else math.nan

    mask = (
        np.isfinite(series.wavelength_nm)
        & np.isfinite(series.values)
        & (series.wavelength_nm >= visible_min_nm)
        & (series.wavelength_nm <= visible_max_nm)
    )
    indices = np.flatnonzero(mask)
    if indices.size == 0:
        raise ValueError("400-700 nm 가시광 영역에 유효한 데이터가 없습니다.")
    local_index = int(np.argmax(series.values[indices]))
    peak_index = int(indices[local_index])
    return MeasurementMetrics(
        a434=a434,
        a578=a578,
        ratio=ratio,
        lambda_max=float(series.wavelength_nm[peak_index]),
        a_max=float(series.values[peak_index]),
    )


def _metric_bundle(values: list[MeasurementMetrics], reducer) -> MeasurementMetrics:
    return MeasurementMetrics(
        **{
            metric: float(reducer(np.array([item.value(metric) for item in values], dtype=float)))
            for metric in METRIC_LABELS
        }
    )


def summarize_groups(
    measurements: Iterable[ResearchMeasurement], half_width_nm: float = 5.0
) -> list[GroupSummary]:
    grouped: dict[float, list[MeasurementMetrics]] = {}
    for measurement in measurements:
        if measurement.concentration_m is None:
            continue
        metrics = calculate_metrics(measurement.series, half_width_nm)
        grouped.setdefault(float(measurement.concentration_m), []).append(metrics)

    summaries: list[GroupSummary] = []
    for concentration, values in sorted(grouped.items()):
        mean = _metric_bundle(values, np.nanmean)

        def sample_std(array: np.ndarray) -> float:
            finite = array[np.isfinite(array)]
            return float(np.std(finite, ddof=1)) if finite.size > 1 else 0.0

        std = _metric_bundle(values, sample_std)
        summaries.append(GroupSummary(concentration, len(values), mean, std))
    return summaries


def fit_linear_calibration(
    measurements: Iterable[ResearchMeasurement],
    metric: str = "ratio",
    half_width_nm: float = 5.0,
) -> LinearFit:
    summaries = summarize_groups(measurements, half_width_nm)
    if len(summaries) < 2:
        raise ValueError("회귀분석에는 서로 다른 농도의 표준 시료가 2개 이상 필요합니다.")
    x = np.array([item.concentration_m for item in summaries], dtype=float)
    y = np.array([item.mean.value(metric) for item in summaries], dtype=float)
    y_std = np.array([item.std.value(metric) for item in summaries], dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    x, y, y_std = x[finite], y[finite], y_std[finite]
    if np.unique(x).size < 2:
        raise ValueError("회귀분석에는 서로 다른 농도의 유효한 값이 2개 이상 필요합니다.")
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    residual = float(np.sum((y - predicted) ** 2))
    total = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 if total <= 1e-30 and residual <= 1e-30 else 1.0 - residual / total if total > 0 else math.nan
    return LinearFit(metric, float(slope), float(intercept), float(r_squared), x, y, y_std)


def average_spectrum(measurements: Iterable[ResearchMeasurement]) -> SpectrumSeries:
    items = list(measurements)
    if not items:
        raise ValueError("평균을 계산할 스펙트럼이 없습니다.")
    lower = max(float(np.min(item.series.wavelength_nm)) for item in items)
    upper = min(float(np.max(item.series.wavelength_nm)) for item in items)
    reference = items[0].series.wavelength_nm
    grid = reference[(reference >= lower) & (reference <= upper)]
    if grid.size < 3:
        raise ValueError("스펙트럼들이 공유하는 파장 범위가 충분하지 않습니다.")
    matrix = np.vstack(
        [np.interp(grid, item.series.wavelength_nm, item.series.values) for item in items]
    )
    return SpectrumSeries(
        label=f"평균 스펙트럼 (n={len(items)})",
        wavelength_nm=grid.copy(),
        values=np.mean(matrix, axis=0),
        value_unit="A.U.",
    )


def infer_sample_metadata(text: str) -> tuple[float | None, int]:
    """Infer concentration and replicate from names such as 0.8M_rep2."""

    concentration: float | None = None
    match = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:mol\s*/\s*l|m)(?![a-z])", text, re.IGNORECASE)
    if match:
        value = float(match.group(1))
        if 0.0 <= value <= 10.0:
            concentration = value
    replicate = 1
    rep_match = re.search(r"(?:rep(?:licate)?|반복|run|r)[ _-]?(\d+)", text, re.IGNORECASE)
    if rep_match:
        replicate = max(1, int(rep_match.group(1)))
    return concentration, replicate

