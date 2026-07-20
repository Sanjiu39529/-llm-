"""Compose deterministic metric tool outputs into a display-ready report."""

from datetime import datetime, timedelta
from typing import Mapping

import pandas as pd

from backend.app.analytics.config import MetricConfig
from backend.app.analytics.models import MetricResult
from backend.app.tools.anomaly_tool import compare_baselines, detect_series_anomalies
from backend.app.tools.channel_tool import calculate_ad_metrics
from backend.app.tools.product_tool import calculate_product_metrics
from backend.app.tools.sales_tool import calculate_sales_metrics
from backend.app.tools.user_tool import calculate_user_metrics


def build_analysis_report(
    tables: Mapping[str, pd.DataFrame],
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
    config: MetricConfig,
) -> dict[str, object]:
    """Assemble report data without duplicating any business calculation formula."""
    sales = calculate_sales_metrics(tables, start, end)
    users = calculate_user_metrics(
        tables, start, end, config.customer_history_days
    )
    ads = calculate_ad_metrics(tables, start, end, config.roi_lookback_days)
    products = calculate_product_metrics(tables, start, end)
    comparisons = compare_baselines(
        lambda source, window_start, window_end: calculate_sales_metrics(
            {"order_info": source.get("order_info")}, window_start, window_end
        )["gmv"],
        tables,
        start,
        end,
        config,
    )
    anomalies = _valuable_anomalies(tables, start, end, config, comparisons)
    metrics = {
        "sales": sales,
        "traffic_and_customer": users,
        "advertising": ads,
        "products": products,
        "gmv_comparisons": comparisons,
    }
    missing = _missing_dependencies(metrics)
    charts = _charts(sales, users, ads, products, missing)
    warnings = _quality_warnings(users, ads, products)
    return {
        "metrics": metrics,
        "charts": charts,
        "analysis_summary": _analysis_summary(sales, users, products, comparisons, missing),
        "missing_dependencies": missing,
        "quality_warnings": warnings,
        "valuable_anomalies": anomalies,
        "recommendations": _recommendations(sales, users, ads, anomalies),
    }


def _analysis_summary(
    sales: Mapping[str, MetricResult],
    users: Mapping[str, object],
    products: Mapping[str, object],
    comparisons: Mapping[str, object],
    missing: list[str],
) -> dict[str, object]:
    """由确定性指标组织可追溯文字结论，绝不自行计算或补造数值。"""
    findings: list[str] = []
    gmv = sales["gmv"]
    if gmv.available:
        findings.append(f"统计期成交 GMV 为 {_format_value(gmv.value)}。")
    net_sales = sales["net_sales"]
    if net_sales.available:
        findings.append(f"净销售额为 {_format_value(net_sales.value)}。")
    day = comparisons.get("day")
    if isinstance(day, MetricResult) and day.available and day.change is not None:
        direction = "增长" if day.change >= 0 else "下降"
        findings.append(f"GMV 较上一日{direction} {abs(float(day.change)):.1%}。")
    channels = users.get("channels")
    if isinstance(channels, Mapping):
        available_channels = [
            (name, values) for name, values in channels.items()
            if isinstance(values, Mapping) and values.get("available")
        ]
        if available_channels:
            top_name, top_values = max(available_channels, key=lambda item: item[1].get("uv", 0))
            findings.append(f"UV 最高的渠道是 {top_name}（{top_values['uv']}）。")
    ranking = products.get("top_by_revenue", {})
    if isinstance(ranking, Mapping) and ranking.get("items"):
        top = ranking["items"][0]
        label = top.get("product_name") or top.get("product_id")
        findings.append(f"销售额最高的商品是 {label}（{_format_value(top.get('revenue'))}）。")
    overview = findings[0] if findings else "当前数据未满足可计算指标的必要条件。"
    return {"overview": overview, "findings": findings, "limitations": missing}


def _format_value(value: object) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _missing_dependencies(metrics: Mapping[str, object]) -> list[str]:
    missing: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, MetricResult):
            if value.reason and value.reason.startswith("missing_"):
                missing.add(value.reason.removeprefix("missing_"))
        elif isinstance(value, Mapping):
            for nested in value.values():
                visit(nested)

    visit(metrics)
    return sorted(missing)


