import pytest
from pydantic import ValidationError

from clinical_trial_matcher.core.config import Settings

BASE = {
    "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
    "database_url_sync": "postgresql://u:p@localhost:5432/db",
}


def test_cors_origins_are_split_and_trimmed():
    settings = Settings(_env_file=None, cors_origins="http://a, http://b ", **BASE)
    assert settings.cors_origins_list == ["http://a", "http://b"]


def test_database_urls_are_normalized_to_expected_drivers():
    settings = Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost:5432/db",
        database_url_sync="postgresql://u:p@localhost:5432/db",
    )
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.database_url_sync.startswith("postgresql+psycopg2://")


def test_development_defaults_are_safe_for_local_use():
    settings = Settings(_env_file=None, app_env="development", **BASE)
    assert settings.docs_enabled_effective is True
    assert settings.log_json_effective is False
    assert settings.llm_provider == "local"


def test_production_rejects_default_secret():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            secret_key="change-me-in-production",
            auto_create_tables=False,
            trusted_hosts="example.com",
            **BASE,
        )


def test_production_rejects_wildcard_cors():
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        Settings(
            _env_file=None,
            app_env="production",
            secret_key="a" * 32,
            cors_origins="*",
            auto_create_tables=False,
            trusted_hosts="example.com",
            **BASE,
        )


def test_production_rejects_auto_create_tables():
    with pytest.raises(ValidationError, match="AUTO_CREATE_TABLES"):
        Settings(
            _env_file=None,
            app_env="production",
            secret_key="a" * 32,
            cors_origins="https://example.com",
            trusted_hosts="example.com",
            auto_create_tables=True,
            **BASE,
        )


def test_production_rejects_non_local_llm():
    with pytest.raises(ValidationError, match="LLM_PROVIDER"):
        Settings(
            _env_file=None,
            app_env="production",
            secret_key="a" * 32,
            cors_origins="https://example.com",
            trusted_hosts="example.com",
            auto_create_tables=False,
            llm_provider="groq",
            **BASE,
        )


def test_production_accepts_hardened_settings():
    settings = Settings(
        _env_file=None,
        app_env="production",
        secret_key="a" * 32,
        cors_origins="https://app.example.com",
        trusted_hosts="app.example.com",
        auto_create_tables=False,
        llm_provider="local",
        debug=False,
        **BASE,
    )
    assert settings.is_production is True
    assert settings.docs_enabled_effective is False
    assert settings.log_json_effective is True
