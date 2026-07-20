from backend.app.analytics.presentation import select_chart_keys


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
