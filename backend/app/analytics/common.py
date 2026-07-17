"""Precision, division, and time-window helpers for analytics."""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

from backend.app.analytics.models import MetricResult

_MONEY_QUANTUM = Decimal("0.01")
_RATIO_QUANTUM = Decimal("0.0001")


def _as_decimal(value: Decimal | int | float) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def quantize_money(value: Decimal | int | float) -> Decimal:
    """Round a monetary value to two decimal places using business rounding."""
    return _as_decimal(value).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def safe_ratio(
    numerator: Decimal | int | float,
    denominator: Decimal | int | float,
    *,
    scale: Decimal = Decimal("1"),
) -> MetricResult:
    """Calculate a four-place ratio or report a zero denominator."""
    decimal_denominator = _as_decimal(denominator)
    if decimal_denominator == 0:
        return MetricResult("ratio", None, False, "zero_denominator")

    value = (_as_decimal(numerator) / decimal_denominator) * scale
    return MetricResult(
        "ratio",
        value.quantize(_RATIO_QUANTUM, rounding=ROUND_HALF_UP),
        True,
        None,
    )


def filter_period(
    frame: pd.DataFrame,
    column: str,
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
) -> pd.DataFrame:
    """Return rows in the left-closed, right-open interval ``[start, end)``."""
    if column not in frame.columns:
        raise KeyError(f"missing dependency column: {column}")
    mask = frame[column].ge(start) & frame[column].lt(end)
    return frame.loc[mask].copy()
