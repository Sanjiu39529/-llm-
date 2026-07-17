import json
from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

from backend.app.analytics.common import filter_period, quantize_money, safe_ratio
from backend.app.analytics.config import MetricConfig
from backend.app.analytics.models import MetricResult


def test_metric_result_is_frozen_and_json_serializable() -> None:
    result = MetricResult("gmv", Decimal("12.30"), True, None)

    with pytest.raises(FrozenInstanceError):
        result.value = Decimal("9.99")

    assert json.dumps(result.to_dict()) == (
        '{"name": "gmv", "value": "12.30", "available": true, "reason": null}'
    )


def test_safe_ratio_marks_zero_denominator_unavailable() -> None:
    result = safe_ratio(10, 0)

    assert result.available is False
    assert result.value is None
    assert result.reason == "zero_denominator"


def test_safe_ratio_applies_scale_and_rounds_half_up_to_four_places() -> None:
    result = safe_ratio(Decimal("1.23445"), 1, scale=Decimal("1"))

    assert result.value == Decimal("1.2345")
    assert result.available is True
    assert result.reason is None


def test_quantize_money_rounds_half_up_to_two_places() -> None:
    assert quantize_money(Decimal("2.345")) == Decimal("2.35")


def test_filter_period_is_left_closed_right_open() -> None:
    start = datetime(2026, 7, 1)
    end = datetime(2026, 7, 2)
    frame = pd.DataFrame(
        {
            "id": ["before", "at_start", "before_end", "at_end"],
            "occurred_at": [
                datetime(2026, 6, 30, 23, 59, 59),
                start,
                datetime(2026, 7, 1, 23, 59, 59),
                end,
            ],
        }
    )

    result = filter_period(frame, "occurred_at", start, end)

    assert result["id"].tolist() == ["at_start", "before_end"]


def test_filter_period_reports_a_missing_dependency() -> None:
    frame = pd.DataFrame({"id": [1]})

    with pytest.raises(KeyError, match="missing dependency column: occurred_at"):
        filter_period(
            frame,
            "occurred_at",
            datetime(2026, 7, 1),
            datetime(2026, 7, 2),
        )


def test_metric_config_has_phase_two_defaults() -> None:
    config = MetricConfig.from_mapping({})

    assert config.mild_threshold == Decimal("0.05")
    assert config.significant_threshold == Decimal("0.15")
    assert config.severe_threshold == Decimal("0.30")
    assert config.roi_lookback_days == 7
    assert config.statistics_days == 30
    assert config.customer_history_days == 365


def test_metric_config_is_json_serializable() -> None:
    config = MetricConfig.from_mapping({})

    assert json.loads(json.dumps(config.to_dict())) == {
        "mild_threshold": "0.05",
        "significant_threshold": "0.15",
        "severe_threshold": "0.30",
        "roi_lookback_days": 7,
        "statistics_days": 30,
        "customer_history_days": 365,
    }


def test_metric_config_parses_supported_string_values() -> None:
    config = MetricConfig.from_mapping(
        {
            "mild_threshold": "0.06",
            "significant_threshold": "0.16",
            "severe_threshold": "0.31",
            "roi_lookback_days": "8",
            "statistics_days": "14",
            "customer_history_days": "180",
            "future_setting": "ignored",
        }
    )

    assert config == MetricConfig(
        mild_threshold=Decimal("0.06"),
        significant_threshold=Decimal("0.16"),
        severe_threshold=Decimal("0.31"),
        roi_lookback_days=8,
        statistics_days=14,
        customer_history_days=180,
    )


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {"mild_threshold": "0.15", "significant_threshold": "0.15"},
            "thresholds must satisfy",
        ),
        ({"mild_threshold": "-0.01"}, "thresholds must satisfy"),
        ({"roi_lookback_days": "0"}, "roi_lookback_days must be positive"),
        ({"statistics_days": "-1"}, "statistics_days must be positive"),
        (
            {"customer_history_days": "0"},
            "customer_history_days must be positive",
        ),
    ],
)
def test_metric_config_rejects_invalid_boundaries(
    values: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        MetricConfig.from_mapping(values)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        (field_name, invalid_value)
        for field_name in (
            "roi_lookback_days",
            "statistics_days",
            "customer_history_days",
        )
        for invalid_value in (1.5, Decimal("1.5"), True)
    ],
)
def test_metric_config_constructor_requires_positive_integer_day_windows(
    field_name: str, invalid_value: object
) -> None:
    with pytest.raises(ValueError, match=f"{field_name} must be a positive integer"):
        MetricConfig(**{field_name: invalid_value})
