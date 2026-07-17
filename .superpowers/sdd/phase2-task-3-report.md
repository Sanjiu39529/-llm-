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

## 审查修复：局部依赖降级

Fix commit：`c7162fa fix: degrade sales metrics by dependency`

### TDD 证据

- RED 命令：`.venv\Scripts\python.exe -m pytest tests/test_sales_tool.py -q`
- RED 结果：`11 failed, 13 passed`。失败均来自缺表或缺关键列后直接索引产生的 `KeyError`；累计退款恰在 `end` 的新增边界测试已通过，证明原实现的 `.lt(end)` 正确但此前未被有效锁定。
- GREEN 命令：`.venv\Scripts\python.exe -m pytest tests/test_sales_tool.py -q`
- GREEN 结果：`24 passed`。
- 定向回归：`.venv\Scripts\python.exe -m pytest tests/test_sales_tool.py tests/test_metric_common.py -q` → `47 passed`。
- 全量回归：`.venv\Scripts\python.exe -m pytest -q` → `118 passed`。
- 差异检查：`git diff --cached --check` → 无输出。

### 最小依赖矩阵

| 指标 | 最小依赖 | 缺依赖时仍独立可用的指标 |
|---|---|---|
| GMV | `order_info.order_time/order_amount` | 付款、退款及比率指标 |
| 实际销售额/客单价 | 周期成功付款的 `paid_at/order_id/payment_amount/payment_status`；截至 `end` 的成功退款 `refunded_at/order_id/refund_amount/refund_status` | GMV、周期退款金额；退款金额缺 `order_id` 时仍可计算 |
| 周期退款金额 | `refund_info.refunded_at/refund_amount/refund_status` | GMV；缺付款数据或退款 `order_id` 不影响该金额 |
| 净销售额 | 可用的实际销售额与周期退款金额 | GMV 继续独立 |
| 件单价 | 实际销售额；成功付款订单 ID；`order_item.order_id/quantity` | 其他金额与退款率不受商品明细缺失影响 |
| 退款率 | 成功付款 `paid_at/order_id/payment_status`；成功退款 `refunded_at/order_id/refund_status` | 不依赖付款/退款金额列 |
| 退货率 | 退款率的订单/状态/时间依赖；`refund_quantity`；付款订单关联 `order_item.order_id/quantity` | 缺 `refund_amount` 时仍可计算；缺 `refund_quantity` 只禁用退货率 |

实现不再因付款域失败提前返回整组结果。订单、付款、周期退款、累计退款和明细数量分别建立依赖 reason，再由各指标组合自身依赖。新增参数化测试覆盖缺整表、缺时间列、缺各域 `order_id`、缺金额列和缺明细数量，并断言未受影响指标仍返回基准值。
