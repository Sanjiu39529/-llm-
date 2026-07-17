from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

from backend.app.tools.product_tool import calculate_product_metrics


START = datetime(2026, 7, 1)
END = datetime(2026, 7, 2)


def _frame(**columns: list[object]) -> pd.DataFrame:
    return pd.DataFrame(columns)


def _tables() -> dict[str, pd.DataFrame]:
    return {
        "payment_info": _frame(
            order_id=["paid", "paid", "failed", "outside"],
            paid_at=[START, START, START, END],
            payment_status=["success", "paid", "failed", "success"],
        ),
        "order_item": _frame(
            order_id=["paid", "paid", "failed", "outside"],
            product_id=["p2", "p1", "p3", "p4"],
            quantity=[2, 2, 99, 99],
            item_amount=[Decimal("30"), None, Decimal("999"), Decimal("999")],
            unit_price=[Decimal("20"), Decimal("10"), Decimal("10"), Decimal("10")],
        ),
        "product_info": _frame(
            product_id=["p1", "p2", "p3"], product_name=["Alpha", "Beta", "Failed"]
        ),
    }


def test_ranks_paid_items_by_quantity_and_revenue_with_stable_id_ties() -> None:
    metrics = calculate_product_metrics(_tables(), START, END, limit=2)

    assert metrics["top_by_quantity"] == {
        "items": [
            {"product_id": "p1", "product_name": "Alpha", "quantity": Decimal("2"), "revenue": Decimal("20.00")},
            {"product_id": "p2", "product_name": "Beta", "quantity": Decimal("2"), "revenue": Decimal("30.00")},
        ],
        "available": True,
        "reason": None,
    }
    assert [item["product_id"] for item in metrics["top_by_revenue"]["items"]] == ["p2", "p1"]


def test_duplicate_successful_payment_rows_do_not_multiply_order_items() -> None:
    metrics = calculate_product_metrics(_tables(), START, END)

    assert sum(item["quantity"] for item in metrics["top_by_quantity"]["items"]) == Decimal("4")


def test_mixed_unknown_payment_statuses_warn_and_use_only_known_successes() -> None:
    tables = _tables()
    tables["payment_info"].loc[2, "payment_status"] = "mystery"

    metrics = calculate_product_metrics(tables, START, END)

    assert {item["product_id"] for item in metrics["top_by_quantity"]["items"]} == {"p1", "p2"}
    assert metrics["quality_warnings"] == {
        "unknown_payment_statuses": {"count": 1, "values": ["mystery"]}
    }


@pytest.mark.parametrize(
    ("statuses", "reason"),
    [([None, "", None, ""], "empty_payment_status"), (["mystery"] * 4, "unknown_payment_status")],
)
def test_unusable_payment_status_quality_disables_product_rankings(statuses: list[object], reason: str) -> None:
    tables = _tables()
    tables["payment_info"]["payment_status"] = statuses

    metrics = calculate_product_metrics(tables, START, END)

    assert metrics["top_by_quantity"]["reason"] == reason
    assert metrics["top_by_revenue"]["reason"] == reason


def test_missing_revenue_columns_only_disables_revenue_ranking() -> None:
    tables = _tables()
    tables["order_item"] = tables["order_item"].drop(columns=["item_amount", "unit_price"])

    metrics = calculate_product_metrics(tables, START, END)

    assert metrics["top_by_quantity"]["available"] is True
    assert metrics["top_by_revenue"] == {"items": [], "available": False, "reason": "missing_item_amount_and_unit_price"}


def test_missing_quantity_only_disables_quantity_ranking_when_item_amount_exists() -> None:
    tables = _tables()
    tables["order_item"]["item_amount"] = [Decimal("30"), Decimal("20"), Decimal("999"), Decimal("999")]
    tables["order_item"] = tables["order_item"].drop(columns="quantity")

    metrics = calculate_product_metrics(tables, START, END)

    assert metrics["top_by_quantity"]["reason"] == "missing_quantity"
    assert metrics["top_by_revenue"]["available"] is True
    assert all("quantity" not in item for item in metrics["top_by_revenue"]["items"])


def test_missing_product_info_keeps_rankings_with_null_names() -> None:
    tables = _tables()
    del tables["product_info"]

    metrics = calculate_product_metrics(tables, START, END)

    assert metrics["top_by_quantity"]["available"] is True
    assert all(item["product_name"] is None for item in metrics["top_by_quantity"]["items"])


@pytest.mark.parametrize(
    ("table", "column", "reason"),
    [
        ("payment_info", None, "missing_payment_info"),
        ("payment_info", "paid_at", "missing_paid_at"),
        ("payment_info", "order_id", "missing_payment_order_id"),
        ("payment_info", "payment_status", "missing_payment_status"),
        ("order_item", None, "missing_order_item"),
        ("order_item", "order_id", "missing_item_order_id"),
        ("order_item", "product_id", "missing_product_id"),
    ],
)
def test_missing_core_dependencies_disable_both_rankings(table: str, column: str | None, reason: str) -> None:
    tables = _tables()
    if column is None:
        del tables[table]
    else:
        tables[table] = tables[table].drop(columns=column)

    metrics = calculate_product_metrics(tables, START, END)

    assert metrics["top_by_quantity"]["reason"] == reason
    assert metrics["top_by_revenue"]["reason"] == reason
