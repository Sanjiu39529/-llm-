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


def test_frontend_renders_deterministic_analysis_summary() -> None:
    script = '''
from frontend.app import _show_analysis_summary
_show_analysis_summary({"overview": "成交 GMV 为 100.00。", "findings": ["成交 GMV 为 100.00。", "净销售额为 90.00。"], "limitations": ["traffic_visit"]})
'''
    app = AppTest.from_string(script).run()

    assert not app.exception
    assert any("分析结论" in item.value for item in app.subheader)


def test_frontend_only_renders_question_selected_chart() -> None:
    script = '''
from frontend.app import _show_report
_show_report({"presentation": {"selected_chart_keys": ["sales_overview"]}, "metrics": {"sales": {"gmv": {"value": 100, "available": True}, "actual_sales": {"value": None, "available": False}, "net_sales": {"value": None, "available": False}, "refund_amount": {"value": None, "available": False}}, "gmv_comparisons": {"day": {}}, "traffic_and_customer": {"channels": {}}, "products": {"top_by_revenue": {"items": []}}, "advertising": {}}, "valuable_anomalies": [], "recommendations": [], "missing_dependencies": [], "quality_warnings": {}})
'''
    app = AppTest.from_string(script).run()

    assert not app.exception
    labels = [item.value for item in app.subheader]
    assert "销售结构" in labels
    assert "渠道流量" not in labels
    assert "商品销售排行" not in labels
    assert "渠道投放花费" not in labels


def test_frontend_renders_llm_business_suggestions() -> None:
    script = '''
from frontend.app import _show_planner_suggestions
_show_planner_suggestions({"business_suggestions": ["先核查退款原因。"]})
'''
    app = AppTest.from_string(script).run()

    assert not app.exception
    assert any("AI 业务建议" in item.value for item in app.subheader)


def test_manual_table_confirmation_does_not_preselect_an_unrelated_table() -> None:
    script = '''
from frontend.app import _show_import_answer
_show_import_answer({"content": {"upload_id": "u1", "data": {"status": "needs_table_confirmation", "message": "无法识别", "available_tables": ["ad_attribution", "order_info"]}}}, "http://127.0.0.1:8000")
'''
    app = AppTest.from_string(script).run()

    assert not app.exception
    assert app.selectbox[0].value is None
    assert app.button[0].disabled is True
