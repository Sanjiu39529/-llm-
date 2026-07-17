"""可审计的文件导入编排。"""

from dataclasses import asdict, dataclass
from pathlib import Path

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


class ImportService:
    """完成读取、自动映射校验、清洗和单事务写入。"""

    def __init__(
        self,
        engine: Engine,
        adapter: FileImportAdapter | None = None,
        repository: ImportRepository | None = None,
    ) -> None:
        self._engine = engine
        self._adapter = adapter or FileImportAdapter()
        self._repository = repository or ImportRepository()

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
        quality_audit = {
            table_name: asdict(result.summary) for table_name, result in cleaned.items()
        }

        with self._engine.begin() as connection:
            batch_id = self._repository.create_batch(
                connection, path.name, list(frames), mapping_audit
            )
            written_rows = sum(
                self._repository.write_frame(
                    connection, table_name, result.frame, batch_id
                )
                for table_name, result in cleaned.items()
            )
            self._repository.complete_batch(connection, batch_id, quality_audit)

        skipped_rows = sum(_skipped_rows(result) for result in cleaned.values())
        return ImportReport(
            batch_id=batch_id,
            processed_tables=list(frames),
            written_rows=written_rows,
            skipped_rows=skipped_rows,
            missing_tables=sorted(STANDARD_TABLES.difference(frames)),
        )


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
