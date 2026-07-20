"""用户画像页面漏斗的确定性统计。"""

from typing import Any

import pandas as pd


STAGES = (
    ("home_page", "首页"),
    ("listing_page", "列表页"),
    ("product_page", "商品页"),
    ("payment_page", "支付页"),
    ("confirmation_page", "确认页"),
)


def build_funnel_report(frame: pd.DataFrame | None) -> dict[str, Any]:
    """输出匿名用户画像数据可支持的页面漏斗与维度转化。"""
    if frame is None or frame.empty:
        return {"available": False, "reason": "missing_behavior_funnel"}
    stages = []
    previous: int | None = None
    for column, label in STAGES:
        visitors = _positive_count(frame, column)
        stages.append(
            {
                "stage": label,
                "visitors": visitors,
                "conversion_from_previous": None if previous is None or previous == 0 else visitors / previous,
            }
        )
        previous = visitors
    report = {
        "available": True,
        "visitors": int(len(frame)),
        "new_user_ratio": _ratio(frame.get("new_user")),
        "funnel": stages,
        "source_conversion": _conversion_by(frame, "source"),
        "device_conversion": _conversion_by(frame, "device"),
    }
    report["analysis_summary"] = _summary(report)
    return report


def _summary(report: dict[str, Any]) -> dict[str, object]:
    stages = report["funnel"]
    confirmation = next(item for item in stages if item["stage"] == "确认页")
    findings = [f"本次漏斗包含 {report['visitors']} 位匿名访客。"]
    if confirmation["conversion_from_previous"] is not None:
        findings.append(
            f"确认页访客为 {confirmation['visitors']}，相对支付页转化率为 {confirmation['conversion_from_previous']:.1%}。"
        )
    return {"overview": findings[0], "findings": findings, "limitations": []}


def _ratio(values: pd.Series | None) -> float | None:
    if values is None:
        return None
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return None if numeric.empty else float(numeric.eq(1).mean())


def _conversion_by(frame: pd.DataFrame, column: str) -> list[dict[str, object]]:
    if column not in frame:
        return []
    completed = _positive_series(frame, "confirmation_page")
    grouped = frame.assign(_completed=completed).groupby(column, dropna=False, sort=True)
    return [
        {
            "dimension": "未知" if pd.isna(name) else str(name),
            "visitors": int(len(group)),
            "confirmation_rate": float(group["_completed"].mean()),
        }
        for name, group in grouped
    ]


def _positive_count(frame: pd.DataFrame, column: str) -> int:
    return int(_positive_series(frame, column).sum())


def _positive_series(frame: pd.DataFrame, column: str) -> pd.Series:
    values = frame[column] if column in frame else pd.Series(0, index=frame.index)
    return pd.to_numeric(values, errors="coerce").fillna(0).gt(0)
