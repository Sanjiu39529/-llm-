"""Sales and after-sales metrics calculated from normalized data frames."""

from datetime import datetime
from decimal import Decimal
from typing import Mapping

import pandas as pd

from backend.app.analytics.common import filter_period, quantize_money, safe_ratio
from backend.app.analytics.models import MetricResult


_PAYMENT_SUCCESS = frozenset({"success", "paid", "支付成功", "已支付"})
_REFUND_SUCCESS = frozenset({"success", "refunded", "退款成功", "已退款"})


def _normalize_status(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().casefold()


def _status_reason(frame: pd.DataFrame, column: str, kind: str) -> str | None:
    if column not in frame.columns:
        return f"missing_{kind}_status"
    if not frame.empty and frame[column].map(_normalize_status).eq("").all():
        return f"empty_{kind}_status"
    return None


def _successful(
    frame: pd.DataFrame, column: str, accepted: frozenset[str]
) -> pd.DataFrame:
    mask = frame[column].map(_normalize_status).isin(accepted)
    return frame.loc[mask].copy()


def _sum_decimal(values: pd.Series) -> Decimal:
    return sum(
        (Decimal(str(value)) for value in values if not pd.isna(value)),
        Decimal("0"),
    )


def _money_result(
    name: str, value: Decimal | int = 0, reason: str | None = None
) -> MetricResult:
    if reason is not None:
        return MetricResult(name, None, False, reason)
    return MetricResult(name, quantize_money(value), True, None)


def _ratio_result(
    name: str, numerator: Decimal | int, denominator: Decimal | int
) -> MetricResult:
    result = safe_ratio(numerator, denominator)
    return MetricResult(name, result.value, result.available, result.reason)


def _unavailable(name: str, reason: str) -> MetricResult:
    return MetricResult(name, None, False, reason)


def _sum_by_order(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=("order_id", *columns)).set_index("order_id")
    rows = []
    for order_id, group in frame.groupby("order_id", sort=False):
        totals = {column: _sum_decimal(group[column]) for column in columns}
        rows.append({"order_id": order_id, **totals})
    return pd.DataFrame(rows).set_index("order_id")


def calculate_sales_metrics(
    tables: Mapping[str, pd.DataFrame],
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
) -> dict[str, MetricResult]:
    """Calculate sales metrics using the left-closed period ``[start, end)``."""
    gmv = _gmv_result(tables.get("order_info"), start, end)

    period_payments, payment_time_reason = _period_dependency(
        tables.get("payment_info"), "payment_info", "paid_at", start, end
    )
    payment_status_reason = payment_time_reason or _status_reason(
        period_payments, "payment_status", "payment"
    )
    successful_payments = (
        period_payments.iloc[0:0].copy()
        if payment_status_reason
        else _successful(period_payments, "payment_status", _PAYMENT_SUCCESS)
    )
    payment_order_reason = payment_status_reason or _missing_column_reason(
        period_payments, "order_id", "missing_payment_order_id"
    )
    payment_amount_reason = payment_order_reason or _missing_column_reason(
        period_payments, "payment_amount", "missing_payment_amount"
    )
    paid_order_ids = (
        set() if payment_order_reason else set(successful_payments["order_id"])
    )

    refund_frame = tables.get("refund_info")
    period_refunds, refund_time_reason = _period_dependency(
        refund_frame, "refund_info", "refunded_at", start, end
    )
    period_refund_status_reason = refund_time_reason or _status_reason(
        period_refunds, "refund_status", "refund"
    )
    successful_period_refunds = (
        period_refunds.iloc[0:0].copy()
        if period_refund_status_reason
        else _successful(period_refunds, "refund_status", _REFUND_SUCCESS)
    )
    refund_order_reason = period_refund_status_reason or _missing_column_reason(
        period_refunds, "order_id", "missing_refund_order_id"
    )
    refund_amount_reason = period_refund_status_reason or _missing_column_reason(
        period_refunds, "refund_amount", "missing_refund_amount"
    )

    cumulative_refund_reason, relevant_refunds = _cumulative_refunds(
        refund_frame, refund_time_reason, paid_order_ids, end
    )
    actual_reason = payment_amount_reason or cumulative_refund_reason
    actual_sales, effective_orders = _actual_sales_result(
        successful_payments,
        relevant_refunds,
        paid_order_ids,
        actual_reason,
    )

    if refund_amount_reason:
        refund_amount = _unavailable("refund_amount", refund_amount_reason)
    else:
        refund_value = _sum_decimal(successful_period_refunds["refund_amount"])
        refund_amount = _money_result("refund_amount", refund_value)

    net_sales = _net_sales_result(actual_sales, refund_amount)
    average_order_value = _average_order_value(actual_sales, len(effective_orders))
    sold_quantity, item_reason = _sold_quantity(
        tables.get("order_item"), paid_order_ids
    )
    item_unit_price = _item_unit_price(actual_sales, sold_quantity, item_reason)
    refund_rate = _refund_rate(
        successful_period_refunds,
        len(paid_order_ids),
        payment_order_reason or refund_order_reason,
    )
    return_rate = _return_rate(
        successful_period_refunds,
        sold_quantity,
        payment_order_reason or refund_order_reason or item_reason,
    )

    return {
        "gmv": gmv,
        "actual_sales": actual_sales,
        "refund_amount": refund_amount,
        "net_sales": net_sales,
        "average_order_value": average_order_value,
        "item_unit_price": item_unit_price,
        "refund_rate": refund_rate,
        "return_rate": return_rate,
    }


def _gmv_result(
    orders: pd.DataFrame | None,
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
) -> MetricResult:
    if orders is None:
        return _unavailable("gmv", "missing_order_info")
    if "order_time" not in orders.columns:
        return _unavailable("gmv", "missing_order_time")
    if "order_amount" not in orders.columns:
        return _unavailable("gmv", "missing_order_amount")
    period_orders = filter_period(orders, "order_time", start, end)
    return _money_result("gmv", _sum_decimal(period_orders["order_amount"]))


def _period_dependency(
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


def _missing_column_reason(
    frame: pd.DataFrame, column: str, reason: str
) -> str | None:
    return reason if column not in frame.columns else None


def _cumulative_refunds(
    refund_frame: pd.DataFrame | None,
    refund_time_reason: str | None,
    paid_order_ids: set[object],
    end: datetime | pd.Timestamp,
) -> tuple[str | None, pd.DataFrame]:
    empty = pd.DataFrame()
    if refund_time_reason:
        return refund_time_reason, empty
    assert refund_frame is not None
    for column, reason in (
        ("refund_status", "missing_refund_status"),
        ("order_id", "missing_refund_order_id"),
        ("refund_amount", "missing_refund_amount"),
    ):
        if column not in refund_frame.columns:
            return reason, empty
    before_end = refund_frame.loc[refund_frame["refunded_at"].lt(end)].copy()
    relevant = before_end.loc[before_end["order_id"].isin(paid_order_ids)].copy()
    reason = _status_reason(relevant, "refund_status", "refund")
    return reason, relevant


def _actual_sales_result(
    successful_payments: pd.DataFrame,
    relevant_refunds: pd.DataFrame,
    paid_order_ids: set[object],
    reason: str | None,
) -> tuple[MetricResult, set[object]]:
    if reason:
        return _unavailable("actual_sales", reason), set()
    payments = successful_payments.copy()
    for column in ("coupon_discount", "promotion_discount", "shipping_fee"):
        if column not in payments.columns:
            payments[column] = Decimal("0")
    payments_by_order = _sum_by_order(
        payments,
        ("payment_amount", "coupon_discount", "promotion_discount", "shipping_fee"),
    )
    successful_refunds = _successful(
        relevant_refunds, "refund_status", _REFUND_SUCCESS
    )
    refunds_by_order = _sum_by_order(successful_refunds, ("refund_amount",))
    fully_refunded = {
        order_id
        for order_id in paid_order_ids
        if order_id in refunds_by_order.index
        and refunds_by_order.at[order_id, "refund_amount"]
        >= payments_by_order.at[order_id, "payment_amount"]
    }
    effective_orders = paid_order_ids - fully_refunded
    actual_value = sum(
        (
            payments_by_order.at[order_id, "payment_amount"]
            - payments_by_order.at[order_id, "coupon_discount"]
            - payments_by_order.at[order_id, "promotion_discount"]
            - payments_by_order.at[order_id, "shipping_fee"]
            for order_id in effective_orders
        ),
        Decimal("0"),
    )
    return _money_result("actual_sales", actual_value), effective_orders


def _net_sales_result(
    actual_sales: MetricResult, refund_amount: MetricResult
) -> MetricResult:
    if not actual_sales.available:
        reason = actual_sales.reason or "unavailable_actual_sales"
        return _unavailable("net_sales", reason)
    if not refund_amount.available:
        reason = refund_amount.reason or "unavailable_refund_amount"
        return _unavailable("net_sales", reason)
    return _money_result("net_sales", actual_sales.value - refund_amount.value)


def _average_order_value(actual_sales: MetricResult, order_count: int) -> MetricResult:
    if not actual_sales.available:
        return _unavailable(
            "average_order_value", actual_sales.reason or "unavailable_actual_sales"
        )
    if order_count == 0:
        return _unavailable("average_order_value", "zero_denominator")
    return _money_result("average_order_value", actual_sales.value / order_count)


def _sold_quantity(
    items: pd.DataFrame | None, paid_order_ids: set[object]
) -> tuple[Decimal, str | None]:
    if items is None:
        return Decimal("0"), "missing_order_item"
    if "order_id" not in items.columns:
        return Decimal("0"), "missing_item_order_id"
    if "quantity" not in items.columns:
        return Decimal("0"), "missing_item_quantity"
    paid_items = items.loc[items["order_id"].isin(paid_order_ids)]
    return _sum_decimal(paid_items["quantity"]), None


def _item_unit_price(
    actual_sales: MetricResult, sold_quantity: Decimal, reason: str | None
) -> MetricResult:
    if not actual_sales.available:
        return _unavailable(
            "item_unit_price", actual_sales.reason or "unavailable_actual_sales"
        )
    if reason is not None:
        return _unavailable("item_unit_price", reason)
    if sold_quantity == 0:
        return _unavailable("item_unit_price", "zero_denominator")
    return _money_result("item_unit_price", actual_sales.value / sold_quantity)


def _refund_rate(
    successful_refunds: pd.DataFrame,
    paid_order_count: int,
    reason: str | None,
) -> MetricResult:
    if reason is not None:
        return _unavailable("refund_rate", reason)
    refunded_order_count = successful_refunds["order_id"].nunique()
    return _ratio_result("refund_rate", refunded_order_count, paid_order_count)


def _return_rate(
    successful_refunds: pd.DataFrame,
    sold_quantity: Decimal,
    reason: str | None,
) -> MetricResult:
    if reason is not None:
        return _unavailable("return_rate", reason)
    if "refund_quantity" not in successful_refunds.columns:
        return _unavailable("return_rate", "missing_refund_quantity")
    return _ratio_result(
        "return_rate",
        _sum_decimal(successful_refunds["refund_quantity"]),
        sold_quantity,
    )
