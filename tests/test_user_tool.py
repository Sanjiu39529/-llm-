from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from backend.app.tools.user_tool import calculate_user_metrics


START = datetime(2026, 7, 1)
END = datetime(2026, 7, 2)
CHANNELS = ("自然搜索", "推荐", "付费投放", "直播", "短视频", "活动流量")


def _frame(**columns: list[object]) -> pd.DataFrame:
    return pd.DataFrame(columns)


def _empty_tables() -> dict[str, pd.DataFrame]:
    return {
        "traffic_visit": _frame(
            visit_id=[], visited_at=[], user_id=[], device_id=[], channel=[]
        ),
        "order_info": _frame(order_id=[], user_id=[], order_time=[]),
        "payment_info": _frame(
            order_id=[], paid_at=[], payment_status=[]
        ),
        "behavior_info": _frame(
            event_id=[], event_type=[], occurred_at=[], user_id=[], visit_id=[]
        ),
    }


def test_strict_visitor_deduplication_and_unidentified_rows_only_add_pv() -> None:
    tables = _empty_tables()
    tables["traffic_visit"] = _frame(
        visit_id=["v1", "v2", "v3", "v4", "v5"],
        visited_at=[START] * 5,
        user_id=["u1", "u1", None, None, None],
        device_id=["d1", "d2", "anon", "anon", None],
        channel=["自然搜索"] * 5,
    )

    metrics = calculate_user_metrics(tables, START, END)

    assert metrics["pv"].value == 5
    assert metrics["uv"].value == 2
    assert metrics["channels"]["自然搜索"] == {"uv": 2, "pv": 5}


def test_first_historical_visit_classifies_period_visitors_as_new_or_old() -> None:
    tables = _empty_tables()
    tables["traffic_visit"] = _frame(
        visit_id=["old-history", "old-now", "new-now", "after-end"],
        visited_at=[START - timedelta(days=20), START, START, END],
        user_id=["old", "old", "new", "ignored"],
        device_id=[None] * 4,
        channel=["推荐"] * 4,
    )

    metrics = calculate_user_metrics(tables, START, END)

    assert metrics["uv"].value == 2
    assert metrics["new_visitors"].value == 1
    assert metrics["old_visitors"].value == 1


def test_outputs_six_channels_and_warns_without_merging_unknown_channels() -> None:
    tables = _empty_tables()
    tables["traffic_visit"] = _frame(
        visit_id=[f"v{i}" for i in range(8)],
        visited_at=[START] * 8,
        user_id=[f"u{i}" for i in range(8)],
        device_id=[None] * 8,
        channel=[*CHANNELS, "站外联盟", None],
    )

    metrics = calculate_user_metrics(tables, START, END)

    assert set(metrics["channels"]) == set(CHANNELS)
    assert all(metrics["channels"][channel] == {"uv": 1, "pv": 1} for channel in CHANNELS)
    assert sum(item["pv"] for item in metrics["channels"].values()) == 6
    assert metrics["quality_warnings"] == {
        "unknown_channels": ["<missing>", "站外联盟"]
    }


def test_calculates_three_conversion_rates_from_period_user_sets() -> None:
    tables = _empty_tables()
    tables["traffic_visit"] = _frame(
        visit_id=["v1", "v2", "v3", "v4"],
        visited_at=[START] * 4,
        user_id=["u1", "u2", "u3", "u4"],
        device_id=[None] * 4,
        channel=["直播"] * 4,
    )
    tables["order_info"] = _frame(
        order_id=["o1", "o2", "outside"],
        user_id=["u1", "u2", "u4"],
        order_time=[START, START, END],
    )
    tables["payment_info"] = _frame(
        order_id=["o1", "o2", "outside", "failed"],
        paid_at=[START, START, START, START],
        payment_status=["支付成功", "failed", "paid", "success"],
    )

    metrics = calculate_user_metrics(tables, START, END)

    assert metrics["order_conversion"].value == Decimal("0.5000")
    assert metrics["payment_conversion"].value == Decimal("1.0000")
    assert metrics["overall_conversion"].value == Decimal("0.5000")


def test_cart_rate_prefers_event_user_then_links_visit_for_anonymous_event() -> None:
    tables = _empty_tables()
    tables["traffic_visit"] = _frame(
        visit_id=["direct", "linked", "other"],
        visited_at=[START] * 3,
        user_id=["u1", None, "u3"],
        device_id=["ignored", "d2", None],
        channel=["短视频"] * 3,
    )
    tables["behavior_info"] = _frame(
        event_id=["e1", "e2", "e3", "e4", "e5"],
        event_type=["add_to_cart", "加购", "view", "加购", "加购"],
        occurred_at=[START] * 5,
        user_id=["u1", None, "u3", None, "override"],
        visit_id=["linked", "linked", "other", "missing", "linked"],
    )

    metrics = calculate_user_metrics(tables, START, END)

    assert metrics["cart_rate"].value == Decimal("1.0000")


