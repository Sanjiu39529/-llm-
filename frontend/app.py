"""Streamlit 操作界面：通过 FastAPI 调用既有业务能力。"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import streamlit as st


DEFAULT_API_URL = "http://127.0.0.1:8000"
CSV_TABLES = ["user_info", "product_info", "order_info", "order_item", "payment_info", "refund_info", "traffic_visit", "behavior_info", "ads_info", "ad_attribution"]


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
    with urlopen(request, timeout=30) as response:  # nosec B310: URL is entered by the local user.
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    st.set_page_config(page_title="电商智能数据分析助手", page_icon="📊", layout="wide")
    st.title("电商智能数据分析助手")
    api_url = st.sidebar.text_input("API 地址", DEFAULT_API_URL).rstrip("/")
    st.sidebar.caption("请先启动 FastAPI：`python -m uvicorn backend.app.api:app --reload`")

    import_tab, ask_tab = st.tabs(["导入数据", "业务知识问答"])
    with import_tab:
        st.subheader("导入 CSV 或 Excel")
        upload = st.file_uploader("选择文件", type=["csv", "xlsx"])
        table = None
        if upload and upload.name.lower().endswith(".csv"):
            table = st.selectbox("CSV 对应标准表", CSV_TABLES)
        if st.button("清洗并导入", disabled=upload is None):
            try:
                result = _post_file(
                    f"{api_url}/api/imports", upload.name, upload.getvalue(), table
                )
            except (URLError, TimeoutError) as exc:
                st.error(f"无法连接 API：{exc}")
            else:
                st.success("导入完成")
                st.json(result)

    with ask_tab:
        st.subheader("运营规则与指标口径")
        question = st.text_input("例如：GMV 的口径是什么？")
        if st.button("提问", disabled=not question.strip()):
            try:
                result = _post_json(f"{api_url}/api/ask", {"question": question})
            except (URLError, TimeoutError) as exc:
                st.error(f"无法连接 API：{exc}")
            else:
                if result.get("error"):
                    st.warning(f"未得到结果：{result['error']}")
                else:
                    st.write(result.get("answer"))
                    for item in result.get("knowledge", []):
                        st.caption(f"来源：{item['source']} · {item['title']}")
                        st.write(item["content"])


if __name__ == "__main__":
    main()
