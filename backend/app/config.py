"""应用环境配置。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量或 .env 文件读取应用配置。"""

    database_url: str
    import_batch_size: int = 1000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
