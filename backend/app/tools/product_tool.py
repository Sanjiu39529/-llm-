"""Product quantity and revenue rankings for successfully paid orders."""

from datetime import datetime
from decimal import Decimal
from typing import Mapping

import pandas as pd

from backend.app.analytics.common import (
    PAYMENT_KNOWN_STATUSES,
    PAYMENT_SUCCESS_STATUSES,
    accepted_status_mask,
    filter_period,
    normalize_status,
    quantize_money,
)


def calculate_product_metrics(
    tables: Mapping[str, pd.DataFrame],
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
    limit: int = 10,
) -> dict[str, dict]:
    """Rank products from unique successful period payment order IDs."""
    payments, payment_reason = _period_payments(
        tables.get("payment_info"), start, end
    )
    successful, status_reason, warning = _successful_payments(
        payments, payment_reason
    )
    core_reason = status_reason or _missing(
        payments, "order_id", "missing_payment_order_id"
    )
    items = tables.get("order_item")
    if core_reason is None and items is None:
        core_reason = "missing_order_item"
    if core_reason is None:
        assert items is not None
        for column, reason in (
            ("order_id", "missing_item_order_id"),
            ("product_id", "missing_product_id"),
        ):
            core_reason = _missing(items, column, reason)
            if core_reason is not None:
                break

    if core_reason is not None:
        return {
            "top_by_quantity": _unavailable(core_reason),
            "top_by_revenue": _unavailable(core_reason),
            "quality_warnings": _quality_warnings(warning),
        }

    assert items is not None
    paid_order_ids = set(successful["order_id"].dropna())
    paid_items = items.loc[items["order_id"].isin(paid_order_ids)].copy()
    quantity_reason = _missing(paid_items, "quantity", "missing_quantity")
    revenue_reason = _revenue_reason(paid_items, quantity_reason)
    names = _product_names(tables.get("product_info"))

    aggregates: dict[object, dict[str, Decimal]] = {}
    for product_id, group in paid_items.groupby("product_id", sort=False):
        quantity = (
            _sum_decimal(group["quantity"])
            if quantity_reason is None
            else Decimal("0")
        )
        revenue = (
            _group_revenue(group) if revenue_reason is None else Decimal("0")
        )
        aggregates[product_id] = {"quantity": quantity, "revenue": revenue}

    quantity_items = []
    if quantity_reason is None:
        quantity_items = _ranked_items(
            aggregates, names, "quantity", limit, True, revenue_reason is None
        )
    revenue_items = []
    if revenue_reason is None:
        revenue_items = _ranked_items(
            aggregates, names, "revenue", limit, quantity_reason is None, True
        )
    return {
        "top_by_quantity": _ranking(quantity_items, quantity_reason),
        "top_by_revenue": _ranking(revenue_items, revenue_reason),
        "quality_warnings": _quality_warnings(warning),
    }


def _period_payments(
    payments: pd.DataFrame | None,
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
) -> tuple[pd.DataFrame, str | None]:
    if payments is None:
        return pd.DataFrame(), "missing_payment_info"
    if "paid_at" not in payments.columns:
        return payments.iloc[0:0].copy(), "missing_paid_at"
    return filter_period(payments, "paid_at", start, end), None


def _successful_payments(
    payments: pd.DataFrame, reason: str | None
) -> tuple[pd.DataFrame, str | None, dict[str, object] | None]:
    if reason is not None:
        return payments.iloc[0:0].copy(), reason, None
    if "payment_status" not in payments.columns:
        return payments.iloc[0:0].copy(), "missing_payment_status", None
    statuses = payments["payment_status"].map(normalize_status)
    known = statuses.isin(PAYMENT_KNOWN_STATUSES)
    unknown = ~known
    warning = None
    if unknown.any():
        warning = {
            "count": int(unknown.sum()),
            "values": sorted({value or "<missing>" for value in statuses.loc[unknown]}),
        }
    if not payments.empty and not known.any():
        status_reason = (
            "empty_payment_status" if statuses.eq("").all() else "unknown_payment_status"
        )
        return payments.iloc[0:0].copy(), status_reason, warning
    successful = payments.loc[
        accepted_status_mask(payments["payment_status"], PAYMENT_SUCCESS_STATUSES)
    ].copy()
    return successful, None, warning


def _revenue_reason(items: pd.DataFrame, quantity_reason: str | None) -> str | None:
    has_item_amount = "item_amount" in items.columns
    has_unit_price = "unit_price" in items.columns and quantity_reason is None
    if not has_item_amount and not has_unit_price:
        return "missing_item_amount_and_unit_price"
    for _, row in items.iterrows():
        if has_item_amount and not pd.isna(row["item_amount"]):
            continue
        if has_unit_price and not pd.isna(row["unit_price"]) and not pd.isna(row["quantity"]):
            continue
        return "missing_item_amount_and_unit_price"
    return None


def _group_revenue(group: pd.DataFrame) -> Decimal:
    total = Decimal("0")
    for _, row in group.iterrows():
        if "item_amount" in group.columns and not pd.isna(row["item_amount"]):
            total += Decimal(str(row["item_amount"]))
        else:
            total += Decimal(str(row["unit_price"])) * Decimal(str(row["quantity"]))
    return total


def _product_names(products: pd.DataFrame | None) -> dict[object, object]:
    if products is None or not {"product_id", "product_name"}.issubset(products.columns):
        return {}
    return dict(
        products.drop_duplicates("product_id", keep="first")[["product_id", "product_name"]]
        .itertuples(index=False, name=None)
    )


def _ranked_items(
    aggregates: dict[object, dict[str, Decimal]],
    names: dict[object, object],
    key: str,
    limit: int,
    include_quantity: bool,
    include_revenue: bool,
) -> list[dict[str, object]]:
    ordered = sorted(
        aggregates.items(), key=lambda item: (-item[1][key], str(item[0]))
    )[: max(limit, 0)]
    rows = []
    for product_id, values in ordered:
        row: dict[str, object] = {
            "product_id": product_id,
            "product_name": names.get(product_id),
        }
        if include_quantity:
            row["quantity"] = values["quantity"]
        if include_revenue:
            row["revenue"] = quantize_money(values["revenue"])
        rows.append(row)
    return rows


def _sum_decimal(values: pd.Series) -> Decimal:
    return sum(
        (Decimal(str(value)) for value in values if not pd.isna(value)),
        Decimal("0"),
    )


def _missing(
    frame: pd.DataFrame, column: str, reason: str
) -> str | None:
    return reason if column not in frame.columns else None


def _ranking(items: list[dict[str, object]], reason: str | None) -> dict[str, object]:
    if reason is not None:
        return _unavailable(reason)
    return {"items": items, "available": True, "reason": None}


def _unavailable(reason: str) -> dict[str, object]:
    return {"items": [], "available": False, "reason": reason}


def _quality_warnings(warning: dict[str, object] | None) -> dict[str, object]:
    return {"unknown_payment_statuses": warning} if warning is not None else {}
