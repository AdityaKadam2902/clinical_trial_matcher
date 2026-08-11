"""
core/config.py
──────────────
Centralized configuration using Pydantic Settings.
All environment variables are validated here at startup.
If a required variable is missing, the app fails immediately with a clear error.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    # ── LLM ──────────────────────────────────────────────────
    groq_api_key: str = Field(..., description="Groq API key")
    groq_model_complex: str = Field(
        default="llama-3.3-70b-versatile",
        description="Model for complex reasoning — eligibility, drug safety, reports"
    )
    groq_model_fast: str = Field(
        default="llama-3.1-8b-instant",
        description="Model for fast/simple tasks — formatting, extraction"
    )

    # ── Database ─────────────────────────────────────────────
    database_url: str = Field(..., description="Async PostgreSQL URL")
    database_url_sync: str = Field(..., description="Sync PostgreSQL URL for Alembic")

    # ── Vector DB ────────────────────────────────────────────
    qdrant_host: str = Field(default="localhost")
    qdrant_port: int = Field(default=6333)
    qdrant_collection: str = Field(default="clinical_trials")

    # ── External APIs ─────────────────────────────────────────
    clinicaltrials_base_url: str = Field(
        default="https://clinicaltrials.gov/api/v2"
    )
    openfda_base_url: str = Field(
        default="https://api.fda.gov/drug"
    )
    rxnorm_base_url: str = Field(
        default="https://rxnav.nlm.nih.gov/REST"
    )

    # ── App ──────────────────────────────────────────────────
    app_env: str = Field(default="development")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    secret_key: str = Field(default="change-me-in-production")
    cors_origins: str = Field(default="http://localhost:3000")

    # ── Pagination ────────────────────────────────────────────
    default_page_size: int = Field(default=10)
    max_page_size: int = Field(default=50)

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.
    lru_cache means this is only created once per process.
    """
    return Settings()


settings = get_settings()
