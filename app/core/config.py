"""
Central application configuration.
Reads from environment variables (see .env.example).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Scalable Real-Time Chat"
    ENV: str = "development"
    INSTANCE_ID: str = "app-1"  # overridden per replica in docker-compose

    # Security / JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://chat_user:chat_pass@postgres:5432/chatdb"

    # Redis (pub/sub + presence + cache)
    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_CHANNEL_PREFIX: str = "chat:room:"
    PRESENCE_TTL_SECONDS: int = 60  # heartbeat window for "online" status

    # CORS
    CORS_ORIGINS: list[str] = ["*"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
