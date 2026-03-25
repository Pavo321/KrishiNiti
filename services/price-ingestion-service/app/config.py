from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    data_gov_api_key: str = ""
    log_level: str = "INFO"
    environment: str = "development"

    # Schedule: daily at 2:00 AM IST (UTC+5:30 → 20:30 UTC previous day)
    ingest_cron_hour_utc: int = 20
    ingest_cron_minute_utc: int = 30

    class Config:
        env_file = ".env"


settings = Settings()
