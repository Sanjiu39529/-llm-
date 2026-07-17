"""Excel/CSV 文件读取适配器。"""

from pathlib import Path

import pandas as pd

from backend.app.datasources.base import STANDARD_TABLES


class FileImportAdapter:
    """将文件中的标准表读取为数据框。"""

    def read(
        self, path: Path, target_table: str | None = None
    ) -> dict[str, pd.DataFrame]:
        """读取 CSV 指定表或 Excel 中的已知工作表。"""
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".csv":
            if target_table is None:
                choices = ", ".join(sorted(STANDARD_TABLES))
                raise ValueError(f"CSV 必须指定 target_table，可选表名: {choices}")
            if target_table not in STANDARD_TABLES:
                raise ValueError(f"不支持的标准表: {target_table}")
            return {target_table: pd.read_csv(path)}

        if suffix == ".xlsx":
            workbook = pd.ExcelFile(path)
            known_sheets = [
                sheet for sheet in workbook.sheet_names if sheet in STANDARD_TABLES
            ]
            return pd.read_excel(workbook, sheet_name=known_sheets)

        raise ValueError(f"不支持的文件类型: {suffix or '<无扩展名>'}")
