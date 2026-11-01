"""Test environment setup.

Environment variables must be set before any application module imports
`settings`, which is constructed at import time.
"""

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/clinical_trials_test",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://test:test@localhost:5432/clinical_trials_test",
)
os.environ.setdefault("AUTO_CREATE_TABLES", "false")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("LLM_PROVIDER", "local")
os.environ.setdefault("TRUSTED_HOSTS", "testserver,localhost,127.0.0.1")
os.environ.setdefault("CORS_ORIGINS", "http://testserver")
os.environ.setdefault("LOG_LEVEL", "WARNING")
