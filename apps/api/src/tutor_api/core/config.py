import json
import re
import unicodedata
from functools import lru_cache
from ipaddress import ip_address
from typing import Annotated, Any, Literal
from urllib.parse import SplitResult, urlsplit

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from tutor_api.knowledge.embeddings import (
    normalize_embedding_backend,
    normalize_embedding_model,
    validate_embedding_dimension,
)
from tutor_api.knowledge.ocr import normalize_ocr_backend

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
_COOKIE_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_EMAIL_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_LANGUAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class ProviderProfileConfig(BaseModel):
    """A non-secret model profile exposed by the server runtime configuration."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    id: str
    provider: str
    model: str
    display_name: str
    supports_usage: bool
    enabled_by_default: bool

    @field_validator("id", "provider", "model", "display_name")
    @classmethod
    def validate_non_blank_profile_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provider profile fields must not be blank")
        return value


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
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True, populate_by_name=True
    )

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
    max_upload_bytes: int = 50 * 1024 * 1024
    knowledge_upload_max_bytes: int = 100 * 1024 * 1024
    max_vault_files: int = 5_000
    max_vault_uncompressed_bytes: int = 500 * 1024 * 1024
    ocr_backend: str = "disabled"
    ocr_languages: Annotated[tuple[str, ...], NoDecode] = ("eng", "chi_sim")
    embedding_backend: str = "hash"
    embedding_model: str = "feature-hash-v1"
    embedding_dimension: int = 384
    faro_api_base_url: str = Field(default="https://faroapi.com/v1", repr=False)
    faro_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    faro_model: str = "gemini-3.7-flash-tiered"
    faro_context_window: int = 32_000
    faro_timeout_seconds: int = 60
    faro_max_concurrency: int = 2
    agent_runtime_url: str = Field(default="http://host.docker.internal:8765", repr=False)
    # Trusted host-reachable callback used by the host-native Runtime. Never derive
    # this URL from a proxied request Host header (for example ``web:3000``).
    agent_runtime_callback_url: str = Field(
        default="http://127.0.0.1:8000/api/v1/agent/runtime/events", repr=False
    )
    agent_runtime_token: SecretStr = Field(default=SecretStr(""), repr=False)
    agent_capability_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    agent_vault_root: str = ".agent-data/vault"
    agent_vault_watch_debounce_ms: int = Field(default=500, ge=1, le=60_000)
    agent_vault_reconcile_interval_seconds: int = Field(default=300, ge=1, le=86_400)
    agent_sidecar_root: str = ".agent-data/sidecars"
    agent_provider: str = "faro"
    agent_model: str = "gemini-3.7-flash-tiered"
    agent_context_window: int = Field(default=32_000, ge=1)
    agent_inline_event_bytes: int = Field(default=262_144, ge=1)
    agent_mcp_config_paths: Annotated[tuple[str, ...], NoDecode] = ()
    agent_skill_paths: Annotated[tuple[str, ...], NoDecode] = ()
    agent_subagent_concurrency: int = Field(default=4, ge=1)
    agent_tool_concurrency: int = Field(default=8, ge=1)
    # Optional explicit egress proxy for provider calls, e.g.
    # http://host.docker.internal:7890 on container deployments where direct
    # TLS to the provider is unreliable. Empty means direct connection.
    faro_proxy_url: str = Field(default="", repr=False)
    session_cookie_name: str = "session"
    session_ttl_seconds: int = 604800
    login_max_attempts: int = 5
    login_lockout_seconds: int = 900
    session_purge_probability: float = 0.05
    register_max_attempts: int = 30
    register_lockout_seconds: int = 3600
    # Explicit key for tutor citation tokens. When unset the object-storage secret is
    # used so pre-existing deployments keep working; new deployments receive the
    # variable through compose (`:?` required) and should rotate it independently.
    citation_hmac_secret: SecretStr | None = Field(default=None, repr=False)

    @property
    def effective_citation_hmac_secret(self) -> str:
        return (self.citation_hmac_secret or self.object_storage_secret_key).get_secret_value()

    provider_profiles: Annotated[tuple[ProviderProfileConfig, ...], NoDecode] = Field(
        default=(),
        validation_alias=AliasChoices("PROVIDER_PROFILES_JSON", "provider_profiles_json"),
        repr=False,
    )
    platform_admin_emails: Annotated[tuple[str, ...], NoDecode] = Field(
        default=(), validation_alias="PLATFORM_ADMIN_EMAILS"
    )

    @field_validator("provider_profiles", mode="before")
    @classmethod
    def parse_provider_profiles(cls, value: Any) -> Any:
        if isinstance(value, tuple):
            return value
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError("PROVIDER_PROFILES_JSON must contain valid JSON") from error
        if not isinstance(value, list):
            raise ValueError("PROVIDER_PROFILES_JSON must be a JSON array")
        return value

    @field_validator("provider_profiles")
    @classmethod
    def validate_unique_provider_profile_ids(
        cls, value: tuple[ProviderProfileConfig, ...]
    ) -> tuple[ProviderProfileConfig, ...]:
        ids = [profile.id for profile in value]
        if len(ids) != len(set(ids)):
            raise ValueError("PROVIDER_PROFILES_JSON must not contain duplicate profile IDs")
        return value

    @field_validator("agent_provider", mode="before")
    @classmethod
    def lock_agent_provider_to_faro(cls, value: Any) -> str:
        del value
        return "faro"

    @field_validator("agent_model", mode="before")
    @classmethod
    def lock_agent_model_to_gemini(cls, value: Any) -> str:
        del value
        return "gemini-3.7-flash-tiered"

    @field_validator("agent_context_window", mode="before")
    @classmethod
    def lock_agent_context_window(cls, value: Any) -> int:
        del value
        return 32_000

    @field_validator("agent_mcp_config_paths", "agent_skill_paths", mode="before")
    @classmethod
    def parse_agent_path_lists(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            values = value.split(",") if value.strip() else ()
        elif isinstance(value, (tuple, list)):
            values = value
        else:
            raise ValueError("Agent path lists must be comma-separated strings")
        normalized = tuple(item.strip() if isinstance(item, str) else "" for item in values)
        if any(not item for item in normalized):
            raise ValueError("Agent path lists must not contain empty paths")
        return tuple(dict.fromkeys(normalized))

    @field_validator("platform_admin_emails", mode="before")
    @classmethod
    def parse_platform_admin_emails(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            values = value.split(",") if value else ()
        elif isinstance(value, (tuple, list)):
            values = value
        else:
            raise ValueError("PLATFORM_ADMIN_EMAILS must be a comma-separated string")
        emails = tuple(
            email.strip().casefold() if isinstance(email, str) else "" for email in values
        )
        if any(not email or not _EMAIL_ADDRESS.fullmatch(email) for email in emails):
            raise ValueError("PLATFORM_ADMIN_EMAILS must contain valid email addresses")
        return tuple(dict.fromkeys(emails))

    @field_validator("max_upload_bytes")
    @classmethod
    def validate_max_upload_bytes(cls, value: int) -> int:
        if not 1 <= value <= 2 * 1024 * 1024 * 1024:
            raise ValueError("MAX_UPLOAD_BYTES must be between 1 and 2147483648")
        return value

    @field_validator("knowledge_upload_max_bytes")
    @classmethod
    def validate_knowledge_upload_max_bytes(cls, value: int) -> int:
        if not 1 <= value <= 2 * 1024 * 1024 * 1024:
            raise ValueError("KNOWLEDGE_UPLOAD_MAX_BYTES must be between 1 and 2147483648")
        return value

    @field_validator("max_vault_files")
    @classmethod
    def validate_max_vault_files(cls, value: int) -> int:
        if not 1 <= value <= 100_000:
            raise ValueError("MAX_VAULT_FILES must be between 1 and 100000")
        return value

    @field_validator("max_vault_uncompressed_bytes")
    @classmethod
    def validate_max_vault_uncompressed_bytes(cls, value: int) -> int:
        if not 1 <= value <= 20 * 1024 * 1024 * 1024:
            raise ValueError("MAX_VAULT_UNCOMPRESSED_BYTES must be between 1 and 21474836480")
        return value

    @field_validator("embedding_dimension")
    @classmethod
    def validate_embedding_dimension_setting(cls, value: int) -> int:
        return validate_embedding_dimension(value)

    @field_validator("ocr_backend", mode="before")
    @classmethod
    def validate_ocr_backend_setting(cls, value: Any) -> str:
        return normalize_ocr_backend(value)

    @field_validator("embedding_backend", mode="before")
    @classmethod
    def validate_embedding_backend_setting(cls, value: Any) -> str:
        return normalize_embedding_backend(value)

    @field_validator("embedding_model", mode="before")
    @classmethod
    def validate_embedding_model_setting(cls, value: Any) -> str:
        return normalize_embedding_model(value)

    @field_validator("faro_api_base_url")
    @classmethod
    def validate_faro_api_base_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = _parse_absolute_url(normalized)
        if parsed is None or parsed.scheme != "https" or parsed.query or parsed.fragment:
            raise ValueError("FARO_API_BASE_URL must be an absolute HTTPS URL")
        return normalized.rstrip("/")

    @field_validator("faro_proxy_url")
    @classmethod
    def validate_faro_proxy_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            return ""
        parsed = _parse_absolute_url(normalized)
        if parsed is None or parsed.scheme != "http" or parsed.query or parsed.fragment:
            raise ValueError("FARO_PROXY_URL must be an absolute http:// proxy URL")
        return normalized

    @field_validator("faro_model")
    @classmethod
    def validate_faro_model(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).strip()
        if not normalized or len(normalized) > 255 or any(char.isspace() for char in normalized):
            raise ValueError("FARO_MODEL must be a non-blank model id without whitespace")
        return normalized

    @field_validator("faro_context_window")
    @classmethod
    def validate_faro_context_window(cls, value: int) -> int:
        if not 1_024 <= value <= 1_000_000:
            raise ValueError("FARO_CONTEXT_WINDOW must be between 1024 and 1000000")
        return value

    @field_validator("faro_timeout_seconds")
    @classmethod
    def validate_faro_timeout_seconds(cls, value: int) -> int:
        if not 5 <= value <= 600:
            raise ValueError("FARO_TIMEOUT_SECONDS must be between 5 and 600")
        return value

    @field_validator("faro_max_concurrency")
    @classmethod
    def validate_faro_max_concurrency(cls, value: int) -> int:
        if not 1 <= value <= 32:
            raise ValueError("FARO_MAX_CONCURRENCY must be between 1 and 32")
        return value

    @field_validator("ocr_languages", mode="before")
    @classmethod
    def normalize_ocr_languages(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            values = value.split(",")
        elif isinstance(value, (tuple, list)):
            values = value
        else:
            raise ValueError("OCR_LANGUAGES must be a comma-separated string")
        normalized = tuple(
            unicodedata.normalize("NFKC", language).strip().casefold()
            if isinstance(language, str)
            else ""
            for language in values
        )
        if not normalized or any(not _LANGUAGE_NAME.fullmatch(language) for language in normalized):
            raise ValueError("OCR_LANGUAGES must contain safe language names")
        return tuple(dict.fromkeys(normalized))

    @field_validator("session_cookie_name")
    @classmethod
    def validate_session_cookie_name(cls, value: str) -> str:
        if not _COOKIE_NAME.fullmatch(value):
            raise ValueError("SESSION_COOKIE_NAME must be a valid cookie token")
        return value

    @field_validator("session_ttl_seconds")
    @classmethod
    def validate_session_ttl_seconds(cls, value: int) -> int:
        if not 3600 <= value <= 2_592_000:
            raise ValueError("SESSION_TTL_SECONDS must be between 3600 and 2592000")
        return value

    @field_validator("login_max_attempts")
    @classmethod
    def validate_login_max_attempts(cls, value: int) -> int:
        if not 1 <= value <= 100:
            raise ValueError("LOGIN_MAX_ATTEMPTS must be between 1 and 100")
        return value

    @field_validator("login_lockout_seconds")
    @classmethod
    def validate_login_lockout_seconds(cls, value: int) -> int:
        if not 1 <= value <= 86_400:
            raise ValueError("LOGIN_LOCKOUT_SECONDS must be between 1 and 86400")
        return value

    @field_validator("session_purge_probability")
    @classmethod
    def validate_session_purge_probability(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("SESSION_PURGE_PROBABILITY must be between 0.0 and 1.0")
        return value

    @field_validator("register_max_attempts")
    @classmethod
    def validate_register_max_attempts(cls, value: int) -> int:
        if not 1 <= value <= 1000:
            raise ValueError("REGISTER_MAX_ATTEMPTS must be between 1 and 1000")
        return value

    @field_validator("register_lockout_seconds")
    @classmethod
    def validate_register_lockout_seconds(cls, value: int) -> int:
        if not 1 <= value <= 86_400:
            raise ValueError("REGISTER_LOCKOUT_SECONDS must be between 1 and 86400")
        return value

    @field_validator("citation_hmac_secret")
    @classmethod
    def validate_citation_hmac_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value()
        if raw != raw.strip() or len(raw) < 32:
            raise ValueError("CITATION_HMAC_SECRET must be a trimmed 32+ character value")
        return value

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
        elif object_endpoint.scheme.casefold() != "https":
            errors.append("OBJECT_STORAGE_ENDPOINT must use HTTPS in production")
        object_access_key = self.object_storage_access_key
        trimmed_object_access_key = object_access_key.strip()
        if object_access_key != trimmed_object_access_key or len(trimmed_object_access_key) < 3:
            errors.append("OBJECT_STORAGE_ACCESS_KEY must be trimmed and at least 3 characters")
        if trimmed_object_access_key.casefold() in _DEVELOPMENT_OBJECT_ACCESS_KEYS:
            errors.append("OBJECT_STORAGE_ACCESS_KEY must be replaced")
        object_secret_key = self.object_storage_secret_key.get_secret_value()
        trimmed_object_secret_key = object_secret_key.strip()
        if object_secret_key != trimmed_object_secret_key or len(trimmed_object_secret_key) < 8:
            errors.append("OBJECT_STORAGE_SECRET_KEY must be trimmed and at least 8 characters")
        if trimmed_object_secret_key.casefold() in _DEVELOPMENT_OBJECT_SECRETS:
            errors.append("OBJECT_STORAGE_SECRET_KEY must be replaced")
        if self.web_origin.startswith("http://"):
            errors.append("WEB_ORIGIN must use HTTPS")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
