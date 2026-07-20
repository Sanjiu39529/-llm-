"""根据用户问题选择已有、可计算的图表，不改变任何指标口径。"""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Protocol
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field


_QUESTION_CHARTS = (
    (("趋势", "环比", "同比", "gmv", "销售", "营收", "订单", "退款"), "sales_overview"),
    (("渠道", "流量", "uv", "pv", "访客"), "traffic_overview"),
    (("商品", "品类", "销量", "排行"), "product_ranking"),
    (("投放", "广告", "roi", "ctr", "cpc", "cpm"), "ad_efficiency"),
)


class AnalysisPlan(BaseModel):
    """LLM 仅可提交的展示与建议计划，数值计算不在此模型内。"""

    selected_chart_keys: list[str] = Field(default_factory=list, max_length=4)
    reasoning_summary: str = Field(min_length=1, max_length=240)
    business_suggestions: list[str] = Field(default_factory=list, max_length=3)


class AnalysisPlanner(Protocol):
    def plan(self, question: str, context: Mapping[str, object]) -> AnalysisPlan: ...


class OpenAICompatibleAnalysisPlanner:
    """只向 LLM 提供聚合结论和图表白名单，绝不传递原始明细。"""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    def plan(self, question: str, context: Mapping[str, object]) -> AnalysisPlan:
        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是受限电商分析规划器。只能从给出的聚合结论、可用图表和数据限制中选择图表并给出行动建议。"
                        "禁止计算或编造任何数字、指标、字段、SQL、图表键或数据事实。"
                        "只输出 JSON：selected_chart_keys、reasoning_summary、business_suggestions。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"question": question, "analysis_context": context},
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        request = Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=20) as response:  # nosec B310: URL is local config.
            body = json.loads(response.read().decode("utf-8"))
        try:
            content = str(body["choices"][0]["message"]["content"]).strip()
            return AnalysisPlan.model_validate_json(content.removeprefix("```json").removesuffix("```").strip())
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("llm_response_invalid_analysis_plan") from exc


def select_chart_keys(question: str, charts: Mapping[str, object]) -> dict[str, object]:
    """返回最多四张与问题相关且数据可用的图表键。"""
    normalized = question.lower()
    matched = [
        chart_key
        for keywords, chart_key in _QUESTION_CHARTS
        if any(keyword in normalized for keyword in keywords)
    ]
    available = [
        key for key, chart in charts.items()
        if isinstance(chart, Mapping) and chart.get("available")
    ]
    selected = [key for key in matched if key in available]
    if not selected:
        selected = available
    return {
        "selected_chart_keys": selected[:4],
        "selection_reason": "问题未指向具体维度，展示可用数据概览。"
        if not matched
        else "已按问题中的业务维度选择相关图表。",
    }


def plan_presentation(
    question: str,
    dashboard: Mapping[str, object],
    planner: AnalysisPlanner | None = None,
) -> dict[str, object]:
    """优先使用经校验的 LLM 计划；失败时无缝回退到规则计划。"""
    charts = dashboard.get("charts", {})
    fallback = select_chart_keys(question, charts if isinstance(charts, Mapping) else {})
    available = {
        key for key, chart in (charts.items() if isinstance(charts, Mapping) else ())
        if isinstance(chart, Mapping) and chart.get("available")
    }
    context = {
        "analysis_summary": dashboard.get("analysis_summary", {}),
        "available_chart_keys": sorted(available),
        "missing_dependencies": dashboard.get("missing_dependencies", []),
    }
    if planner is None:
        return {**fallback, "planner": "rules", "business_suggestions": []}
    try:
        plan = planner.plan(question, context)
        selected = [key for key in plan.selected_chart_keys if key in available]
        return {
            "selected_chart_keys": selected or fallback["selected_chart_keys"],
            "selection_reason": plan.reasoning_summary,
            "business_suggestions": plan.business_suggestions,
            "planner": "llm",
        }
    except Exception:
        return {**fallback, "planner": "rules", "business_suggestions": [], "fallback_reason": "llm_unavailable"}
