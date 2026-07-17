"""Advertising spend, efficiency, attribution, and channel metrics."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Mapping

import pandas as pd

from backend.app.analytics.common import filter_period, quantize_money, safe_ratio
from backend.app.analytics.models import MetricResult


_CHANNELS = ("自然搜索", "推荐", "付费投放", "直播", "短视频", "活动流量")
_ATTRIBUTION_TYPES = frozenset({"direct", "indirect"})


def calculate_ad_metrics(
    tables: Mapping[str, pd.DataFrame],
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
    lookback_days: int = 7,
) -> dict[str, MetricResult | dict]:
    """Calculate advertising metrics for the left-closed period ``[start, end)``."""
    ads, ads_reason = _period_ads(tables.get("ads_info"), start, end)
    cost_reason = ads_reason or _missing(ads, "cost")
    impression_reason = ads_reason or _missing(ads, "impressions")
    click_reason = ads_reason or _missing(ads, "clicks")

    cost = _sum_decimal(ads["cost"]) if cost_reason is None else Decimal("0")
    impressions = (
        _sum_decimal(ads["impressions"])
        if impression_reason is None
        else Decimal("0")
    )
    clicks = _sum_decimal(ads["clicks"]) if click_reason is None else Decimal("0")

    spend = _money_result("spend", cost, cost_reason)
    ctr = _ratio_result("ctr", clicks, impressions, click_reason or impression_reason)
    cpm = _ratio_result(
        "cpm", cost, impressions, cost_reason or impression_reason, Decimal("1000")
    )
    cpc = _ratio_result("cpc", cost, clicks, cost_reason or click_reason)

    attributions, attribution_reason, unknown_types = _attributions(
        tables.get("ad_attribution")
    )
    ad_id_reason = ads_reason or _missing(ads, "ad_id", "missing_ad_id")
    roi_reason = cost_reason or ad_id_reason or attribution_reason
    direct_amount = indirect_amount = seven_day_amount = Decimal("0")
    if roi_reason is None:
        period_ad_ids = set(ads["ad_id"].dropna())
        period_attributions = filter_period(
            attributions, "attributed_at", start, end
        )
        period_attributions = period_attributions.loc[
            period_attributions["ad_id"].isin(period_ad_ids)
        ]
        direct_amount = _sum_decimal(
            period_attributions.loc[
                period_attributions["_attribution_type"].eq("direct"),
                "attribution_amount",
            ]
        )
        indirect_amount = _sum_decimal(
            period_attributions.loc[
                period_attributions["_attribution_type"].eq("indirect"),
                "attribution_amount",
            ]
        )
        seven_day_amount = _seven_day_amount(
            ads, attributions, lookback_days
        )

    channels, unknown_channels = _channel_results(ads, ads_reason)
    return {
        "spend": spend,
        "ctr": ctr,
        "cpm": cpm,
        "cpc": cpc,
        "direct_roi": _ratio_result("direct_roi", direct_amount, cost, roi_reason),
        "indirect_roi": _ratio_result(
            "indirect_roi", indirect_amount, cost, roi_reason
        ),
        "roi_7d": _ratio_result("roi_7d", seven_day_amount, cost, roi_reason),
        "channels": channels,
        "quality_warnings": {
            "unknown_channels": unknown_channels,
            "unknown_attribution_types": unknown_types,
        },
    }


def _period_ads(
    ads: pd.DataFrame | None,
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
) -> tuple[pd.DataFrame, str | None]:
    if ads is None:
        return pd.DataFrame(), "missing_ads_info"
    if "ad_date" not in ads.columns:
        return ads.iloc[0:0].copy(), "missing_ad_date"
    return filter_period(ads, "ad_date", start, end), None


def _attributions(
    frame: pd.DataFrame | None,
) -> tuple[pd.DataFrame, str | None, list[str]]:
    if frame is None:
        return pd.DataFrame(), "missing_ad_attribution", []
    for column in ("ad_id", "attributed_at", "attribution_amount"):
        if column not in frame.columns:
            reason = "missing_attribution_ad_id" if column == "ad_id" else f"missing_{column}"
            return frame.iloc[0:0].copy(), reason, []
    result = frame.copy()
    if "attribution_type" not in result.columns:
        normalized = pd.Series("direct", index=result.index, dtype="object")
    else:
        normalized = result["attribution_type"].map(_normalize)
        normalized = normalized.mask(normalized.eq(""), "direct")
    unknown_mask = ~normalized.isin(_ATTRIBUTION_TYPES)
    unknown = sorted(set(normalized.loc[unknown_mask]))
    result["_attribution_type"] = normalized
    return result.loc[~unknown_mask].copy(), None, unknown


def _seven_day_amount(
    ads: pd.DataFrame, attributions: pd.DataFrame, lookback_days: int
) -> Decimal:
    windows: dict[object, list[object]] = {}
    for ad_id, group in ads.dropna(subset=["ad_id"]).groupby("ad_id", sort=False):
        windows[ad_id] = list(group["ad_date"])
    included = []
    window = timedelta(days=lookback_days + 1)
    for index, row in attributions.iterrows():
        attributed_at = row["attributed_at"]
        if pd.isna(attributed_at):
            continue
        if any(
            ad_date <= attributed_at < ad_date + window
            for ad_date in windows.get(row["ad_id"], ())
        ):
            included.append(index)
    return _sum_decimal(attributions.loc[included, "attribution_amount"])


def _channel_results(
    ads: pd.DataFrame, reason: str | None
) -> tuple[dict[str, dict[str, object]], list[str]]:
    if reason is not None:
        return {
            channel: {
                "cost": None, "impressions": None, "clicks": None,
                "available": False, "reason": reason,
            }
            for channel in _CHANNELS
        }, []
    result = {}
    for channel in _CHANNELS:
        rows = (
            ads.loc[ads["channel"].map(_normalize).eq(channel)]
            if "channel" in ads.columns
            else ads.iloc[0:0]
        )
        result[channel] = {
            "cost": quantize_money(_sum_decimal(rows["cost"])) if "cost" in rows else None,
            "impressions": _sum_decimal(rows["impressions"]) if "impressions" in rows else None,
            "clicks": _sum_decimal(rows["clicks"]) if "clicks" in rows else None,
            "available": True,
            "reason": None,
        }
    if "channel" not in ads.columns:
        return result, ["<missing>"]
    unknown = {
        _normalize(value) or "<missing>"
        for value in ads["channel"]
        if _normalize(value) not in _CHANNELS
    }
    return result, sorted(unknown)


def _normalize(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().casefold()


def _missing(
    frame: pd.DataFrame, column: str, reason: str | None = None
) -> str | None:
    return (reason or f"missing_{column}") if column not in frame.columns else None


def _sum_decimal(values: pd.Series) -> Decimal:
    return sum(
        (Decimal(str(value)) for value in values if not pd.isna(value)),
        Decimal("0"),
    )


def _money_result(name: str, value: Decimal, reason: str | None) -> MetricResult:
    if reason is not None:
        return MetricResult(name, None, False, reason)
    return MetricResult(name, quantize_money(value), True, None)


def _ratio_result(
    name: str,
    numerator: Decimal,
    denominator: Decimal,
    reason: str | None,
    scale: Decimal = Decimal("1"),
) -> MetricResult:
    if reason is not None:
        return MetricResult(name, None, False, reason)
    ratio = safe_ratio(numerator, denominator, scale=scale)
    return MetricResult(name, ratio.value, ratio.available, ratio.reason)
