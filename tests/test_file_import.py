"""Excel/CSV 文件读取与导入编排测试。"""

from pathlib import Path
import json
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from backend.app.database.repository import ImportRepository
from backend.app.datasources.base import STANDARD_TABLES
from backend.app.datasources.file_import import FileImportAdapter
from backend.app.services.import_service import ImportReport, ImportService
from backend.app.services.import_service import CrossBatchDuplicateError


def test_csv_requires_target_table_and_returns_one_frame(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    path.write_text(
        "订单编号,用户ID,下单时间,渠道,订单状态\n"
        "o1,u1,2026-01-01,自然搜索,已下单\n",
        encoding="utf-8",
    )

    frames = FileImportAdapter().read(path, target_table="order_info")

    assert list(frames) == ["order_info"]
    assert frames["order_info"].iloc[0]["订单编号"] == "o1"


def test_excel_ignores_unknown_sheet_and_reads_known_sheet(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"用户ID": ["u1"], "注册时间": ["2026-01-01"]}).to_excel(
            writer, sheet_name="user_info", index=False
        )
        pd.DataFrame({"x": [1]}).to_excel(writer, sheet_name="notes", index=False)

    assert list(FileImportAdapter().read(path)) == ["user_info"]


def test_excel_rejects_target_table_instead_of_ignoring_it(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"user_id": ["u1"]}).to_excel(writer, sheet_name="user_info", index=False)
    with pytest.raises(ValueError, match="--table.*CSV"):
        FileImportAdapter().read(path, target_table="user_info")


