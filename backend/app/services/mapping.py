"""源数据列名到标准表字段的自动映射。"""

import logging
import re
from dataclasses import dataclass

from backend.app.datasources.base import FieldMapping, TABLE_CONTRACTS


logger = logging.getLogger(__name__)
_SEPARATOR_PATTERN = re.compile(r"[\s_-]+")


@dataclass(frozen=True, slots=True)
class MappingResult:
    """自动映射结果，歧义列不自动处理以便用户确认。"""

    mapping: dict[str, str]
    unmapped_required: list[str]
    ambiguous_columns: dict[str, list[str]]


@dataclass(frozen=True, slots=True)
class TableDetection:
    """根据列名给出的可解释表识别结论。"""

    table_name: str | None
    matched_fields: tuple[str, ...]
    candidates: tuple[str, ...]
    reason: str | None


def _normalise_column_name(column_name: str) -> str:
    """去除空白、下划线和连字符后，以小写形式比较列名。"""
    return _SEPARATOR_PATTERN.sub("", column_name).lower()


def _build_alias_index(contract: FieldMapping) -> dict[str, set[str]]:
    """构建标准化别名到候选字段的索引。"""
    alias_index: dict[str, set[str]] = {}
    for field_name, aliases in contract.aliases.items():
        for alias in aliases:
            alias_index.setdefault(_normalise_column_name(alias), set()).add(field_name)
    return alias_index


def suggest_mapping(table_name: str, columns: list[str]) -> MappingResult:
    """为源列给出唯一候选的标准字段映射建议。

    Args:
        table_name: 目标标准表名称。
        columns: 文件导入适配器读取到的源列名。

    Raises:
        ValueError: 表名不在标准表契约中，或列名不是字符串时抛出。
    """
    try:
        contract = TABLE_CONTRACTS[table_name]
    except KeyError as exc:
        logger.warning("未找到标准表契约: %s", table_name)
        raise ValueError(f"不支持的标准表: {table_name}") from exc

    alias_index = _build_alias_index(contract)
    mapping: dict[str, str] = {}
    ambiguous_columns: dict[str, list[str]] = {}
    for column in columns:
        if not isinstance(column, str):
            logger.warning("列名必须为字符串: %r", column)
            raise ValueError("列名必须为字符串")
        candidates = alias_index.get(_normalise_column_name(column), set())
        if len(candidates) == 1:
            mapping[column] = next(iter(candidates))
        elif len(candidates) > 1:
            ambiguous_columns[column] = sorted(candidates)

    mapped_fields = set(mapping.values())
    unmapped_required = sorted(contract.required_fields - mapped_fields)
    return MappingResult(
        mapping=mapping,
        unmapped_required=unmapped_required,
        ambiguous_columns=ambiguous_columns,
    )


def detect_table(columns: list[str]) -> TableDetection:
    """仅在唯一候选满足必填字段且无歧义时自动识别表类型。"""
    candidates: list[tuple[str, MappingResult]] = []
    for table_name in sorted(TABLE_CONTRACTS):
        result = suggest_mapping(table_name, columns)
        if not result.unmapped_required and not result.ambiguous_columns:
            candidates.append((table_name, result))
    if not candidates:
        return TableDetection(None, (), (), "no_matching_table")
    highest_score = max(len(result.mapping) for _, result in candidates)
    winners = [(name, result) for name, result in candidates if len(result.mapping) == highest_score]
    if len(winners) != 1:
        return TableDetection(None, (), tuple(name for name, _ in winners), "ambiguous_table")
    table_name, result = winners[0]
    return TableDetection(
        table_name, tuple(sorted(result.mapping.values())), tuple(name for name, _ in candidates), None
    )
