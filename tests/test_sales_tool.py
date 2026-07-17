from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from backend.app.tools.sales_tool import calculate_sales_metrics


START = datetime(2026, 7, 1)
END = datetime(2026, 7, 2)


def _frame(**columns: list[object]) -> pd.DataFrame:
    return pd.DataFrame(columns)


def _empty_tables() -> dict[str, pd.DataFrame]:
    return {
        "order_info": _frame(order_id=[], order_time=[], order_amount=[]),
        "payment_info": _frame(
            order_id=[], paid_at=[], payment_amount=[], payment_status=[]
        ),
        "refund_info": _frame(
            order_id=[],
            refunded_at=[],
            refund_amount=[],
            refund_status=[],
            refund_quantity=[],
        ),
        "order_item": _frame(order_id=[], quantity=[]),
    }


def test_calculates_sales_metrics_after_aggregating_each_order() -> None:
    tables = {
        "order_info": _frame(
            order_id=["normal", "partial", "full"],
            order_time=[START, START, START],
            order_amount=[Decimal("100"), Decimal("200"), Decimal("300")],
        ),
        "payment_info": _frame(
            order_id=["normal", "partial", "partial", "full"],
            paid_at=[START, START, START, START],
            payment_amount=[
                Decimal("100"), Decimal("120"), Decimal("80"), Decimal("300")
            ],
            payment_status=[" SUCCESS ", "paid", "支付成功", "已支付"],
            coupon_discount=[Decimal("10"), Decimal("5"), Decimal("0"), Decimal("0")],
            promotion_discount=[
                Decimal("5"), Decimal("10"), Decimal("0"), Decimal("0")
            ],
            shipping_fee=[Decimal("3"), Decimal("0"), Decimal("0"), Decimal("0")],
        ),
        "refund_info": _frame(
            order_id=["partial", "partial", "full"],
            refunded_at=[START, START, START - timedelta(seconds=1)],
            refund_amount=[Decimal("20"), Decimal("30"), Decimal("300")],
            refund_status=["success", "退款成功", "已退款"],
            refund_quantity=[1, 1, 4],
        ),
        "order_item": _frame(
            order_id=["normal", "normal", "partial", "full"],
            quantity=[2, 1, 2, 4],
        ),
    }

    metrics = calculate_sales_metrics(tables, START, END)

    assert set(metrics) == {
        "gmv",
        "actual_sales",
        "refund_amount",
        "net_sales",
        "average_order_value",
        "item_unit_price",
        "refund_rate",
        "return_rate",
    }
    assert metrics["gmv"].value == Decimal("600.00")
    assert metrics["actual_sales"].value == Decimal("267.00")
    assert metrics["refund_amount"].value == Decimal("50.00")
    assert metrics["net_sales"].value == Decimal("217.00")
    assert metrics["average_order_value"].value == Decimal("133.50")
    assert metrics["item_unit_price"].value == Decimal("29.67")
    assert metrics["refund_rate"].value == Decimal("0.3333")
    assert metrics["return_rate"].value == Decimal("0.2222")
    assert all(metric.available for metric in metrics.values())


def test_rejects_failed_payment_and_refund_statuses() -> None:
    tables = _empty_tables()
    tables["payment_info"] = _frame(
        order_id=["paid", "failed"],
        paid_at=[START, START],
        payment_amount=[Decimal("50"), Decimal("900")],
        payment_status=["success", "failed"],
    )
    tables["refund_info"] = _frame(
        order_id=["paid", "paid"],
        refunded_at=[START, START],
        refund_amount=[Decimal("10"), Decimal("40")],
        refund_status=["refunded", "failed"],
        refund_quantity=[1, 7],
    )
    tables["order_item"] = _frame(order_id=["paid", "failed"], quantity=[2, 99])

    metrics = calculate_sales_metrics(tables, START, END)

    assert metrics["actual_sales"].value == Decimal("50.00")
    assert metrics["refund_amount"].value == Decimal("10.00")
    assert metrics["refund_rate"].value == Decimal("1.0000")
    assert metrics["return_rate"].value == Decimal("0.5000")


def test_zero_successful_payments_only_disable_ratio_metrics() -> None:
    tables = _empty_tables()
    tables["order_info"] = _frame(
        order_id=["ordered"], order_time=[START], order_amount=[Decimal("25")]
    )

    metrics = calculate_sales_metrics(tables, START, END)

    assert metrics["gmv"].value == Decimal("25.00")
    assert metrics["actual_sales"].value == Decimal("0.00")
    assert metrics["refund_amount"].value == Decimal("0.00")
    assert metrics["net_sales"].value == Decimal("0.00")
    for name in (
        "average_order_value",
        "item_unit_price",
        "refund_rate",
        "return_rate",
    ):
        assert metrics[name].available is False
        assert metrics[name].reason == "zero_denominator"


