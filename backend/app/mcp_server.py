"""Minimal stdio MCP server for read-only generic dataset analysis."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.analytics.generic_sales_snapshot import analyze_generic_sales_snapshot


_TOOLS = [
    {"name": "inspect_dataset", "description": "Read CSV/Excel headers and profile columns without writing data.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "analyze_sales_snapshot", "description": "Analyze a generic product sales snapshot with price and confirmed sale_count.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "suggest_charts", "description": "Return safe chart specifications for a generic sales snapshot.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "suggest_business_actions", "description": "Return deterministic business actions grounded in snapshot aggregates.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
]


def _path(arguments: dict[str, Any]) -> Path:
    path = Path(str(arguments.get("path", ""))).resolve()
    if path.suffix.lower() not in {".csv", ".xlsx"} or not path.is_file() or path.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("invalid_dataset_path")
    return path


def _inspect(path: Path) -> dict[str, object]:
    frame = pd.read_csv(path, nrows=1000, dtype=object) if path.suffix.lower() == ".csv" else pd.read_excel(path, nrows=1000, dtype=object)
    return {"path": str(path), "sample_rows": len(frame), "columns": [{"name": name, "non_empty": int(frame[name].astype(str).str.strip().ne("").sum())} for name in frame.columns]}


def _analyze(path: Path) -> dict[str, object]:
    report = analyze_generic_sales_snapshot(path)
    if report is None:
        raise ValueError("unsupported_generic_dataset")
    return report


def _call(name: str, arguments: dict[str, Any]) -> dict[str, object]:
    path = _path(arguments)
    if name == "inspect_dataset": result = _inspect(path)
    elif name == "analyze_sales_snapshot": result = _analyze(path)
    elif name == "suggest_charts":
        report = _analyze(path)
        result = {"charts": [{"type": "bar", "title": "店铺预估销售额排行", "data_key": "top_stores"}, {"type": "table", "title": "商品预估销售额排行", "data_key": "top_products"}], "notice": report["notice"]}
    elif name == "suggest_business_actions":
        report = _analyze(path)
        actions = ["优先复核预估销售额最高的商品与店铺，确认库存和履约能力。"]
        if report["top_stores"]: actions.append("将头部店铺商品作为大促资源位和补货优先级的候选对象。")
        result = {"actions": actions, "evidence": report["metrics"], "notice": report["notice"]}
    else: raise ValueError("unknown_tool")
    text = json.dumps(result, ensure_ascii=False, default=str)
    return {"content": [{"type": "text", "text": text}], "structuredContent": result, "isError": False}


def _response(identifier: object, result: dict[str, object] | None = None, error: tuple[int, str] | None = None) -> dict[str, object]:
    body: dict[str, object] = {"jsonrpc": "2.0", "id": identifier}
    if error is None:
        body["result"] = result
    else:
        body["error"] = {"code": error[0], "message": error[1]}
    return body


def main() -> None:
    for line in sys.stdin:
        try:
            request = json.loads(line); method = request.get("method"); identifier = request.get("id")
            if method == "initialize": result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "ecommerce-generic-analysis", "version": "0.1.0"}}
            elif method == "tools/list": result = {"tools": _TOOLS}
            elif method == "tools/call": result = _call(request["params"]["name"], request["params"].get("arguments", {}))
            elif method == "notifications/initialized": continue
            else: raise ValueError("method_not_found")
            print(json.dumps(_response(identifier, result), ensure_ascii=False), flush=True)
        except Exception as exc:
            print(json.dumps(_response(locals().get("identifier"), error=(-32602, str(exc))), ensure_ascii=False), flush=True)


if __name__ == "__main__": main()
