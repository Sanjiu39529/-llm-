"""电商标准表的字段契约与常见列别名。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FieldMapping:
    """一张标准表的字段定义与可识别别名。"""

    required_fields: frozenset[str]
    optional_fields: frozenset[str]
    aliases: dict[str, frozenset[str]]


STANDARD_TABLES: frozenset[str] = frozenset(
    {
        "user_info",
        "product_info",
        "order_info",
        "order_item",
        "payment_info",
        "refund_info",
        "traffic_visit",
        "behavior_info",
        "ads_info",
        "ad_attribution",
    }
)


def _aliases(**fields: tuple[str, ...]) -> dict[str, frozenset[str]]:
    """将字段的别名整理为不可变集合，字段名本身也可直接识别。"""
    return {
        field: frozenset((field, *field_aliases))
        for field, field_aliases in fields.items()
    }


TABLE_CONTRACTS: dict[str, FieldMapping] = {
    "user_info": FieldMapping(
        required_fields=frozenset({"user_id"}),
        optional_fields=frozenset({"user_name", "phone", "email", "register_time"}),
        aliases=_aliases(
            user_id=("用户id", "用户编号", "会员id", "member_id"),
            user_name=("用户名", "用户名称", "昵称", "姓名"),
            phone=("手机号", "手机号码", "电话"),
            email=("邮箱", "电子邮箱"),
            register_time=("注册时间", "注册日期"),
        ),
    ),
    "product_info": FieldMapping(
        required_fields=frozenset({"product_id", "product_name"}),
        optional_fields=frozenset({"category", "brand", "price", "stock"}),
        aliases=_aliases(
            product_id=("商品id", "商品编号", "sku", "sku_id"),
            product_name=("商品名称", "产品名称", "商品名"),
            category=("品类", "分类", "商品分类"),
            brand=("品牌",),
            price=("价格", "商品价格", "单价"),
            stock=("库存", "库存数量"),
        ),
    ),
    "order_info": FieldMapping(
        required_fields=frozenset({"order_id", "user_id", "order_time"}),
        optional_fields=frozenset({"channel", "order_status", "order_amount"}),
        aliases=_aliases(
            order_id=("订单编号", "订单id", "订单号"),
            user_id=("用户id", "用户编号", "会员id"),
            order_time=("下单时间", "订单时间", "创建时间"),
            channel=("渠道", "来源渠道", "下单渠道"),
            order_status=("订单状态", "状态"),
            order_amount=("订单金额", "订单总额", "总金额"),
        ),
    ),
    "order_item": FieldMapping(
        required_fields=frozenset({"order_id", "product_id", "quantity"}),
        optional_fields=frozenset({"unit_price", "item_amount"}),
        aliases=_aliases(
            order_id=("订单编号", "订单id", "订单号"),
            product_id=("商品id", "商品编号", "sku", "sku_id"),
            quantity=("数量", "购买数量", "商品数量"),
            unit_price=("单价", "商品单价"),
            item_amount=("明细金额", "小计", "商品金额"),
        ),
    ),
    "payment_info": FieldMapping(
        required_fields=frozenset({"order_id", "paid_at", "payment_amount"}),
        optional_fields=frozenset({"payment_id", "payment_method", "payment_status"}),
        aliases=_aliases(
            order_id=("订单编号", "订单id", "订单号"),
            paid_at=("支付时间", "付款时间", "支付日期"),
            payment_amount=("支付金额", "付款金额", "实付金额"),
            payment_id=("支付id", "支付编号", "交易号"),
            payment_method=("支付方式", "付款方式"),
            payment_status=("支付状态", "付款状态"),
        ),
    ),
    "refund_info": FieldMapping(
        required_fields=frozenset({"order_id", "refund_amount", "refunded_at"}),
        optional_fields=frozenset({"refund_id", "refund_reason", "refund_status"}),
        aliases=_aliases(
            order_id=("订单编号", "订单id", "订单号"),
            refund_amount=("退款金额", "退货金额"),
            refunded_at=("退款时间", "退货时间"),
            refund_id=("退款id", "退款编号"),
            refund_reason=("退款原因", "退货原因"),
            refund_status=("退款状态", "退货状态"),
        ),
    ),
    "traffic_visit": FieldMapping(
        required_fields=frozenset({"visit_id", "visited_at"}),
        optional_fields=frozenset({"user_id", "channel", "page_url"}),
        aliases=_aliases(
            visit_id=("访问id", "会话id", "session_id"),
            visited_at=("访问时间", "到访时间"),
            user_id=("用户id", "用户编号"),
            channel=("渠道", "来源渠道"),
            page_url=("页面地址", "url", "页面url"),
        ),
    ),
    "behavior_info": FieldMapping(
        required_fields=frozenset({"event_id", "event_type", "occurred_at"}),
        optional_fields=frozenset({"user_id", "product_id", "visit_id"}),
        aliases=_aliases(
            event_id=("行为id", "事件id", "event_id"),
            event_type=("行为类型", "事件类型", "动作类型"),
            occurred_at=("行为时间", "事件时间", "发生时间"),
            user_id=("用户id", "用户编号"),
            product_id=("商品id", "商品编号", "sku"),
            visit_id=("访问id", "会话id", "session_id"),
        ),
    ),
    "ads_info": FieldMapping(
        required_fields=frozenset({"ad_id", "ad_date"}),
        optional_fields=frozenset({"campaign_id", "channel", "impressions", "clicks", "cost"}),
        aliases=_aliases(
            ad_id=("广告id", "广告编号", "创意id"),
            ad_date=("广告日期", "投放日期", "日期"),
            campaign_id=("计划id", "广告计划id", "campaign_id"),
            channel=("渠道", "投放渠道"),
            impressions=("曝光量", "展示量", "impression"),
            clicks=("点击量", "点击次数", "click"),
            cost=("花费", "广告花费", "消耗"),
        ),
    ),
    "ad_attribution": FieldMapping(
        required_fields=frozenset({"order_id", "ad_id", "attributed_at"}),
        optional_fields=frozenset({"user_id", "attribution_amount"}),
        aliases=_aliases(
            order_id=("订单编号", "订单id", "订单号"),
            ad_id=("广告id", "广告编号", "创意id"),
            attributed_at=("归因时间", "转化时间"),
            user_id=("用户id", "用户编号"),
            attribution_amount=("归因金额", "转化金额"),
        ),
    ),
}
