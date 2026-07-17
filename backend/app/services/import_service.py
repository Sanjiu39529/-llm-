"""可审计的文件导入编排。"""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from backend.app.database.repository import ImportRepository
from backend.app.datasources.base import STANDARD_TABLES
from backend.app.datasources.file_import import FileImportAdapter
from backend.app.services.cleaning import CleanResult, clean_frame
from backend.app.services.mapping import MappingResult, suggest_mapping


@dataclass(frozen=True, slots=True)
class ImportReport:
    """一次文件导入的汇总结果。"""

    batch_id: int
    processed_tables: list[str]
    written_rows: int
    skipped_rows: int
    missing_tables: list[str]


class CrossBatchDuplicateError(ValueError):
    """新批次包含数据库中已存在业务键时的稳定领域错误。"""


class ImportService:
    """完成读取、自动映射校验、清洗和单事务写入。"""

    def __init__(
        self,
        engine: Engine,
        adapter: FileImportAdapter | None = None,
        repository: ImportRepository | None = None,
        batch_size: int = 1000,
    ) -> None:
        self._engine = engine
        self._adapter = adapter or FileImportAdapter()
        self._repository = repository or ImportRepository(batch_size=batch_size)

    def import_file(
        self, path: Path, target_table: str | None = None
    ) -> ImportReport:
        path = Path(path)
        frames = self._adapter.read(path, target_table)
        if not frames:
            raise ValueError("文件中未找到可导入的标准表")

        mappings = {
            table_name: suggest_mapping(table_name, list(frame.columns))
            for table_name, frame in frames.items()
        }
        _validate_mappings(mappings)

        cleaned = {
            table_name: clean_frame(
                table_name,
                frame.loc[:, list(mappings[table_name].mapping)].rename(
                    columns=mappings[table_name].mapping
                ),
            )
            for table_name, frame in frames.items()
        }
        mapping_audit = {
            table_name: result.mapping for table_name, result in mappings.items()
        }
        missing_tables = sorted(STANDARD_TABLES.difference(frames))
        quality_audit: dict[str, Any] = {
            "missing_tables": missing_tables,
            "tables": {
                table_name: {
                    **asdict(cleaned[table_name].summary),
                    "unmapped_source_columns": sorted(
                        set(frames[table_name].columns) - set(mappings[table_name].mapping)
                    ),
                }
                for table_name in frames
            },
            "relationship_anomalies": _relationship_anomalies(cleaned),
        }

        with self._engine.begin() as connection:
            batch_id = self._repository.create_batch(
                connection, path.name, list(frames), mapping_audit, quality_audit
            )

        written_rows = 0
        error_code = "database_write_failed"
        try:
            with self._engine.begin() as connection:
                for table_name, result in cleaned.items():
                    duplicate_count = self._repository.duplicate_count(
                        connection, table_name, result.frame
                    )
                    if duplicate_count:
                        error_code = "cross_batch_duplicate"
                        raise CrossBatchDuplicateError(
                            f"cross_batch_duplicate: table={table_name} count={duplicate_count}"
                        )
                written_rows = sum(
                    self._repository.write_frame(
                        connection, table_name, result.frame, batch_id
                    )
                    for table_name, result in cleaned.items()
                )
                self._repository.complete_batch(connection, batch_id, quality_audit)
        except Exception:
            with self._engine.begin() as connection:
                self._repository.fail_batch(
                    connection, batch_id, error_code, quality_audit
                )
            raise

        skipped_rows = sum(_skipped_rows(result) for result in cleaned.values())
        return ImportReport(
            batch_id=batch_id,
            processed_tables=list(frames),
            written_rows=written_rows,
            skipped_rows=skipped_rows,
            missing_tables=missing_tables,
        )


def _relationship_anomalies(cleaned: dict[str, CleanResult]) -> dict[str, dict[str, int]]:
    """检查同一文件中可判定的父子关联，不因缺表臆测异常。"""
    rules = (
        ("order_info", "user_id", "user_info", "user_id"),
        ("order_item", "order_id", "order_info", "order_id"),
        ("order_item", "product_id", "product_info", "product_id"),
        ("payment_info", "order_id", "order_info", "order_id"),
        ("refund_info", "order_id", "order_info", "order_id"),
        ("behavior_info", "user_id", "user_info", "user_id"),
        ("behavior_info", "product_id", "product_info", "product_id"),
        ("behavior_info", "visit_id", "traffic_visit", "visit_id"),
        ("ad_attribution", "order_id", "order_info", "order_id"),
        ("ad_attribution", "ad_id", "ads_info", "ad_id"),
    )
    anomalies: dict[str, dict[str, int]] = {}
    for child, child_field, parent, parent_field in rules:
        if child not in cleaned or parent not in cleaned:
            continue
        child_frame = cleaned[child].frame
        parent_frame = cleaned[parent].frame
        if child_field not in child_frame or parent_field not in parent_frame:
            continue
        populated = child_frame[child_field].dropna()
        missing = ~populated.isin(set(parent_frame[parent_field].dropna()))
        if missing.any():
            anomalies[f"{child}.{child_field}"] = {"missing_parent": int(missing.sum())}
    return anomalies


def _validate_mappings(mappings: dict[str, MappingResult]) -> None:
    errors = []
    for table_name, result in mappings.items():
        if result.unmapped_required:
            errors.append(
                f"{table_name}: unmapped_required={result.unmapped_required}"
            )
        ambiguous_columns = {
            source: list(targets)
            for source, targets in result.ambiguous_columns.items()
        }
        sources_by_target: dict[str, list[str]] = {}
        for source, target in result.mapping.items():
            sources_by_target.setdefault(target, []).append(source)
        for target, sources in sources_by_target.items():
            if len(sources) > 1:
                for source in sources:
                    ambiguous_columns.setdefault(source, []).append(target)
        if ambiguous_columns:
            ambiguous_columns = {
                source: sorted(set(ambiguous_columns[source]))
                for source in sorted(ambiguous_columns)
            }
            errors.append(
                f"{table_name}: ambiguous_columns={ambiguous_columns}"
            )
    if errors:
        raise ValueError("自动字段映射无法确认: " + "; ".join(errors))


def _skipped_rows(result: CleanResult) -> int:
    return result.summary.skipped + result.summary.deduplicated
