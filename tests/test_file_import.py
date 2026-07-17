"""Excel/CSV 文件读取与导入编排测试。"""

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from backend.app.database.repository import ImportRepository
from backend.app.datasources.base import STANDARD_TABLES
from backend.app.datasources.file_import import FileImportAdapter
from backend.app.services.import_service import ImportReport, ImportService
from backend.app.services.mapping import MappingResult


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app.services import import_service

    engine = create_engine("sqlite:///:memory:")
    _create_import_tables(
        engine,
        "CREATE TABLE user_info (user_id TEXT, import_batch_id INTEGER)",
    )
    path = tmp_path / "users.csv"
    path.write_text("用户ID\nu1\n", encoding="utf-8")
    monkeypatch.setattr(
        import_service,
        "suggest_mapping",
        lambda table_name, columns: MappingResult(
            mapping={},
            unmapped_required=[],
            ambiguous_columns={"用户ID": ["user_id", "other_id"]},
        ),
    )

    with pytest.raises(ValueError, match="ambiguous_columns.*用户ID"):
        ImportService(engine).import_file(path, target_table="user_info")

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
        assert connection.scalar(text("SELECT COUNT(*) FROM import_batch")) == 0
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
        assert connection.scalar(text("SELECT COUNT(*) FROM import_batch")) == 0
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
    assert capsys.readouterr().out.strip() == '{"error": "bad file"}'


def test_cli_argument_error_outputs_json_and_exit_code_one(capsys: object) -> None:
    from backend.scripts import import_data

    exit_code = import_data.main([])

    assert exit_code == 1
    assert "error" in capsys.readouterr().out
