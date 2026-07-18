"""应用环境配置。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量或 .env 文件读取应用配置。"""

    database_url: str
    import_batch_size: int = 1000
    nl2sql_max_rows: int = 1000
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
