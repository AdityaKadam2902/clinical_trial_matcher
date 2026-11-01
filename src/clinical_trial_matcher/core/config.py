"""Application configuration.

All environment variables are validated here at startup. Production settings
fail fast when insecure defaults are still present, rather than starting a
service that looks healthy but is not safe to expose.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production", "test"]
LLMProvider = Literal["local", "groq"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    # ── Runtime ──────────────────────────────────────────────────────────────
    app_env: Environment = Field(default="development")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    log_json: bool | None = Field(
        default=None,
        description="Force JSON logs. Defaults to true outside development.",
    )
    docs_enabled: bool | None = Field(
        default=None,
        description="Expose OpenAPI/Swagger. Defaults to true outside production.",
    )

    # ── Security ─────────────────────────────────────────────────────────────
    secret_key: SecretStr = Field(default=SecretStr("change-me-in-production"))
    jwt_algorithm: str = Field(default="HS256")
    jwt_issuer: str = Field(default="clinical-trial-matcher")
    jwt_audience: str = Field(default="clinical-trial-matcher-api")
    access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)
    auth_enabled: bool = Field(default=True)
    allow_registration: bool = Field(default=False)
    password_min_length: int = Field(default=12, ge=8, le=128)
    trusted_hosts: str = Field(default="localhost,127.0.0.1,testserver")
    cors_origins: str = Field(default="http://localhost:3000,http://localhost:5173")
    max_request_body_bytes: int = Field(default=1_000_000, ge=1024)
    trusted_proxy_count: int = Field(default=0, ge=0, le=10)
    patient_data_encryption_key: SecretStr | None = Field(default=None)

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str
    database_url_sync: str
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=100)
    db_echo: bool = Field(default=False)
    auto_create_tables: bool = Field(
        default=True,
        description="Development convenience. Must be false in production.",
    )

    # ── Cache / rate limiting ────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_default: str = Field(default="120/minute")
    rate_limit_match: str = Field(default="5/minute")
    rate_limit_read: str = Field(default="60/minute")
    rate_limit_auth: str = Field(default="10/minute")

    # ── Vector DB (optional) ─────────────────────────────────────────────────
    qdrant_host: str = Field(default="localhost")
    qdrant_port: int = Field(default=6333)
    qdrant_collection: str = Field(default="clinical_trials")

    # ── LLM ──────────────────────────────────────────────────────────────────
    llm_provider: LLMProvider = Field(default="local")
    local_llm_base_url: str = Field(default="http://localhost:11434/v1")
    local_llm_model: str = Field(default="llama3.1:8b")
    local_llm_api_key: SecretStr = Field(default=SecretStr("local"))
    local_llm_timeout_seconds: float = Field(default=120.0, ge=1.0, le=600.0)
    local_llm_max_eligibility_trials: int = Field(default=3, ge=1, le=50)
    eligibility_timeout_seconds: float = Field(
        default=90.0,
        ge=5.0,
        le=600.0,
        description="Hard limit for one trial's eligibility inference.",
    )
    pipeline_budget_seconds: float = Field(
        default=180.0,
        ge=30.0,
        le=900.0,
        description=(
            "Total time the match pipeline may spend on LLM evaluation. "
            "Trials that do not fit are returned as NEEDS_REVIEW."
        ),
    )
    groq_api_key: SecretStr = Field(default=SecretStr(""))
    groq_model_complex: str = Field(default="llama-3.3-70b-versatile")
    groq_model_fast: str = Field(default="llama-3.1-8b-instant")

    # ── External APIs ────────────────────────────────────────────────────────
    clinicaltrials_base_url: str = Field(default="https://clinicaltrials.gov/api/v2")
    openfda_base_url: str = Field(default="https://api.fda.gov/drug")
    rxnorm_base_url: str = Field(default="https://rxnav.nlm.nih.gov/REST")
    external_api_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)

    # ── Pagination ───────────────────────────────────────────────────────────
    default_page_size: int = Field(default=10, ge=1, le=100)
    max_page_size: int = Field(default=50, ge=1, le=200)

    # ── Observability ────────────────────────────────────────────────────────
    sentry_dsn: SecretStr | None = Field(default=None)
    otel_exporter_otlp_endpoint: str | None = Field(default=None)
    metrics_enabled: bool = Field(default=True)

    @field_validator("database_url")
    @classmethod
    def _normalize_async_database_url(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        return value

    @field_validator("database_url_sync")
    @classmethod
    def _normalize_sync_database_url(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return "postgresql+psycopg2://" + value.removeprefix("postgresql://")
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def trusted_hosts_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def docs_enabled_effective(self) -> bool:
        if self.docs_enabled is not None:
            return self.docs_enabled
        return not self.is_production

    @property
    def log_json_effective(self) -> bool:
        if self.log_json is not None:
            return self.log_json
        return not self.is_development

    @model_validator(mode="after")
    def _validate_production_safety(self) -> Settings:
        if self.is_production:
            secret = self.secret_key.get_secret_value()
            if secret in {"", "change-me-in-production"} or len(secret) < 32:
                raise ValueError("SECRET_KEY must be set to a strong value of at least 32 characters in production")
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if "*" in self.cors_origins_list:
                raise ValueError("CORS_ORIGINS must not contain '*' in production")
            if "*" in self.trusted_hosts_list:
                raise ValueError("TRUSTED_HOSTS must not contain '*' in production")
            if self.auto_create_tables:
                raise ValueError("AUTO_CREATE_TABLES must be false in production")
            if not self.auth_enabled:
                raise ValueError("AUTH_ENABLED must be true in production")
            if self.llm_provider != "local":
                raise ValueError(
                    "LLM_PROVIDER must be 'local' in production; this project "
                    "must not send patient data to a non-local model provider"
                )
            if self.allow_registration:
                raise ValueError(
                    "ALLOW_REGISTRATION must be false in production; create users with the admin bootstrap CLI instead"
                )
        if self.max_page_size < self.default_page_size:
            raise ValueError("MAX_PAGE_SIZE must be >= DEFAULT_PAGE_SIZE")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance for this process."""
    return Settings()


settings = get_settings()
