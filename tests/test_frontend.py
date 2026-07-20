from streamlit.testing.v1 import AppTest
from urllib.error import HTTPError
from urllib.request import Request
import io
from pathlib import Path

import pytest

from frontend.app import _read_json


def test_frontend_renders_gpt_style_question_and_attachment_workflow():
    app = AppTest.from_file("frontend/app.py").run()

    assert app.title[0].value == "电商智能数据分析助手"
    assert len(app.chat_input) == 1
    assert app.chat_input[0].placeholder == "输入业务问题，或附加 CSV/Excel 后发送"


def test_frontend_surfaces_non_json_http_error_as_readable_message(monkeypatch):
    def failing_urlopen(request, timeout):
        raise HTTPError(request.full_url, 500, "Internal Server Error", {}, io.BytesIO(b""))

    monkeypatch.setattr("frontend.app.urlopen", failing_urlopen)

    with pytest.raises(RuntimeError, match="HTTP 500"):
        _read_json(Request("http://127.0.0.1:8000/api/imports"))


def test_frontend_keeps_dataset_context_in_session_state():
    app = AppTest.from_file("frontend/app.py").run()

    assert "active_datasets" in app.session_state
    assert "selected_dataset_ids" in app.session_state


def test_frontend_uses_native_financial_theme_without_custom_css() -> None:
    config = Path(".streamlit/config.toml").read_text(encoding="utf-8")
    source = Path("frontend/app.py").read_text(encoding="utf-8")

    assert 'primaryColor = "#60A5FA"' in config
    assert 'backgroundColor = "#0F172A"' in config
    assert "unsafe_allow_html" not in source


def test_dynamic_report_components_render_with_current_streamlit_version() -> None:
    script = """
from frontend.app import _show_report
_show_report({
    "metrics": {
        "sales": {
            "gmv": {"value": "100.00", "available": True},
            "actual_sales": {"value": "90.00", "available": True},
            "net_sales": {"value": "80.00", "available": True},
            "refund_amount": {"value": "10.00", "available": True},
        },
        "gmv_comparisons": {"day": {"available": True, "change": "0.1"}},
        "traffic_and_customer": {"channels": {}},
        "products": {"top_by_revenue": {"items": []}},
    },
    "valuable_anomalies": [],
    "recommendations": ["保持观察"],
    "missing_dependencies": [],
    "quality_warnings": {},
})
"""
    app = AppTest.from_string(script).run()

    assert not app.exception
    assert len(app.metric) == 4
