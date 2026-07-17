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
