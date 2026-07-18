import pandas as pd
from sqlalchemy import create_engine, text

from backend.app.database.analysis_repository import AnalysisRepository


def test_analysis_repository_reads_only_requested_standard_tables():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE order_info (order_id TEXT, order_time TEXT)"))
        connection.execute(text("INSERT INTO order_info VALUES ('o1', '2026-01-01')"))

    tables = AnalysisRepository().load_tables(engine, ["order_info"])

    assert tables["order_info"].loc[0, "order_id"] == "o1"
    assert isinstance(tables["order_info"].loc[0, "order_time"], pd.Timestamp)
