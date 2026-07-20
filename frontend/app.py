"""Streamlit 操作界面：通过 FastAPI 调用既有业务能力。"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import pandas as pd
import streamlit as st


DEFAULT_API_URL = "http://127.0.0.1:8000"
CSV_TABLES = ["user_info", "product_info", "order_info", "order_item", "payment_info", "refund_info", "traffic_visit", "behavior_info", "behavior_funnel", "ads_info", "ad_attribution"]


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _read_json(request)


def _post_file(url: str, filename: str, content: bytes, table: str | None) -> dict[str, Any]:
    boundary = f"----ecommerce-agent-{uuid4().hex}"
    fields = [] if table is None else [("table", table.encode("utf-8"))]
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode()
        + value
        + b"\r\n"
        for name, value in fields
    ]
    parts.extend(
        [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode(),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    request = Request(
        url,
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    return _read_json(request)


def _read_json(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=180) as response:  # nosec B310: URL is entered by the local user.
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("detail", f"HTTP {exc.code}")
        except json.JSONDecodeError:
            detail = body.strip() or f"HTTP {exc.code}"
        raise RuntimeError(detail) from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("API returned a non-JSON response") from exc


def main() -> None:
    st.set_page_config(page_title="电商智能数据分析助手", page_icon=":material/analytics:", layout="wide")
    st.title("电商智能数据分析助手")
    api_url = st.sidebar.text_input("API 地址", DEFAULT_API_URL).rstrip("/")
    st.sidebar.caption("数据与指标由后端固定规则计算；LLM 只在 RAG 边界内解释知识。")

    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("pending_uploads", {})
    st.session_state.setdefault("active_datasets", {})
    st.session_state.setdefault("selected_dataset_ids", [])
    if "pending_dataset_selection" in st.session_state:
        st.session_state.selected_dataset_ids = st.session_state.pop(
            "pending_dataset_selection"
        )
    if st.button("新建对话", icon=":material/add_comment:"):
        st.session_state.chat_history = []
        st.session_state.pending_uploads = {}
        st.session_state.active_datasets = {}
        st.session_state.selected_dataset_ids = []
        st.rerun()
    dataset_options = list(st.session_state.active_datasets)
    if dataset_options:
        st.sidebar.multiselect(
            "当前分析数据集",
            dataset_options,
            format_func=lambda dataset_id: st.session_state.active_datasets[dataset_id][
                "label"
            ],
            key="selected_dataset_ids",
        )
    if not st.session_state.chat_history:
        st.info("直接提问，或在下方附加 CSV/Excel。示例：分析用户行为漏斗｜查看 GMV｜GMV 的口径是什么？")
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"], avatar=":material/smart_toy:" if message["role"] == "assistant" else None):
            if message["role"] == "user":
                st.write(message["content"])
            else:
                _show_assistant_message(message, api_url)

    submission = st.chat_input(
        "输入业务问题，或附加 CSV/Excel 后发送",
        key="dashboard_question",
        accept_file="multiple",
        file_type=["csv", "xlsx"],
        submit_mode="disable",
    )
    if submission:
        text = submission.text.strip()
        files = list(submission.files)
        filenames = "、".join(file.name for file in files)
        content = text
        if filenames:
            content = f"{text}\n\n附件：{filenames}" if text else f"已发送文件：{filenames}"
        st.session_state.chat_history.append({"role": "user", "content": content})
        with st.chat_message("user"):
            st.write(content)
        context_tables: list[str] = []
        current_dataset_ids: list[str] = []
        pending_import = False
        for upload in files:
            import_result = _append_import_message(api_url, upload.name, upload.getvalue())
            context_tables.extend(import_result.get("processed_tables", []))
            if import_result.get("dataset_id"):
                current_dataset_ids.append(import_result["dataset_id"])
            pending_import = pending_import or import_result.get("status") in {
                "needs_table_confirmation", "needs_csv_confirmation",
                "database_requires_attention", "import_requires_attention",
            }
        if text and not pending_import:
            try:
                result = _post_json(
                    f"{api_url}/api/dashboard/ask",
                    {
                        "question": text,
                        "context_tables": sorted(
                            set(context_tables)
                            | _selected_context_tables()
                        ),
                        "dataset_ids": sorted(
                            set(st.session_state.selected_dataset_ids)
                            | set(current_dataset_ids)
                        ),
                    },
                )
            except (URLError, TimeoutError, RuntimeError) as exc:
                result = {"error": f"暂时无法连接分析服务：{exc}"}
            message = {"role": "assistant", "content": {"kind": "dashboard", "data": result}}
            with st.chat_message("assistant", avatar=":material/smart_toy:"):
                _show_assistant_message(message, api_url)
            st.session_state.chat_history.append(message)


def _append_import_message(api_url: str, filename: str, content: bytes) -> dict[str, Any]:
    try:
        result = _post_file(f"{api_url}/api/imports", filename, content, None)
    except (URLError, TimeoutError, RuntimeError) as exc:
        result = {"status": "import_requires_attention", "message": f"导入服务暂时没有完成请求：{exc}"}
    upload_id = uuid4().hex
    if result.get("status") == "needs_table_confirmation":
        st.session_state.pending_uploads[upload_id] = {"filename": filename, "content": content}
    _remember_dataset(result, filename)
    message = {"role": "assistant", "content": {"kind": "import", "data": result, "upload_id": upload_id}}
    with st.chat_message("assistant", avatar=":material/smart_toy:"):
        _show_assistant_message(message, api_url)
    st.session_state.chat_history.append(message)
    return result


def _show_assistant_message(message: dict[str, Any], api_url: str) -> None:
    content = message["content"]
    if content.get("kind") == "import":
        _show_import_answer(message, api_url)
        return
    _show_dashboard_answer(content["data"])


def _show_import_answer(message: dict[str, Any], api_url: str) -> None:
    content = message["content"]
    result = content["data"]
    status = result.get("status")
    if status == "needs_table_confirmation":
        st.write(result["message"])
        selected = st.selectbox(
            "选择数据类型",
            result["available_tables"],
            key=f"table_{content['upload_id']}",
        )
        if st.button("按此类型继续导入", key=f"import_{content['upload_id']}", icon=":material/upload:"):
            upload = st.session_state.pending_uploads.get(content["upload_id"])
            if upload is None:
                st.warning("文件已不在当前对话中，请重新附加后发送。")
                return
            try:
                imported = _post_file(f"{api_url}/api/imports", upload["filename"], upload["content"], selected)
            except (URLError, TimeoutError, RuntimeError) as exc:
                st.warning(f"暂时无法连接导入服务：{exc}")
                return
            content["data"] = imported
            _remember_dataset(imported, upload["filename"])
            st.session_state.pending_uploads.pop(content["upload_id"], None)
            st.rerun()
        return
    if status == "needs_csv_confirmation":
        st.write(result["message"])
        return
    if status in {"database_requires_attention", "import_requires_attention"}:
        st.warning(result["message"])
        return
    if status == "already_imported":
        st.info(result["message"])
        return
    detected = "、".join(result.get("processed_tables", []))
    st.success(f"已完成导入：{detected}，写入 {result.get('written_rows', 0)} 行。")
    for recommendation in result.get("analysis_recommendations", []):
        st.write(f"- {recommendation}")


def _remember_dataset(result: dict[str, Any], filename: str) -> None:
    dataset_id = result.get("dataset_id")
    if not dataset_id:
        return
    st.session_state.active_datasets[dataset_id] = {
        "label": filename,
        "tables": sorted(set(result.get("processed_tables", []))),
    }
    selected = set(st.session_state.get("selected_dataset_ids", []))
    selected.add(dataset_id)
    st.session_state.pending_dataset_selection = sorted(selected)


def _selected_context_tables() -> set[str]:
    tables: set[str] = set()
    for dataset_id in st.session_state.get("selected_dataset_ids", []):
        dataset = st.session_state.active_datasets.get(dataset_id, {})
        tables.update(dataset.get("tables", []))
    return tables


def _show_dashboard_answer(result: dict[str, Any]) -> None:
    if result.get("error"):
        st.warning(result["error"])
        return
    st.write(result.get("answer", "未得到可展示的结果。"))
    intent = result.get("intent")
    if intent == "analysis":
        _show_report(result.get("dashboard", {}))
    elif intent == "funnel":
        _show_funnel(result.get("dashboard", {}))
    elif intent == "knowledge":
        citations = {item["index"]: item for item in result.get("citations", [])}
        for index, item in enumerate(result.get("knowledge", []), start=1):
            citation = citations.get(index, item)
            with st.container(border=True):
                st.caption(
                    f"[{index}] {citation['source']} · {citation['title']}"
                )
                st.write(item["content"])
    if result.get("trace_events"):
        with st.expander("运行轨迹", icon=":material/account_tree:"):
            st.dataframe(pd.DataFrame(result["trace_events"]), hide_index=True)


def _show_report(report: dict[str, Any]) -> None:
    sales = report.get("metrics", {}).get("sales", {})
    labels = {"gmv": "成交 GMV", "actual_sales": "实际销售额", "net_sales": "净销售额", "refund_amount": "退款金额"}
    available = {
        name: metric.get("value")
        for name, metric in sales.items()
        if name in labels and metric.get("available") and metric.get("value") is not None
    }
    comparison = report.get("metrics", {}).get("gmv_comparisons", {}).get("day", {})
    gmv_delta = comparison.get("change") if comparison.get("available") else None
    with st.container(horizontal=True):
        for name in labels:
            delta = None
            if name == "gmv" and gmv_delta is not None:
                delta = f"{float(gmv_delta):+.1%} 日环比"
            st.metric(
                labels[name],
                _format_metric(available.get(name)),
                delta=delta,
                border=True,
            )
    if available:
        chart = pd.DataFrame(
            {
                "指标": [labels[name] for name in available],
                "金额": [float(available[name]) for name in available],
            }
        )
        with st.container(border=True):
            st.subheader("销售结构")
            st.bar_chart(chart, x="指标", y="金额", horizontal=True)

    users = report.get("metrics", {}).get("traffic_and_customer", {})
    channels = [
        {"渠道": name, "UV": value.get("uv"), "PV": value.get("pv")}
        for name, value in users.get("channels", {}).items()
        if value.get("available")
    ]
    products = report.get("metrics", {}).get("products", {})
    ranking = products.get("top_by_revenue", {}).get("items", [])
    left, right = st.columns(2)
    if channels:
        with left.container(border=True, height="stretch"):
            st.subheader("渠道流量")
            st.bar_chart(pd.DataFrame(channels), x="渠道", y=["UV", "PV"])
    if ranking:
        with right.container(border=True, height="stretch"):
            st.subheader("商品销售排行")
            st.dataframe(
                pd.DataFrame(ranking),
                hide_index=True,
                column_config={
                    "revenue": st.column_config.NumberColumn("销售额", format="%.2f"),
                    "quantity": st.column_config.NumberColumn("销量"),
                },
            )
    if report.get("valuable_anomalies"):
        with st.container(border=True):
            st.subheader("值得复核的异常", help="异常记录不会在清洗阶段被擅自删除")
            st.dataframe(pd.DataFrame(report["valuable_anomalies"]), hide_index=True)
    if report.get("recommendations"):
        with st.container(border=True):
            st.subheader("运营建议")
            for recommendation in report["recommendations"]:
                st.write(f":material/arrow_right: {recommendation}")
    if report.get("missing_dependencies"):
        st.info(
            "缺少依赖表：" + "、".join(report["missing_dependencies"]),
            icon=":material/info:",
        )
    if report.get("quality_warnings"):
        with st.expander("数据质量说明", icon=":material/fact_check:"):
            st.json(report["quality_warnings"])


def _format_metric(value: object) -> str:
    if value is None:
        return "数据缺失"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _show_funnel(report: dict[str, Any]) -> None:
    if not report.get("available"):
        st.info("尚未导入用户行为漏斗数据。")
        return
    with st.container(horizontal=True):
        st.metric("匿名访客数", report["visitors"], border=True)
        ratio = report.get("new_user_ratio")
        st.metric("新访客占比", "数据缺失" if ratio is None else f"{ratio:.1%}", border=True)
    stages = pd.DataFrame(report["funnel"])
    with st.container(border=True):
        st.subheader("页面访问漏斗")
        st.bar_chart(stages, x="stage", y="visitors", horizontal=True)
        st.dataframe(
            stages,
            hide_index=True,
            column_config={
                "visitors": st.column_config.NumberColumn("访客数"),
                "conversion_from_previous": st.column_config.NumberColumn(
                    "阶段转化率", format="percent"
                ),
            },
        )
    dimensions = pd.DataFrame(report["source_conversion"])
    if not dimensions.empty:
        with st.container(border=True):
            st.subheader("来源渠道确认页转化")
            st.bar_chart(dimensions, x="dimension", y="confirmation_rate")


if __name__ == "__main__":
    main()
