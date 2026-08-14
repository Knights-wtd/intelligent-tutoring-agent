from functools import lru_cache
from typing import Literal

from pydantic import HttpUrl, SecretStr, TypeAdapter, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


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
    object_storage_secret_key: SecretStr = SecretStr("replace-for-non-local-use")
    object_storage_bucket: str = "textbook-assets"

    @field_validator("web_origin")
    @classmethod
    def validate_web_origin(cls, value: str) -> str:
        error_message = "WEB_ORIGIN must be a single absolute HTTP(S) origin"
        try:
            parsed = _HTTP_URL_ADAPTER.validate_python(value)
        except ValidationError as error:
            raise ValueError(error_message) from error

        host = parsed.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        origin_without_port = f"{parsed.scheme}://{host}"
        default_port = 80 if parsed.scheme == "http" else 443
        if parsed.port in {None, default_port}:
            canonical_origin = origin_without_port
            accepted_origins = {canonical_origin, f"{canonical_origin}:{default_port}"}
        else:
            canonical_origin = f"{origin_without_port}:{parsed.port}"
            accepted_origins = {canonical_origin}

        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/"
            or parsed.query is not None
            or parsed.fragment is not None
            or "*" in host
            or value.casefold() not in {origin.casefold() for origin in accepted_origins}
        ):
            raise ValueError(error_message)
        return canonical_origin

    def production_errors(self) -> list[str]:
        if self.app_env != "production":
            return []
        errors: list[str] = []
        if self.object_storage_secret_key.get_secret_value() == "replace-for-non-local-use":
            errors.append("OBJECT_STORAGE_SECRET_KEY must be replaced")
        if self.web_origin.startswith("http://"):
            errors.append("WEB_ORIGIN must use HTTPS")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
