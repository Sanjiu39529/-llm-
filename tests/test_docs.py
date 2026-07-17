"""Phase 1 文档契约测试。"""

from pathlib import Path


README_PATH = Path("README.md")
GUIDE_PATH = Path("docs/learning/项目学习与面试指南.md")


def _line_containing(text: str, token: str) -> str:
    matches = [line for line in text.splitlines() if token in line]
    assert matches, f"文档缺少语义标记: {token}"
    return matches[0]


def test_readme_contains_only_intro_quickstart_and_phase_status() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    nonempty_lines = [line for line in readme.splitlines() if line]

    assert [line for line in readme.splitlines() if line.startswith("#")] == [
        "# 电商智能数据分析助手",
        "## 最短运行命令",
        "## Phase 1 状态",
    ]
    assert len(nonempty_lines) == 11
    assert readme.count("```powershell") == 1
    assert "python -m pip install -r requirements.txt" in readme
    assert "Copy-Item .env.example .env" in readme
    assert "python -m backend.scripts.import_data --file data/phase1.xlsx" in readme


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

    deduplication = _line_containing(guide, "当前去重")
    assert "只按业务键" in deduplication
    assert "保留首条" in deduplication
    assert "不比较或记录同键内容冲突" in deduplication

    no_valid_age = _line_containing(guide, "全批次无有效年龄")
    assert "保持为空" in no_valid_age
    assert 'filled["age"] = 0' in no_valid_age
    assert "纯缺失或不可解析不会增加" in no_valid_age
    assert "越界仍会增加" in no_valid_age

    ambiguity = _line_containing(guide, "人工确认与映射模板保存")
    assert "都属于后续 Streamlit" in ambiguity
    assert "当前 CLI 只拒绝歧义" in ambiguity
