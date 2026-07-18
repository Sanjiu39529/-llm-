"""文件导入所需的数据库写入操作。"""

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import Connection, text

from backend.app.datasources.base import TABLE_CONTRACTS


class ImportRepository:
    """在调用方提供的事务连接中写入审计记录与业务数据。"""

    def __init__(self, batch_size: int = 1000) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._batch_size = batch_size

    def create_batch(
        self,
        connection: Connection,
        source_name: str,
        table_names: list[str],
        field_mapping: dict[str, dict[str, str]],
        quality_summary: dict[str, Any] | None = None,
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
                "quality_summary": json.dumps(quality_summary or {}, ensure_ascii=False),
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

        contract = TABLE_CONTRACTS[table_name]
        allowed_columns = set(contract.aliases) | set(contract.generated_fields)
        columns = [column for column in frame.columns if column in allowed_columns]
        insert_columns = [*columns, "import_batch_id"]
        values = ", ".join(f":{column}" for column in insert_columns)
        statement = text(
            f"INSERT INTO {table_name} ({', '.join(insert_columns)}) VALUES ({values})"
        )
        written = 0
        for start in range(0, len(frame), self._batch_size):
            chunk = frame.iloc[start : start + self._batch_size].loc[:, columns]
            records = [
                {
                    **{column: _database_value(value) for column, value in row.items()},
                    "import_batch_id": batch_id,
                }
                for row in chunk.to_dict(orient="records")
            ]
            connection.execute(statement, records)
            written += len(records)
        return written

    def duplicate_count(
        self, connection: Connection, table_name: str, frame: pd.DataFrame
    ) -> int:
        """在写入前主动检查数据库中已经存在的业务键。"""
        if frame.empty:
            return 0
        if table_name == "behavior_funnel":
            return 0
        grouped: dict[tuple[str, ...], list[tuple[Any, ...]]] = {}
        for columns, values in _key_rows(table_name, frame):
            grouped.setdefault(columns, []).append(values)

        count = 0
        for columns, values_group in grouped.items():
            for start in range(0, len(values_group), self._batch_size):
                parameters: dict[str, Any] = {}
                alternatives = []
                for row_index, values in enumerate(
                    values_group[start : start + self._batch_size]
                ):
                    predicates = []
                    for column_index, (column, value) in enumerate(zip(columns, values)):
                        name = f"key_{row_index}_{column_index}"
                        predicates.append(f"{column} = :{name}")
                        parameters[name] = _database_value(value)
                    alternatives.append("(" + " AND ".join(predicates) + ")")
                statement = text(
                    f"SELECT COUNT(*) FROM {table_name} WHERE "
                    + " OR ".join(alternatives)
                )
                count += int(connection.scalar(statement, parameters) or 0)
        return count

    def existing_values(
        self,
        connection: Connection,
        table_name: str,
        column: str,
        candidates: set[Any],
    ) -> set[Any]:
        """集合式读取数据库已有父键，查询也受数据库分块大小约束。"""
        contract = TABLE_CONTRACTS[table_name]
        if column not in contract.aliases:
            raise ValueError(f"unsupported relationship column: {table_name}.{column}")
        values = sorted(candidates, key=str)
        existing: set[Any] = set()
        for start in range(0, len(values), self._batch_size):
            chunk = values[start : start + self._batch_size]
            parameters = {
                f"value_{index}": _database_value(value)
                for index, value in enumerate(chunk)
            }
            placeholders = ", ".join(f":value_{index}" for index in range(len(chunk)))
            rows = connection.execute(
                text(f"SELECT {column} FROM {table_name} WHERE {column} IN ({placeholders})"),
                parameters,
            )
            existing.update(row[0] for row in rows)
        return existing

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

    def fail_batch(
        self,
        connection: Connection,
        batch_id: int,
        error_code: str,
        quality_summary: dict[str, Any],
    ) -> None:
        connection.execute(
            text(
                """
                UPDATE import_batch
                SET status = :status, error_code = :error_code,
                    quality_summary = :quality_summary, completed_at = :completed_at
                WHERE id = :batch_id
                """
            ),
            {
                "status": "failed",
                "error_code": error_code,
                "quality_summary": json.dumps(quality_summary, ensure_ascii=False),
                "completed_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
                "batch_id": batch_id,
            },
        )


_BUSINESS_KEYS: dict[str, tuple[str, ...]] = {
    "user_info": ("user_id",), "product_info": ("product_id",),
    "order_info": ("order_id",), "order_item": ("order_id", "product_id"),
    "traffic_visit": ("visit_id",), "behavior_info": ("event_id",),
    "ads_info": ("ad_id", "ad_date"),
    "ad_attribution": ("order_id", "ad_id", "attributed_at"),
}


def _key_rows(table_name: str, frame: pd.DataFrame) -> list[tuple[tuple[str, ...], tuple[Any, ...]]]:
    rows: list[tuple[tuple[str, ...], tuple[Any, ...]]] = []
    if table_name in {"payment_info", "refund_info"}:
        id_column = "payment_id" if table_name == "payment_info" else "refund_id"
        fallback = (
            ("order_id", "paid_at", "payment_amount")
            if table_name == "payment_info"
            else ("order_id", "refunded_at", "refund_amount")
        )
        for _, row in frame.iterrows():
            has_id = id_column in frame and not pd.isna(row[id_column]) and str(row[id_column]).strip()
            if has_id:
                rows.append(((id_column,), (row[id_column],)))
            rows.append((fallback, tuple(row[column] for column in fallback)))
        return rows
    columns = _BUSINESS_KEYS[table_name]
    return [(columns, tuple(row[column] for column in columns)) for _, row in frame.iterrows()]


def _database_value(value: Any) -> Any:
    """将 pandas/numpy 标量转换为数据库驱动可接受的值。"""
    if pd.isna(value):
        return None
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    if hasattr(value, "item"):
        return value.item()
    return value
