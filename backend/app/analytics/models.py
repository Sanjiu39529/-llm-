"""Serializable result types shared by metric tools."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class MetricResult:
    """A metric value together with its calculation availability."""

    name: str
    value: Decimal | int | None
    available: bool
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation without losing decimals."""
        value = str(self.value) if isinstance(self.value, Decimal) else self.value
        return {
            "name": self.name,
            "value": value,
            "available": self.available,
            "reason": self.reason,
        }
