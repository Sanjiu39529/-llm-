from pathlib import Path

from backend.app.mcp_server import _call


def test_mcp_sales_snapshot_tools_return_structured_results(tmp_path: Path):
    path = tmp_path / "sales.csv"
    path.write_text("id,title,price,sale_count,店名\n1,A,10,3,S\n", encoding="utf-8")
    result = _call("analyze_sales_snapshot", {"path": str(path)})
    assert result["structuredContent"]["metrics"]["estimated_sales"] == 30.0
    assert _call("suggest_charts", {"path": str(path)})["structuredContent"]["charts"][0]["type"] == "bar"
