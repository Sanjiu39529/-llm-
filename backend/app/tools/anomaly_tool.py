"""Baseline comparisons and lightweight time-series anomaly detection."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping

import pandas as pd

from backend.app.analytics.config import MetricConfig
from backend.app.analytics.models import MetricResult


@dataclass(frozen=True, slots=True)
class Comparison:
    """A current value's signed change relative to one baseline."""

    current: Decimal | None
    baseline: Decimal | None
    change: Decimal | None
    level: str | None
    available: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class Anomaly:
    """One outlying daily observation and the methods that identified it."""

    date: object
    value: Decimal | int | float
    evidences: tuple[str, ...]
    valuable: bool


def classify_change(
    current: Decimal | int | float | None,
    baseline: Decimal | int | float | None,
    config: MetricConfig,
) -> Comparison:
    """Classify a signed relative change without treating a zero baseline as zero."""
    current_value = _decimal_value(current)
    baseline_value = _decimal_value(baseline)
    if current_value is None or baseline_value is None:
        return Comparison(None, None, None, None, False, "unavailable_value")
    if baseline_value == 0:
        return Comparison(current_value, baseline_value, None, None, False, "zero_baseline")

    change = (current_value - baseline_value) / abs(baseline_value)
    magnitude = abs(change)
    if magnitude < config.mild_threshold:
        level = "normal"
    elif magnitude < config.significant_threshold:
        level = "mild"
    elif magnitude <= config.severe_threshold:
        level = "significant"
    else:
        level = "severe"
    return Comparison(current_value, baseline_value, change, level, True, None)


def compare_baselines(
    metric_fn: Callable[[object, object, object], object],
    tables: object,
    start: object,
    end: object,
    config: MetricConfig,
) -> dict[str, Comparison]:
    """Compare one supplied metric against prior daily, weekly, and monthly windows."""
    current = _metric_value(metric_fn(tables, start, end))
    duration = end - start
    windows = {
        "day": (start - duration, start),
        "week": (start - pd.Timedelta(days=7), end - pd.Timedelta(days=7)),
        "month": (start - pd.DateOffset(months=1), end - pd.DateOffset(months=1)),
    }
    return {
        name: classify_change(current, _metric_value(metric_fn(tables, *window)), config)
        for name, window in windows.items()
    }


def detect_series_anomalies(
    series: pd.Series,
    config: MetricConfig,
    *,
    comparison_level: str | None = None,
) -> list[Anomaly]:
    """Detect observations outside IQR or sample three-sigma bounds."""
    del config
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) < 8:
        return []

    q1, q3 = values.quantile([0.25, 0.75])
    iqr = q3 - q1
    iqr_low, iqr_high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    mean = values.mean()
    standard_deviation = values.std(ddof=1)
    sigma_low, sigma_high = mean - 3 * standard_deviation, mean + 3 * standard_deviation

    anomalies: list[Anomaly] = []
    for date, value in values.items():
        evidences: list[str] = []
        if value < iqr_low or value > iqr_high:
            evidences.append("iqr")
        if value < sigma_low or value > sigma_high:
            evidences.append("three_sigma")
        if evidences:
            anomalies.append(
                Anomaly(
                    date,
                    value,
                    tuple(evidences),
                    comparison_level == "severe" or len(evidences) == 2,
                )
            )
    return anomalies


def _metric_value(result: object) -> Decimal | None:
    if isinstance(result, Mapping):
        if len(result) != 1:
            raise ValueError("metric_fn mapping must contain exactly one metric")
        result = next(iter(result.values()))
    if isinstance(result, MetricResult):
        return _decimal_value(result.value) if result.available else None
    return _decimal_value(result)


def _decimal_value(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return converted if converted.is_finite() else None
