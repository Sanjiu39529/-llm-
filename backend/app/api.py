"""FastAPI application exposing the existing import, analysis and Agent workflows."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import logging
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from backend.app.agents.supervisor import EcommerceSupervisor
from backend.app.analytics.config import MetricConfig
from backend.app.analytics.funnel import build_funnel_report
from backend.app.analytics.presentation import (
    AnalysisPlanner,
    OpenAICompatibleAnalysisPlanner,
    plan_presentation,
)
from backend.app.config import Settings
from backend.app.database.analysis_repository import AnalysisRepository
from backend.app.datasources.base import STANDARD_TABLES
from backend.app.knowledge.rag_answerer import OpenAICompatibleRagAnswerer
from backend.app.services.import_service import ImportService


logger = logging.getLogger(__name__)


class UploadTooLargeError(ValueError):
    pass


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class AnalysisRequest(BaseModel):
    tables: dict[str, list[dict[str, Any]]]
    start: datetime
    end: datetime


class DashboardQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    start: datetime | None = None
    end: datetime | None = None
    context_tables: list[str] = Field(default_factory=list)
    dataset_ids: list[str] = Field(default_factory=list)


def create_app(
    supervisor: EcommerceSupervisor | None = None,
    table_loader: Callable[[], Mapping[str, pd.DataFrame]] | None = None,
    analysis_planner: AnalysisPlanner | None = None,
) -> FastAPI:
    app = FastAPI(title="电商智能数据分析助手", version="0.1.0")
    agent = supervisor or _configured_supervisor()
    planner = analysis_planner or _configured_analysis_planner()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/ask")
    def ask(request: AskRequest) -> dict[str, Any]:
        result = agent.run(request.question)
        return jsonable_encoder(
            {
                "route": result.route,
                "answer": result.answer,
                "error": result.error,
                "trace": result.trace,
                "run_id": result.run_id,
                "trace_events": result.trace_events,
                "knowledge": result.knowledge,
                "citations": result.citations,
            }
        )

    @app.post("/api/dashboard/ask")
    def dashboard_question(request: DashboardQuestionRequest) -> dict[str, Any]:
        """Route a natural-language question to a fixed, display-safe dashboard."""
        context_tables = [name for name in request.context_tables if name in STANDARD_TABLES]
        intent = _dashboard_intent(request.question, context_tables)
        if intent == "knowledge":
            result = agent.run(f"知识库解释：{request.question}")
            return jsonable_encoder(
                {
                    "intent": intent,
                    "answer": result.answer,
                    "error": result.error,
                    "knowledge": result.knowledge,
                    "trace": result.trace,
                    "run_id": result.run_id,
                    "trace_events": result.trace_events,
                    "citations": result.citations,
                }
            )

        if intent == "funnel":
            funnel = (
                build_funnel_report(table_loader().get("behavior_funnel"))
                if table_loader
                else _load_funnel_report(request.dataset_ids)
            )
            answer = (
                "已根据用户行为数据生成页面漏斗与来源转化看板。"
                if funnel["available"]
                else "尚未导入可用于用户行为漏斗的数据。请先上传行为分析 CSV 或 Excel。"
            )
            return jsonable_encoder({"intent": intent, "answer": answer, "dashboard": funnel})

        end = request.end or datetime.now()
        start = request.start or end - timedelta(days=30)
        if start >= end:
            raise HTTPException(status_code=422, detail="start_must_be_before_end")
        config = MetricConfig()
        tables = (
            table_loader()
            if table_loader
            else _load_database_tables(
                start=start,
                end=end,
                dataset_ids=request.dataset_ids,
                config=config,
            )
        )
        report = agent.run(
            "分析请求", tables=tables, start=start, end=end, config=config
        )
        if report.error:
            raise HTTPException(status_code=422, detail=report.error)
        dashboard = dict(report.report or {})
        dashboard["presentation"] = plan_presentation(request.question, dashboard, planner)
        summary = dashboard.get("analysis_summary", {})
        return jsonable_encoder(
            {
                "intent": intent,
                "answer": summary.get("overview", "已按固定指标口径生成经营分析看板。"),
                "dashboard": dashboard,
                "trace": report.trace,
                "run_id": report.run_id,
                "trace_events": report.trace_events,
                "period": {"start": start, "end": end},
            }
        )

    @app.post("/api/analysis")
    def analysis(request: AnalysisRequest) -> dict[str, Any]:
        tables = {name: _frame(rows) for name, rows in request.tables.items()}
        result = agent.run(
            "分析请求", tables=tables, start=request.start, end=request.end, config=MetricConfig()
        )
        if result.error:
            raise HTTPException(status_code=422, detail=result.error)
        return jsonable_encoder(
            {
                "report": result.report,
                "trace": result.trace,
                "run_id": result.run_id,
                "trace_events": result.trace_events,
            }
        )

    @app.get("/api/reports")
    def report_from_database(start: datetime, end: datetime) -> dict[str, Any]:
        config = MetricConfig()
        tables = (
            table_loader()
            if table_loader
            else _load_database_tables(start=start, end=end, config=config)
        )
        result = agent.run("分析请求", tables=tables, start=start, end=end, config=config)
        if result.error:
            raise HTTPException(status_code=422, detail=result.error)
        return jsonable_encoder(
            {
                "report": result.report,
                "trace": result.trace,
                "run_id": result.run_id,
                "trace_events": result.trace_events,
            }
        )

    @app.get("/api/funnels")
    def funnel_from_database() -> dict[str, Any]:
        report = (
            build_funnel_report(table_loader().get("behavior_funnel"))
            if table_loader
            else _load_funnel_report()
        )
        return jsonable_encoder(report)

    @app.post("/api/imports")
    async def import_data(
        file: UploadFile = File(...), table: str | None = Form(default=None)
    ) -> dict[str, Any]:
        filename = Path(file.filename or "upload").name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".xlsx"}:
            raise HTTPException(status_code=400, detail="unsupported_file_type")
        with TemporaryDirectory() as directory:
            path = Path(directory) / filename
            try:
                settings = Settings()
                file_hash, file_size = await _save_upload(
                    file,
                    path,
                    max_bytes=settings.import_max_file_size_mb * 1024 * 1024,
                )
                engine = create_engine(settings.database_url)
                report = ImportService(
                    engine,
                    batch_size=settings.import_batch_size,
                    csv_chunk_size=settings.import_csv_chunk_size,
                    max_file_size_mb=settings.import_max_file_size_mb,
                ).import_file(
                    path, table, file_hash=file_hash, file_size=file_size
                )
            except UploadTooLargeError as exc:
                raise HTTPException(status_code=413, detail=str(exc)) from exc
            except ValueError as exc:
                recovery = _import_recovery(str(exc))
                if recovery is not None:
                    return recovery
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except SQLAlchemyError as exc:
                logger.exception("导入时数据库不可用或数据表缺失")
                return {
                    "status": "database_requires_attention",
                    "message": "文件已接收，但数据库连接或数据表尚未就绪。请运行数据库初始化后重新发送。",
                }
            except Exception:
                logger.exception("导入出现未预期异常")
                return {
                    "status": "import_requires_attention",
                    "message": "文件已接收，但本次导入没有完成。请确认文件可正常打开、首行为字段名，然后重新发送。",
                }
        return {
            **asdict(report),
            "auto_detected": table is None,
            "analysis_recommendations": _recommend_reports(report.processed_tables),
        }

    return app


async def _save_upload(
    file: UploadFile, path: Path, *, max_bytes: int
) -> tuple[str, int]:
    """Stream an upload to disk while calculating its stable content identity."""
    digest = hashlib.sha256()
    file_size = 0
    with path.open("wb") as destination:
        while chunk := await file.read(1024 * 1024):
            destination.write(chunk)
            digest.update(chunk)
            file_size += len(chunk)
            if file_size > max_bytes:
                raise UploadTooLargeError(
                    f"file_too_large: max_size_mb={max_bytes // 1024 // 1024}"
                )
    return digest.hexdigest(), file_size


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for column in frame.columns:
        if column.endswith(("_time", "_at", "_date")):
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def _configured_supervisor() -> EcommerceSupervisor:
    """LLM is optional; the deterministic local RAG path always remains available."""
    try:
        settings = Settings()
    except ValidationError:
        return EcommerceSupervisor()
    if all((settings.llm_base_url, settings.llm_api_key, settings.llm_model)):
        return EcommerceSupervisor(
            knowledge_answerer=OpenAICompatibleRagAnswerer(
                settings.llm_base_url, settings.llm_api_key, settings.llm_model
            )
        )
    return EcommerceSupervisor()


def _configured_analysis_planner() -> AnalysisPlanner | None:
    try:
        settings = Settings()
    except ValidationError:
        return None
    base_url = getattr(settings, "llm_base_url", None)
    api_key = getattr(settings, "llm_api_key", None)
    model = getattr(settings, "llm_model", None)
    if all((base_url, api_key, model)):
        return OpenAICompatibleAnalysisPlanner(
            base_url, api_key, model
        )
    return None


def _import_recovery(detail: str) -> dict[str, Any] | None:
    """Turn uncertain structure into a guided next step, never a false import success."""
    if detail.startswith("cannot_auto_identify"):
        return {
            "status": "needs_table_confirmation",
            "message": "文件已读取，但无法安全判断业务数据类型。请选择最接近的数据类型后继续导入。",
            "available_tables": sorted(STANDARD_TABLES),
        }
    if detail == "文件中未找到可导入的标准表":
        return {
            "status": "needs_csv_confirmation",
            "message": "Excel 已读取，但没有可安全识别的工作表。请将需要导入的一个工作表另存为 CSV 后重新发送。",
        }
    if detail.startswith("cross_batch_duplicate"):
        match = re.search(r"table=([a-z_]+)", detail)
        table_name = match.group(1) if match else None
        return {
            "status": "already_imported",
            "message": "该文件中的业务数据已经存在，无需重复写入；可以直接继续提问分析。",
            "processed_tables": [table_name] if table_name in STANDARD_TABLES else [],
            "written_rows": 0,
        }
    return None


def _dashboard_intent(question: str, context_tables: list[str] | None = None) -> str:
    """Classify only the presentation path; business metric formulas stay unchanged."""
    normalized = question.lower()
    if any(word in normalized for word in ("口径", "定义", "规则", "怎么算", "如何计算", "是什么")):
        return "knowledge"
    if any(word in normalized for word in ("漏斗", "用户行为", "页面", "来源", "渠道转化", "设备")):
        return "funnel"
    if any(
        word in normalized
        for word in ("gmv", "销售", "营收", "订单", "退款", "roi", "投放", "流量", "转化", "客单")
    ):
        return "analysis"
    tables = set(context_tables or [])
    if "behavior_funnel" in tables:
        return "funnel"
    if tables:
        return "analysis"
    return "knowledge"


def _load_database_tables(
    table_names: list[str] | None = None,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    dataset_ids: list[str] | None = None,
    config: MetricConfig | None = None,
) -> Mapping[str, pd.DataFrame]:
    settings = Settings()
    metric_config = config or MetricConfig()
    engine = create_engine(settings.database_url)
    repository = AnalysisRepository()
    tables = repository.load_tables(
        engine,
        table_names or None,
        start=start,
        end=end,
        history_days=metric_config.customer_history_days,
        attribution_lookahead_days=metric_config.roi_lookback_days,
        dataset_ids=dataset_ids,
    )
    if start is not None and end is not None and (
        table_names is None or "order_info" in table_names
    ):
        baseline_start = start - timedelta(days=metric_config.customer_history_days)
        tables["_daily_gmv"] = repository.load_daily_gmv(
            engine, baseline_start, end, dataset_ids
        )
    return tables


def _load_funnel_report(dataset_ids: list[str] | None = None) -> dict[str, object]:
    settings = Settings()
    return AnalysisRepository().load_funnel_report(
        create_engine(settings.database_url), dataset_ids
    )


def _recommend_reports(table_names: list[str]) -> list[str]:
    tables = set(table_names)
    recommendations = ["数据质量摘要：已生成，包含清洗、跳过与字段映射审计。"]
    if "behavior_funnel" in tables:
        recommendations.append("用户行为漏斗：可立即查看页面漏斗、来源与设备转化。")
    if "order_info" in tables:
        recommendations.append("销售报告：选择统计区间后可计算 GMV 与订单相关指标。")
    if "traffic_visit" in tables:
        recommendations.append("流量报告：可计算 UV、PV 与渠道流量。")
    if "ads_info" in tables:
        recommendations.append("投放报告：可计算 CTR、CPC、CPM 和 ROI（需归因数据支持）。")
    return recommendations


app = create_app()
