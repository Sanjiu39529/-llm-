from datetime import datetime
from decimal import Decimal

import pandas as pd

from backend.app.analytics.config import MetricConfig
from backend.app.analytics.report import build_analysis_report


START = datetime(2026, 7, 1)
END = datetime(2026, 7, 2)


def test_report_keeps_sales_and_cancels_missing_traffic_and_ad_charts() -> None:
    report = build_analysis_report(
        {
            "order_info": pd.DataFrame({"order_id": ["o1"], "order_time": [START], "order_amount": [Decimal("10")]}),
            "payment_info": pd.DataFrame({"order_id": ["o1"], "paid_at": [START], "payment_amount": [Decimal("10")], "payment_status": ["success"]}),
            "refund_info": pd.DataFrame({"order_id": [], "refunded_at": [], "refund_amount": [], "refund_status": [], "refund_quantity": []}),
            "order_item": pd.DataFrame({"order_id": ["o1"], "quantity": [1]}),
        },
        START,
        END,
        MetricConfig(),
    )

    assert report["metrics"]["sales"]["gmv"].value == Decimal("10.00")
    assert report["charts"]["traffic_overview"]["cancelled"] is True
    assert report["charts"]["ad_efficiency"]["cancelled"] is True
    assert "traffic_visit" in report["missing_dependencies"]
    assert "ads_info" in report["missing_dependencies"]


def test_report_returns_structured_charts_for_complete_inputs() -> None:
    tables = {
        "order_info": pd.DataFrame({"order_id": ["o1"], "user_id": ["u1"], "order_time": [START], "order_amount": [Decimal("10")]}),
        "payment_info": pd.DataFrame({"order_id": ["o1"], "paid_at": [START], "payment_amount": [Decimal("10")], "payment_status": ["success"]}),
        "refund_info": pd.DataFrame({"order_id": [], "refunded_at": [], "refund_amount": [], "refund_status": [], "refund_quantity": []}),
        "order_item": pd.DataFrame({"order_id": ["o1"], "product_id": ["p1"], "quantity": [1], "item_amount": [Decimal("10")]}),
        "traffic_visit": pd.DataFrame({"user_id": ["u1"], "device_id": ["d1"], "visited_at": [START], "channel": ["自然搜索"]}),
        "ads_info": pd.DataFrame({"ad_id": ["a1"], "ad_date": [START], "channel": ["推荐"], "cost": [Decimal("1")], "impressions": [10], "clicks": [1]}),
        "ad_attribution": pd.DataFrame({"ad_id": ["a1"], "attributed_at": [START], "attribution_amount": [Decimal("2")], "attribution_type": ["direct"]}),
    }
    report = build_analysis_report(tables, START, END, MetricConfig())

    assert report["charts"]["sales_overview"]["available"] is True
    assert report["charts"]["traffic_overview"]["available"] is True
    assert report["charts"]["ad_efficiency"]["available"] is True
    assert report["charts"]["product_ranking"]["available"] is True
