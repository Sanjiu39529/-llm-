"""MySQL Schema DDL 契约测试。"""

from pathlib import Path

BUSINESS_TABLES = (
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
)


def test_schema_contains_required_fact_and_audit_tables() -> None:
    """DDL 应定义所有必需的事实表和审计表。"""
    sql = Path("sql/001_schema.sql").read_text(encoding="utf-8")

    for table in (*BUSINESS_TABLES, "import_batch", "metric_config"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql


def test_schema_enforces_audit_type_and_index_invariants() -> None:
    """DDL 应保留批次审计、存储类型和关键复合索引。"""
    sql = Path("sql/001_schema.sql").read_text(encoding="utf-8")

    for table in BUSINESS_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
        definition = sql.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1]
        definition = definition.split(") ENGINE=InnoDB", 1)[0]
        assert "import_batch_id BIGINT UNSIGNED NOT NULL" in definition

    for fragment in (
        "field_mapping JSON NOT NULL",
        "quality_summary JSON NOT NULL",
        "DECIMAL(18,2)",
        "DATETIME",
        "INDEX idx_order_info_user_time (user_id, order_time)",
        "INDEX idx_payment_info_order_paid (order_id, paid_at)",
        "INDEX idx_refund_info_order_refunded (order_id, refunded_at)",
        "INDEX idx_traffic_visit_user_time (user_id, visited_at)",
        "INDEX idx_ads_info_campaign_date (campaign_id, ad_date)",
        "INDEX idx_ad_attribution_ad_time (ad_id, attributed_at)",
    ):
        assert fragment in sql

    assert sql.count("DEFAULT CHARSET=utf8mb4") == 12


def test_schema_declares_money_and_time_field_types() -> None:
    """金额与业务时间字段应逐项使用约定的存储类型。"""
    sql = Path("sql/001_schema.sql").read_text(encoding="utf-8")
    field_types = {
        "import_batch": {
            "created_at": "DATETIME",
            "completed_at": "DATETIME",
        },
        "metric_config": {"updated_at": "DATETIME"},
        "user_info": {"register_time": "DATETIME"},
        "product_info": {"price": "DECIMAL(18,2)"},
        "order_info": {
            "order_time": "DATETIME",
            "order_amount": "DECIMAL(18,2)",
        },
        "order_item": {
            "unit_price": "DECIMAL(18,2)",
            "item_amount": "DECIMAL(18,2)",
        },
        "payment_info": {
            "paid_at": "DATETIME",
            "payment_amount": "DECIMAL(18,2)",
        },
        "refund_info": {
            "refund_amount": "DECIMAL(18,2)",
            "refunded_at": "DATETIME",
        },
        "traffic_visit": {"visited_at": "DATETIME"},
        "behavior_info": {"occurred_at": "DATETIME"},
        "ads_info": {
            "ad_date": "DATETIME",
            "cost": "DECIMAL(18,2)",
        },
        "ad_attribution": {
            "attributed_at": "DATETIME",
            "attribution_amount": "DECIMAL(18,2)",
        },
    }

    for table, fields in field_types.items():
        definition = sql.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1]
        definition = definition.split(") ENGINE=InnoDB", 1)[0]
        for field, field_type in fields.items():
            assert f"{field} {field_type}" in definition


def test_schema_persists_age_outlier_and_failed_audit_fields() -> None:
    sql = Path("sql/001_schema.sql").read_text(encoding="utf-8")
    assert "age INT NULL" in sql
    assert sql.count("is_outlier BOOLEAN NOT NULL DEFAULT FALSE") == 7
    assert "error_code VARCHAR(64) NULL" in sql


def test_schema_enforces_payment_and_refund_business_keys() -> None:
    sql = Path("sql/001_schema.sql").read_text(encoding="utf-8")
    assert "UNIQUE KEY uq_payment_info_id (payment_id)" in sql
    assert "UNIQUE KEY uq_payment_info_business_key (order_id, paid_at, payment_amount)" in sql
    assert "UNIQUE KEY uq_refund_info_id (refund_id)" in sql
    assert "UNIQUE KEY uq_refund_info_business_key (order_id, refunded_at, refund_amount)" in sql


def test_integrity_upgrade_migration_contains_all_phase_one_additions() -> None:
    migration = Path("sql/002_phase1_integrity_upgrade.sql").read_text(encoding="utf-8")
    assert migration.count("ADD COLUMN is_outlier BOOLEAN NOT NULL DEFAULT FALSE") == 7
    for fragment in (
        "ADD COLUMN error_code VARCHAR(64) NULL",
        "ADD COLUMN age INT NULL",
        "ADD UNIQUE KEY uq_payment_info_business_key",
        "ADD UNIQUE KEY uq_payment_info_id",
        "ADD UNIQUE KEY uq_refund_info_business_key",
        "ADD UNIQUE KEY uq_refund_info_id",
    ):
        assert fragment in migration
