from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    redis_url: str = "redis://localhost:6379/3"
    whatsapp_api_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_app_secret: str = ""
    pii_encryption_key: str = ""
    log_level: str = "INFO"
    environment: str = "development"

    class Config:
        env_file = ".env"


settings = Settings()
