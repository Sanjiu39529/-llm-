"""为分析报告读取已导入业务表的只读仓储。"""

from collections.abc import Iterable

import pandas as pd
from sqlalchemy import Engine, text

from backend.app.datasources.base import STANDARD_TABLES


DEFAULT_ANALYSIS_TABLES = STANDARD_TABLES.difference({"behavior_funnel"})


class AnalysisRepository:
    """仅按标准表白名单读取数据，供报告内核使用。"""

    def load_tables(
        self, engine: Engine, table_names: Iterable[str] | None = None
    ) -> dict[str, pd.DataFrame]:
        names = tuple(table_names if table_names is not None else DEFAULT_ANALYSIS_TABLES)
        unknown = set(names).difference(STANDARD_TABLES)
        if unknown:
            raise ValueError(f"unsupported_analysis_tables: {sorted(unknown)}")
        with engine.connect() as connection:
            return {
                name: _normalize_time_columns(pd.read_sql_query(text(f"SELECT * FROM {name}"), connection))
                for name in names
            }


def _normalize_time_columns(frame: pd.DataFrame) -> pd.DataFrame:
    for column in frame.columns:
        if column.endswith(("_time", "_at", "_date")):
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame
