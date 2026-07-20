# 项目交接文档

> 写给完全没有历史上下文的新会话。请先完整阅读本文件，再执行任何修改。

## 1. 项目与仓库信息

- 项目：基于 LLM Agent 的电商智能数据分析助手
- 本地目录：`D:\shufen\ecommerce-agent`
- Python：只使用 Python 3.10，虚拟环境为 `D:\shufen\ecommerce-agent\.venv`
- Git 分支：`feat/ecommerce-agent-mvp`
- GitHub：`https://github.com/Sanjiu39529/-llm-.git`
- 当前最新提交：`ab86a1d feat: complete dataset-scoped agent dashboards`
- 当前测试基线：`231 passed`，另有 1 条 FastAPI/Starlette TestClient 第三方弃用警告
- 工作树中存在用户自己的未跟踪目录 `docs/superpowers/plans/`，不要擅自添加、删除或提交

用户是初学者，项目用于简历。回答必须使用中文，并用容易理解的方式说明。用户明确要求：减少冗余 Task 报告和重复测试，只保留主设计文档、学习与面试指南及必要测试；完成有效改动后通常需要提交并推送当前分支。

## 2. 我们在做什么

目标是构建一个 GPT 式电商数据分析助手：用户在 Streamlit 聊天页面提出问题，并可附加 CSV/Excel；后端自动识别数据类型、确定性清洗、写入或复用 MySQL 数据集，再根据问题生成 KPI、图表、异常说明和文字建议。

不可改变的边界：

- GMV、ROI、转化率等指标只由固定 SQL/Pandas 代码计算。
- LLM 只负责路由、知识解释和建议表达，绝不能修改指标公式或编造数字。
- RAG 只检索口径/规则 Markdown，不把规则文档当成交易事实数据库。
- 数据字段不足时输出可计算部分，列出缺失名称，并取消依赖图表。
- 自动识别或字段映射不确定时不写库，转人工确认。
- 前端不直连数据库；所有业务能力通过 FastAPI。

主文档：

- `docs/项目设计文档.md`：唯一主设计文档和阶段状态
- `docs/learning/项目学习与面试指南.md`：学习重点和面试问答
- `docs/knowledge/电商指标口径.md`：RAG 与业务指标口径资料

## 3. 当前架构

- 前端：`frontend/app.py`，Streamlit GPT 式聊天、附件、多数据集选择和动态看板
- API：`backend/app/api.py`，FastAPI 上传、分析、漏斗、问答接口
- Agent：`backend/app/agents/supervisor.py`，LangGraph 路由分析、只读查询和知识检索
- 导入：`backend/app/services/import_service.py`
- 文件读取：`backend/app/datasources/file_import.py`
- 清洗：`backend/app/services/cleaning.py`
- 写入仓储：`backend/app/database/repository.py`
- 分析仓储：`backend/app/database/analysis_repository.py`
- 指标：`backend/app/tools/` 与 `backend/app/analytics/`
- RAG：`backend/app/knowledge/`
- 平台接口预留：`backend/app/datasources/platform_api.py`
- 新库建表：`sql/001_schema.sql`
- 旧库数据集身份迁移：`sql/005_import_dataset_identity.sql`
- 一键启动：`scripts/start_app.ps1`

## 4. 已经完成的功能

### 4.1 数据基础与清洗

- MySQL 标准表、导入批次审计和指标配置表已经建立。
- 同时支持 CSV 与 Excel；Excel 工作表不要求齐全，字段名可以使用已定义别名。
- 自动识别标准表；无法唯一识别时要求用户手工确认。
- 导入前执行确定性清洗并记录质量摘要。
- 年龄有效范围为 1～100；缺失、不可解析、越界或小数年龄用全文件有效年龄均值填充。
- 必填字段、日期、金额、整数范围、文本长度、渠道、批内去重和跨批重复均有规则。
- 有业务价值的金额异常不会删除，而是按照全批 `Q3 + 3 × IQR` 标记。
- 缺少表或字段时报告缺失依赖，不伪造图表。

### 4.2 大文件与幂等导入

- HTTP 上传每次读取 1 MiB 并写临时文件，不再一次性 `await file.read()`。
- 文件上传时计算 SHA256 和大小。
- `import_batch` 保存 `dataset_id`、`file_hash`、文件大小、处理/写入/跳过行数和最后访问时间。
- 相同成功文件再次上传会复用原 `dataset_id`，写入 0 行。
- CSV 默认每 10,000 行读取和清洗；数据库默认每 1,000 行写入。
- 跨块去重保持全文件语义；年龄先扫描全文件均值；金额异常写完后按整个批次统一计算。
- Excel 按工作表逐个读取。
- 文件默认上限 100 MB，超限返回 HTTP 413。
- 配置项：`IMPORT_BATCH_SIZE`、`IMPORT_CSV_CHUNK_SIZE`、`IMPORT_MAX_FILE_SIZE_MB`。

