"""文件导入所需的数据库写入操作。"""

import json
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import Connection, text

from backend.app.datasources.base import TABLE_CONTRACTS


class ImportRepository:
    """在调用方提供的事务连接中写入审计记录与业务数据。"""

    def create_batch(
        self,
        connection: Connection,
        source_name: str,
        table_names: list[str],
        field_mapping: dict[str, dict[str, str]],
    ) -> int:
        result = connection.execute(
            text(
                """
                INSERT INTO import_batch
                    (source_name, table_name, status, field_mapping, quality_summary)
                VALUES
                    (:source_name, :table_name, :status, :field_mapping, :quality_summary)
                """
            ),
            {
                "source_name": source_name,
                "table_name": table_names[0] if len(table_names) == 1 else "multiple",
                "status": "processing",
                "field_mapping": json.dumps(field_mapping, ensure_ascii=False),
                "quality_summary": json.dumps({}, ensure_ascii=False),
            },
        )
        if result.lastrowid is None:
            raise RuntimeError("创建导入批次后未获得批次 ID")
        return int(result.lastrowid)

    def write_frame(
        self,
        connection: Connection,
        table_name: str,
        frame: pd.DataFrame,
        batch_id: int,
    ) -> int:
        if frame.empty:
            return 0

        allowed_columns = set(TABLE_CONTRACTS[table_name].aliases)
        columns = [column for column in frame.columns if column in allowed_columns]
        insert_columns = [*columns, "import_batch_id"]
        values = ", ".join(f":{column}" for column in insert_columns)
        statement = text(
            f"INSERT INTO {table_name} ({', '.join(insert_columns)}) VALUES ({values})"
        )
        records = []
        for row in frame.loc[:, columns].to_dict(orient="records"):
            records.append(
                {
                    **{column: _database_value(value) for column, value in row.items()},
                    "import_batch_id": batch_id,
                }
            )
        connection.execute(statement, records)
        return len(records)

    def complete_batch(
        self,
        connection: Connection,
        batch_id: int,
        quality_summary: dict[str, dict[str, Any]],
    ) -> None:
        connection.execute(
            text(
                """
                UPDATE import_batch
                SET status = :status,
                    quality_summary = :quality_summary,
                    completed_at = :completed_at
                WHERE id = :batch_id
                """
            ),
            {
                "status": "completed",
                "quality_summary": json.dumps(quality_summary, ensure_ascii=False),
                "completed_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
                "batch_id": batch_id,
            },
        )


def _database_value(value: Any) -> Any:
    """将 pandas/numpy 标量转换为数据库驱动可接受的值。"""
    if pd.isna(value):
        return None
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    if hasattr(value, "item"):
        return value.item()
    return value
