# Phase 2 Task 4 实施报告

## 状态

已实现流量、转化与客户指标工具：

- 新增 `calculate_user_metrics(tables, start, end, customer_history_days=365)`。
- 访客键优先账号、其次设备；无标识访问只计 PV。
- 按首次历史访问区分新老访客。
- 输出六个标准渠道，未知或缺失渠道只进入质量提示。
- 下单 UV 按周期下单用户；付款 UV 按周期成功付款并经订单关联用户。
- 实现下单、付款、整体转化率和加购率。
- 实现 365 天可配置历史窗口的复购率与新客占比。
- 缺表或关键列时仅禁用依赖指标；零分母统一使用 `safe_ratio`。

## TDD 证据

1. 初始 RED：`tests/test_user_tool.py` 收集失败，原因为
   `ModuleNotFoundError: backend.app.tools.user_tool`。
2. 首轮 GREEN：8 个核心场景通过。
3. 补齐缺关键列覆盖后：12 个测试通过。
4. 独立审查补充两个 RED：
   - 周期内加购错误关联周期外访问，实际得到 `2.0000`，期望 `1.0000`。
   - 整列缺少 `channel` 时质量提示为空。
5. 修复后定向测试：`14 passed in 0.58s`。

## 验证

- 定向：`.venv\\Scripts\\python.exe -m pytest tests/test_user_tool.py -q`
  - `14 passed in 0.58s`
- 全量：`.venv\\Scripts\\python.exe -m pytest -q`
  - `132 passed in 1.83s`
- Diff whitespace：`git diff --check`
  - 退出码 0

## 审查修正

- 加购事件的 `visit_id` 只关联统计周期内访问，确保分子分母同周期。
- `traffic_visit` 缺少整个 `channel` 列时写入
  `quality_warnings.unknown_channels = ["<missing>"]`，不伪装成可归因的零流量。
- 删除未使用的 `Decimal` 导入。

## 环境说明

Windows Python Launcher 能列出 Python 3.13，但对应 WindowsApps 可执行文件无法创建进程；
因此本次使用仓库 `.venv` 的 Python 3.10 完成验证。该限制与本次代码变更无关。

## 独立审查修复（第二轮）

主流程独立审查提出的三项 Important 与一项 Minor 已按 TDD 修复：

- 加购 UV 现在必须属于周期内店铺 visitor key 集合；行为账号无本期访问、或仅有
  `device:<id>` 访问却上报 `user:<id>` 时均不计入分子。
- 周期付款状态全空时返回 `empty_payment_status`，全未知时返回
  `unknown_payment_status`；付款依赖指标均标记 unavailable。
- 已知与未知付款状态混合时只使用已知成功行，并在
  `quality_warnings.unknown_payment_statuses` 记录排除数量和稳定排序后的值。
- 缺少 `traffic_visit` 或 `visited_at` 时仍保留六个渠道键，但每个渠道均返回
  `available=false`、对应原因及空值，不再伪装成真实零。
- 支付/退款成功白名单、状态规范化与白名单 mask 已小范围提取到
  `backend/app/analytics/common.py`，销售与用户工具共用；销售公式未改动。

### 第二轮 RED/GREEN 证据

- RED：新增针对性测试稳定得到 6 个失败；共享 helper 测试因导入不存在而失败。
- GREEN 定向：
  `.venv\\Scripts\\python.exe -m pytest tests/test_user_tool.py tests/test_sales_tool.py tests/test_metric_common.py -q`
  输出 `68 passed in 0.80s`。
- GREEN 全量：`.venv\\Scripts\\python.exe -m pytest -q`
  输出 `139 passed in 1.89s`。
- `git diff --check`：退出码 0。
