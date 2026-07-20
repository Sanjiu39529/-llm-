"""可审计的文件导入编排。"""

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import Connection, Engine

from backend.app.database.repository import ImportRepository
from backend.app.datasources.base import STANDARD_TABLES
from backend.app.datasources.file_import import FileImportAdapter
from backend.app.services.cleaning import (
    CleanResult,
    CleanSummary,
    clean_frame,
    outlier_columns,
)
from backend.app.services.mapping import MappingResult, detect_table, suggest_mapping


@dataclass(frozen=True, slots=True)
class ImportReport:
    """一次文件导入的汇总结果。"""

    batch_id: int
    processed_tables: list[str]
    written_rows: int
    skipped_rows: int
    missing_tables: list[str]
    dataset_id: str | None = None
    reused: bool = False


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
        csv_chunk_size: int = 10000,
        max_file_size_mb: int = 100,
    ) -> None:
        if csv_chunk_size < 1:
            raise ValueError("csv_chunk_size must be positive")
        if max_file_size_mb < 1:
            raise ValueError("max_file_size_mb must be positive")
        self._engine = engine
        self._adapter = adapter or FileImportAdapter()
        self._repository = repository or ImportRepository(batch_size=batch_size)
        self._csv_chunk_size = csv_chunk_size
        self._max_file_size_bytes = max_file_size_mb * 1024 * 1024

    def import_file(
        self,
        path: Path,
        target_table: str | None = None,
        *,
        file_hash: str | None = None,
        file_size: int | None = None,
    ) -> ImportReport:
        path = Path(path)
        file_hash, file_size = _file_identity(path, file_hash, file_size)
        if file_size > self._max_file_size_bytes:
            raise ValueError(
                f"file_too_large: max_size_mb={self._max_file_size_bytes // 1024 // 1024}"
            )
        with self._engine.begin() as connection:
            existing = self._repository.find_completed_by_hash(connection, file_hash)
        if existing is not None:
            return ImportReport(
                batch_id=existing.batch_id,
                processed_tables=existing.table_names,
                written_rows=0,
                skipped_rows=existing.skipped_rows,
                missing_tables=sorted(STANDARD_TABLES.difference(existing.table_names)),
                dataset_id=existing.dataset_id,
                reused=True,
            )

        if path.suffix.lower() == ".csv":
            return self._import_csv(
                path, target_table, file_hash=file_hash, file_size=file_size
            )

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
            "relationship_anomalies": {},
        }

        with self._engine.begin() as connection:
            dataset_id = str(uuid4())
            batch_id = self._repository.create_batch(
                connection,
                path.name,
                list(frames),
                mapping_audit,
                quality_audit,
                dataset_id=dataset_id,
                file_hash=file_hash,
                file_size=file_size,
            )

        written_rows = 0
        error_code = "database_write_failed"
        try:
            with self._engine.begin() as connection:
                quality_audit["relationship_anomalies"] = _relationship_anomalies(
                    connection, self._repository, cleaned
                )
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
                skipped_rows = sum(_skipped_rows(result) for result in cleaned.values())
                self._repository.complete_batch(
                    connection,
                    batch_id,
                    quality_audit,
                    processed_rows=sum(len(frame) for frame in frames.values()),
                    written_rows=written_rows,
                    skipped_rows=skipped_rows,
                )
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
            dataset_id=dataset_id,
        )

    def _import_csv(
        self,
        path: Path,
        target_table: str | None,
        *,
        file_hash: str,
        file_size: int,
    ) -> ImportReport:
        try:
            first_chunk = next(self._adapter.iter_csv(path, self._csv_chunk_size))
        except StopIteration as exc:
            raise ValueError("文件中未找到可导入的标准表") from exc

        if target_table is None:
            detection = detect_table(list(first_chunk.columns))
            if detection.table_name is None:
                raise ValueError(
                    f"cannot_auto_identify: reason={detection.reason} "
                    f"candidates={list(detection.candidates)}"
                )
            target_table = detection.table_name
        if target_table not in STANDARD_TABLES:
            raise ValueError(f"不支持的标准表: {target_table}")

        mapping = suggest_mapping(target_table, list(first_chunk.columns))
        _validate_mappings({target_table: mapping})
        missing_tables = sorted(STANDARD_TABLES.difference({target_table}))
        quality_audit: dict[str, Any] = {
            "missing_tables": missing_tables,
            "tables": {},
            "relationship_anomalies": {},
        }
        dataset_id = str(uuid4())
        with self._engine.begin() as connection:
            batch_id = self._repository.create_batch(
                connection,
                path.name,
                [target_table],
                {target_table: mapping.mapping},
                quality_audit,
                dataset_id=dataset_id,
                file_hash=file_hash,
                file_size=file_size,
            )

        age_fill_value = self._csv_age_fill_value(path, mapping)
        total_summary = CleanSummary()
        seen_keys: set[tuple[object, ...]] = set()
        written_rows = 0
        processed_rows = 0
        error_code = "database_write_failed"
        try:
            with self._engine.begin() as connection:
                for frame in self._adapter.iter_csv(path, self._csv_chunk_size):
                    processed_rows += len(frame)
                    selected = frame.loc[:, list(mapping.mapping)].rename(
                        columns=mapping.mapping
                    )
                    result = clean_frame(
                        target_table,
                        selected,
                        age_fill_value=age_fill_value,
                        seen_keys=seen_keys,
                        mark_outliers=False,
                    )
                    _merge_summary(total_summary, result.summary)
                    _merge_relationship_anomalies(
                        quality_audit["relationship_anomalies"],
                        _relationship_anomalies(
                            connection,
                            self._repository,
                            {target_table: result},
                        ),
                    )
                    duplicate_count = self._repository.duplicate_count(
                        connection, target_table, result.frame
                    )
                    if duplicate_count:
                        error_code = "cross_batch_duplicate"
                        raise CrossBatchDuplicateError(
                            f"cross_batch_duplicate: table={target_table} "
                            f"count={duplicate_count}"
                        )
                    written_rows += self._repository.write_frame(
                        connection, target_table, result.frame, batch_id
                    )

                self._repository.mark_batch_outliers(
                    connection,
                    target_table,
                    batch_id,
                    outlier_columns(target_table, set(mapping.mapping.values())),
                )
                skipped_rows = total_summary.skipped + total_summary.deduplicated
                quality_audit["tables"][target_table] = {
                    **asdict(total_summary),
                    "unmapped_source_columns": sorted(
                        set(first_chunk.columns) - set(mapping.mapping)
                    ),
                }
                self._repository.complete_batch(
                    connection,
                    batch_id,
                    quality_audit,
                    processed_rows=processed_rows,
                    written_rows=written_rows,
                    skipped_rows=skipped_rows,
                )
        except Exception:
            with self._engine.begin() as connection:
                self._repository.fail_batch(
                    connection, batch_id, error_code, quality_audit
                )
            raise

        return ImportReport(
            batch_id=batch_id,
            processed_tables=[target_table],
            written_rows=written_rows,
            skipped_rows=skipped_rows,
            missing_tables=missing_tables,
            dataset_id=dataset_id,
        )

    def _csv_age_fill_value(
        self, path: Path, mapping: MappingResult
    ) -> int | None:
        source_age = next(
            (source for source, target in mapping.mapping.items() if target == "age"),
            None,
        )
        if source_age is None:
            return None
        total = Decimal(0)
        count = 0
        for frame in self._adapter.iter_csv(path, self._csv_chunk_size):
            ages = pd.to_numeric(frame[source_age], errors="coerce")
            valid = ages.notna() & ages.between(1, 100) & ages.mod(1).eq(0)
            total += sum(Decimal(str(value)) for value in ages.loc[valid])
            count += int(valid.sum())
        if count == 0:
            return None
        return int((total / count).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _file_identity(
    path: Path, file_hash: str | None, file_size: int | None
) -> tuple[str, int]:
    if file_hash is not None and file_size is not None:
        return file_hash, file_size
    digest = hashlib.sha256()
    measured_size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            measured_size += len(chunk)
    return file_hash or digest.hexdigest(), file_size if file_size is not None else measured_size


def _merge_summary(target: CleanSummary, source: CleanSummary) -> None:
    target.skipped += source.skipped
    target.deduplicated += source.deduplicated
    target.invalid += source.invalid
    target.unknown_values += source.unknown_values
    for column, count in source.filled.items():
        target.filled[column] = target.filled.get(column, 0) + count
    for column, reasons in source.reasons.items():
        for reason, count in reasons.items():
            target.record(column, reason, count)


def _merge_relationship_anomalies(
    target: dict[str, dict[str, int]],
    source: dict[str, dict[str, int]],
) -> None:
    for relationship, counts in source.items():
        accumulated = target.setdefault(relationship, {})
        for reason, count in counts.items():
            accumulated[reason] = accumulated.get(reason, 0) + count


def _relationship_anomalies(
    connection: Connection,
    repository: ImportRepository,
    cleaned: dict[str, CleanResult],
) -> dict[str, dict[str, int]]:
    """用本批父键与数据库父键的并集检查关联异常。"""
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
        if child not in cleaned:
            continue
        child_frame = cleaned[child].frame
        if child_field not in child_frame:
            continue
        populated = child_frame[child_field].dropna()
        batch_parent_values: set[Any] = set()
        if parent in cleaned and parent_field in cleaned[parent].frame:
            batch_parent_values.update(cleaned[parent].frame[parent_field].dropna())
        database_parent_values = repository.existing_values(
            connection,
            parent,
            parent_field,
            set(populated) - batch_parent_values,
        )
        known_parent_values = batch_parent_values | database_parent_values
        missing = ~populated.isin(known_parent_values)
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
