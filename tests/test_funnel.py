import pandas as pd

from backend.app.analytics.funnel import build_funnel_report
from backend.app.services.cleaning import clean_frame


def test_behavior_funnel_cleaning_and_report_preserve_page_funnel_semantics():
    cleaned = clean_frame(
        "behavior_funnel",
        pd.DataFrame(
            [
                {"new_user": "1", "age": "20", "source": "Direct", "total_pages_visited": "5", "home_page": "1", "listing_page": "1", "product_page": "1", "payment_page": "1", "confirmation_page": "1"},
                {"new_user": "0", "age": "30", "source": "Seo", "total_pages_visited": "3", "home_page": "1", "listing_page": "1", "product_page": "1", "payment_page": "0", "confirmation_page": "0"},
            ]
        ),
    )

    report = build_funnel_report(cleaned.frame)

    assert report["visitors"] == 2
    assert report["new_user_ratio"] == 0.5
    assert [stage["visitors"] for stage in report["funnel"]] == [2, 2, 2, 1, 1]
    assert report["source_conversion"] == [
        {"dimension": "Direct", "visitors": 1, "confirmation_rate": 1.0},
        {"dimension": "Seo", "visitors": 1, "confirmation_rate": 0.0},
    ]
