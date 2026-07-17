"""确定性数据清洗服务测试。"""

import pandas as pd

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