def _charts(
    sales: Mapping[str, MetricResult],
    users: Mapping[str, object],
    ads: Mapping[str, object],
    products: Mapping[str, object],
    missing: list[str],
) -> dict[str, object]:
    charts: dict[str, object] = {
        "sales_overview": {
            "available": any(metric.available for metric in sales.values()),
            "series": {name: metric for name, metric in sales.items()},
        },
        "traffic_overview": {
            "available": isinstance(users.get("uv"), MetricResult)
            and users["uv"].available,
            "series": {name: users[name] for name in ("uv", "pv", "new_visitors", "old_visitors")},
        },
        "ad_efficiency": {
            "available": isinstance(ads.get("spend"), MetricResult)
            and ads["spend"].available,
            "series": {name: ads[name] for name in ("spend", "ctr", "cpm", "cpc", "direct_roi", "indirect_roi", "roi_7d")},
        },
        "product_ranking": {
            "available": products["top_by_quantity"]["available"]
            or products["top_by_revenue"]["available"],
            "series": products,
        },
    }
    for chart in charts.values():
        chart["cancelled"] = not chart["available"]
        chart["missing_dependencies"] = missing if chart["cancelled"] else []
    return charts


def _quality_warnings(*results: Mapping[str, object]) -> dict[str, object]:
    warnings: dict[str, object] = {}
    for result in results:
        quality = result.get("quality_warnings")
        if isinstance(quality, Mapping):
            warnings.update({name: value for name, value in quality.items() if value})
    return warnings


def _valuable_anomalies(
    tables: Mapping[str, pd.DataFrame],
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
    config: MetricConfig,
    comparisons: Mapping[str, object],
) -> list[dict[str, object]]:
    series = _daily_gmv_series(tables, start, end)
    anomalies = [
        {"metric": "gmv", "date": item.date, "value": item.value, "evidences": item.evidences}
        for item in detect_series_anomalies(series, config)
        if item.valuable
    ]
    for baseline, comparison in comparisons.items():
        if getattr(comparison, "available", False) and comparison.level == "severe":
            anomalies.append({"metric": "gmv", "baseline": baseline, "change": comparison.change, "evidences": ("severe_change",)})
    return anomalies


def _daily_gmv_series(
    tables: Mapping[str, pd.DataFrame],
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
) -> pd.Series:
    aggregate = tables.get("_daily_gmv")
    if aggregate is not None and {"date", "gmv"}.issubset(aggregate.columns):
        dates = pd.to_datetime(aggregate["date"], errors="coerce")
        mask = dates.ge(start) & dates.lt(end)
        return pd.Series(aggregate.loc[mask, "gmv"].values, index=dates.loc[mask])
    series: dict[pd.Timestamp, object] = {}
    cursor = pd.Timestamp(start).normalize()
    stop = pd.Timestamp(end).normalize()
    while cursor < stop:
        metric = calculate_sales_metrics(
            {"order_info": tables.get("order_info")}, cursor, cursor + timedelta(days=1)
        )["gmv"]
        if metric.available:
            series[cursor] = metric.value
        cursor += timedelta(days=1)
    return pd.Series(series)


def _recommendations(
    sales: Mapping[str, MetricResult],
    users: Mapping[str, object],
    ads: Mapping[str, object],
    anomalies: list[dict[str, object]],
) -> list[str]:
    recommendations: list[str] = []
    net_sales = sales["net_sales"]
    if net_sales.available and net_sales.value == 0:
        recommendations.append("净销售额为 0，请核查支付与退款数据后再制定运营动作。")
    cart_rate = users.get("cart_rate")
    if isinstance(cart_rate, MetricResult) and cart_rate.available and cart_rate.value < 0.05:
        recommendations.append("加购率偏低，建议优先检查商品详情页与促销承接。")
    direct_roi = ads.get("direct_roi")
    if isinstance(direct_roi, MetricResult) and direct_roi.available and direct_roi.value < 1:
        recommendations.append("直接 ROI 低于 1，建议复核投放定向与落地页转化。")
    if anomalies:
        recommendations.append("检测到有价值的 GMV 异动，建议结合导入批次和业务事件复核。")
    return recommendations
