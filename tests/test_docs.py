"""Phase 1 文档契约测试。"""

from pathlib import Path


README_PATH = Path("README.md")
GUIDE_PATH = Path("docs/learning/项目学习与面试指南.md")


def _line_containing(text: str, token: str) -> str:
    matches = [line for line in text.splitlines() if token in line]
    assert matches, f"文档缺少语义标记: {token}"
    return matches[0]


def test_readme_describes_current_capabilities_and_safe_quickstart() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    assert readme.startswith("# 电商智能数据分析助手")
    for token in (
        "## 功能亮点", "## 快速开始", "## MCP 接入其他 Agent",
        "通用商品销售快照", "mcp.json.example", "Copy-Item .env.example .env",
    ):
        assert token in readme
    assert ".env` 被 Git 忽略" in readme
    assert ".\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt" in readme


def test_phase_one_guide_documents_executable_excel_and_csv_commands() -> None:
    guide = GUIDE_PATH.read_text(encoding="utf-8")

    assert (
        "Get-Content -Raw sql/001_schema.sql | mysql -u root -p ecommerce_db"
        in guide
    )
    assert "python -m backend.scripts.import_data --file data/phase1.xlsx" in guide
    csv_commands = [
        line
        for line in guide.splitlines()
        if "python -m backend.scripts.import_data" in line and "--table" in line
    ]
    assert (
        "python -m backend.scripts.import_data --file data/users.csv --table user_info"
        in csv_commands
    )
    assert (
        "python -m backend.scripts.import_data --file data/orders.csv --table order_info"
        in csv_commands
    )


def test_phase_one_guide_documents_quality_summary_boundaries() -> None:
    guide = GUIDE_PATH.read_text(encoding="utf-8")

    age_example = _line_containing(guide, "[20, 缺失, 40, 150]")
    assert "[20, 30, 40, 30]" in age_example
    assert "filled.age" in age_example

    invalid_records = _line_containing(guide, "无法解析日期")
    assert "金额小于等于 0" in invalid_records
    assert "skipped" in invalid_records
    assert "invalid" in invalid_records

    missing_tables = _line_containing(guide, "missing_tables")
    assert "Phase 1" in missing_tables
    assert "只报告" in missing_tables
    assert "不执行指标/图表降级" in missing_tables
    for forbidden_claim in (
        "Phase 1 执行指标/图表降级",
        "Phase 1 会执行指标/图表降级",
        "Phase 1 已执行指标/图表降级",
    ):
        assert forbidden_claim not in guide


def test_phase_one_guide_matches_current_deduplication_age_and_mapping_behavior() -> None:
    guide = GUIDE_PATH.read_text(encoding="utf-8")

    deduplication = _line_containing(guide, "当前批内去重")
    assert "完整业务键" in deduplication
    assert "保留首条" in deduplication
    assert "不比较同键内容冲突" in deduplication
    assert "deduplicated" in deduplication

    no_valid_age = _line_containing(guide, "全批次无有效年龄")
    assert "保持为空" in no_valid_age
    assert 'filled["age"] = 0' in no_valid_age
    assert "纯缺失不增加" in no_valid_age
    assert "不可解析和越界值都会按原因增加" in no_valid_age
    assert "`invalid`" in no_valid_age

    ambiguity = _line_containing(guide, "人工确认与映射模板保存")
    assert "都属于后续 Streamlit" in ambiguity
    assert "当前 CLI 只拒绝歧义" in ambiguity


def test_guide_separates_future_goal_from_current_phase_and_matches_audit_contract() -> None:
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    introduction = _line_containing(guide, "项目最终目标")
    assert "Phase 10 自动识别与报告建议" in introduction
    assert "我开发了一个基于 LLM Agent" not in guide
    for token in (
        "unmapped_source_columns", "relationship_anomalies", "error_code",
        "cross_batch_duplicate", "reasons", "IMPORT_BATCH_SIZE",
    ):
        assert token in guide
    assert "GMV" in guide
    assert "Decimal" in guide


def test_guide_documents_excel_table_rejection_and_decimal_policy() -> None:
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    assert "Excel 不接受 `--table`" in guide
    assert "ROUND_HALF_UP" in guide
    assert "9999999999999999.99" in guide
    assert "只有 `order_time`" in guide


def test_docs_distinguish_fresh_schema_upgrade_and_memory_boundary() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    assert "全新数据库" in readme and "sql/001_schema.sql" in readme
    assert "旧版 Phase 1 数据库" in readme and "sql/002_phase1_integrity_upgrade.sql" in readme
    assert "仅控制数据库查询和写入分块" in guide
    assert "整表加载到内存" in guide
    assert "文本单元格" in guide and "数值单元格" in guide
    assert "前导零" in guide
    assert "重复 ID" in guide and "重复自然键" in guide