@pytest.mark.parametrize(
    ("payment_status", "reason"),
    [(None, "missing_payment_status"), ([None, "  "], "empty_payment_status")],
)
def test_unknown_payment_status_disables_payment_dependent_metrics(
    payment_status: list[object] | None, reason: str
) -> None:
    tables = _empty_tables()
    payment_columns = {
        "order_id": ["one", "two"],
        "paid_at": [START, START],
        "payment_amount": [Decimal("10"), Decimal("20")],
    }
    if payment_status is not None:
        payment_columns["payment_status"] = payment_status
    tables["payment_info"] = _frame(**payment_columns)

    metrics = calculate_sales_metrics(tables, START, END)

    assert metrics["gmv"].available is True
    assert metrics["refund_amount"].value == Decimal("0.00")
    for name in (
        "actual_sales",
        "net_sales",
        "average_order_value",
        "item_unit_price",
        "refund_rate",
        "return_rate",
    ):
        assert metrics[name].available is False
        assert metrics[name].reason == reason


@pytest.mark.parametrize(
    ("refund_status", "reason"),
    [(None, "missing_refund_status"), ([None, ""], "empty_refund_status")],
)
def test_unknown_refund_status_disables_refund_dependent_metrics(
    refund_status: list[object] | None, reason: str
) -> None:
    tables = _empty_tables()
    tables["payment_info"] = _frame(
        order_id=["one"],
        paid_at=[START],
        payment_amount=[Decimal("10")],
        payment_status=["success"],
    )
    refund_columns = {
        "order_id": ["one", "one"],
        "refunded_at": [START, START],
        "refund_amount": [Decimal("2"), Decimal("3")],
        "refund_quantity": [1, 1],
    }
    if refund_status is not None:
        refund_columns["refund_status"] = refund_status
    tables["refund_info"] = _frame(**refund_columns)
    tables["order_item"] = _frame(order_id=["one"], quantity=[2])

    metrics = calculate_sales_metrics(tables, START, END)

    assert metrics["gmv"].available is True
    for name in (
        "actual_sales",
        "refund_amount",
        "net_sales",
        "average_order_value",
        "item_unit_price",
        "refund_rate",
        "return_rate",
    ):
        assert metrics[name].available is False
        assert metrics[name].reason == reason


def test_missing_refund_quantity_only_disables_return_rate() -> None:
    tables = _empty_tables()
    tables["payment_info"] = _frame(
        order_id=["one"],
        paid_at=[START],
        payment_amount=[Decimal("40")],
        payment_status=["success"],
    )
    tables["refund_info"] = _frame(
        order_id=["one"],
        refunded_at=[START],
        refund_amount=[Decimal("10")],
        refund_status=["success"],
    )
    tables["order_item"] = _frame(order_id=["one"], quantity=[2])

    metrics = calculate_sales_metrics(tables, START, END)

    assert metrics["refund_amount"].value == Decimal("10.00")
    assert metrics["refund_rate"].value == Decimal("1.0000")
    assert metrics["return_rate"].available is False
    assert metrics["return_rate"].reason == "missing_refund_quantity"
    assert all(
        metrics[name].available
        for name in set(metrics) - {"return_rate"}
    )


def test_all_metric_timestamps_use_left_closed_right_open_period() -> None:
    tables = {
        "order_info": _frame(
            order_id=["at-start", "at-end"],
            order_time=[START, END],
            order_amount=[Decimal("10"), Decimal("900")],
        ),
        "payment_info": _frame(
            order_id=["at-start", "at-end"],
            paid_at=[START, END],
            payment_amount=[Decimal("10"), Decimal("900")],
            payment_status=["success", "success"],
        ),
        "refund_info": _frame(
            order_id=["at-start", "at-end"],
            refunded_at=[START, END],
            refund_amount=[Decimal("2"), Decimal("900")],
            refund_status=["success", "success"],
            refund_quantity=[1, 9],
        ),
        "order_item": _frame(order_id=["at-start", "at-end"], quantity=[2, 9]),
    }

    metrics = calculate_sales_metrics(tables, START, END)

    assert metrics["gmv"].value == Decimal("10.00")
    assert metrics["actual_sales"].value == Decimal("10.00")
    assert metrics["refund_amount"].value == Decimal("2.00")
    assert metrics["refund_rate"].value == Decimal("1.0000")
    assert metrics["return_rate"].value == Decimal("0.5000")
