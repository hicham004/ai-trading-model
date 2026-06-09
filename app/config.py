"""Application configuration.

All settings come from environment variables (optionally loaded from a local
``.env`` file). Defaults are safe, non-secret, and point at the local Docker
PostgreSQL service defined in ``docker-compose.yml``.

IMPORTANT (current safety boundary):
- This file only configures PUBLIC market-data access and local storage.
- It must never hold API keys, account credentials, or other secrets.
- ``LIVE_TRADING_ENABLED`` is a hard lock that must stay ``False``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from math import isfinite

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


def _get_positive_float(name: str, default: float) -> float:
    """Read a positive finite float, failing closed on invalid configuration."""
    raw = os.getenv(name)
    try:
        value = default if raw is None else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return value


def _get_positive_int(name: str, default: int, *, maximum: int | None = None) -> int:
    """Read a bounded positive integer, failing closed on invalid values."""
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0 or (maximum is not None and value > maximum):
        suffix = f" no greater than {maximum}" if maximum is not None else ""
        raise ValueError(f"{name} must be a positive integer{suffix}")
    return value


def _get_nonnegative_unit_float(name: str, default: float) -> float:
    """Read a fee/slippage fraction in [0.0, 1.0), failing closed otherwise."""
    raw = os.getenv(name)
    try:
        value = default if raw is None else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number in [0.0, 1.0)") from exc
    if not isfinite(value) or not 0.0 <= value < 1.0:
        raise ValueError(f"{name} must be a number in [0.0, 1.0)")
    return value


def _get_fraction(name: str, default: float) -> float:
    """Read a fraction in (0.0, 1.0], failing closed on invalid configuration."""
    raw = os.getenv(name)
    try:
        value = default if raw is None else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number in (0.0, 1.0]") from exc
    if not isfinite(value) or not 0.0 < value <= 1.0:
        raise ValueError(f"{name} must be a number in (0.0, 1.0]")
    return value


def _get_instruments(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Read a comma-separated instrument list (membership validated downstream)."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    items = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not items:
        raise ValueError(f"{name} must list at least one instrument")
    if len(set(items)) != len(items):
        raise ValueError(f"{name} must not contain duplicate instruments")
    return items


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

    # Hard safety lock. Keep this False. The codebase contains no live
    # execution path; this flag only documents and enforces that intent.
    live_trading_enabled: bool = _get_bool("LIVE_TRADING_ENABLED", False)

    # --- Phase 3A: live PUBLIC market-data observation (no trading) ---------
    # Public, UNAUTHENTICATED OKX WebSocket URLs. These are market-data only;
    # they never carry credentials. Tickers/trades use the public endpoint and
    # candles use the business endpoint (both public).
    okx_public_ws_url: str = field(
        default_factory=lambda: os.getenv(
            "OKX_PUBLIC_WS_URL", "wss://ws.okx.com:8443/ws/v5/public"
        )
    )
    okx_business_ws_url: str = field(
        default_factory=lambda: os.getenv(
            "OKX_BUSINESS_WS_URL", "wss://ws.okx.com:8443/ws/v5/business"
        )
    )

    # When True, the FastAPI app opens the public stream in-process on startup
    # so the read-only /live endpoints show live data. Default False so imports
    # and tests never open a WebSocket; it must be opted into explicitly.
    live_ws_autostart: bool = field(
        default_factory=lambda: _get_bool("LIVE_WS_AUTOSTART", False)
    )

    # Seconds without accepted market data before the feed is reported stale.
    live_stale_after_seconds: float = field(
        default_factory=lambda: _get_positive_float(
            "LIVE_STALE_AFTER_SECONDS", 30.0
        )
    )

    # --- Phase 3B: optional durable PUBLIC market-data writes --------------
    # Off by default so the Phase 3A observation path remains usable without a
    # database. Enabling this stores confirmed candles and sampled, validated
    # order-book snapshots only; it never stores account or order data.
    live_persistence_enabled: bool = field(
        default_factory=lambda: _get_bool("LIVE_PERSISTENCE_ENABLED", False)
    )
    live_persistence_poll_seconds: float = field(
        default_factory=lambda: _get_positive_float(
            "LIVE_PERSISTENCE_POLL_SECONDS", 1.0
        )
    )
    live_order_book_snapshot_seconds: float = field(
        default_factory=lambda: _get_positive_float(
            "LIVE_ORDER_BOOK_SNAPSHOT_SECONDS", 5.0
        )
    )
    live_order_book_depth: int = field(
        default_factory=lambda: _get_positive_int(
            "LIVE_ORDER_BOOK_DEPTH", 20, maximum=400
        )
    )
    live_order_book_retention: int = field(
        default_factory=lambda: _get_positive_int(
            "LIVE_ORDER_BOOK_RETENTION", 10_000
        )
    )
    live_backfill_max_bars: int = field(
        default_factory=lambda: _get_positive_int(
            "LIVE_BACKFILL_MAX_BARS", 300, maximum=300
        )
    )

    # --- Phase 4: local paper trading (SIMULATION ONLY) --------------------
    # Defaults for the opt-in paper-trading runner (scripts/run_paper_trading.py).
    # Every value is a non-secret simulation parameter; the CLI can override
    # them. None of these enable real, demo, authenticated, or order access -
    # the runner only consumes PUBLIC market data and fills virtually.
    paper_account_name: str = field(
        default_factory=lambda: os.getenv("PAPER_ACCOUNT_NAME", "default")
    )
    paper_strategy: str = field(
        default_factory=lambda: os.getenv("PAPER_STRATEGY", "ma_crossover")
    )
    paper_instruments: tuple = field(
        default_factory=lambda: _get_instruments("PAPER_INSTRUMENTS", ("BTC-USDT",))
    )
    paper_timeframe: str = field(
        default_factory=lambda: os.getenv("PAPER_TIMEFRAME", "1m")
    )
    paper_starting_cash: float = field(
        default_factory=lambda: _get_positive_float("PAPER_STARTING_CASH", 10_000.0)
    )
    paper_fee_rate: float = field(
        default_factory=lambda: _get_nonnegative_unit_float("PAPER_FEE_RATE", 0.001)
    )
    paper_slippage_rate: float = field(
        default_factory=lambda: _get_nonnegative_unit_float("PAPER_SLIPPAGE_RATE", 0.0005)
    )
    paper_min_confidence: float = field(
        default_factory=lambda: _get_fraction("PAPER_MIN_CONFIDENCE", 0.60)
    )
    paper_max_risk_per_trade: float = field(
        default_factory=lambda: _get_fraction("PAPER_MAX_RISK_PER_TRADE", 0.01)
    )
    paper_max_position_size: float = field(
        default_factory=lambda: _get_fraction("PAPER_MAX_POSITION_SIZE", 0.25)
    )
    paper_max_total_exposure: float = field(
        default_factory=lambda: _get_fraction("PAPER_MAX_TOTAL_EXPOSURE", 0.50)
    )
    paper_max_daily_loss: float = field(
        default_factory=lambda: _get_fraction("PAPER_MAX_DAILY_LOSS", 0.05)
    )
    paper_max_open_positions: int = field(
        default_factory=lambda: _get_positive_int("PAPER_MAX_OPEN_POSITIONS", 1)
    )
    paper_max_quote_age_seconds: float = field(
        default_factory=lambda: _get_positive_float("PAPER_MAX_QUOTE_AGE_SECONDS", 10.0)
    )
    paper_max_candle_age_seconds: float = field(
        default_factory=lambda: _get_positive_float("PAPER_MAX_CANDLE_AGE_SECONDS", 180.0)
    )
    paper_poll_seconds: float = field(
        default_factory=lambda: _get_positive_float("PAPER_POLL_SECONDS", 1.0)
    )
    paper_window_size: int = field(
        default_factory=lambda: _get_positive_int("PAPER_WINDOW_SIZE", 300)
    )
    paper_lock_stale_seconds: float = field(
        default_factory=lambda: _get_positive_float("PAPER_LOCK_STALE_SECONDS", 60.0)
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings."""
    settings = Settings()

    # Defense in depth: refuse to ever run with the live-trading lock disabled.
    if settings.live_trading_enabled:
        raise RuntimeError(
            "LIVE_TRADING_ENABLED is True, but the current phases forbid live trading. "
            "This project has no live execution path. Set it back to false."
        )
    return settings
