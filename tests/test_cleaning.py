"""确定性数据清洗服务测试。"""

import pandas as pd
from decimal import Decimal

from backend.app.services.cleaning import clean_frame


def test_clean_users_fills_missing_and_invalid_age_with_valid_mean() -> None:
    """缺失及越界年龄应使用有效年龄均值填充。"""
    frame = pd.DataFrame(
        {
            "user_id": [1, 2, 3],
            "age": [20, None, 101],
            "register_time": ["2026-01-01"] * 3,
        }
    )

    result = clean_frame("user_info", frame)

    assert result.frame["age"].tolist() == [20, 20, 20]
    assert result.summary.filled["age"] == 2


def test_clean_orders_removes_non_positive_amount_and_duplicate_key() -> None:
    """重复主键保留首条订单记录。"""
    frame = pd.DataFrame(
        {
            "order_id": ["a", "a", "b"],
            "user_id": [1, 1, 2],
            "order_time": ["2026-01-01"] * 3,
            "channel": ["自然搜索"] * 3,
            "order_status": ["已下单"] * 3,
        }
    )

    result = clean_frame("order_info", frame)

    assert result.frame["order_id"].tolist() == ["a", "b"]
    assert result.summary.deduplicated == 1


def test_clean_orders_skips_invalid_dates_and_non_positive_amounts() -> None:
    """不可解析或未来日期、非正金额的订单不能入库。"""
    frame = pd.DataFrame(
        {
            "order_id": ["valid", "bad-date", "future", "zero"],
            "user_id": [1, 2, 3, 4],
            "order_time": ["2026-01-01", "not-a-date", "2099-01-01", "2026-01-01"],
            "order_amount": [10, 10, 10, 0],
        }
    )

    result = clean_frame("order_info", frame)

    assert result.frame["order_id"].tolist() == ["valid"]
    assert result.summary.skipped == 3


def test_clean_orders_standardises_channels_and_marks_high_amounts() -> None:
    """渠道别名应标准化，未知值保留为未知，异常高额订单保留并标记。"""
    frame = pd.DataFrame(
        {
            "order_id": ["a", "b", "c", "d", "e"],
            "user_id": [1, 2, 3, 4, 5],
            "order_time": ["2026-01-01"] * 5,
            "channel": ["自然搜索", "SEO", "陌生渠道", None, "广告投放"],
            "order_amount": [10, 10, 10, 10, 1000],
        }
    )

    result = clean_frame("order_info", frame)

    assert result.frame["channel"].tolist() == ["自然搜索", "自然搜索", "未知", "未知", "付费广告"]
    assert result.summary.unknown_values == 2
    assert result.frame["is_outlier"].tolist() == [False, False, False, False, True]


def test_clean_order_items_deduplicates_by_order_and_product() -> None:
    """同一订单中的不同商品不是重复明细。"""
    frame = pd.DataFrame(
        {
            "order_id": ["order-1", "order-1", "order-1"],
            "product_id": ["product-a", "product-b", "product-a"],
            "quantity": [1, 1, 1],
        }
    )

    result = clean_frame("order_item", frame)

    assert result.frame[["order_id", "product_id"]].values.tolist() == [
        ["order-1", "product-a"],
        ["order-1", "product-b"],
    ]
    assert result.summary.deduplicated == 1


def test_clean_ad_attribution_deduplicates_by_order_and_ad() -> None:
    """同一订单归因到不同广告时应全部保留。"""
    frame = pd.DataFrame(
        {
            "order_id": ["order-1", "order-1", "order-1"],
            "ad_id": ["ad-a", "ad-b", "ad-a"],
            "attributed_at": ["2026-01-01"] * 3,
        }
    )

    result = clean_frame("ad_attribution", frame)

    assert result.frame[["order_id", "ad_id"]].values.tolist() == [
        ["order-1", "ad-a"],
        ["order-1", "ad-b"],
    ]
    assert result.summary.deduplicated == 1


def test_clean_payments_without_payment_id_uses_required_fields_as_key() -> None:
    """缺少可选支付 ID 时，以必填业务字段去重。"""
    frame = pd.DataFrame(
        {
            "order_id": ["order-1", "order-1", "order-1"],
            "paid_at": ["2026-01-01", "2026-01-01", "2026-01-02"],
            "payment_amount": [10, 10, 10],
        }
    )

    result = clean_frame("payment_info", frame)

    assert result.frame["paid_at"].dt.strftime("%Y-%m-%d").tolist() == ["2026-01-01", "2026-01-02"]
    assert result.summary.deduplicated == 1


