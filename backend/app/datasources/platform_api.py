"""Stable boundary for future Taobao and other commerce platform connectors."""

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Protocol


@dataclass(frozen=True, slots=True)
class PlatformSyncRequest:
    resources: tuple[str, ...]
    start: datetime
    end: datetime
    cursor: str | None = None

    def __post_init__(self) -> None:
        if not self.resources:
            raise ValueError("at_least_one_resource_is_required")
        if self.start >= self.end:
            raise ValueError("start_must_be_before_end")


@dataclass(frozen=True, slots=True)
class PlatformPage:
    resource: str
    rows: tuple[Mapping[str, object], ...]
    next_cursor: str | None = None


class CommercePlatformConnector(Protocol):
    """Implemented by REST/OpenAPI or MCP adapters, never by metric code."""

    @property
    def platform(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def fetch(self, request: PlatformSyncRequest) -> Iterable[PlatformPage]: ...


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, CommercePlatformConnector] = {}

    def register(self, connector: CommercePlatformConnector) -> None:
        platform = connector.platform.strip().casefold()
        if not platform:
            raise ValueError("platform_name_is_required")
        if platform in self._connectors:
            raise ValueError(f"connector_already_registered: {platform}")
        self._connectors[platform] = connector

    def get(self, platform: str) -> CommercePlatformConnector:
        key = platform.strip().casefold()
        if key not in self._connectors:
            raise KeyError(f"connector_not_registered: {key}")
        return self._connectors[key]

    def platforms(self) -> tuple[str, ...]:
        return tuple(sorted(self._connectors))
