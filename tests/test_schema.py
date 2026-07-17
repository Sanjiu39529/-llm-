"""MySQL Schema DDL 契约测试。"""

from pathlib import Path


def test_schema_contains_required_fact_and_audit_tables() -> None:
    """DDL 应定义所有必需的事实表和审计表。"""
    sql = Path("sql/001_schema.sql").read_text(encoding="utf-8")

    for table in (
        "user_info",
        "order_info",
        "payment_info",
        "refund_info",
        "traffic_visit",
        "ad_attribution",
        "import_batch",
        "metric_config",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
