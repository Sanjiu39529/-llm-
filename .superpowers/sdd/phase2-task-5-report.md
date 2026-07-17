# Phase 2 Task 5 实施报告

## 状态

已完成投放与商品分析工具，并按 TDD 完成 RED、GREEN、全量回归和自审。

## 实现范围

- `calculate_ad_metrics`：周期消耗、CTR、CPM、CPC、直接/间接 ROI、7 日 ROI、六渠道拆分和质量告警。
- 归因严格按周期投放 `ad_id` 过滤；7 日窗口包含投放后第 0–7 日、排除第 8 日，并对每条归因做存在性匹配以避免重叠窗口重复计数。
- `calculate_product_metrics`：成功付款订单集合与商品明细半连接，按销量和销售额生成稳定 Top N；销售额逐行优先 `item_amount`，必要时回退 `unit_price * quantity`。
- 缺表、缺列、未知状态、未知渠道/归因类型和零分母均局部降级，不影响仍可计算的结果。

## 测试证据

- RED：目标模块不存在时，两个测试模块均以 `ModuleNotFoundError` 失败。
- 首轮 GREEN：`20 passed`。
- 自审新增局部降级回归后：定向测试 `22 passed`。
- 全量与 diff 检查在提交前重新运行，最终结果见提交记录与任务回复。

## 自审结论

- 修复缺 `quantity`、但 `item_amount` 完整时，收入排行错误显示虚假数量 0 的问题；现在仅省略不可用字段。
- 未实现异常分析、统一报告或修改学习指南。
- 仓库原有未跟踪虚拟环境、缓存和计划目录未纳入提交。

## 审查修复

- 7 日窗口先把 `ad_date` 归一到自然日 0 点，再按左闭右开区间 `[day_start, day_start + 8 天)` 判断；新增非午夜投放、同日早时刻、第 7 日末和第 8 日早时刻测试。
- 7 日归因在局部重置索引并使用逐行布尔 mask，消除重复 DataFrame index 标签导致的金额放大；重叠投放窗口仍对每条归因最多计一次。
- 六个渠道槽位的 cost、impressions、clicks 分别使用 `MetricResult` 表达可用性；缺 `channel` 时六键保留并统一返回 `missing_channel`，缺单个度量列时只禁用相应字段和依赖指标。
- 审查问题 RED：5 个失败；修复后 channel/product 定向测试 `27 passed`，全量测试 `170 passed`。