def test_cart_visit_linkage_ignores_traffic_outside_period() -> None:
    tables = _empty_tables()
    tables["traffic_visit"] = _frame(
        visit_id=["current", "historical"],
        visited_at=[START, START - timedelta(days=1)],
        user_id=["current-user", None],
        device_id=[None, "historical-device"],
        channel=["自然搜索", "自然搜索"],
    )
    tables["behavior_info"] = _frame(
        event_id=["current-cart", "historical-cart"],
        event_type=["加购", "加购"],
        occurred_at=[START, START],
        user_id=["current-user", None],
        visit_id=["current", "historical"],
    )

    metrics = calculate_user_metrics(tables, START, END)

    assert metrics["cart_rate"].value == Decimal("1.0000")


def test_customer_metrics_use_successful_payments_in_configured_history_window() -> None:
    tables = _empty_tables()
    tables["order_info"] = _frame(
        order_id=["old-history", "too-old", "old-now", "new-now", "too-old-now"],
        user_id=["old", "too-old", "old", "new", "too-old"],
        order_time=[
            START - timedelta(days=30),
            START - timedelta(days=400),
            START,
            START,
            START,
        ],
    )
    tables["payment_info"] = _frame(
        order_id=["old-history", "too-old", "old-now", "new-now", "too-old-now"],
        paid_at=[
            START - timedelta(days=30),
            START - timedelta(days=400),
            START,
            START,
            START,
        ],
        payment_status=["success", "已支付", "paid", "支付成功", "success"],
    )

    metrics = calculate_user_metrics(
        tables, START, END, customer_history_days=365
    )

    assert metrics["repeat_rate"].value == Decimal("0.3333")
    assert metrics["new_customer_share"].value == Decimal("0.6667")


def test_missing_traffic_only_disables_traffic_dependent_metrics() -> None:
    tables = _empty_tables()
    del tables["traffic_visit"]
    tables["order_info"] = _frame(
        order_id=["history", "now"],
        user_id=["u1", "u1"],
        order_time=[START - timedelta(days=1), START],
    )
    tables["payment_info"] = _frame(
        order_id=["history", "now"],
        paid_at=[START - timedelta(days=1), START],
        payment_status=["success", "success"],
    )

    metrics = calculate_user_metrics(tables, START, END)

    for name in (
        "uv",
        "pv",
        "new_visitors",
        "old_visitors",
        "order_conversion",
        "overall_conversion",
        "cart_rate",
    ):
        assert metrics[name].available is False
        assert metrics[name].reason == "missing_traffic_visit"
    assert metrics["payment_conversion"].value == Decimal("1.0000")
    assert metrics["repeat_rate"].value == Decimal("1.0000")
    assert metrics["new_customer_share"].value == Decimal("0.0000")


def test_missing_dependencies_degrade_only_metrics_that_need_them() -> None:
    tables = _empty_tables()
    del tables["behavior_info"]
    del tables["payment_info"]

    metrics = calculate_user_metrics(tables, START, END)

    assert metrics["uv"].value == 0
    assert metrics["pv"].value == 0
    assert metrics["cart_rate"].reason == "missing_behavior_info"
    for name in (
        "payment_conversion",
        "overall_conversion",
        "repeat_rate",
        "new_customer_share",
    ):
        assert metrics[name].available is False
        assert metrics[name].reason == "missing_payment_info"
    assert metrics["order_conversion"].reason == "zero_denominator"


def test_missing_channel_column_is_reported_as_unattributed_traffic() -> None:
    tables = _empty_tables()
    tables["traffic_visit"] = _frame(
        visit_id=["v1"],
        visited_at=[START],
        user_id=["u1"],
        device_id=[None],
    )

    metrics = calculate_user_metrics(tables, START, END)

    assert metrics["channels"] == {
        channel: {"uv": 0, "pv": 0} for channel in CHANNELS
    }
    assert metrics["quality_warnings"] == {"unknown_channels": ["<missing>"]}


@pytest.mark.parametrize(
    ("table_name", "column", "reason", "unavailable_names"),
    [
        (
            "traffic_visit",
            "visited_at",
            "missing_visited_at",
            {
                "uv",
                "pv",
                "new_visitors",
                "old_visitors",
                "order_conversion",
                "overall_conversion",
                "cart_rate",
            },
        ),
        (
            "order_info",
            "order_time",
            "missing_order_time",
            {"order_conversion", "payment_conversion"},
        ),
        (
            "payment_info",
            "paid_at",
            "missing_paid_at",
            {
                "payment_conversion",
                "overall_conversion",
                "repeat_rate",
                "new_customer_share",
            },
        ),
        (
            "behavior_info",
            "event_type",
            "missing_event_type",
            {"cart_rate"},
        ),
    ],
)
def test_missing_critical_columns_only_disable_dependent_metrics(
    table_name: str,
    column: str,
    reason: str,
    unavailable_names: set[str],
) -> None:
    tables = _empty_tables()
    tables[table_name] = tables[table_name].drop(columns=column)

    metrics = calculate_user_metrics(tables, START, END)

    for name in unavailable_names:
        assert metrics[name].available is False
        assert metrics[name].reason == reason
