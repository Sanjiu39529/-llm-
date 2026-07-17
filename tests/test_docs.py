"""Phase 1 文档契约测试。"""

from pathlib import Path


README_PATH = Path("README.md")
GUIDE_PATH = Path("docs/learning/项目学习与面试指南.md")


def test_readme_contains_only_intro_quickstart_and_phase_status() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    assert [line for line in readme.splitlines() if line.startswith("#")] == [
        "# 电商智能数据分析助手",
        "## 最短运行命令",
        "## Phase 1 状态",
    ]


def test_phase_one_guide_documents_actionable_import_and_quality_contracts() -> None:
    guide = GUIDE_PATH.read_text(encoding="utf-8")

    assert "sql/001_schema.sql" in guide
    assert "python -m backend.scripts.import_data --file data/phase1.xlsx" in guide
    assert (
        "python -m backend.scripts.import_data --file data/users.csv --table user_info"
        in guide
    )
    assert "年龄 `[20, 缺失, 40, 150]` 会清洗为 `[20, 30, 40, 30]`" in guide
    assert "缺少 `traffic_visit` 时，UV、PV 和转化率分析降级为不可用" in guide
    assert "无法解析日期的记录会被跳过，并计入质量摘要" in guide
    assert "金额小于等于 0 的记录会被跳过，并计入质量摘要" in guide
