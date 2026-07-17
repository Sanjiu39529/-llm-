# Phase 2 Task 3 销售与售后指标工具报告

## 实现范围

- 新增 `calculate_sales_metrics(tables, start, end)`，返回 `gmv`、`actual_sales`、`refund_amount`、`net_sales`、`average_order_value`、`item_unit_price`、`refund_rate`、`return_rate`。
- 所有订单、付款和退款时间窗口使用左闭右开区间 `[start, end)`。
- 支付成功状态仅接受 `success`、`paid`、`支付成功`、`已支付`；退款成功状态仅接受 `success`、`refunded`、`退款成功`、`已退款`，匹配前去除首尾空白并规范英文大小写。
- 支付、累计退款、周期退款和商品件数分别先按 `order_id` 聚合，不进行会放大金额或件数的一对多连接。
- 实际销售额扣除优惠券、促销折扣和运费，缺失折扣列按 0；截至 `end` 的累计成功退款达到成功付款金额时剔除整单。
- 状态列缺失或相关记录状态全空时，依赖成功状态的指标以稳定 reason 降级；GMV 独立计算。缺 `refund_quantity` 只禁用退货率。

## TDD 证据

1. 先创建 `tests/test_sales_tool.py`，覆盖正常/部分退款/全额退款、失败状态、零分母、支付与退款状态缺失或全空、缺 `refund_quantity`、边界时间和一对多数据。
2. RED：`.venv\Scripts\python.exe -m pytest tests/test_sales_tool.py -q` 在收集阶段失败，错误为 `ModuleNotFoundError: No module named 'backend.app.tools'`。
3. GREEN：完成最小实现后，同一命令输出 `9 passed`。

## 验证结果

- 定向测试：`.venv\Scripts\python.exe -m pytest tests/test_sales_tool.py tests/test_metric_common.py -q` → `32 passed`。
- 全量回归：`.venv\Scripts\python.exe -m pytest -q` → `103 passed`。
- 编译检查：`.venv\Scripts\python.exe -m compileall -q backend/app/tools` → exit 0。
- 行宽检查：新增 Python 文件无超过 88 字符的行。
- 差异检查：`git diff --cached --check` → 无输出。

## 自审结论

- 金额口径、成功状态白名单、累计退款与周期退款的不同时间范围均有直接测试。
- 全额退款发生在周期开始前的样例仍会剔除实际销售额，但不会计入本周期退款金额。
- 退款率使用周期成功退款订单去重数/周期成功付款订单去重数；退货率使用周期成功退款件数/周期成功付款订单关联售出件数。
- 未改动其他业务工具、数据库迁移或学习指南。

## 环境说明

仓库 `.venv313` 的解释器入口指向已失效的 WindowsApps Python 3.13 路径，`py -3.13` 同样无法创建进程。本次使用仓库可用的 Python 3.10 `.venv` 完成全部测试；Python 3.13 需修复本机解释器后复验。
