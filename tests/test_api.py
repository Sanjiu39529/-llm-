from fastapi.testclient import TestClient
import pandas as pd
from types import SimpleNamespace

from backend.app.agents.supervisor import EcommerceSupervisor
from backend.app.api import _import_recovery, create_app
from backend.app.services.import_service import ImportReport


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


def test_funnel_endpoint_returns_page_funnel_from_injected_read_model():
    client = TestClient(
        create_app(
            EcommerceSupervisor(),
            table_loader=lambda: {
                "behavior_funnel": pd.DataFrame(
                    [{"new_user": 1, "source": "Direct", "total_pages_visited": 2, "home_page": 1, "listing_page": 1, "product_page": 0, "payment_page": 0, "confirmation_page": 0}]
                )
            },
        )
    )

    response = client.get("/api/funnels")

    assert response.status_code == 200
    assert response.json()["funnel"][0]["visitors"] == 1


def test_dashboard_question_routes_to_a_funnel_dashboard():
    client = TestClient(
        create_app(
            EcommerceSupervisor(),
            table_loader=lambda: {
                "behavior_funnel": pd.DataFrame(
                    [{"new_user": 1, "source": "Direct", "total_pages_visited": 2, "home_page": 1, "listing_page": 1, "product_page": 0, "payment_page": 0, "confirmation_page": 0}]
                )
            },
        )
    )

    response = client.post("/api/dashboard/ask", json={"question": "分析用户行为漏斗"})

    assert response.status_code == 200
    assert response.json()["intent"] == "funnel"
    assert response.json()["dashboard"]["funnel"][0]["visitors"] == 1


def test_dashboard_question_routes_metric_definition_to_knowledge():
    client = TestClient(create_app(EcommerceSupervisor()))

    response = client.post("/api/dashboard/ask", json={"question": "GMV 的口径是什么？"})

    assert response.status_code == 200
    assert response.json()["intent"] == "knowledge"
    assert response.json()["knowledge"]


def test_dashboard_question_routes_sales_question_to_fixed_metric_report():
    client = TestClient(
        create_app(
            EcommerceSupervisor(),
            table_loader=lambda: {
                "order_info": pd.DataFrame(
                    [{"order_id": "o1", "order_time": pd.Timestamp("2026-01-01"), "order_amount": "100"}]
                )
            },
        )
    )

    response = client.post(
        "/api/dashboard/ask",
        json={
            "question": "查看 GMV",
            "start": "2026-01-01T00:00:00",
            "end": "2026-01-02T00:00:00",
        },
    )

    assert response.status_code == 200
    assert response.json()["intent"] == "analysis"
    assert response.json()["dashboard"]["metrics"]["sales"]["gmv"]["value"] == 100.0
    assert response.json()["answer"] == "统计期成交 GMV 为 100.00。"
    assert response.json()["dashboard"]["presentation"]["selected_chart_keys"] == ["sales_overview"]


def test_dashboard_question_scopes_database_load_to_selected_datasets(monkeypatch):
    captured = {}

    def load_tables(**kwargs):
        captured.update(kwargs)
        return {
            "order_info": pd.DataFrame(
                [
                    {
                        "order_id": "o1",
                        "order_time": pd.Timestamp("2026-01-01"),
                        "order_amount": "100",
                    }
                ]
            )
        }

    monkeypatch.setattr("backend.app.api._load_database_tables", load_tables)
    client = TestClient(create_app(EcommerceSupervisor()))

    response = client.post(
        "/api/dashboard/ask",
        json={
            "question": "查看 GMV",
            "start": "2026-01-01T00:00:00",
            "end": "2026-01-02T00:00:00",
            "dataset_ids": ["dataset-a", "dataset-b"],
        },
    )

    assert response.status_code == 200
    assert captured["dataset_ids"] == ["dataset-a", "dataset-b"]


def test_unknown_file_structure_returns_guided_confirmation_instead_of_import_error():
    response = _import_recovery("cannot_auto_identify: reason=no_matching_table candidates=[]")

    assert response is not None
    assert response["status"] == "needs_table_confirmation"
    assert "order_info" in response["available_tables"]


def test_generic_analysis_question_uses_uploaded_funnel_context():
    client = TestClient(
        create_app(
            EcommerceSupervisor(),
            table_loader=lambda: {
                "behavior_funnel": pd.DataFrame(
                    [{"total_pages_visited": 2, "home_page": 1, "confirmation_page": 0}]
                )
            },
        )
    )

    response = client.post(
        "/api/dashboard/ask",
        json={"question": "帮我分析该数据", "context_tables": ["behavior_funnel"]},
    )

    assert response.status_code == 200
    assert response.json()["intent"] == "funnel"
    assert response.json().get("error") is None


def test_generic_question_without_context_never_returns_analysis_inputs_required():
    client = TestClient(create_app(EcommerceSupervisor()))

    response = client.post("/api/dashboard/ask", json={"question": "你好"})

    assert response.status_code == 200
    assert response.json()["intent"] == "knowledge"
    assert response.json().get("error") != "analysis_inputs_required"


def test_duplicate_import_is_a_reusable_existing_dataset():
    response = _import_recovery("cross_batch_duplicate: table=order_info count=3")

    assert response is not None
    assert response["status"] == "already_imported"
    assert response["processed_tables"] == ["order_info"]


def test_import_endpoint_passes_batch_size_by_keyword(monkeypatch):
    captured = {}

    class FakeImportService:
        def __init__(
            self, engine, *, batch_size, csv_chunk_size, max_file_size_mb
        ):
            captured["batch_size"] = batch_size
            captured["csv_chunk_size"] = csv_chunk_size
            captured["max_file_size_mb"] = max_file_size_mb

        def import_file(self, path, table, *, file_hash, file_size):
            captured["file_hash"] = file_hash
            captured["file_size"] = file_size
            return ImportReport(1, ["behavior_funnel"], 1, 0, [])

    monkeypatch.setattr(
        "backend.app.api.Settings",
        lambda: SimpleNamespace(
            database_url="sqlite://",
            import_batch_size=321,
            import_csv_chunk_size=123,
            import_max_file_size_mb=2,
        ),
    )
    monkeypatch.setattr("backend.app.api.create_engine", lambda url: object())
    monkeypatch.setattr("backend.app.api.ImportService", FakeImportService)
    client = TestClient(create_app(EcommerceSupervisor()))

    response = client.post(
        "/api/imports", files={"file": ("data.csv", b"total_pages_visited\n1\n", "text/csv")}
    )

    assert response.status_code == 200
    assert response.json()["processed_tables"] == ["behavior_funnel"]
    assert captured["batch_size"] == 321
    assert captured["csv_chunk_size"] == 123
    assert captured["max_file_size_mb"] == 2
    assert len(captured["file_hash"]) == 64
    assert captured["file_size"] == len(b"total_pages_visited\n1\n")


def test_import_endpoint_rejects_file_over_configured_limit(monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.Settings",
        lambda: SimpleNamespace(
            database_url="sqlite://",
            import_batch_size=100,
            import_csv_chunk_size=10,
            import_max_file_size_mb=1,
        ),
    )
    client = TestClient(create_app(EcommerceSupervisor()))

    response = client.post(
        "/api/imports",
        files={"file": ("large.csv", b"x" * (1024 * 1024 + 1), "text/csv")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "file_too_large: max_size_mb=1"
