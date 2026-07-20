from backend.app.analytics.presentation import AnalysisPlan, plan_presentation, select_chart_keys


def test_chart_selection_matches_question_and_excludes_unavailable_charts() -> None:
    plan = select_chart_keys(
        "比较渠道流量和商品销量",
        {
            "sales_overview": {"available": True},
            "traffic_overview": {"available": True},
            "product_ranking": {"available": False},
        },
    )

    assert plan["selected_chart_keys"] == ["traffic_overview"]


def test_chart_selection_uses_available_overview_when_question_is_generic() -> None:
    plan = select_chart_keys(
        "帮我分析这份数据",
        {
            "sales_overview": {"available": True},
            "traffic_overview": {"available": True},
        },
    )

    assert plan["selected_chart_keys"] == ["sales_overview", "traffic_overview"]


def test_llm_plan_is_limited_to_available_charts_and_keeps_suggestions() -> None:
    class FakePlanner:
        def plan(self, question, context):
            assert "analysis_summary" in context
            return AnalysisPlan(
                selected_chart_keys=["sales_overview", "unknown"],
                reasoning_summary="优先查看销售结果。",
                business_suggestions=["核查高价值订单的业务背景。"],
            )

    plan = plan_presentation(
        "分析销售",
        {"charts": {"sales_overview": {"available": True}}, "analysis_summary": {}},
        FakePlanner(),
    )

    assert plan["planner"] == "llm"
    assert plan["selected_chart_keys"] == ["sales_overview"]
    assert plan["business_suggestions"] == ["核查高价值订单的业务背景。"]


def test_invalid_llm_plan_falls_back_to_rules() -> None:
    class BrokenPlanner:
        def plan(self, question, context):
            raise ValueError("bad response")

    plan = plan_presentation(
        "分析销售",
        {"charts": {"sales_overview": {"available": True}}},
        BrokenPlanner(),
    )

    assert plan["planner"] == "rules"
    assert plan["selected_chart_keys"] == ["sales_overview"]
