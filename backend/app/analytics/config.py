"""Configuration consumed by phase-two metric calculations."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class MetricConfig:
    """Validated thresholds and analysis windows used by phase two."""

    mild_threshold: Decimal = Decimal("0.05")
    significant_threshold: Decimal = Decimal("0.15")
    severe_threshold: Decimal = Decimal("0.30")
    roi_lookback_days: int = 7
    statistics_days: int = 30
    customer_history_days: int = 365

    def __post_init__(self) -> None:
        if not (
            Decimal("0")
            <= self.mild_threshold
            < self.significant_threshold
            < self.severe_threshold
        ):
            raise ValueError(
                "thresholds must satisfy 0 <= mild < significant < severe"
            )
        for field_name in (
            "roi_lookback_days",
            "statistics_days",
            "customer_history_days",
        ):
            value = getattr(self, field_name)
            if type(value) is not int:
                raise ValueError(f"{field_name} must be a positive integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "MetricConfig":
        """Parse only the phase-two keys supported by this configuration."""
        threshold_fields = (
            "mild_threshold",
            "significant_threshold",
            "severe_threshold",
        )
        day_fields = (
            "roi_lookback_days",
            "statistics_days",
            "customer_history_days",
        )
        parsed: dict[str, Decimal | int] = {}
        for field_name in threshold_fields:
            if field_name in values:
                parsed[field_name] = Decimal(values[field_name])
        for field_name in day_fields:
            if field_name in values:
                parsed[field_name] = int(values[field_name])
        return cls(**parsed)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "mild_threshold": str(self.mild_threshold),
            "significant_threshold": str(self.significant_threshold),
            "severe_threshold": str(self.severe_threshold),
            "roi_lookback_days": self.roi_lookback_days,
            "statistics_days": self.statistics_days,
            "customer_history_days": self.customer_history_days,
        }
