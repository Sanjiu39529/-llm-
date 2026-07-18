"""Streamlit 操作界面：通过 FastAPI 调用既有业务能力。"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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


def _get_json(url: str, parameters: dict[str, str]) -> dict[str, Any]:
    return _read_json(Request(f"{url}?{urlencode(parameters)}"))


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
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        raise RuntimeError(payload.get("detail", f"HTTP {exc.code}")) from exc


def main() -> None:
    st.set_page_config(page_title="电商智能数据分析助手", page_icon="📊", layout="wide")
    st.title("电商智能数据分析助手")
    api_url = st.sidebar.text_input("API 地址", DEFAULT_API_URL).rstrip("/")
    st.sidebar.caption("请先启动 FastAPI：`python -m uvicorn backend.app.api:app --reload`")

    import_tab, dashboard_tab, funnel_tab, ask_tab = st.tabs(["导入数据", "分析看板", "用户行为漏斗", "业务知识问答"])
    with import_tab:
        st.subheader("导入 CSV 或 Excel")
        upload = st.file_uploader("选择文件", type=["csv", "xlsx"])
        with st.expander("无法自动识别时，手动选择表", expanded=False):
            table = st.selectbox("CSV 对应标准表", ["自动识别", *CSV_TABLES])
        target_table = None if table == "自动识别" else table
        if st.button("自动识别、清洗并导入", disabled=upload is None):
            try:
                result = _post_file(
                    f"{api_url}/api/imports", upload.name, upload.getvalue(), target_table
                )
            except (URLError, TimeoutError, RuntimeError) as exc:
                st.error(f"导入失败：{exc}")
            else:
                detected = "、".join(result["processed_tables"])
                st.success(f"已识别为：{detected}；导入完成")
                for recommendation in result.get("analysis_recommendations", []):
                    st.write(f"- {recommendation}")
                st.json(result)
                if "behavior_funnel" in result["processed_tables"]:
                    _show_funnel(_get_json(f"{api_url}/api/funnels", {}))

    with dashboard_tab:
        st.subheader("数据库分析报告")
        start, end = st.columns(2)
        start_date = start.date_input("开始日期")
        end_date = end.date_input("结束日期")
        if st.button("生成报告"):
            try:
                result = _get_json(
                    f"{api_url}/api/reports",
                    {"start": start_date.isoformat(), "end": end_date.isoformat()},
                )
            except (URLError, TimeoutError, RuntimeError) as exc:
                st.error(f"无法连接 API：{exc}")
            else:
                _show_report(result.get("report", {}))

    with funnel_tab:
        st.subheader("用户行为漏斗")
        st.caption("适用于用户画像与页面访问标记数据，不替代订单或 GMV 分析。")
        if st.button("生成漏斗分析"):
            try:
                _show_funnel(_get_json(f"{api_url}/api/funnels", {}))
            except (URLError, TimeoutError, RuntimeError) as exc:
                st.error(f"获取漏斗失败：{exc}")

    with ask_tab:
        st.subheader("运营规则与指标口径")
        question = st.text_input("例如：GMV 的口径是什么？")
        if st.button("提问", disabled=not question.strip()):
            try:
                result = _post_json(f"{api_url}/api/ask", {"question": question})
            except (URLError, TimeoutError, RuntimeError) as exc:
                st.error(f"无法连接 API：{exc}")
            else:
                if result.get("error"):
                    st.warning(f"未得到结果：{result['error']}")
                else:
                    st.write(result.get("answer"))
                    for item in result.get("knowledge", []):
                        st.caption(f"来源：{item['source']} · {item['title']}")
                        st.write(item["content"])


def _show_report(report: dict[str, Any]) -> None:
    sales = report.get("metrics", {}).get("sales", {})
    labels = {"gmv": "成交 GMV", "actual_sales": "实际销售额", "net_sales": "净销售额", "refund_amount": "退款金额"}
    available = {
        name: metric.get("value")
        for name, metric in sales.items()
        if name in labels and metric.get("available") and metric.get("value") is not None
    }
    columns = st.columns(len(labels))
    for column, name in zip(columns, labels):
        column.metric(labels[name], available.get(name, "数据缺失"))
    if available:
        chart = pd.DataFrame({"金额": [available[name] for name in available]}, index=[labels[name] for name in available])
        st.bar_chart(chart)
    if report.get("valuable_anomalies"):
        st.warning("发现值得复核的异常")
        st.json(report["valuable_anomalies"])
    if report.get("recommendations"):
        st.subheader("运营建议")
        for recommendation in report["recommendations"]:
            st.write(f"- {recommendation}")
    if report.get("missing_dependencies"):
        st.info("缺少依赖表：" + "、".join(report["missing_dependencies"]))


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
        st.bar_chart(stages, x="stage", y="visitors")
        st.dataframe(stages, hide_index=True)
    dimensions = pd.DataFrame(report["source_conversion"])
    if not dimensions.empty:
        with st.container(border=True):
            st.subheader("来源渠道确认页转化")
            st.bar_chart(dimensions, x="dimension", y="confirmation_rate")


if __name__ == "__main__":
    main()
