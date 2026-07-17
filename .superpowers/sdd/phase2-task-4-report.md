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
