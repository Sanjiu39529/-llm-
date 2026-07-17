from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from backend.app.tools.channel_tool import calculate_ad_metrics


START = datetime(2026, 7, 1)
END = datetime(2026, 7, 3)
CHANNELS = ("自然搜索", "推荐", "付费投放", "直播", "短视频", "活动流量")


def _frame(**columns: list[object]) -> pd.DataFrame:
    return pd.DataFrame(columns)


def _tables() -> dict[str, pd.DataFrame]:
    return {
        "ads_info": _frame(
            ad_id=["a1", "a1", "a2", "outside"],
            ad_date=[START, START + timedelta(days=1), START, END],
            channel=["推荐", "推荐", "直播", "推荐"],
            impressions=[100, 100, 200, 900],
            clicks=[10, 20, 20, 900],
            cost=[Decimal("20"), Decimal("30"), Decimal("50"), Decimal("900")],
        ),
        "ad_attribution": _frame(
            order_id=["d", "i", "late", "foreign"],
            ad_id=["a1", "a2", "a1", "outside"],
            attributed_at=[START, START + timedelta(days=1), END, START],
            attribution_amount=[Decimal("50"), Decimal("100"), Decimal("70"), Decimal("900")],
            attribution_type=["direct", "indirect", "direct", "direct"],
        ),
    }


def test_calculates_period_ad_metrics_and_direct_indirect_roi() -> None:
    metrics = calculate_ad_metrics(_tables(), START, END)

    assert metrics["spend"].value == Decimal("100.00")
    assert metrics["ctr"].value == Decimal("0.1250")
    assert metrics["cpm"].value == Decimal("250.0000")
    assert metrics["cpc"].value == Decimal("2.0000")
    assert metrics["direct_roi"].value == Decimal("0.5000")
    assert metrics["indirect_roi"].value == Decimal("1.0000")


def test_seven_day_roi_includes_day_zero_and_seven_but_excludes_day_eight() -> None:
    tables = {
        "ads_info": _frame(
            ad_id=["a"], ad_date=[START], channel=["推荐"],
            impressions=[1], clicks=[1], cost=[Decimal("10")]
        ),
        "ad_attribution": _frame(
            order_id=["zero", "seven", "eight"],
            ad_id=["a", "a", "a"],
            attributed_at=[START, START + timedelta(days=7, hours=23), START + timedelta(days=8)],
            attribution_amount=[Decimal("10"), Decimal("20"), Decimal("900")],
            attribution_type=["direct", "indirect", "direct"],
        ),
    }

    metrics = calculate_ad_metrics(tables, START, END)

    assert metrics["roi_7d"].value == Decimal("3.0000")


def test_seven_day_window_normalizes_non_midnight_ad_date_to_day_start() -> None:
    tables = {
        "ads_info": _frame(
            ad_id=["a"], ad_date=[START + timedelta(hours=12)], channel=["推荐"],
            impressions=[1], clicks=[1], cost=[Decimal("10")]
        ),
        "ad_attribution": _frame(
            order_id=["same-day-early", "day-seven-end", "day-eight-early"],
            ad_id=["a", "a", "a"],
            attributed_at=[
                START + timedelta(hours=1),
                START + timedelta(days=7, hours=23, minutes=59),
                START + timedelta(days=8, hours=1),
            ],
            attribution_amount=[Decimal("10"), Decimal("20"), Decimal("900")],
            attribution_type=["direct", "indirect", "direct"],
        ),
    }

    assert calculate_ad_metrics(tables, START, END)["roi_7d"].value == Decimal("3.0000")


def test_seven_day_roi_counts_each_attribution_once_when_ad_windows_overlap() -> None:
    tables = {
        "ads_info": _frame(
            ad_id=["a", "a"],
            ad_date=[START, START + timedelta(days=1)],
            channel=["推荐", "推荐"], impressions=[1, 1], clicks=[1, 1],
            cost=[Decimal("5"), Decimal("5")],
        ),
        "ad_attribution": _frame(
            order_id=["one"], ad_id=["a"],
            attributed_at=[START + timedelta(days=2)],
            attribution_amount=[Decimal("20")], attribution_type=["direct"],
        ),
    }

    assert calculate_ad_metrics(tables, START, END)["roi_7d"].value == Decimal("2.0000")


