from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

from backend.app.analytics.config import MetricConfig
from backend.app.analytics.models import MetricResult
from backend.app.tools.anomaly_tool import (
    classify_change,
    compare_baselines,
    detect_series_anomalies,
)


@pytest.mark.parametrize(
    ("current", "expected_change", "expected_level"),
    [
        (Decimal("104.99"), Decimal("0.0499"), "normal"),
        (Decimal("105"), Decimal("0.05"), "mild"),
        (Decimal("114.99"), Decimal("0.1499"), "mild"),
        (Decimal("115"), Decimal("0.15"), "significant"),
        (Decimal("130"), Decimal("0.30"), "significant"),
        (Decimal("130.01"), Decimal("0.3001"), "severe"),
        (Decimal("85"), Decimal("-0.15"), "significant"),
    ],
)
def test_classify_change_uses_exact_absolute_threshold_boundaries(
    current: Decimal, expected_change: Decimal, expected_level: str
) -> None:
    result = classify_change(current, Decimal("100"), MetricConfig())

    assert result.change == expected_change
    assert result.level == expected_level
    assert result.available is True


def test_classify_change_marks_zero_or_unavailable_baseline_unavailable() -> None:
    zero = classify_change(Decimal("10"), Decimal("0"), MetricConfig())
    missing = classify_change(None, Decimal("10"), MetricConfig())

    assert zero.available is False
    assert zero.change is None
    assert missing.available is False
    assert missing.change is None


def test_compare_baselines_uses_daily_weekly_and_calendar_month_windows() -> None:
    start = datetime(2026, 3, 31)
    end = datetime(2026, 4, 30)
    calls: list[tuple[datetime, datetime]] = []

    def metric_fn(_tables: object, window_start: datetime, window_end: datetime):
        calls.append((window_start, window_end))
        return {"gmv": MetricResult("gmv", Decimal("100"), True, None)}

    result = compare_baselines(metric_fn, {}, start, end, MetricConfig())

    assert set(result) == {"day", "week", "month"}
    assert calls == [
        (start, end),
        (datetime(2026, 3, 1), datetime(2026, 3, 31)),
        (datetime(2026, 3, 24), datetime(2026, 4, 23)),
        (datetime(2026, 2, 28), datetime(2026, 3, 30)),
    ]


def test_detect_series_anomalies_skips_insufficient_samples() -> None:
    series = pd.Series(
        [1, 1, 1, 100, None], index=pd.date_range("2026-01-01", periods=5)
    )

    assert detect_series_anomalies(series, MetricConfig()) == []


def test_detect_series_anomalies_marks_iqr_and_three_sigma_evidence_valuable() -> None:
    series = pd.Series(
        [0] * 11 + [100], index=pd.date_range("2026-01-01", periods=12)
    )

    result = detect_series_anomalies(series, MetricConfig())

    assert len(result) == 1
    assert result[0].date == pd.Timestamp("2026-01-12")
    assert result[0].value == 100
    assert result[0].evidences == ("iqr", "three_sigma")
    assert result[0].valuable is True
