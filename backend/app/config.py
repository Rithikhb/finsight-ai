from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_NAME: str = "FinSight AI"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "dev-only-secret-key-replace-via-env-in-production-9f8d7a6b5c4e"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    DATABASE_URL: str = "sqlite:///./finsight_local.db"
    MAX_UPLOAD_SIZE_MB: int = 10
    ENABLE_OCR_FALLBACK: bool = False
    ENABLE_LOCAL_LLM: bool = False
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1"

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()