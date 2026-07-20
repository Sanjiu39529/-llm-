"""根据已确认的字段语义，推断数据集行粒度和安全去重策略。"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


PRESERVE_ROWS = "preserve_rows"
BUSINESS_KEY = "business_key"


@dataclass(frozen=True, slots=True)
class DatasetProfile:
    """供导入审计和后续分析使用的、可解释的数据集画像。"""

    row_granularity: str
    entity_key: tuple[str, ...]
    deduplication_policy: str
    confidence: float
    rationale: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_KEYED_TABLES: dict[str, tuple[str, tuple[str, ...], str]] = {
    "user_info": ("用户实体快照", ("user_id",), "检测到用户标识；同一用户标识代表同一实体。"),
    "product_info": ("商品实体快照", ("product_id",), "检测到商品标识；同一商品标识代表同一实体。"),
    "order_info": ("订单明细", ("order_id",), "检测到订单标识；同一订单标识代表同一订单。"),
    "order_item": ("订单商品明细", ("order_id", "product_id"), "订单和商品共同确定一条商品明细。"),
    "traffic_visit": ("访问会话", ("visit_id",), "检测到访问标识；同一访问标识代表同一次会话。"),
    "behavior_info": ("行为事件", ("event_id",), "检测到事件标识；同一事件标识代表同一行为事件。"),
    "ads_info": ("广告日明细", ("ad_id", "ad_date"), "广告标识与日期共同确定一条投放记录。"),
    "ad_attribution": ("广告归因明细", ("order_id", "ad_id", "attributed_at"), "订单、广告和归因时间共同确定一条归因记录。"),
    "payment_info": ("支付流水", ("payment_id",), "支付标识存在时按支付标识；缺失时由既有自然键规则处理。"),
    "refund_info": ("退款流水", ("refund_id",), "退款标识存在时按退款标识；缺失时由既有自然键规则处理。"),
}


def infer_dataset_profile(table_name: str, frame: pd.DataFrame) -> DatasetProfile:
    """从已映射字段推断行粒度；不能可靠证明重复时保留原始行。"""
    if table_name == "behavior_funnel":
        return DatasetProfile(
            row_granularity="匿名用户级漏斗快照",
            entity_key=(),
            deduplication_policy=PRESERVE_ROWS,
            confidence=0.95,
            rationale="该结构没有稳定的用户或事件标识；每行视为一个独立匿名用户画像，不按整行内容去重。",
        )

    granularity, keys, rationale = _KEYED_TABLES[table_name]
    available_keys = tuple(key for key in keys if key in frame.columns)
    confidence = 0.95 if available_keys else 0.55
    policy = BUSINESS_KEY if available_keys else PRESERVE_ROWS
    if not available_keys:
        rationale = "未检测到可用于证明重复的稳定业务标识；为避免误删独立记录，保留全部行。"
    return DatasetProfile(
        row_granularity=granularity,
        entity_key=available_keys,
        deduplication_policy=policy,
        confidence=confidence,
        rationale=rationale,
    )
