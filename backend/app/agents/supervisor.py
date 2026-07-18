"""用 LangGraph 编排安全查询与指标分析工具。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, TypedDict

import pandas as pd
from langgraph.graph import END, START, StateGraph

from backend.app.analytics.config import MetricConfig
from backend.app.analytics.report import build_analysis_report
from backend.app.nl2sql.service import (
    Nl2SqlService,
    QueryResult,
    ReadonlySqlExecutor,
    SqlGenerator,
    SqlGuardError,
)


class AgentState(TypedDict, total=False):
    question: str
    tables: Mapping[str, pd.DataFrame]
    start: datetime
    end: datetime
    config: MetricConfig
    route: str
    report: dict[str, object]
    query_result: QueryResult
    answer: str
    error: str
    trace: list[str]


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    route: str
    answer: str | None
    report: dict[str, object] | None
    query_result: QueryResult | None
    error: str | None
    trace: tuple[str, ...]


class EcommerceSupervisor:
    """将问题路由到固定口径分析或已受保护的 SQL 查询工具。"""

    def __init__(
        self,
        generator: SqlGenerator | None = None,
        executor: ReadonlySqlExecutor | None = None,
        max_rows: int = 1000,
    ) -> None:
        self._generator = generator
        self._executor = executor
        self._sql_service = Nl2SqlService(max_rows)
        self._graph = self._build_graph()

    def run(
        self,
        question: str,
        tables: Mapping[str, pd.DataFrame] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        config: MetricConfig | None = None,
    ) -> AgentRunResult:
        state = self._graph.invoke(
            {
                "question": question,
                "tables": tables,
                "start": start,
                "end": end,
                "config": config or MetricConfig(),
                "trace": [],
            }
        )
        return AgentRunResult(
            route=state["route"],
            answer=state.get("answer"),
            report=state.get("report"),
            query_result=state.get("query_result"),
            error=state.get("error"),
            trace=tuple(state.get("trace", [])),
        )

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("supervisor", self._supervisor_node)
        graph.add_node("analysis_report", self._analysis_node)
        graph.add_node("safe_query", self._query_node)
        graph.add_edge(START, "supervisor")
        graph.add_conditional_edges(
            "supervisor", self._route, {"analysis": "analysis_report", "query": "safe_query"}
        )
        graph.add_edge("analysis_report", END)
        graph.add_edge("safe_query", END)
        return graph.compile()

    @staticmethod
    def _supervisor_node(state: AgentState) -> AgentState:
        question = state.get("question", "").strip()
        route = "query" if any(token in question.lower() for token in ("sql", "原始", "明细")) else "analysis"
        return {"route": route, "trace": [*state.get("trace", []), f"supervisor:{route}"]}

    @staticmethod
    def _route(state: AgentState) -> str:
        return state["route"]

    @staticmethod
    def _analysis_node(state: AgentState) -> AgentState:
        if state.get("tables") is None or state.get("start") is None or state.get("end") is None:
            return {
                "error": "analysis_inputs_required",
                "trace": [*state["trace"], "tool:analysis_report"],
            }
        report = build_analysis_report(
            state["tables"], state["start"], state["end"], state["config"]
        )
        return {
            "report": report,
            "answer": "已完成统一指标、异常与报告分析。",
            "trace": [*state["trace"], "tool:analysis_report"],
        }

    def _query_node(self, state: AgentState) -> AgentState:
        if self._generator is None or self._executor is None:
            return {
                "error": "nl2sql_not_configured",
                "trace": [*state["trace"], "tool:safe_query"],
            }
        try:
            prepared = self._sql_service.prepare(state["question"], self._generator)
            result = self._executor.execute_prepared(prepared)
        except (SqlGuardError, ValueError):
            return {
                "error": "nl2sql_rejected",
                "trace": [*state["trace"], "tool:safe_query"],
            }
        return {
            "query_result": result,
            "answer": "已执行通过安全校验的只读查询。",
            "trace": [*state["trace"], "tool:safe_query"],
        }
