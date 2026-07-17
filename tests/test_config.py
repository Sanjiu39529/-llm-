"""配置模块测试。"""

from backend.app.config import Settings


def test_settings_uses_safe_defaults() -> None:
    """显式数据库地址时应使用安全的导入批次默认值。"""
    settings = Settings(
        database_url="mysql+pymysql://user:pass@localhost:3306/ecommerce_db"
    )

    assert settings.import_batch_size == 1000
    assert settings.database_url.startswith("mysql+pymysql://")
