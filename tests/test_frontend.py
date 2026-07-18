from streamlit.testing.v1 import AppTest
from urllib.error import HTTPError
from urllib.request import Request
import io

import pytest

from frontend.app import _read_json


def test_frontend_renders_import_and_knowledge_workflows():
    app = AppTest.from_file("frontend/app.py").run()

    assert app.title[0].value == "电商智能数据分析助手"
    assert len(app.file_uploader) == 1
    assert [tab.label for tab in app.tabs] == ["导入数据", "分析看板", "用户行为漏斗", "业务知识问答"]


def test_frontend_surfaces_non_json_http_error_as_readable_message(monkeypatch):
    def failing_urlopen(request, timeout):
        raise HTTPError(request.full_url, 500, "Internal Server Error", {}, io.BytesIO(b""))

    monkeypatch.setattr("frontend.app.urlopen", failing_urlopen)

    with pytest.raises(RuntimeError, match="HTTP 500"):
        _read_json(Request("http://127.0.0.1:8000/api/imports"))
