"""Excel/CSV 文件读取适配器。"""

from pathlib import Path

import pandas as pd

from backend.app.datasources.base import STANDARD_TABLES
from backend.app.services.mapping import detect_table


class FileImportAdapter:
    """将文件中的标准表读取为数据框。"""

    def read(
        self, path: Path, target_table: str | None = None
    ) -> dict[str, pd.DataFrame]:
        """读取 CSV 指定表或 Excel 中的已知工作表。"""
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".csv":
            frame = pd.read_csv(path, dtype=object, keep_default_na=False)
            if target_table is None:
                detection = detect_table(list(frame.columns))
                if detection.table_name is None:
                    raise ValueError(
                        f"cannot_auto_identify: reason={detection.reason} candidates={list(detection.candidates)}"
                    )
                target_table = detection.table_name
            if target_table not in STANDARD_TABLES:
                raise ValueError(f"不支持的标准表: {target_table}")
            return {target_table: frame}

        if suffix == ".xlsx":
            if target_table is not None:
                raise ValueError("--table 仅适用于 CSV；Excel 会导入所有已知工作表")
            workbook = pd.ExcelFile(path)
            detected: dict[str, pd.DataFrame] = {}
            for sheet_name in workbook.sheet_names:
                frame = pd.read_excel(
                    workbook, sheet_name=sheet_name, dtype=object, keep_default_na=False
                )
                table_name = sheet_name if sheet_name in STANDARD_TABLES else detect_table(list(frame.columns)).table_name
                if table_name is None:
                    continue
                if table_name in detected:
                    raise ValueError(f"duplicate_detected_table: {table_name}")
                detected[table_name] = frame
            return detected

        raise ValueError(f"不支持的文件类型: {suffix or '<无扩展名>'}")

    def iter_csv(self, path: Path, chunk_size: int):
        """Yield bounded CSV frames without retaining the complete file in memory."""
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        yield from pd.read_csv(
            Path(path), dtype=object, keep_default_na=False, chunksize=chunk_size
        )
