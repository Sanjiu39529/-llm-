from fastapi.testclient import TestClient
import pandas as pd

from backend.app.agents.supervisor import EcommerceSupervisor
from backend.app.api import create_app


def test_health_and_knowledge_question_are_available_over_http():
    client = TestClient(create_app(EcommerceSupervisor()))

    assert client.get("/health").json() == {"status": "ok"}
    response = client.post("/api/ask", json={"question": "GMV 的口径是什么？"})

    assert response.status_code == 200
    assert response.json()["route"] == "knowledge"
    assert response.json()["knowledge"][0]["source"] == "knowledge/电商指标口径.md"


def test_analysis_endpoint_reuses_existing_report_workflow():
    client = TestClient(create_app(EcommerceSupervisor()))

    response = client.post(
        "/api/analysis",
        json={
            "tables": {
                "order_info": [
                    {"order_id": "o1", "order_time": "2026-01-01", "order_amount": "100"}
                ]
            },
            "start": "2026-01-01T00:00:00",
            "end": "2026-01-02T00:00:00",
        },
    )

    assert response.status_code == 200
    assert response.json()["report"]["metrics"]["sales"]["gmv"]["value"] == 100.0


def test_database_report_endpoint_uses_injected_read_model():
    tables = {
        "order_info": pd.DataFrame(
            [{"order_id": "o1", "order_time": pd.Timestamp("2026-01-01"), "order_amount": "100"}]
        )
    }
    client = TestClient(
        create_app(
            EcommerceSupervisor(),
            table_loader=lambda: tables,
        )
    )

    response = client.get(
        "/api/reports", params={"start": "2026-01-01T00:00:00", "end": "2026-01-02T00:00:00"}
    )

    assert response.status_code == 200
    assert response.json()["report"]["metrics"]["sales"]["gmv"]["value"] == 100.0
