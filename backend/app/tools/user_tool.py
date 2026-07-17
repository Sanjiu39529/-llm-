"""Traffic, conversion, and customer metrics from normalized data frames."""

from datetime import datetime, timedelta
from typing import Mapping

import pandas as pd

from backend.app.analytics.common import filter_period, safe_ratio
from backend.app.analytics.models import MetricResult


_CHANNELS = ("自然搜索", "推荐", "付费投放", "直播", "短视频", "活动流量")
_PAYMENT_SUCCESS = frozenset({"success", "paid", "支付成功", "已支付"})
_CART_EVENTS = frozenset({"add_to_cart", "加购"})


def calculate_user_metrics(
    tables: Mapping[str, pd.DataFrame],
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
    customer_history_days: int = 365,
) -> dict[str, MetricResult | dict]:
    """Calculate user metrics in the left-closed period ``[start, end)``."""
    traffic, traffic_reason = _period_frame(
        tables.get("traffic_visit"), "traffic_visit", "visited_at", start, end
    )
    traffic_keys = _visitor_keys(traffic)

    uv = _count_result("uv", traffic_keys.nunique(), traffic_reason)
    pv = _count_result("pv", len(traffic), traffic_reason)
    new_visitors, old_visitors = _visitor_age_results(
        tables.get("traffic_visit"), traffic_keys, start, traffic_reason
    )

    orders, order_reason = _period_frame(
        tables.get("order_info"), "order_info", "order_time", start, end
    )
    order_user_reason = order_reason or _missing_column(orders, "user_id")
    order_users = _values(orders, "user_id") if not order_user_reason else set()

    payments, payment_reason = _successful_period_payments(tables, start, end)
    payment_users, payment_user_reason = _payment_users(
        tables.get("order_info"), payments, payment_reason
    )

    order_conversion = _ratio_result(
        "order_conversion",
        len(order_users),
        len(traffic_keys.dropna().unique()),
        traffic_reason or order_user_reason,
    )
    payment_conversion = _ratio_result(
        "payment_conversion",
        len(payment_users),
        len(order_users),
        order_user_reason or payment_user_reason,
    )
    overall_conversion = _ratio_result(
        "overall_conversion",
        len(payment_users),
        len(traffic_keys.dropna().unique()),
        traffic_reason or payment_user_reason,
    )
    cart_rate = _cart_rate(
        tables.get("behavior_info"),
        traffic,
        start,
        end,
        len(traffic_keys.dropna().unique()),
        traffic_reason,
    )
    repeat_rate, new_customer_share = _customer_results(
        tables.get("order_info"),
        tables.get("payment_info"),
        payment_users,
        start,
        customer_history_days,
        payment_user_reason,
    )
    channels, unknown_channels = _channel_results(traffic, traffic_reason)

    return {
        "uv": uv,
        "pv": pv,
        "new_visitors": new_visitors,
        "old_visitors": old_visitors,
        "order_conversion": order_conversion,
        "payment_conversion": payment_conversion,
        "overall_conversion": overall_conversion,
        "cart_rate": cart_rate,
        "repeat_rate": repeat_rate,
        "new_customer_share": new_customer_share,
        "channels": channels,
        "quality_warnings": {"unknown_channels": unknown_channels},
    }


def _period_frame(
    frame: pd.DataFrame | None,
    table_name: str,
    time_column: str,
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
) -> tuple[pd.DataFrame, str | None]:
    if frame is None:
        return pd.DataFrame(), f"missing_{table_name}"
    if time_column not in frame.columns:
        return frame.iloc[0:0].copy(), f"missing_{time_column}"
    return filter_period(frame, time_column, start, end), None


def _identifier(value: object) -> str | None:
    if pd.isna(value):
        return None
    normalized = str(value).strip()
    return normalized or None


def _visitor_key(user_id: object, device_id: object) -> str | None:
    user = _identifier(user_id)
    if user is not None:
        return f"user:{user}"
    device = _identifier(device_id)
    return f"device:{device}" if device is not None else None


def _visitor_keys(frame: pd.DataFrame) -> pd.Series:
    users = frame["user_id"] if "user_id" in frame else pd.Series(None, index=frame.index)
    devices = (
        frame["device_id"] if "device_id" in frame else pd.Series(None, index=frame.index)
    )
    return pd.Series(
        (_visitor_key(user, device) for user, device in zip(users, devices)),
        index=frame.index,
        dtype="object",
    )


def _visitor_age_results(
    all_traffic: pd.DataFrame | None,
    period_keys: pd.Series,
    start: datetime | pd.Timestamp,
    reason: str | None,
) -> tuple[MetricResult, MetricResult]:
    if reason is not None:
        return (
            _unavailable("new_visitors", reason),
            _unavailable("old_visitors", reason),
        )
    assert all_traffic is not None
    history = all_traffic.copy()
    history["_visitor_key"] = _visitor_keys(history)
    first_visits = history.dropna(subset=["_visitor_key"]).groupby("_visitor_key")[
        "visited_at"
    ].min()
    current = set(period_keys.dropna().unique())
    old_count = sum(first_visits[key] < start for key in current)
    return (
        _count_result("new_visitors", len(current) - old_count),
        _count_result("old_visitors", old_count),
    )


def _successful_period_payments(
    tables: Mapping[str, pd.DataFrame],
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
) -> tuple[pd.DataFrame, str | None]:
    payments, reason = _period_frame(
        tables.get("payment_info"), "payment_info", "paid_at", start, end
    )
    reason = reason or _missing_column(payments, "payment_status")
    if reason is not None:
        return payments.iloc[0:0].copy(), reason
    statuses = payments["payment_status"].map(_normalize)
    return payments.loc[statuses.isin(_PAYMENT_SUCCESS)].copy(), None