def test_clean_refunds_without_refund_id_uses_required_fields_as_key() -> None:
    """缺少可选退款 ID 时，以必填业务字段去重。"""
    frame = pd.DataFrame(
        {
            "order_id": ["order-1", "order-1", "order-1"],
            "refunded_at": ["2026-01-01", "2026-01-01", "2026-01-02"],
            "refund_amount": [10, 10, 10],
        }
    )

    result = clean_frame("refund_info", frame)

    assert result.frame["refunded_at"].dt.strftime("%Y-%m-%d").tolist() == ["2026-01-01", "2026-01-02"]
    assert result.summary.deduplicated == 1


def test_clean_order_items_marks_outlier_from_each_amount_column() -> None:
    """任一金额列超过自身阈值，都应标记对应记录。"""
    frame = pd.DataFrame(
        {
            "order_id": ["o1", "o2", "o3", "o4", "o5"],
            "product_id": ["p1", "p2", "p3", "p4", "p5"],
            "quantity": [1] * 5,
            "item_amount": [10, 10, 10, 1000, 10],
            "unit_price": [10, 10, 10, 10, 1000],
        }
    )

    result = clean_frame("order_item", frame)

    assert result.frame["is_outlier"].tolist() == [False, False, False, True, True]


def test_ads_and_attribution_deduplicate_with_ddl_keys() -> None:
    ads = clean_frame("ads_info", pd.DataFrame({
        "ad_id": ["a", "a", "a"],
        "ad_date": ["2026-01-01", "2026-01-02", "2026-01-01"],
    }))
    attribution = clean_frame("ad_attribution", pd.DataFrame({
        "order_id": ["o", "o", "o"], "ad_id": ["a", "a", "a"],
        "attributed_at": ["2026-01-01", "2026-01-02", "2026-01-01"],
    }))
    assert len(ads.frame) == 2 and ads.summary.deduplicated == 1
    assert len(attribution.frame) == 2 and attribution.summary.deduplicated == 1


def test_required_values_types_and_ranges_are_skipped_with_reason_audit() -> None:
    result = clean_frame("order_item", pd.DataFrame({
        "order_id": ["ok", "", "bad-quantity", "fraction"],
        "product_id": ["p1", "p2", "p3", "p4"],
        "quantity": [1, 1, "nope", 1.5],
        "unit_price": ["12.345", "10", "10", "10"],
    }))
    assert result.frame["order_id"].tolist() == ["ok"]
    assert result.frame.iloc[0]["unit_price"] == Decimal("12.35")
    assert result.summary.reasons["order_id"]["required_blank"] == 1
    assert result.summary.reasons["quantity"]["invalid_integer"] == 2
    assert result.summary.skipped == 3


def test_invalid_and_overflow_money_are_skipped_before_database_write() -> None:
    result = clean_frame("payment_info", pd.DataFrame({
        "order_id": ["a", "b", "c"],
        "paid_at": ["2026-01-01"] * 3,
        "payment_amount": ["not-money", "10000000000000000", "0.105"],
    }))
    assert result.frame["payment_amount"].tolist() == [Decimal("0.11")]
    assert result.summary.reasons["payment_amount"]["invalid_decimal"] == 1
    assert result.summary.reasons["payment_amount"]["decimal_out_of_range"] == 1


def test_only_order_time_rejects_future_dates() -> None:
    user = clean_frame("user_info", pd.DataFrame({"user_id": ["u"], "register_time": ["2099-01-01"]}))
    order = clean_frame("order_info", pd.DataFrame({"order_id": ["o"], "user_id": ["u"], "order_time": ["2099-01-01"]}))
    assert len(user.frame) == 1
    assert order.frame.empty
    assert order.summary.reasons["order_time"]["future_order_time"] == 1


def test_string_and_integer_storage_bounds_are_validated() -> None:
    users = clean_frame("user_info", pd.DataFrame({"user_id": ["u", "x" * 65]}))
    ads = clean_frame("ads_info", pd.DataFrame({
        "ad_id": ["a", "b"], "ad_date": ["2026-01-01"] * 2,
        "impressions": [10, 9223372036854775808],
    }))
    assert users.frame["user_id"].tolist() == ["u"]
    assert users.summary.reasons["user_id"]["text_too_long"] == 1
    assert ads.frame["ad_id"].tolist() == ["a"]
    assert ads.summary.reasons["impressions"]["integer_out_of_range"] == 1


def test_age_mean_is_stored_as_an_integer() -> None:
    result = clean_frame("user_info", pd.DataFrame({
        "user_id": ["a", "b", "c"], "age": [20, 21, None],
    }))
    assert result.frame["age"].tolist() == [20, 21, 21]
    assert all(isinstance(value, int) for value in result.frame["age"])


def test_fractional_age_is_invalid_then_filled_without_truncation() -> None:
    result = clean_frame("user_info", pd.DataFrame({
        "user_id": ["a", "b", "c", "d"], "age": [20, 21, 20.5, None],
    }))
    assert result.frame["age"].tolist() == [20, 21, 21, 21]
    assert result.summary.reasons["age"]["invalid_integer"] == 1
    assert result.summary.filled["age"] == 2
