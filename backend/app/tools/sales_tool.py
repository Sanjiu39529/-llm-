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
    orders = filter_period(tables["order_info"], "order_time", start, end)
    if "order_amount" in orders.columns:
        gmv = _money_result("gmv", _sum_decimal(orders["order_amount"]))
    else:
        gmv = _unavailable("gmv", "missing_order_amount")

    payment_frame = tables["payment_info"]
    period_payments = filter_period(payment_frame, "paid_at", start, end)
    payment_reason = _status_reason(period_payments, "payment_status", "payment")

    refund_frame = tables["refund_info"]
    period_refunds = filter_period(refund_frame, "refunded_at", start, end)
    period_refund_reason = _status_reason(period_refunds, "refund_status", "refund")

    if payment_reason is not None:
        return _payment_unavailable_results(
            gmv, period_refunds, period_refund_reason, payment_reason
        )

    successful_payments = _successful(
        period_payments, "payment_status", _PAYMENT_SUCCESS
    )
    for column in ("coupon_discount", "promotion_discount", "shipping_fee"):
        if column not in successful_payments.columns:
            successful_payments[column] = Decimal("0")
    payments_by_order = _sum_by_order(
        successful_payments,
        ("payment_amount", "coupon_discount", "promotion_discount", "shipping_fee"),
    )
    paid_order_ids = set(payments_by_order.index)

    refunds_before_end = refund_frame.loc[refund_frame["refunded_at"].lt(end)].copy()
    relevant_refunds = refunds_before_end.loc[
        refunds_before_end["order_id"].isin(paid_order_ids)
    ].copy()
    cumulative_refund_reason = _status_reason(
        relevant_refunds, "refund_status", "refund"
    )

    if cumulative_refund_reason is None:
        successful_cumulative_refunds = _successful(
            relevant_refunds, "refund_status", _REFUND_SUCCESS
        )
        cumulative_by_order = _sum_by_order(
            successful_cumulative_refunds, ("refund_amount",)
        )
        fully_refunded = {
            order_id
            for order_id in paid_order_ids
            if order_id in cumulative_by_order.index
            and cumulative_by_order.at[order_id, "refund_amount"]
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
        actual_sales = _money_result("actual_sales", actual_value)
    else:
        effective_orders = set()
        actual_sales = _unavailable("actual_sales", cumulative_refund_reason)

    if period_refund_reason is None:
        successful_period_refunds = _successful(
            period_refunds, "refund_status", _REFUND_SUCCESS
        )
        refund_value = _sum_decimal(successful_period_refunds["refund_amount"])
        refund_amount = _money_result("refund_amount", refund_value)
    else:
        successful_period_refunds = period_refunds.iloc[0:0].copy()
        refund_amount = _unavailable("refund_amount", period_refund_reason)

    net_sales = _net_sales_result(actual_sales, refund_amount)
    average_order_value = _average_order_value(actual_sales, len(effective_orders))
    sold_quantity, item_reason = _sold_quantity(
        tables.get("order_item"), paid_order_ids
    )
    item_unit_price = _item_unit_price(actual_sales, sold_quantity, item_reason)
    refund_rate = _refund_rate(
        successful_period_refunds,
        len(paid_order_ids),
        period_refund_reason,
    )
    return_rate = _return_rate(
        successful_period_refunds,
        sold_quantity,
        period_refund_reason or item_reason,
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


def _payment_unavailable_results(
    gmv: MetricResult,
    period_refunds: pd.DataFrame,
    refund_reason: str | None,
    payment_reason: str,
) -> dict[str, MetricResult]:
    if refund_reason is None:
        successful_refunds = _successful(
            period_refunds, "refund_status", _REFUND_SUCCESS
        )
        refund_amount = _money_result(
            "refund_amount", _sum_decimal(successful_refunds["refund_amount"])
        )
    else:
        refund_amount = _unavailable("refund_amount", refund_reason)
    return {
        "gmv": gmv,
        "actual_sales": _unavailable("actual_sales", payment_reason),
        "refund_amount": refund_amount,
        "net_sales": _unavailable("net_sales", payment_reason),
        "average_order_value": _unavailable("average_order_value", payment_reason),
        "item_unit_price": _unavailable("item_unit_price", payment_reason),
        "refund_rate": _unavailable("refund_rate", payment_reason),
        "return_rate": _unavailable("return_rate", payment_reason),
    }


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