def test_csv_without_target_table_lists_available_tables(tmp_path: Path) -> None:
    path = tmp_path / "users.csv"
    path.write_text("用户ID\nu1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="user_info"):
        FileImportAdapter().read(path)


def _create_import_tables(engine: object, business_ddl: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE import_batch (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    field_mapping TEXT NOT NULL,
                    quality_summary TEXT NOT NULL,
                    error_code TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME
                )
                """
            )
        )
        connection.execute(text(business_ddl))


def test_import_service_returns_auditable_report(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_import_tables(
        engine,
        """
        CREATE TABLE user_info (
            user_id TEXT PRIMARY KEY,
            import_batch_id INTEGER NOT NULL
        )
        """,
    )
    path = tmp_path / "users.csv"
    path.write_text("用户ID\nu1\n", encoding="utf-8")

    report = ImportService(engine).import_file(path, target_table="user_info")

    assert report.batch_id == 1
    assert report.processed_tables == ["user_info"]
    assert report.written_rows == 1
    assert report.skipped_rows == 0
    assert "order_info" in report.missing_tables
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM user_info")) == 1
        assert connection.scalar(text("SELECT status FROM import_batch")) == "completed"


def test_import_service_rejects_unmapped_required_fields_before_writes(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_import_tables(
        engine,
        "CREATE TABLE user_info (user_id TEXT, import_batch_id INTEGER)",
    )
    path = tmp_path / "users.csv"
    path.write_text("昵称\n张三\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unmapped_required.*user_id"):
        ImportService(engine).import_file(path, target_table="user_info")

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM import_batch")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM user_info")) == 0


def test_import_service_rejects_ambiguous_columns_before_writes(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_import_tables(
        engine,
        "CREATE TABLE user_info (user_id TEXT, import_batch_id INTEGER)",
    )
    path = tmp_path / "users.csv"
    path.write_text(
        "用户ID,用户编号\n"
        "u1,u1-alias\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc_info:
        ImportService(engine).import_file(path, target_table="user_info")
    assert str(exc_info.value) == (
        "自动字段映射无法确认: user_info: "
        "ambiguous_columns={'用户ID': ['user_id'], '用户编号': ['user_id']}"
    )

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM import_batch")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM user_info")) == 0


def test_import_service_rolls_back_batch_when_business_write_fails(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_import_tables(
        engine,
        """
        CREATE TABLE user_info (
            user_id TEXT CHECK (user_id <> 'u1'),
            import_batch_id INTEGER NOT NULL
        )
        """,
    )
    path = tmp_path / "users.csv"
    path.write_text("用户ID\nu1\n", encoding="utf-8")

    with pytest.raises(Exception):
        ImportService(engine).import_file(path, target_table="user_info")

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM import_batch")) == 1
        assert connection.scalar(text("SELECT status FROM import_batch")) == "failed"
        assert connection.scalar(text("SELECT error_code FROM import_batch")) == "database_write_failed"
        assert connection.scalar(text("SELECT COUNT(*) FROM user_info")) == 0


def test_import_service_rolls_back_earlier_tables_when_later_table_fails(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_import_tables(
        engine,
        "CREATE TABLE user_info (user_id TEXT, import_batch_id INTEGER NOT NULL)",
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE product_info (
                    product_id TEXT CHECK (product_id <> 'p1'),
                    product_name TEXT NOT NULL,
                    import_batch_id INTEGER NOT NULL
                )
                """
            )
        )
    path = tmp_path / "input.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"用户ID": ["u1"]}).to_excel(
            writer, sheet_name="user_info", index=False
        )
        pd.DataFrame({"商品ID": ["p1"], "商品名称": ["商品"]}).to_excel(
            writer, sheet_name="product_info", index=False
        )

    with pytest.raises(Exception):
        ImportService(engine).import_file(path)

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM import_batch")) == 1
        assert connection.scalar(text("SELECT status FROM import_batch")) == "failed"
        assert connection.scalar(text("SELECT COUNT(*) FROM user_info")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM product_info")) == 0


def test_repository_uses_bounded_label_for_multi_table_batch() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE import_batch (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    table_name VARCHAR(64) NOT NULL,
                    status TEXT NOT NULL,
                    field_mapping TEXT NOT NULL,
                    quality_summary TEXT NOT NULL
                )
                """
            )
        )
        ImportRepository().create_batch(
            connection,
            "all.xlsx",
            sorted(STANDARD_TABLES),
            {table_name: {} for table_name in STANDARD_TABLES},
        )

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT table_name FROM import_batch")) == "multiple"


def test_cli_outputs_report_json(monkeypatch: pytest.MonkeyPatch, capsys: object) -> None:
    from backend.scripts import import_data

    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(
        import_data.ImportService,
        "import_file",
        lambda self, path, target_table=None: ImportReport(
            batch_id=7,
            processed_tables=["user_info"],
            written_rows=2,
            skipped_rows=1,
            missing_tables=["order_info"],
        ),
    )

    exit_code = import_data.main(["--file", "users.csv", "--table", "user_info"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"batch_id": 7' in output
    assert '"written_rows": 2' in output


def test_cli_outputs_json_error_and_exit_code_one(
    monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    from backend.scripts import import_data

    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(
        import_data.ImportService,
        "import_file",
        lambda self, path, target_table=None: (_ for _ in ()).throw(ValueError("bad file")),
    )

    exit_code = import_data.main(["--file", "bad.csv", "--table", "user_info"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error_code": "invalid_input", "error": "bad file"}


def test_cli_argument_error_outputs_json_and_exit_code_one(capsys: object) -> None:
    from backend.scripts import import_data

    exit_code = import_data.main([])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error_code"] == "invalid_input"


def test_cli_redacts_internal_error_details(
    monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    from backend.scripts import import_data

    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(
        import_data.ImportService,
        "import_file",
        lambda self, path, target_table=None: (_ for _ in ()).throw(
            RuntimeError("mysql://admin:secret@private-host/db")
        ),
    )
    assert import_data.main(["--file", "users.csv", "--table", "user_info"]) == 1
    captured = capsys.readouterr()
    assert "secret" not in captured.err
    assert json.loads(captured.err) == {
        "error_code": "internal_error", "error": "导入失败"
    }


def test_quality_summary_persists_missing_unmapped_reasons_and_relationships(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_import_tables(engine, "CREATE TABLE user_info (user_id TEXT PRIMARY KEY, age INT, import_batch_id INTEGER NOT NULL)")
    path = tmp_path / "users.csv"
    path.write_text("user_id,age,ignored\nu1,101,x\n", encoding="utf-8")

    ImportService(engine).import_file(path, target_table="user_info")

    with engine.connect() as connection:
        audit = json.loads(connection.scalar(text("SELECT quality_summary FROM import_batch")))
    assert "order_info" in audit["missing_tables"]
    assert audit["tables"]["user_info"]["unmapped_source_columns"] == ["ignored"]
    assert audit["tables"]["user_info"]["reasons"]["age"]["age_out_of_range"] == 1
    assert audit["relationship_anomalies"] == {}


def test_quality_summary_counts_relationship_anomalies(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_import_tables(
        engine,
        "CREATE TABLE user_info (user_id TEXT PRIMARY KEY, import_batch_id INTEGER NOT NULL)",
    )
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE order_info (
                order_id TEXT PRIMARY KEY, user_id TEXT, order_time DATETIME,
                is_outlier BOOLEAN, import_batch_id INTEGER NOT NULL
            )
        """))
    path = tmp_path / "relations.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"user_id": ["u1"]}).to_excel(writer, sheet_name="user_info", index=False)
        pd.DataFrame({
            "order_id": ["o1", "o2"], "user_id": ["u1", "missing-user"],
            "order_time": ["2026-01-01", "2026-01-01"],
        }).to_excel(writer, sheet_name="order_info", index=False)

    ImportService(engine).import_file(path)

    with engine.connect() as connection:
        audit = json.loads(connection.scalar(text("SELECT quality_summary FROM import_batch")))
    assert audit["relationship_anomalies"] == {
        "order_info.user_id": {"missing_parent": 1}
    }


