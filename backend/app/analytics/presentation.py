"""根据用户问题选择已有、可计算的图表，不改变任何指标口径。"""

from __future__ import annotations

from collections.abc import Mapping


_QUESTION_CHARTS = (
    (("趋势", "环比", "同比", "gmv", "销售", "营收", "订单", "退款"), "sales_overview"),
    (("渠道", "流量", "uv", "pv", "访客"), "traffic_overview"),
    (("商品", "品类", "销量", "排行"), "product_ranking"),
    (("投放", "广告", "roi", "ctr", "cpc", "cpm"), "ad_efficiency"),
)


def select_chart_keys(question: str, charts: Mapping[str, object]) -> dict[str, object]:
    """返回最多四张与问题相关且数据可用的图表键。"""
    normalized = question.lower()
    matched = [
        chart_key
        for keywords, chart_key in _QUESTION_CHARTS
        if any(keyword in normalized for keyword in keywords)
    ]
    available = [
        key for key, chart in charts.items()
        if isinstance(chart, Mapping) and chart.get("available")
    ]
    selected = [key for key in matched if key in available]
    if not selected:
        selected = available
    return {
        "selected_chart_keys": selected[:4],
        "selection_reason": "问题未指向具体维度，展示可用数据概览。"
        if not matched
        else "已按问题中的业务维度选择相关图表。",
    }
