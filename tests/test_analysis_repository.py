import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, event, text

from backend.app.database.analysis_repository import AnalysisRepository


def test_analysis_repository_reads_only_requested_standard_tables():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE order_info (order_id TEXT, order_time TEXT)"))
        connection.execute(text("INSERT INTO order_info VALUES ('o1', '2026-01-01')"))

    tables = AnalysisRepository().load_tables(engine, ["order_info"])

    assert tables["order_info"].loc[0, "order_id"] == "o1"
    assert isinstance(tables["order_info"].loc[0, "order_time"], pd.Timestamp)


def test_analysis_repository_pushes_projection_time_and_dataset_to_sql():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE import_batch (id INTEGER PRIMARY KEY, dataset_id TEXT)")
        )
        connection.execute(
            text(
                "CREATE TABLE order_info (order_id TEXT, order_time TEXT, "
                "order_amount NUMERIC, import_batch_id INTEGER)"
            )
        )
        connection.execute(text("INSERT INTO import_batch VALUES (1, 'dataset-a')"))
        connection.execute(
            text(
                "INSERT INTO order_info VALUES "
                "('old', '2020-01-01', 1, 1), ('current', '2026-07-01', 10, 1)"
            )
        )
    statements = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, parameters, context, executemany: statements.append(statement),
    )

    tables = AnalysisRepository().load_tables(
        engine,
        ["order_info"],
        start=datetime(2026, 7, 1),
        end=datetime(2026, 7, 2),
        history_days=30,
        dataset_ids=["dataset-a"],
    )

    assert tables["order_info"]["order_id"].tolist() == ["current"]
    select = next(statement for statement in statements if "FROM order_info" in statement)
    assert "SELECT *" not in select.upper()
    assert "order_time >=" in select
    assert "dataset_id IN" in select


def test_analysis_repository_aggregates_daily_gmv_in_sql():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE order_info (order_time TEXT, order_amount NUMERIC, "
                "import_batch_id INTEGER)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO order_info VALUES "
                "('2026-07-01 01:00:00', 10, 1), "
                "('2026-07-01 02:00:00', 20, 1), "
                "('2026-07-02 01:00:00', 5, 1)"
            )
        )

    daily = AnalysisRepository().load_daily_gmv(
        engine, datetime(2026, 7, 1), datetime(2026, 7, 3)
    )

    assert daily["gmv"].tolist() == [30, 5]


def test_analysis_repository_aggregates_behavior_funnel_in_sql():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE behavior_funnel (new_user INTEGER, source TEXT, device TEXT, "
                "home_page INTEGER, listing_page INTEGER, product_page INTEGER, "
                "payment_page INTEGER, confirmation_page INTEGER, import_batch_id INTEGER)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO behavior_funnel VALUES "
                "(1, 'Direct', 'PC', 1, 1, 1, 1, 1, 1), "
                "(0, 'Direct', 'Mobile', 1, 1, 1, 0, 0, 1)"
            )
        )

    report = AnalysisRepository().load_funnel_report(engine)

    assert report["visitors"] == 2
    assert report["new_user_ratio"] == 0.5
    assert [stage["visitors"] for stage in report["funnel"]] == [2, 2, 2, 1, 1]
    assert report["source_conversion"][0]["confirmation_rate"] == 0.5