def test_cross_batch_duplicate_rejects_new_batch_with_failed_audit(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_import_tables(engine, "CREATE TABLE user_info (user_id TEXT PRIMARY KEY, import_batch_id INTEGER NOT NULL)")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO user_info (user_id, import_batch_id) VALUES ('u1', 99)"))
    path = tmp_path / "users.csv"
    path.write_text("user_id\nu1\n", encoding="utf-8")

    with pytest.raises(CrossBatchDuplicateError, match="cross_batch_duplicate.*user_info"):
        ImportService(engine).import_file(path, target_table="user_info")

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM user_info")) == 1
        assert connection.scalar(text("SELECT status FROM import_batch")) == "failed"
        assert connection.scalar(text("SELECT error_code FROM import_batch")) == "cross_batch_duplicate"


def test_repository_chunks_executemany_and_preserves_generated_fields() -> None:
    calls: list[list[dict[str, object]]] = []

    class ConnectionSpy:
        def execute(self, statement: object, records: list[dict[str, object]]) -> None:
            calls.append(records)

    frame = pd.DataFrame({
        "order_id": [f"o{i}" for i in range(5)], "user_id": ["u"] * 5,
        "order_time": pd.to_datetime(["2026-01-01"] * 5),
        "is_outlier": [False, False, False, False, True],
    })
    written = ImportRepository(batch_size=2).write_frame(ConnectionSpy(), "order_info", frame, 1)
    assert written == 5
    assert [len(records) for records in calls] == [2, 2, 1]
    assert calls[-1][0]["is_outlier"] is True


def test_repository_binds_decimal_without_binary_float_loss() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE payment_info (
                order_id TEXT, paid_at DATETIME, payment_amount NUMERIC,
                is_outlier BOOLEAN, import_batch_id INTEGER
            )
        """))
        ImportRepository().write_frame(connection, "payment_info", pd.DataFrame({
            "order_id": ["o1"], "paid_at": pd.to_datetime(["2026-01-01"]),
            "payment_amount": [Decimal("0.11")], "is_outlier": [False],
        }), 1)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT CAST(payment_amount AS TEXT) FROM payment_info")) == "0.11"


def _create_payment_import_tables(engine: object) -> None:
    _create_import_tables(
        engine,
        """
        CREATE TABLE payment_info (
            order_id TEXT NOT NULL, paid_at DATETIME NOT NULL,
            payment_amount TEXT NOT NULL, is_outlier BOOLEAN NOT NULL,
            import_batch_id INTEGER NOT NULL
        )
        """,
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE order_info (order_id TEXT PRIMARY KEY)"))


@pytest.mark.parametrize("file_type", ["csv", "xlsx"])
def test_file_to_service_preserves_text_ids_and_decimal_boundaries(
    tmp_path: Path, file_type: str
) -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_payment_import_tables(engine)
    rows = pd.DataFrame({
        "order_id": ["00123", "00999", "00001"],
        "paid_at": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "payment_amount": ["0.105", "9999999999999999.99", "10000000000000000.00"],
    })
    if file_type == "csv":
        path = tmp_path / "payments.csv"
        rows.to_csv(path, index=False)
        report = ImportService(engine).import_file(path, target_table="payment_info")
    else:
        path = tmp_path / "payments.xlsx"
        with pd.ExcelWriter(path) as writer:
            rows.to_excel(writer, sheet_name="payment_info", index=False)
        report = ImportService(engine).import_file(path)

    assert report.written_rows == 2
    assert report.skipped_rows == 1
    with engine.connect() as connection:
        stored = connection.execute(text(
            "SELECT order_id, payment_amount FROM payment_info ORDER BY paid_at"
        )).all()
    assert stored == [("00123", "0.11"), ("00999", "9999999999999999.99")]


def test_child_only_import_checks_database_parent_keys(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_import_tables(engine, """
        CREATE TABLE order_info (
            order_id TEXT PRIMARY KEY, user_id TEXT, order_time DATETIME,
            is_outlier BOOLEAN, import_batch_id INTEGER NOT NULL
        )
    """)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE user_info (user_id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO user_info (user_id) VALUES ('known')"))
    path = tmp_path / "orders.csv"
    path.write_text(
        "order_id,user_id,order_time\no1,known,2026-01-01\no2,missing,2026-01-01\n",
        encoding="utf-8",
    )

    ImportService(engine).import_file(path, target_table="order_info")

    with engine.connect() as connection:
        audit = json.loads(connection.scalar(text("SELECT quality_summary FROM import_batch")))
    assert audit["relationship_anomalies"] == {
        "order_info.user_id": {"missing_parent": 1}
    }


def test_batch_parent_subset_unions_existing_database_parents(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_import_tables(
        engine, "CREATE TABLE user_info (user_id TEXT PRIMARY KEY, import_batch_id INTEGER NOT NULL)"
    )
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO user_info VALUES ('existing', 99)"))
        connection.execute(text("""
            CREATE TABLE order_info (
                order_id TEXT PRIMARY KEY, user_id TEXT, order_time DATETIME,
                is_outlier BOOLEAN, import_batch_id INTEGER NOT NULL
            )
        """))
    path = tmp_path / "subset.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"user_id": ["new"]}).to_excel(writer, sheet_name="user_info", index=False)
        pd.DataFrame({
            "order_id": ["o1", "o2"], "user_id": ["new", "existing"],
            "order_time": ["2026-01-01"] * 2,
        }).to_excel(writer, sheet_name="order_info", index=False)

    ImportService(engine).import_file(path)

    with engine.connect() as connection:
        audit = json.loads(connection.scalar(text("SELECT quality_summary FROM import_batch ORDER BY id DESC LIMIT 1")))
    assert audit["relationship_anomalies"] == {}


def test_duplicate_check_uses_one_set_query_per_key_shape() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE user_info (user_id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO user_info VALUES ('u3')"))
    selects: list[str] = []

    from sqlalchemy import event
    event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, parameters, context, executemany:
            selects.append(statement) if statement.startswith("SELECT COUNT(*) FROM user_info") else None,
    )
    with engine.connect() as connection:
        count = ImportRepository(batch_size=100).duplicate_count(
            connection, "user_info", pd.DataFrame({"user_id": [f"u{i}" for i in range(10)]})
        )
    assert count == 1
    assert len(selects) == 1
