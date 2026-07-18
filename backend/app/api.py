"""FastAPI application exposing the existing import, analysis and Agent workflows."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import create_engine

from backend.app.agents.supervisor import EcommerceSupervisor
from backend.app.analytics.config import MetricConfig
from backend.app.analytics.funnel import build_funnel_report
from backend.app.config import Settings
from backend.app.database.analysis_repository import AnalysisRepository
from backend.app.services.import_service import ImportService


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class AnalysisRequest(BaseModel):
    tables: dict[str, list[dict[str, Any]]]
    start: datetime
    end: datetime


def create_app(
    supervisor: EcommerceSupervisor | None = None,
    table_loader: Callable[[], Mapping[str, pd.DataFrame]] | None = None,
) -> FastAPI:
    app = FastAPI(title="电商智能数据分析助手", version="0.1.0")
    agent = supervisor or EcommerceSupervisor()

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
                "knowledge": result.knowledge,
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
        return jsonable_encoder({"report": result.report, "trace": result.trace})

    @app.get("/api/reports")
    def report_from_database(start: datetime, end: datetime) -> dict[str, Any]:
        tables = table_loader() if table_loader else _load_database_tables()
        result = agent.run("分析请求", tables=tables, start=start, end=end, config=MetricConfig())
        if result.error:
            raise HTTPException(status_code=422, detail=result.error)
        return jsonable_encoder({"report": result.report, "trace": result.trace})

    @app.get("/api/funnels")
    def funnel_from_database() -> dict[str, Any]:
        tables = table_loader() if table_loader else _load_database_tables(["behavior_funnel"])
        return jsonable_encoder(build_funnel_report(tables.get("behavior_funnel")))

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
            path.write_bytes(await file.read())
            try:
                settings = Settings()
                engine = create_engine(settings.database_url)
                report = ImportService(engine, settings.import_batch_size).import_file(path, table)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            **asdict(report),
            "auto_detected": table is None,
            "analysis_recommendations": _recommend_reports(report.processed_tables),
        }

    return app


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for column in frame.columns:
        if column.endswith(("_time", "_at", "_date")):
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def _load_database_tables(table_names: list[str] | None = None) -> Mapping[str, pd.DataFrame]:
    settings = Settings()
    return AnalysisRepository().load_tables(
        create_engine(settings.database_url), table_names or None
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
