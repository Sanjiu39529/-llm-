"""导入数据的确定性清洗规则。"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import pandas as pd

from backend.app.datasources.base import TABLE_CONTRACTS


logger = logging.getLogger(__name__)

_BUSINESS_KEYS = {
    "user_info": ("user_id",),
    "product_info": ("product_id",),
    "order_info": ("order_id",),
    "order_item": ("order_id", "product_id"),
    "traffic_visit": ("visit_id",),
    "behavior_info": ("event_id",),
    "ads_info": ("ad_id", "ad_date"),
    "ad_attribution": ("order_id", "ad_id", "attributed_at"),
}
_OPTIONAL_ID_KEYS = {
    "payment_info": ("payment_id", ("order_id", "paid_at", "payment_amount")),
    "refund_info": ("refund_id", ("order_id", "refunded_at", "refund_amount")),
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
_INTEGER_COLUMNS = frozenset({"age", "stock", "quantity", "impressions", "clicks"})
_DECIMAL_MAX = Decimal("9999999999999999.99")
_DECIMAL_QUANTUM = Decimal("0.01")
_INTEGER_LIMITS = {
    "stock": (0, 2_147_483_647),
    "quantity": (1, 2_147_483_647),
    "impressions": (0, 9_223_372_036_854_775_807),
    "clicks": (0, 9_223_372_036_854_775_807),
}
_TEXT_LIMITS = {
    "user_name": 255, "email": 255, "product_name": 255,
    "refund_reason": 255, "page_url": 2048,
    "category": 128, "brand": 128,
}
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
    reasons: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, column: str, reason: str, count: int = 1) -> None:
        reasons = self.reasons.setdefault(column, {})
        reasons[reason] = reasons.get(reason, 0) + count


@dataclass(slots=True)
class CleanResult:
    """可入库数据和对应质量摘要。"""

    frame: pd.DataFrame
    summary: CleanSummary


def _is_blank(value: object) -> bool:
    return pd.isna(value) or (isinstance(value, str) and not value.strip())


def _decimal_value(value: object) -> Decimal | None:
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _validate_rows(
    table_name: str, frame: pd.DataFrame, summary: CleanSummary
) -> pd.DataFrame:
    """在数据库写入前逐行验证必填值、类型和值域。"""
    contract = TABLE_CONTRACTS[table_name]
    invalid_rows = pd.Series(False, index=frame.index)

    for column in contract.required_fields:
        if column not in frame:
            continue
        blank = frame[column].map(_is_blank)
        if blank.any():
            summary.record(column, "required_blank", int(blank.sum()))
            summary.invalid += int(blank.sum())
            invalid_rows |= blank

    for column in _DATE_COLUMNS.intersection(frame.columns):
        blank = frame[column].map(_is_blank)
        parsed = pd.to_datetime(frame[column], errors="coerce")
        bad_parse = ~blank & parsed.isna()
        if bad_parse.any():
            summary.record(column, "invalid_datetime", int(bad_parse.sum()))
            summary.invalid += int(bad_parse.sum())
            invalid_rows |= bad_parse
        if column == "order_time":
            future = parsed.notna() & (parsed.dt.date > date.today())
            if future.any():
                summary.record(column, "future_order_time", int(future.sum()))
                summary.invalid += int(future.sum())
                invalid_rows |= future
        frame[column] = parsed.where(~blank, None)

    for column in _AMOUNT_COLUMNS.intersection(frame.columns):
        converted: list[Decimal | None] = []
        bad_parse = pd.Series(False, index=frame.index)
        bad_range = pd.Series(False, index=frame.index)
        for index, value in frame[column].items():
            if _is_blank(value):
                converted.append(None)
                continue
            amount = _decimal_value(value)
            if amount is None:
                bad_parse.loc[index] = True
                converted.append(None)
            elif amount <= 0 or amount > _DECIMAL_MAX:
                bad_range.loc[index] = True
                converted.append(None)
            else:
                converted.append(amount.quantize(_DECIMAL_QUANTUM, rounding=ROUND_HALF_UP))
        if bad_parse.any():
            summary.record(column, "invalid_decimal", int(bad_parse.sum()))
        if bad_range.any():
            summary.record(column, "decimal_out_of_range", int(bad_range.sum()))
        violations = bad_parse | bad_range
        summary.invalid += int(violations.sum())
        invalid_rows |= violations
        frame[column] = converted

    typed_fields = _DATE_COLUMNS | _AMOUNT_COLUMNS | _INTEGER_COLUMNS
    for column in (set(contract.aliases) - typed_fields).intersection(frame.columns):
        converted: list[str | None] = []
        too_long = pd.Series(False, index=frame.index)
        limit = _TEXT_LIMITS.get(column, 64)
        for index, value in frame[column].items():
            if _is_blank(value):
                converted.append(None)
                continue
            text_value = str(value).strip()
            if len(text_value) > limit:
                too_long.loc[index] = True
                converted.append(None)
            else:
                converted.append(text_value)
        if too_long.any():
            summary.record(column, "text_too_long", int(too_long.sum()))
            summary.invalid += int(too_long.sum())
            invalid_rows |= too_long
        frame[column] = converted

    for column in (_INTEGER_COLUMNS - {"age"}).intersection(frame.columns):
        converted: list[int | None] = []
        bad = pd.Series(False, index=frame.index)
        for index, value in frame[column].items():
            if _is_blank(value):
                converted.append(None)
                continue
            number = _decimal_value(value)
            minimum, maximum = _INTEGER_LIMITS[column]
            if number is None or number != number.to_integral_value():
                bad.loc[index] = True
                converted.append(None)
            elif number < minimum or number > maximum:
                converted.append(None)
                summary.record(column, "integer_out_of_range")
                summary.invalid += 1
                invalid_rows.loc[index] = True
            else:
                converted.append(int(number))
        if bad.any():
            summary.record(column, "invalid_integer", int(bad.sum()))
            summary.invalid += int(bad.sum())
            invalid_rows |= bad
        frame[column] = converted

    summary.skipped += int(invalid_rows.sum())
    return frame.loc[~invalid_rows].copy()


def _clean_age(frame: pd.DataFrame, summary: CleanSummary) -> None:
    """将年龄越界值置空，再用当前批次有效年龄均值填充。"""
    if "age" not in frame:
        return

    ages = pd.to_numeric(frame["age"], errors="coerce")
    fractional = ages.notna() & ages.mod(1).ne(0)
    invalid = ages.lt(1) | ages.gt(100) | fractional
    summary.invalid += int(invalid.sum())
    out_of_range = ages.lt(1) | ages.gt(100)
    if out_of_range.any():
        summary.record("age", "age_out_of_range", int(out_of_range.sum()))
    if fractional.any():
        summary.record("age", "invalid_integer", int(fractional.sum()))
    unparsable = ~frame["age"].map(_is_blank) & ages.isna()
    if unparsable.any():
        summary.record("age", "invalid_integer", int(unparsable.sum()))
        summary.invalid += int(unparsable.sum())
    ages = ages.mask(invalid)
    valid_mean = ages.mean()
    missing = ages.isna()
    if pd.notna(valid_mean):
        summary.filled["age"] = int(missing.sum())
        mean_age = int(Decimal(str(valid_mean)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        ages = ages.fillna(mean_age)
    elif missing.any():
        summary.filled["age"] = 0
    frame["age"] = ages.map(lambda value: int(value) if pd.notna(value) else None)


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

    outliers = pd.Series(False, index=frame.index)
    for column in amount_columns:
        amounts = pd.to_numeric(frame[column], errors="coerce")
        q1, q3 = amounts.quantile([0.25, 0.75])
        outliers |= amounts.gt(q3 + 3 * (q3 - q1)).fillna(False)
    frame["is_outlier"] = outliers


def _deduplicate(frame: pd.DataFrame, table_name: str) -> pd.Series:
    """返回业务键重复记录掩码，支付和退款缺少 ID 时使用必填自然键。"""
    if table_name in _OPTIONAL_ID_KEYS:
        id_column, fallback_columns = _OPTIONAL_ID_KEYS[table_name]
        seen_ids: set[object] = set()
        seen_natural_keys: set[tuple[object, ...]] = set()
        duplicate = pd.Series(False, index=frame.index)
        for index, row in frame.iterrows():
            natural_key = tuple(row[column] for column in fallback_columns)
            has_id = (
                id_column in frame
                and pd.notna(row[id_column])
                and bool(str(row[id_column]).strip())
            )
            identifier = row[id_column] if has_id else None
            if natural_key in seen_natural_keys or (
                has_id and identifier in seen_ids
            ):
                duplicate.loc[index] = True
                continue
            seen_natural_keys.add(natural_key)
            if has_id:
                seen_ids.add(identifier)
        return duplicate
    else:
        keys = list(_BUSINESS_KEYS[table_name])

    if not set(keys).issubset(frame.columns):
        return pd.Series(False, index=frame.index)
    return frame.duplicated(subset=keys, keep="first")


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
    cleaned = _validate_rows(table_name, cleaned, summary)
    _clean_age(cleaned, summary)
    duplicate = _deduplicate(cleaned, table_name)
    summary.deduplicated = int(duplicate.sum())
    cleaned = cleaned.loc[~duplicate].copy()

    _clean_channel(cleaned, summary)
    _mark_outliers(cleaned)
    for column in TABLE_CONTRACTS[table_name].generated_fields:
        if column not in cleaned:
            cleaned[column] = False
    return CleanResult(frame=cleaned.reset_index(drop=True), summary=summary)
