from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    web_origin: str = "http://localhost:3000"
    database_url: str = "sqlite:///./textbook-local.db"
    redis_url: str = "redis://localhost:6379/0"
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_access_key: str = "textbook-local"
    object_storage_secret_key: str = "replace-for-non-local-use"
    object_storage_bucket: str = "textbook-assets"

    def production_errors(self) -> list[str]:
        if self.app_env != "production":
            return []
        errors: list[str] = []
        if self.object_storage_secret_key == "replace-for-non-local-use":
            errors.append("OBJECT_STORAGE_SECRET_KEY must be replaced")
        if self.web_origin.startswith("http://"):
            errors.append("WEB_ORIGIN must use HTTPS")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