def _payment_users(
    all_orders: pd.DataFrame | None,
    payments: pd.DataFrame,
    reason: str | None,
) -> tuple[set[str], str | None]:
    if reason is not None:
        return set(), reason
    if all_orders is None:
        return set(), "missing_order_info"
    for column in ("order_id", "user_id"):
        if column not in all_orders.columns:
            return set(), f"missing_{column}"
    if "order_id" not in payments.columns:
        return set(), "missing_order_id"
    order_users = {
        _identifier(order_id): _identifier(user_id)
        for order_id, user_id in zip(all_orders["order_id"], all_orders["user_id"])
        if _identifier(order_id) is not None
    }
    users = {
        order_users[order_id]
        for value in payments["order_id"]
        if (order_id := _identifier(value)) in order_users
        and order_users[order_id] is not None
    }
    return users, None


def _cart_rate(
    behavior: pd.DataFrame | None,
    traffic: pd.DataFrame | None,
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
    store_uv: int,
    traffic_reason: str | None,
) -> MetricResult:
    if traffic_reason is not None:
        return _unavailable("cart_rate", traffic_reason)
    period, reason = _period_frame(
        behavior, "behavior_info", "occurred_at", start, end
    )
    reason = reason or _missing_column(period, "event_type")
    if reason is not None:
        return _unavailable("cart_rate", reason)
    carts = period.loc[period["event_type"].map(_normalize).isin(_CART_EVENTS)]
    visit_keys: dict[str, str] = {}
    assert traffic is not None
    if "visit_id" in traffic.columns:
        for visit_id, key in zip(traffic["visit_id"], _visitor_keys(traffic)):
            normalized_visit = _identifier(visit_id)
            if normalized_visit is not None and key is not None:
                visit_keys[normalized_visit] = key
    cart_users: set[str] = set()
    for _, row in carts.iterrows():
        user = _identifier(row.get("user_id"))
        if user is not None:
            cart_users.add(f"user:{user}")
            continue
        visit_id = _identifier(row.get("visit_id"))
        if visit_id in visit_keys:
            cart_users.add(visit_keys[visit_id])
    return _ratio_result("cart_rate", len(cart_users), store_uv)


def _customer_results(
    orders: pd.DataFrame | None,
    payments: pd.DataFrame | None,
    period_users: set[str],
    start: datetime | pd.Timestamp,
    history_days: int,
    reason: str | None,
) -> tuple[MetricResult, MetricResult]:
    if reason is not None:
        return (
            _unavailable("repeat_rate", reason),
            _unavailable("new_customer_share", reason),
        )
    assert payments is not None
    history_start = start - timedelta(days=history_days)
    history = filter_period(payments, "paid_at", history_start, start)
    if "payment_status" not in history.columns:
        reason = "missing_payment_status"
    elif "order_id" not in history.columns:
        reason = "missing_order_id"
    if reason is not None:
        return (
            _unavailable("repeat_rate", reason),
            _unavailable("new_customer_share", reason),
        )
    successful = history.loc[
        history["payment_status"].map(_normalize).isin(_PAYMENT_SUCCESS)
    ]
    historical_users, history_reason = _payment_users(orders, successful, None)
    if history_reason is not None:
        return (
            _unavailable("repeat_rate", history_reason),
            _unavailable("new_customer_share", history_reason),
        )
    old_users = period_users & historical_users
    return (
        _ratio_result("repeat_rate", len(old_users), len(period_users)),
        _ratio_result(
            "new_customer_share", len(period_users - old_users), len(period_users)
        ),
    )


def _channel_results(
    traffic: pd.DataFrame, reason: str | None
) -> tuple[dict[str, dict[str, int]], list[str]]:
    empty = {channel: {"uv": 0, "pv": 0} for channel in _CHANNELS}
    if reason is not None:
        return empty, []
    if "channel" not in traffic.columns:
        return empty, ["<missing>"]
    keys = _visitor_keys(traffic)
    result = {}
    for channel in _CHANNELS:
        rows = traffic.loc[traffic["channel"].map(_normalize).eq(channel)]
        result[channel] = {
            "uv": int(keys.loc[rows.index].nunique()),
            "pv": len(rows),
        }
    unknown = {
        "<missing>" if _identifier(value) is None else str(value).strip()
        for value in traffic["channel"]
        if _normalize(value) not in _CHANNELS
    }
    return result, sorted(unknown)


def _normalize(value: object) -> str:
    normalized = _identifier(value)
    return normalized.casefold() if normalized is not None else ""


def _values(frame: pd.DataFrame, column: str) -> set[str]:
    return {
        normalized
        for value in frame[column]
        if (normalized := _identifier(value)) is not None
    }


def _missing_column(frame: pd.DataFrame, column: str) -> str | None:
    return f"missing_{column}" if column not in frame.columns else None


def _count_result(name: str, value: int, reason: str | None = None) -> MetricResult:
    return _unavailable(name, reason) if reason else MetricResult(name, value, True, None)


def _ratio_result(
    name: str, numerator: int, denominator: int, reason: str | None = None
) -> MetricResult:
    if reason is not None:
        return _unavailable(name, reason)
    ratio = safe_ratio(numerator, denominator)
    return MetricResult(name, ratio.value, ratio.available, ratio.reason)


def _unavailable(name: str, reason: str) -> MetricResult:
    return MetricResult(name, None, False, reason)
