from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./hookline.db"
    webhook_secret: str = "local-demo-secret-change-this"
    max_attempts: int = 5
    retry_base_seconds: int = 5
    retry_max_seconds: int = 300


settings = Settings()
