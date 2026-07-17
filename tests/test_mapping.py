"""字段映射服务测试。"""

import backend.app.services.mapping as mapping_module
from backend.app.datasources.base import FieldMapping
from backend.app.services.mapping import suggest_mapping
from pytest import MonkeyPatch


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


def test_suggest_mapping_normalises_whitespace_underscores_and_hyphens() -> None:
    """空白、下划线和连字符形式的订单 ID 都应映射到同一标准字段。"""
    result = suggest_mapping("order_info", [" order id ", "order_id", "order-id"])

    assert result.mapping == {
        " order id ": "order_id",
        "order_id": "order_id",
        "order-id": "order_id",
    }


def test_suggest_mapping_keeps_ambiguous_columns_for_user_confirmation(
    monkeypatch: MonkeyPatch,
) -> None:
    """歧义别名不能自动映射，候选字段应以稳定顺序返回。"""
    contract = FieldMapping(
        required_fields=frozenset(),
        optional_fields=frozenset({"field_a", "field_b"}),
        aliases={
            "field_b": frozenset({"共享列"}),
            "field_a": frozenset({"共享列"}),
        },
    )
    monkeypatch.setattr(mapping_module, "TABLE_CONTRACTS", {"ambiguous_info": contract})

    result = suggest_mapping("ambiguous_info", ["共享列"])

    assert result.mapping == {}
    assert result.ambiguous_columns == {"共享列": ["field_a", "field_b"]}