def test_seven_day_roi_uses_row_positions_when_attribution_indexes_repeat() -> None:
    tables = {
        "ads_info": _frame(
            ad_id=["a", "a"], ad_date=[START, START + timedelta(days=1)],
            channel=["推荐", "推荐"], impressions=[1, 1], clicks=[1, 1],
            cost=[Decimal("5"), Decimal("5")],
        ),
        "ad_attribution": _frame(
            order_id=["one", "two"], ad_id=["a", "a"],
            attributed_at=[START + timedelta(days=2), START + timedelta(days=3)],
            attribution_amount=[Decimal("10"), Decimal("20")],
            attribution_type=["direct", "indirect"],
        ).set_axis([0, 0]),
    }

    assert calculate_ad_metrics(tables, START, END)["roi_7d"].value == Decimal("3.0000")


def test_zero_denominators_only_disable_affected_ad_metrics() -> None:
    tables = {
        "ads_info": _frame(
            ad_id=["a"], ad_date=[START], channel=["推荐"],
            impressions=[0], clicks=[0], cost=[Decimal("0")]
        ),
        "ad_attribution": _frame(
            order_id=[], ad_id=[], attributed_at=[], attribution_amount=[], attribution_type=[]
        ),
    }

    metrics = calculate_ad_metrics(tables, START, END)

    assert metrics["spend"].value == Decimal("0.00")
    for name in ("ctr", "cpm", "cpc", "direct_roi", "indirect_roi", "roi_7d"):
        assert metrics[name].available is False
        assert metrics[name].reason == "zero_denominator"


def test_channels_and_attribution_types_are_strict_and_unknown_values_warn() -> None:
    tables = _tables()
    tables["ads_info"].loc[0, "channel"] = "站外联盟"
    tables["ad_attribution"].loc[0, "attribution_type"] = "assisted"

    metrics = calculate_ad_metrics(tables, START, END)

    assert set(metrics["channels"]) == set(CHANNELS)
    assert metrics["channels"]["推荐"]["cost"].value == Decimal("30.00")
    assert sum(item["cost"].value for item in metrics["channels"].values()) == Decimal("80.00")
    assert metrics["direct_roi"].value == Decimal("0.0000")
    assert metrics["quality_warnings"] == {
        "unknown_channels": ["站外联盟"],
        "unknown_attribution_types": ["assisted"],
    }


def test_missing_or_empty_attribution_type_is_backward_compatible_direct() -> None:
    for value in (None, ""):
        tables = _tables()
        tables["ad_attribution"] = tables["ad_attribution"].drop(columns="attribution_type")
        if value == "":
            tables["ad_attribution"]["attribution_type"] = [None, "", None, ""]
        metrics = calculate_ad_metrics(tables, START, END)
        assert metrics["direct_roi"].value == Decimal("1.5000")
        assert metrics["indirect_roi"].value == Decimal("0.0000")


@pytest.mark.parametrize(
    ("column", "unavailable_metrics"),
    [
        ("cost", {"spend", "cpm", "cpc", "direct_roi", "indirect_roi", "roi_7d"}),
        ("impressions", {"ctr", "cpm"}),
        ("clicks", {"ctr", "cpc"}),
    ],
)
def test_missing_ad_measurement_degrades_only_dependent_metrics_and_channel_field(
    column: str, unavailable_metrics: set[str]
) -> None:
    tables = _tables()
    tables["ads_info"] = tables["ads_info"].drop(columns=column)

    metrics = calculate_ad_metrics(tables, START, END)

    for name in ("spend", "ctr", "cpm", "cpc", "direct_roi", "indirect_roi", "roi_7d"):
        if name in unavailable_metrics:
            assert metrics[name].available is False
            assert metrics[name].reason == f"missing_{column}"
        else:
            assert metrics[name].available is True
    channel = metrics["channels"]["推荐"]
    for field in ("cost", "impressions", "clicks"):
        assert channel[field].available is (field != column)
        assert channel[field].reason == (f"missing_{column}" if field == column else None)
    assert channel["available"] is False
    assert channel["reason"] == f"missing_{column}"


def test_missing_channel_keeps_six_unavailable_channel_slots() -> None:
    tables = _tables()
    tables["ads_info"] = tables["ads_info"].drop(columns="channel")

    metrics = calculate_ad_metrics(tables, START, END)

    assert set(metrics["channels"]) == set(CHANNELS)
    for channel in metrics["channels"].values():
        assert channel["available"] is False
        assert channel["reason"] == "missing_channel"
        for field in ("cost", "impressions", "clicks"):
            assert channel[field].available is False
            assert channel[field].reason == "missing_channel"
    assert metrics["quality_warnings"]["unknown_channels"] == ["<missing>"]
