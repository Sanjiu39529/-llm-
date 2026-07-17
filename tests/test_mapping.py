"""字段映射服务测试。"""

from backend.app.services.mapping import suggest_mapping


def test_suggest_mapping_recognises_chinese_order_columns() -> None:
    """应识别订单表的中文常用列名。"""
    result = suggest_mapping("order_info", ["订单编号", "用户ID", "下单时间", "渠道"])

    assert result.mapping == {
        "订单编号": "order_id",
        "用户ID": "user_id",
        "下单时间": "order_time",
        "渠道": "channel",
    }
    assert result.unmapped_required == []


def test_suggest_mapping_reports_missing_required_columns() -> None:
    """缺少必填付款时间时应明确报告。"""
    result = suggest_mapping("payment_info", ["订单编号", "支付金额"])

    assert "paid_at" in result.unmapped_required
