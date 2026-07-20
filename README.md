# 电商智能数据分析助手

面向电商运营场景的智能数据分析项目。用户可在 Streamlit 聊天界面上传 CSV/Excel、提出业务问题；系统会先识别数据语义与质量，再由固定 SQL/Pandas 计算指标、生成图表和可追溯的业务建议。

项目同时支持两类数据：

- **标准电商数据**：订单、商品、流量、投放、退款、用户行为等，经过确定性清洗后写入 MySQL。
- **通用商品销售快照**：例如包含商品标题、价格、销量和店铺名的 CSV，无需强行套用订单模板，可直接生成店铺/商品排行与预估销售额分析。

> 指标数值只由后端固定代码计算；LLM 只负责在白名单范围内选择图表、组织建议，不能改公式、生成 SQL 或编造数字。

## 功能亮点

- CSV/Excel 上传、字段别名识别、数据质量审计和幂等导入。
- 自动识别数据行粒度；匿名用户级漏斗快照不会因“内容相同”被错误去重。
- 销售、流量、商品、投放、退款、复购、漏斗与异常分析。
- 问题驱动图表选择：询问 GMV、渠道、商品或投放时，优先展示对应可用图表。
- 文字分析结论：输出真实指标、关键发现、数据限制与运营建议。
- 受限 LLM 分析规划：只接收聚合结论和图表白名单，调用失败自动回退规则计划。
- MCP stdio 服务：其他 Agent 可调用通用数据探查、销售快照分析、图表建议与业务动作工具。

## 技术栈

Python 3.10 · FastAPI · Streamlit · Pandas · SQLAlchemy · MySQL · LangGraph · Pydantic · MCP (stdio)

## 快速开始

### 1. 创建环境并安装依赖

```powershell
cd D:\shufen\ecommerce-agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`，至少配置本机 MySQL 的 `DATABASE_URL`。不要提交 `.env`；仓库只保留不含真实密钥的 `.env.example`。

### 2. 初始化数据库

全新数据库执行：

```powershell
Get-Content -Raw sql/001_schema.sql | mysql -u root -p ecommerce_db
```

旧版 Phase 1 数据库请先备份并按 `sql/002_phase1_integrity_upgrade.sql` 等迁移脚本顺序和项目设计文档操作；不要在全新数据库重复执行升级脚本。

### 3. 启动服务

```powershell
.\scripts\start_app.ps1
```

浏览器打开 `http://127.0.0.1:8501`，即可上传文件或提问。

## 使用示例

上传标准数据后可以直接问：

- `查看近 30 天 GMV`
- `哪个渠道的流量最高？`
- `分析用户行为漏斗`
- `商品销售排行`
- `ROI 的口径是什么？`

上传商品销售快照（含 `title`、`price`、`sale_count`，可选 `店名`）后，系统会识别为通用快照。若已确认 `sale_count` 为实际累计销量，则以 `price × sale_count` 计算**预估销售额**；该结果会清楚标注为预估值，不伪装成订单级交易金额。

## MCP 接入其他 Agent

将 [mcp.json.example](mcp.json.example) 中的服务配置复制到 MCP 客户端配置中。服务通过标准输入输出运行：

```powershell
.\.venv\Scripts\python.exe -m backend.app.mcp_server
```

可用工具：

- `inspect_dataset`：读取列名与样本质量摘要。
- `analyze_sales_snapshot`：分析通用商品销售快照。
- `suggest_charts`：返回安全的图表规范。
- `suggest_business_actions`：基于聚合结果返回业务动作建议。

这些工具只读本地 CSV/Excel，不写库、不执行用户提供的 SQL。

## 项目结构

```text
backend/app/api.py                 FastAPI 接口
backend/app/services/              导入、映射、清洗与数据画像
backend/app/analytics/             固定指标、通用快照和展示规划
backend/app/mcp_server.py          通用分析 MCP 服务
frontend/app.py                    Streamlit 聊天与看板
docs/项目设计文档.md                架构与边界
docs/learning/项目学习与面试指南.md  学习与面试说明
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 安全与数据边界

- `.env` 被 Git 忽略；如密钥曾暴露，应立即在供应商后台轮换。
- 前端不直连数据库；NL2SQL 仅允许受保护的只读查询。
- 数据字段不足时，系统会说明缺失依赖并取消相关图表，不补造结果。
- 有业务价值的异常仅标记和提示核验，不会在清洗阶段擅自删除。
