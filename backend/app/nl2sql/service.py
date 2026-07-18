"""将 LLM 候选 SQL 约束为可审计的只读查询。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Protocol

from sqlalchemy import Engine, text

from backend.app.datasources.base import TABLE_CONTRACTS


class SqlGuardError(ValueError):
    """候选 SQL 不满足只读安全约束。"""


class SqlGenerator(Protocol):
    """可替换的 LLM/规则引擎 SQL 生成接口。"""

    def generate(self, question: str, schema_context: str) -> str:
        """根据问题与可查询 schema 返回一条 SQL。"""


@dataclass(frozen=True, slots=True)
class PreparedSql:
    sql: str
    parameters: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]


_FORBIDDEN_WORDS = frozenset(
    {
        "alter", "benchmark", "call", "create", "delete", "drop", "grant",
        "insert", "into", "load_file", "lock", "outfile", "replace", "revoke",
        "set", "sleep", "truncate", "update", "use",
    }
)
_TOKEN = re.compile(
    r"`[^`]+`|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[A-Za-z_][A-Za-z0-9_$]*|\d+|[(),.*=<>!+\-/]"
)


class Nl2SqlService:
    """构造 schema 提示词并校验生成器返回的 SQL。"""

    def __init__(self, max_rows: int = 1000) -> None:
        if max_rows < 1:
            raise ValueError("max_rows must be positive")
        self._max_rows = max_rows

    def prepare(self, question: str, generator: SqlGenerator) -> PreparedSql:
        if not question.strip():
            raise ValueError("question must not be blank")
        candidate = generator.generate(question, self.schema_context())
        return validate_readonly_sql(candidate, self._max_rows)

    @staticmethod
    def schema_context() -> str:
        lines = ["只允许查询以下表和字段；只输出一条 SELECT 或 WITH ... SELECT SQL："]
        for table_name in sorted(TABLE_CONTRACTS):
            fields = sorted(TABLE_CONTRACTS[table_name].aliases)
            lines.append(f"- {table_name}: {', '.join(fields)}")
        return "\n".join(lines)


class ReadonlySqlExecutor:
    """执行已通过白名单校验的 SQL；数据库账户仍必须设置为只读。"""

    def __init__(self, engine: Engine, max_rows: int = 1000) -> None:
        self._engine = engine
        self._max_rows = max_rows

    def execute(self, sql: str) -> QueryResult:
        prepared = validate_readonly_sql(sql, self._max_rows)
        return self.execute_prepared(prepared)

    def execute_prepared(self, prepared: PreparedSql) -> QueryResult:
        with self._engine.connect() as connection:
            result = connection.execute(text(prepared.sql), dict(prepared.parameters))
            rows = tuple(tuple(row) for row in result)
            return QueryResult(tuple(result.keys()), rows)


def validate_readonly_sql(sql: str, max_rows: int = 1000) -> PreparedSql:
    """仅允许访问标准业务表的一条只读 SQL，并强制限制返回行数。"""
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    normalized = sql.strip()
    if not normalized:
        raise SqlGuardError("empty_sql")
    if any(marker in normalized for marker in ("--", "#", "/*", "*/")):
        raise SqlGuardError("comments_not_allowed")
    if normalized.endswith(";"):
        normalized = normalized[:-1].rstrip()
    if ";" in normalized:
        raise SqlGuardError("multiple_statements_not_allowed")

    tokens = _tokenize(normalized)
    words = [token.lower() for token in tokens if _is_word(token)]
    if not words or words[0] not in {"select", "with"}:
        raise SqlGuardError("read_query_required")
    if _FORBIDDEN_WORDS.intersection(words):
        raise SqlGuardError("forbidden_keyword")
    _validate_tables(tokens)

    if "limit" in words:
        index = words.index("limit")
        if index + 1 >= len(words) or not words[index + 1].isdigit():
            raise SqlGuardError("numeric_limit_required")
        if int(words[index + 1]) > max_rows:
            raise SqlGuardError("limit_exceeds_max_rows")
        return PreparedSql(normalized, {})
    return PreparedSql(f"{normalized} LIMIT :_nl2sql_limit", {"_nl2sql_limit": max_rows})


def _tokenize(sql: str) -> list[str]:
    tokens = _TOKEN.findall(sql)
    compact = "".join(tokens)
    source = re.sub(r"\s+", "", sql)
    if compact != source:
        raise SqlGuardError("unsupported_sql_syntax")
    return tokens


def _validate_tables(tokens: list[str]) -> None:
    allowed = set(TABLE_CONTRACTS)
    ctes = _cte_names(tokens)
    index = 0
    while index < len(tokens):
        if tokens[index].lower() not in {"from", "join"}:
            index += 1
            continue
        if index + 1 >= len(tokens):
            raise SqlGuardError("table_reference_required")
        table = tokens[index + 1]
        if table == "(":
            index += 1
            continue
        normalized = table.strip("`").lower()
        if normalized not in allowed | ctes:
            raise SqlGuardError("table_not_allowed")
        index += 2


def _cte_names(tokens: list[str]) -> set[str]:
    if not tokens or tokens[0].lower() != "with":
        return set()
    names: set[str] = set()
    index = 1
    while index + 1 < len(tokens):
        name, following = tokens[index], tokens[index + 1].lower()
        if not _is_word(name) or following != "as":
            break
        names.add(name.lower())
        index += 2
        while index < len(tokens) and tokens[index] != "(":
            index += 1
        depth = 0
        while index < len(tokens):
            depth += tokens[index] == "("
            depth -= tokens[index] == ")"
            index += 1
            if depth == 0:
                break
        if index >= len(tokens) or tokens[index] != ",":
            break
        index += 1
    return names


def _is_word(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*|\d+", token))
