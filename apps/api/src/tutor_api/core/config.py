import re
from functools import lru_cache
from ipaddress import ip_address
from typing import Literal
from urllib.parse import SplitResult, urlsplit

from pydantic import Field, HttpUrl, SecretStr, TypeAdapter, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)
_POSTGRESQL_SCHEMES = {"postgres", "postgresql", "postgresql+psycopg"}
_REDIS_SCHEMES = {"redis", "rediss"}
_DEVELOPMENT_OBJECT_ACCESS_KEYS = {"textbook-local", "textbook-storage-app-local"}
_DEVELOPMENT_OBJECT_SECRETS = {
    "development-secret",
    "replace-for-non-local-use",
    "replace-with-long-random-object-app-secret",
}
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def _parse_absolute_url(value: str) -> SplitResult | None:
    if "\\" in value or any(character.isspace() for character in value):
        return None
    if _INVALID_PERCENT_ESCAPE.search(value):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if port == 0:
        return None
    if not parsed.scheme or not parsed.netloc or parsed.hostname is None:
        return None
    return parsed


def _is_local_host(host: str, development_names: set[str]) -> bool:
    normalized_host = host.rstrip(".").casefold()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        return True
    if normalized_host in development_names:
        return True
    try:
        address = ip_address(normalized_host)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    web_origin: str = "http://localhost:3000"
    database_url: str = Field(default="sqlite:///./textbook-local.db", repr=False)
    redis_url: str = Field(default="redis://localhost:6379/0", repr=False)
    object_storage_endpoint: str = Field(default="http://localhost:9000", repr=False)
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
        database_url = _parse_absolute_url(self.database_url)
        if (
            database_url is None
            or database_url.scheme.casefold() not in _POSTGRESQL_SCHEMES
            or _is_local_host(database_url.hostname, {"postgres"})
        ):
            errors.append("DATABASE_URL must use a non-local PostgreSQL database")
        redis_url = _parse_absolute_url(self.redis_url)
        if (
            redis_url is None
            or redis_url.scheme.casefold() not in _REDIS_SCHEMES
            or not redis_url.password
            or _is_local_host(redis_url.hostname, {"redis"})
        ):
            errors.append("REDIS_URL must use authenticated, non-local Redis")
        object_endpoint = _parse_absolute_url(self.object_storage_endpoint)
        if (
            object_endpoint is None
            or object_endpoint.scheme.casefold() not in {"http", "https"}
            or object_endpoint.username is not None
            or object_endpoint.password is not None
            or object_endpoint.path not in {"", "/"}
            or object_endpoint.query
            or object_endpoint.fragment
            or _is_local_host(object_endpoint.hostname, {"minio"})
        ):
            errors.append("OBJECT_STORAGE_ENDPOINT must use a non-local HTTP(S) endpoint")
        if self.object_storage_access_key.casefold() in _DEVELOPMENT_OBJECT_ACCESS_KEYS:
            errors.append("OBJECT_STORAGE_ACCESS_KEY must be replaced")
        if (
            self.object_storage_secret_key.get_secret_value().casefold()
            in _DEVELOPMENT_OBJECT_SECRETS
        ):
            errors.append("OBJECT_STORAGE_SECRET_KEY must be replaced")
        if self.web_origin.startswith("http://"):
            errors.append("WEB_ORIGIN must use HTTPS")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
