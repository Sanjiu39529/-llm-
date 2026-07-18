from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine, text

from backend.app.agents.supervisor import EcommerceSupervisor
from backend.app.analytics.config import MetricConfig
from backend.app.knowledge.retriever import MarkdownKnowledgeBase
from backend.app.nl2sql.service import ReadonlySqlExecutor


class FixedGenerator:
    def generate(self, question: str, schema_context: str) -> str:
        return "SELECT order_id FROM order_info"


class FixedKnowledgeAnswerer:
    def answer(self, question, chunks) -> str:
        return "成交 GMV 按固定口径计算。[1]"


def test_supervisor_routes_analysis_question_to_existing_report_tools():
    result = EcommerceSupervisor().run(
        "分析本期 GMV",
        tables={
            "order_info": pd.DataFrame(
                    [{"order_id": "o1", "order_time": pd.Timestamp("2026-01-01"), "order_amount": "100"}]
            )
        },
        start=datetime(2026, 1, 1),
        end=datetime(2026, 1, 2),
        config=MetricConfig(),
    )

    assert result.route == "analysis"
    assert result.report is not None
    assert result.error is None
    assert result.trace == ("supervisor:analysis", "tool:analysis_report")


def test_supervisor_returns_safe_error_when_sql_dependencies_are_not_configured():
    result = EcommerceSupervisor().run("查询原始订单 SQL")

    assert result.route == "query"
    assert result.error == "nl2sql_not_configured"


def test_supervisor_routes_sql_through_readonly_executor():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE order_info (order_id TEXT)"))
        connection.execute(text("INSERT INTO order_info VALUES ('o1')"))

    result = EcommerceSupervisor(
        generator=FixedGenerator(), executor=ReadonlySqlExecutor(engine)
    ).run("查询原始订单 SQL")

    assert result.route == "query"
    assert result.query_result is not None
    assert result.query_result.rows == (("o1",),)


def test_supervisor_routes_metric_definition_to_local_knowledge_base():
    result = EcommerceSupervisor().run("GMV 的口径是什么？")

    assert result.route == "knowledge"
    assert result.error is None
    assert result.knowledge[0].source == "knowledge/电商指标口径.md"
    assert "成交 GMV" in result.knowledge[0].content
    assert result.trace == ("supervisor:knowledge", "tool:knowledge_search")


def test_supervisor_reports_when_knowledge_base_has_no_matching_content():
    result = EcommerceSupervisor(knowledge_base=MarkdownKnowledgeBase(())).run("知识库规则")

    assert result.route == "knowledge"
    assert result.error == "knowledge_not_found"


def test_supervisor_can_use_optional_llm_only_after_local_rag_retrieval():
    result = EcommerceSupervisor(knowledge_answerer=FixedKnowledgeAnswerer()).run("GMV 的口径是什么？")

    assert result.answer == "成交 GMV 按固定口径计算。[1]"
    assert result.trace == ("supervisor:knowledge", "tool:knowledge_search", "tool:rag_answer")
