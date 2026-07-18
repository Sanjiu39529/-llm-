from __future__ import annotations

from sqlalchemy import create_engine, text

from backend.app.nl2sql.service import Nl2SqlService, ReadonlySqlExecutor, SqlGuardError
from backend.app.nl2sql.openai_compatible import _strip_markdown


class FixedGenerator:
    def __init__(self, sql: str) -> None:
        self.sql = sql

    def generate(self, question: str, schema_context: str) -> str:
        assert question
        assert "order_info" in schema_context
        return self.sql


def test_service_allows_single_read_query_and_applies_limit():
    service = Nl2SqlService(max_rows=2)

    prepared = service.prepare("查询订单", FixedGenerator("SELECT order_id FROM order_info"))

    assert prepared.sql.endswith("LIMIT :_nl2sql_limit")
    assert prepared.parameters == {"_nl2sql_limit": 2}


def test_service_rejects_write_comments_multiple_statements_and_unknown_tables():
    service = Nl2SqlService()
    invalid_sql = (
        "DELETE FROM order_info",
        "SELECT * FROM order_info; DELETE FROM order_info",
        "SELECT * FROM order_info -- bypass",
        "SELECT * FROM secret_table",
        "SELECT * FROM order_info, secret_table",
    )

    for sql in invalid_sql:
        try:
            service.prepare("查询", FixedGenerator(sql))
        except SqlGuardError:
            continue
        raise AssertionError(f"expected SqlGuardError for {sql}")


def test_executor_runs_validated_sql_with_row_cap():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE order_info (order_id TEXT)"))
        connection.execute(text("INSERT INTO order_info VALUES ('o1'), ('o2'), ('o3')"))

    result = ReadonlySqlExecutor(engine, max_rows=2).execute("SELECT order_id FROM order_info")

    assert result.columns == ("order_id",)
    assert result.rows == (("o1",), ("o2",))


def test_markdown_wrapped_model_output_is_reduced_to_sql():
    assert _strip_markdown("```sql\nSELECT * FROM order_info\n```") == "SELECT * FROM order_info"
