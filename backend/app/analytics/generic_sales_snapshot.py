"""任意商品销售快照的只读即时分析，不写入标准业务表。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


_FIELDS = {
    "product_id": ("id", "商品id", "商品编号"),
    "title": ("title", "商品标题", "商品名称"),
    "price": ("price", "价格", "售价"),
    "sale_count": ("sale_count", "销量", "销售量"),
    "store": ("店名", "store", "店铺", "店铺名"),
    "comment_count": ("comment_count", "评论数", "评价数"),
}


def analyze_generic_sales_snapshot(path: Path) -> dict[str, object] | None:
    frame = pd.read_csv(path, dtype=object, keep_default_na=False)
    columns = {alias: target for target, aliases in _FIELDS.items() for alias in aliases}
    mapped = {target: source for source, target in columns.items() if source in frame.columns}
    required = {"title", "price", "sale_count"}
    if not required.issubset(mapped):
        return None
    data = pd.DataFrame({target: frame[source] for target, source in mapped.items()})
    data["price"] = pd.to_numeric(data["price"], errors="coerce")
    data["sale_count"] = pd.to_numeric(data["sale_count"], errors="coerce")
    data = data.dropna(subset=["price", "sale_count"])
    data = data.loc[(data["price"] >= 0) & (data["sale_count"] >= 0)].copy()
    data["estimated_sales"] = data["price"] * data["sale_count"]
    top_products = data.nlargest(10, "estimated_sales")[["title", "sale_count", "estimated_sales"]].to_dict("records")
    top_stores = []
    if "store" in data:
        top_stores = data.groupby("store", dropna=False)[["sale_count", "estimated_sales"]].sum().nlargest(10, "estimated_sales").reset_index().to_dict("records")
    return {
        "kind": "generic_sales_snapshot",
        "row_count": int(len(data)),
        "metrics": {"estimated_sales": float(data["estimated_sales"].sum()), "total_sales_count": int(data["sale_count"].sum())},
        "top_products": top_products,
        "top_stores": top_stores,
        "notice": "预估销售额按已确认的 price × sale_count 计算；该文件是商品销售快照，不作为订单明细入库。",
    }
