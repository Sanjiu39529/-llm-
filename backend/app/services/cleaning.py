"""导入数据的确定性清洗规则。"""

import logging
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from backend.app.datasources.base import TABLE_CONTRACTS


logger = logging.getLogger(__name__)

_PRIMARY_KEYS = {
    "user_info": "user_id",
    "product_info": "product_id",
    "order_info": "order_id",
    "order_item": "order_id",
    "payment_info": "payment_id",
    "refund_info": "refund_id",
    "traffic_visit": "visit_id",
    "behavior_info": "event_id",
    "ads_info": "ad_id",
    "ad_attribution": "order_id",
}
_DATE_COLUMNS = frozenset(
    {
        "register_time",
        "order_time",
        "paid_at",
        "refunded_at",
        "visited_at",
        "occurred_at",
        "ad_date",
        "attributed_at",
    }
)
_AMOUNT_COLUMNS = frozenset(
    {
        "price",
        "order_amount",
        "unit_price",
        "item_amount",
        "payment_amount",
        "refund_amount",
        "cost",
        "attribution_amount",
    }
)
_CHANNEL_ALIASES = {
    "自然搜索": "自然搜索",
    "seo": "自然搜索",
    "搜索引擎": "自然搜索",
    "广告投放": "付费广告",
    "付费广告": "付费广告",
    "sem": "付费广告",
    "社交媒体": "社交媒体",
    "social": "社交媒体",
    "直接访问": "直接访问",
    "direct": "直接访问",
}


@dataclass(slots=True)
class CleanSummary:
    """清洗过程中的可审计计数。"""

    filled: dict[str, int] = field(default_factory=dict)
    skipped: int = 0
    deduplicated: int = 0
    invalid: int = 0
    unknown_values: int = 0


@dataclass(slots=True)
class CleanResult:
    """可入库数据和对应质量摘要。"""

    frame: pd.DataFrame
    summary: CleanSummary


def _drop_invalid_dates(frame: pd.DataFrame, summary: CleanSummary) -> pd.DataFrame:
    """移除无法解析或晚于当天的日期记录。"""
    for column in _DATE_COLUMNS.intersection(frame.columns):
        parsed = pd.to_datetime(frame[column], errors="coerce")
        invalid = parsed.isna() | (parsed.dt.date > date.today())
        if invalid.any():
            count = int(invalid.sum())
            summary.skipped += count
            summary.invalid += count
            frame = frame.loc[~invalid].copy()
            parsed = parsed.loc[~invalid]
        frame[column] = parsed
    return frame


def _drop_non_positive_amounts(frame: pd.DataFrame, summary: CleanSummary) -> pd.DataFrame:
    """移除金额或价格小于等于零的记录。"""
    for column in _AMOUNT_COLUMNS.intersection(frame.columns):
        amounts = pd.to_numeric(frame[column], errors="coerce")
        invalid = amounts.le(0).fillna(False)
        if invalid.any():
            count = int(invalid.sum())
            summary.skipped += count
            summary.invalid += count
            frame = frame.loc[~invalid].copy()
            amounts = amounts.loc[~invalid]
        frame[column] = amounts
    return frame


def _clean_age(frame: pd.DataFrame, summary: CleanSummary) -> None:
    """将年龄越界值置空，再用当前批次有效年龄均值填充。"""
    if "age" not in frame:
        return

    ages = pd.to_numeric(frame["age"], errors="coerce")
    invalid = ages.lt(1) | ages.gt(100)
    summary.invalid += int(invalid.sum())
    ages = ages.mask(invalid)
    valid_mean = ages.mean()
    missing = ages.isna()
    if pd.notna(valid_mean):
        summary.filled["age"] = int(missing.sum())
        ages = ages.fillna(valid_mean)
    elif missing.any():
        summary.filled["age"] = 0
    frame["age"] = ages


def _clean_channel(frame: pd.DataFrame, summary: CleanSummary) -> None:
    """将已知渠道别名规范化，其他值统一记为未知。"""
    if "channel" not in frame:
        return

    def normalise(value: object) -> str:
        if not isinstance(value, str):
            return "未知"
        return _CHANNEL_ALIASES.get(value.strip().lower(), "未知")

    channels = frame["channel"].map(normalise)
    summary.unknown_values += int(channels.eq("未知").sum())
    frame["channel"] = channels


def _mark_outliers(frame: pd.DataFrame) -> None:
    """保留高金额记录，并以布尔列标记其异常性。"""
    amount_columns = _AMOUNT_COLUMNS.intersection(frame.columns)
    if not amount_columns:
        return

    column = sorted(amount_columns)[0]
    amounts = frame[column]
    q1, q3 = amounts.quantile([0.25, 0.75])
    frame["is_outlier"] = amounts.gt(q3 + 3 * (q3 - q1)).fillna(False)


def clean_frame(table_name: str, frame: pd.DataFrame) -> CleanResult:
    """按标准表规则清洗已完成字段映射的数据框。"""
    if table_name not in TABLE_CONTRACTS:
        logger.warning("不支持的标准表: %s", table_name)
        raise ValueError(f"不支持的标准表: {table_name}")
    if not isinstance(frame, pd.DataFrame):
        logger.warning("清洗输入不是 DataFrame: %r", type(frame))
        raise TypeError("frame 必须是 pandas.DataFrame")

    cleaned = frame.copy()
    summary = CleanSummary()
    primary_key = _PRIMARY_KEYS[table_name]
    if primary_key in cleaned:
        duplicate = cleaned.duplicated(subset=[primary_key], keep="first")
        summary.deduplicated = int(duplicate.sum())
        cleaned = cleaned.loc[~duplicate].copy()

    cleaned = _drop_invalid_dates(cleaned, summary)
    cleaned = _drop_non_positive_amounts(cleaned, summary)
    _clean_age(cleaned, summary)
    _clean_channel(cleaned, summary)
    _mark_outliers(cleaned)
    return CleanResult(frame=cleaned.reset_index(drop=True), summary=summary)
