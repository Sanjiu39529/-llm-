from streamlit.testing.v1 import AppTest


def test_frontend_renders_import_and_knowledge_workflows():
    app = AppTest.from_file("frontend/app.py").run()

    assert app.title[0].value == "电商智能数据分析助手"
    assert len(app.file_uploader) == 1
    assert [tab.label for tab in app.tabs] == ["导入数据", "业务知识问答"]
