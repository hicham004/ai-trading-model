"""Application configuration.

All settings come from environment variables (optionally loaded from a local
``.env`` file). Defaults are safe, non-secret, and point at the local Docker
PostgreSQL service defined in ``docker-compose.yml``.

IMPORTANT (Phase 1 safety):
- This file only configures PUBLIC market-data access and local storage.
- It must never hold API keys, account credentials, or other secrets.
- ``LIVE_TRADING_ENABLED`` is a hard lock that must stay ``False`` in Phase 1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

# Loading a local .env is optional. If python-dotenv is installed we use it so
# beginners can keep settings in one place, but the app also works with plain
# environment variables (or the defaults below).
try:  # pragma: no cover - tiny optional convenience
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass


def _get_bool(name: str, default: bool) -> bool:
    """Read a boolean-ish environment variable in a beginner-friendly way."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Strongly-typed view of the environment configuration."""

    # Public OKX REST base URL. Public market-data endpoints only.
    okx_base_url: str = os.getenv("OKX_PUBLIC_API_BASE_URL", "https://www.okx.com")

    # How long to wait (seconds) for a single OKX HTTP request.
    okx_request_timeout: float = float(os.getenv("OKX_REQUEST_TIMEOUT", "10"))

    # How many times to retry a failed network request before giving up.
    okx_max_retries: int = int(os.getenv("OKX_MAX_RETRIES", "3"))

    # SQLAlchemy database URL. Defaults to the local Docker PostgreSQL service.
    # The password here is a LOCAL-ONLY, non-secret development default. Never
    # put a real credential in code or commit one to Git.
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://trading:trading_local_dev@localhost:5432/trading",
    )

    app_env: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # Phase 1 hard safety lock. Keep this False. The codebase contains no live
    # execution path; this flag only documents and enforces that intent.
    live_trading_enabled: bool = _get_bool("LIVE_TRADING_ENABLED", False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings."""
    settings = Settings()

    # Defense in depth: refuse to ever run with the live-trading lock disabled.
    if settings.live_trading_enabled:
        raise RuntimeError(
            "LIVE_TRADING_ENABLED is True, but Phase 1 forbids live trading. "
            "This project has no live execution path. Set it back to false."
        )
    return settings
