"""为分析报告读取已导入业务表的只读仓储。"""

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import Engine, inspect, text

from backend.app.datasources.base import STANDARD_TABLES, TABLE_CONTRACTS
from backend.app.analytics.funnel import STAGES


DEFAULT_ANALYSIS_TABLES = STANDARD_TABLES.difference({"behavior_funnel"})
_TIME_COLUMNS = {
    "order_info": "order_time",
    "payment_info": "paid_at",
    "refund_info": "refunded_at",
    "traffic_visit": "visited_at",
    "behavior_info": "occurred_at",
    "ads_info": "ad_date",
    "ad_attribution": "attributed_at",
}


class AnalysisRepository:
    """仅按标准表白名单读取数据，供报告内核使用。"""

    def load_tables(
        self,
        engine: Engine,
        table_names: Iterable[str] | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        history_days: int = 365,
        attribution_lookahead_days: int = 7,
        dataset_ids: Sequence[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        names = tuple(table_names if table_names is not None else DEFAULT_ANALYSIS_TABLES)
        unknown = set(names).difference(STANDARD_TABLES)
        if unknown:
            raise ValueError(f"unsupported_analysis_tables: {sorted(unknown)}")
        if (start is None) != (end is None):
            raise ValueError("start_and_end_must_be_provided_together")
        if start is not None and start >= end:
            raise ValueError("start_must_be_before_end")
        available = {
            table: {column["name"] for column in inspect(engine).get_columns(table)}
            for table in names
        }
        history_start = start - timedelta(days=history_days) if start else None
        parameters = _dataset_parameters(dataset_ids)
        if history_start is not None:
            parameters.update(
                {
                    "history_start": history_start,
                    "end": end,
                    "attribution_end": end
                    + timedelta(days=attribution_lookahead_days),
                }
            )
        with engine.connect() as connection:
            return {
                name: _normalize_time_columns(
                    pd.read_sql_query(
                        text(
                            _select_sql(
                                name,
                                available[name],
                                bounded=history_start is not None,
                                dataset_count=len(dataset_ids or ()),
                            )
                        ),
                        connection,
                        params=parameters,
                    )
                )
                for name in names
            }

    def load_daily_gmv(
        self,
        engine: Engine,
        start: datetime,
        end: datetime,
        dataset_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        dataset_clause = _dataset_clause("o", len(dataset_ids or ()))
        statement = text(
            "SELECT DATE(o.order_time) AS date, SUM(o.order_amount) AS gmv "
            "FROM order_info o "
            "WHERE o.order_time >= :start AND o.order_time < :end"
            f"{dataset_clause} GROUP BY DATE(o.order_time) ORDER BY date"
        )
        parameters = {"start": start, "end": end, **_dataset_parameters(dataset_ids)}
        with engine.connect() as connection:
            frame = pd.read_sql_query(statement, connection, params=parameters)
        if "date" in frame:
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        return frame

    def load_funnel_report(
        self,
        engine: Engine,
        dataset_ids: Sequence[str] | None = None,
    ) -> dict[str, object]:
        dataset_clause = _dataset_clause("f", len(dataset_ids or ()))
        stage_sql = ", ".join(
            f"SUM(CASE WHEN f.{column} > 0 THEN 1 ELSE 0 END) AS {column}"
            for column, _ in STAGES
        )
        parameters = _dataset_parameters(dataset_ids)
        with engine.connect() as connection:
            summary = connection.execute(
                text(
                    "SELECT COUNT(*) AS visitors, "
                    "AVG(CASE WHEN f.new_user = 1 THEN 1.0 "
                    "WHEN f.new_user = 0 THEN 0.0 ELSE NULL END) AS new_user_ratio, "
                    f"{stage_sql} FROM behavior_funnel f WHERE 1=1{dataset_clause}"
                ),
                parameters,
            ).mappings().one()
            if int(summary["visitors"] or 0) == 0:
                return {"available": False, "reason": "missing_behavior_funnel"}
            dimensions = {
                column: _funnel_dimension(
                    connection, column, dataset_clause, parameters
                )
                for column in ("source", "device")
            }
        previous: int | None = None
        stages = []
        for column, label in STAGES:
            visitors = int(summary[column] or 0)
            stages.append(
                {
                    "stage": label,
                    "visitors": visitors,
                    "conversion_from_previous": (
                        None if previous in (None, 0) else visitors / previous
                    ),
                }
            )
            previous = visitors
        return {
            "available": True,
            "visitors": int(summary["visitors"]),
            "new_user_ratio": (
                None
                if summary["new_user_ratio"] is None
                else float(summary["new_user_ratio"])
            ),
            "funnel": stages,
            "source_conversion": dimensions["source"],
            "device_conversion": dimensions["device"],
        }


def _select_sql(
    table_name: str,
    available_columns: set[str],
    *,
    bounded: bool,
    dataset_count: int,
) -> str:
    contract = TABLE_CONTRACTS[table_name]
    allowed = set(contract.aliases) | set(contract.generated_fields) | {"import_batch_id", "id"}
    columns = sorted(available_columns.intersection(allowed))
    if not columns:
        raise ValueError(f"analysis_table_has_no_supported_columns: {table_name}")
    alias = "t"
    clauses: list[str] = []
    if bounded and table_name in _TIME_COLUMNS:
        time_column = _TIME_COLUMNS[table_name]
        clauses.append(f"{alias}.{time_column} >= :history_start")
        end_parameter = "attribution_end" if table_name == "ad_attribution" else "end"
        clauses.append(f"{alias}.{time_column} < :{end_parameter}")
    if dataset_count and "import_batch_id" in available_columns:
        clauses.append(_dataset_clause(alias, dataset_count).removeprefix(" AND "))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    selected = ", ".join(f"{alias}.{column}" for column in columns)
    return f"SELECT {selected} FROM {table_name} {alias}{where}"


def _dataset_clause(alias: str, count: int) -> str:
    if count == 0:
        return ""
    placeholders = ", ".join(f":dataset_{index}" for index in range(count))
    return (
        f" AND {alias}.import_batch_id IN ("
        "SELECT id FROM import_batch WHERE dataset_id IN ("
        f"{placeholders}))"
    )


def _dataset_parameters(dataset_ids: Sequence[str] | None) -> dict[str, str]:
    return {
        f"dataset_{index}": dataset_id
        for index, dataset_id in enumerate(dataset_ids or ())
    }


def _funnel_dimension(
    connection,
    column: str,
    dataset_clause: str,
    parameters: dict[str, str],
) -> list[dict[str, object]]:
    rows = connection.execute(
        text(
            f"SELECT f.{column} AS dimension, COUNT(*) AS visitors, "
            "AVG(CASE WHEN f.confirmation_page > 0 THEN 1.0 ELSE 0.0 END) "
            "AS confirmation_rate FROM behavior_funnel f "
            f"WHERE 1=1{dataset_clause} GROUP BY f.{column} ORDER BY f.{column}"
        ),
        parameters,
    ).mappings()
    return [
        {
            "dimension": "未知" if row["dimension"] is None else str(row["dimension"]),
            "visitors": int(row["visitors"]),
            "confirmation_rate": float(row["confirmation_rate"]),
        }
        for row in rows
    ]


def _normalize_time_columns(frame: pd.DataFrame) -> pd.DataFrame:
    for column in frame.columns:
        if column.endswith(("_time", "_at", "_date")):
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame
