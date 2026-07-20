from datetime import datetime

import pytest

from backend.app.datasources.platform_api import ConnectorRegistry, PlatformSyncRequest


class FakeConnector:
    platform = "Taobao"

    def capabilities(self):
        return frozenset({"orders", "traffic"})

    def fetch(self, request):
        return ()


def test_connector_registry_keeps_platform_integration_outside_metric_layer() -> None:
    registry = ConnectorRegistry()
    registry.register(FakeConnector())

    assert registry.platforms() == ("taobao",)
    assert registry.get("TAOBAO").capabilities() == frozenset({"orders", "traffic"})


def test_platform_sync_request_rejects_invalid_period() -> None:
    with pytest.raises(ValueError, match="start_must_be_before_end"):
        PlatformSyncRequest(
            resources=("orders",),
            start=datetime(2026, 1, 2),
            end=datetime(2026, 1, 1),
        )