### 4.3 指标、Agent 与安全

- 已实现销售、流量、用户、商品、投放、售后、复购、波动和异常等固定口径。
- 波动采用日环比、周同比、月环比；阈值可配置。
- NL2SQL 只接受单条 `SELECT`/`WITH ... SELECT`，限制白名单表和最大 1,000 行；生产仍应使用数据库只读账号。
- LangGraph Supervisor 可路由到固定指标分析、只读查询或知识检索。
- LLM 未配置或失败时保留确定性本地能力。

### 4.4 SQL 下推与数据集隔离

- 分析仓储不再使用无条件 `SELECT *`。
- 字段投影、时间窗口和 `dataset_ids` 过滤下推到 SQL。
- 日 GMV 在 SQL 中按日聚合。
- 行为漏斗的访客数、阶段人数、来源/设备转化率直接在 SQL 聚合，不再把整张行为表加载到 Pandas。
- Streamlit 会话保存已上传数据集，侧边栏可多选切换；后续问题自动携带所选 `dataset_ids`。
- 新建对话会清空数据集上下文，防止串数据。

### 4.5 RAG、追踪与看板

- 知识片段拥有稳定内容哈希 `chunk_id`。
- 检索融合正文覆盖率、标题命中和精确匹配信号。
- API 返回结构化 citations；LLM 引用超出本轮检索范围时拒绝答案并回退。
- 有 Hit Rate 与 MRR 检索评测工具和测试。
- 每次 Agent 运行返回 `run_id`、字符串 trace 和结构化 `trace_events`。
- 看板使用 Streamlit 原生金融主题，没有自定义 CSS。
- 已有响应式 KPI、销售结构、渠道比较、商品排行、漏斗、异常、建议和数据质量说明。
- `CommercePlatformConnector` 已为淘宝等 REST/OpenAPI 或 MCP 适配器预留稳定接口；没有伪造真实平台连接。

## 5. 当前数据库的真实状态

当前本机 MySQL 已执行 `sql/005_import_dataset_identity.sql`。

真实文件：`D:\Desktop\lyf\project\用户行为分析.csv`

- 原始 100,000 行
- 清洗后每次有效 57,994 行
- 识别为 `behavior_funnel`，不是 `behavior_info`
- 当前数据库存在两个历史批次：批次 1 和批次 2，各 57,994 行，总计 115,988 行
- 这两批是在文件哈希幂等能力完成前重复导入的
- 批次 2 已回填真实文件 SHA256、大小和行数，因此以后再次上传该文件会复用批次 2，不再增长
- 用批次 2 的 `dataset_id` 做 SQL 漏斗验证结果：`57,994 → 41,330 → 26,209 → 5,770 → 2,191`

重要：不要未经用户明确同意删除批次 1 或其业务数据。两批看起来来源和行数相同，但删除属于破坏性数据操作。当前前端选择单个 `dataset_id` 可以避免分析时重复计数；不带数据集过滤的全局分析仍可能受到这两批历史重复数据影响。

## 6. 当前卡在哪里

没有代码阻塞，设计文档中的 Phase A1～E 均已完成，测试全部通过。

当前项目没有运行：最后检查时端口 8000 和 8500～8599 均无监听进程。用户需要运行：

```powershell
cd D:\shufen\ecommerce-agent
.\scripts\start_app.ps1
```

新主题通常需要重启 Streamlit 才完全生效。

尚未完成但不属于当前 MVP 阻塞项：

- 未经用户确认，尚未清理上述历史重复批次。
- 尚未实际执行 50 MB CSV 峰值内存基准测试；代码已经分块，但 PRD 中的“峰值不超过 512 MB”仍需要专门测量。
- 设计文档规划过的 `/api/imports/inspect`、导入状态、数据集详情和质量详情独立接口尚未全部实现。
- 淘宝等真实平台没有企业应用授权、OAuth、签名和限流配置；目前只有连接器接口边界。
- 尚未做生产部署、鉴权、多用户隔离、任务队列、对象存储和数据库只读账号部署验证。

## 7. 建议的下一步顺序

1. 启动 API 和 Streamlit，手工完成一轮用户验收：上传文件、自动识别、选择数据集、追问漏斗、询问 GMV 口径、查看引用和运行轨迹。
2. 若页面或接口异常，先读取 API 终端日志和浏览器实际响应，不要凭截图猜测。
3. 在用户明确授权后，核对两个行为批次内容完全一致，再制定可回滚的历史重复数据清理 SQL；执行前必须备份并报告影响行数。
4. 建立 50 MB CSV 基准文件，记录导入耗时和 Python 进程峰值内存，验证 512 MB 目标。
5. 按需要补齐数据集管理 API：inspect、status、metadata、quality；不要先做没有用户价值的管理后台。
6. 部署前轮换已经暴露过的 LLM API Key，创建 MySQL 只读分析账号并加入 API 鉴权。
7. 只有在获得淘宝等平台正式授权资料后，才实现 `CommercePlatformConnector` 的具体适配器。

