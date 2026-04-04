from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    data_path: str = "/app/data/raw/weather"
    log_level: str = "INFO"
    environment: str = "development"
    load_cron_hour_utc: int = 21   # 2:30 AM IST (UTC+5:30)
    load_cron_minute_utc: int = 0

    class Config:
        env_file = ".env"


settings = Settings()