## 8. 绝对不要再踩的坑

### 8.1 环境和启动

- 不要在 `C:\Windows\System32` 运行项目相对路径命令。必须先 `cd D:\shufen\ecommerce-agent`。
- 只使用 `.\.venv\Scripts\python.exe` 和 Python 3.10，不要重新引入 Python 3.13。
- Streamlit 首次出现邮箱提示时直接留空按 Enter，不是报错。
- 修改 `.streamlit/config.toml` 后应重启 Streamlit，不要只刷新浏览器。

### 8.2 配置和密钥

- `.env` 已被 Git 忽略，包含数据库连接和 LLM 配置。绝对不要读取后打印、写入文档、提交或在回复中展示真实密钥。
- 用户曾在对话中公开过 LLM API Key，应建议轮换；不要把旧 Key 写入任何文件。
- `DATABASE_URL` 是必填配置；缺失时 Pydantic 会报 `database_url Field required`。
- OpenAI 兼容地址需要包含正确 `/v1` 前缀，但不要未经验证猜模型名。

### 8.3 导入链路

- `ImportService` 构造函数的第二个位置参数是 adapter。`batch_size` 必须使用命名参数，不能把整数按位置传入，否则会出现“整数没有 read 方法”。
- “上传分块”不等于“CSV 解析分块”。两层现在都已处理，后续重构不能退回整文件 `await file.read()` 或 `pd.read_csv()` 无 `chunksize`。
- 分块清洗不能按块独立算年龄均值、异常阈值或去重；必须保持全文件/全批口径。
- 同一文件幂等判断使用 SHA256，不使用文件名。
- 失败批次会释放唯一哈希以允许重试；不要改成失败后永远无法重新导入。
- `用户行为分析.csv` 是匿名访客页面漏斗画像，没有事件 ID、用户 ID 或时间，必须映射到 `behavior_funnel`，绝不能强行映射成事件表 `behavior_info`。
- 前端人工确认导入时必须保留本轮附件内容；不能因为 Streamlit rerun 丢失文件。
- HTTP 错误响应不一定是 JSON，前端必须保留可读错误处理，不能直接无保护地 `json.loads()`。

### 8.4 数据库和指标

- 不要删除当前两个历史行为批次，除非用户明确授权且已备份。
- 不要恢复分析层无条件 `SELECT *`；新增分析必须带字段、时间或数据集边界，大数据聚合优先下推 SQL。
- 不要让 LLM 直接计算 GMV、ROI、UV 或转化率，也不要让 RAG 修改指标口径。
- 不要把“预留平台连接器”描述成“已经连接淘宝 API”。
- 缺字段时不要补造结果；取消依赖图表并报告缺失名称。
- 有价值异常只标记和建议核验，不要在清洗阶段擅自删除。

### 8.5 Git、测试与文档

- 不要触碰或提交用户未跟踪的 `docs/superpowers/plans/`。
- 不要使用 `git reset --hard` 或 `git checkout --` 清理用户修改。
- 不要生成新的冗余 Task 报告；更新 `docs/项目设计文档.md` 和 `docs/learning/项目学习与面试指南.md` 即可。
- 用户要求减少测试数量，但不能省掉高风险边界测试。优先测试：幂等、跨块一致性、SQL 无整表读取、dataset 隔离、RAG 引用边界和当前 Streamlit API 渲染。
- 最近完整测试命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

- 最近结果：`231 passed, 1 warning`。

## 9. 新会话开始工作的最短检查清单

```powershell
cd D:\shufen\ecommerce-agent
git status --short
git branch --show-current
git log -5 --oneline
.\.venv\Scripts\python.exe -m pytest -q
```

确认以下事实后再修改：

- 分支应为 `feat/ecommerce-agent-mvp`
- 最新远端提交至少包含 `ab86a1d`
- 除 `docs/superpowers/plans/` 外不应有未知改动
- `.env` 不得加入 Git
- 若要调试页面，先运行 `.\scripts\start_app.ps1`

## 10. 交接结论

当前 MVP 已形成完整闭环：文件上传 → 自动识别 → 确定性清洗 → 幂等数据集写入 → dataset 隔离 → SQL/Pandas 固定指标 → Agent 路由 → 受限 RAG/引用 → 动态看板。下一会话不需要从头设计，应从用户验收、历史重复数据治理、性能基准或生产化缺口中选择一个明确目标继续。
