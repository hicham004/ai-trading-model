"""Persisted Phase 6a shadow-period configuration (fail-closed loader).

The caps live in ``config/shadow_period.json`` (checked in, not run flags).
The loader refuses any configuration that would LOOSEN the reviewed demo
settings: the shadow period may only tighten them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from app.config import Settings

DEFAULT_CONFIG_PATH = Path("config/shadow_period.json")


class ShadowConfigError(ValueError):
    """Raised when the shadow configuration is missing, invalid, or looser
    than the reviewed demo settings (fail closed)."""


@dataclass(frozen=True)
class ShadowConfig:
    """Validated Phase 6a caps and supervisor limits."""

    instrument: str
    timeframe: str
    max_order_notional_usdt: float
    max_open_positions: int
    max_entries_per_day: int
    max_daily_loss_usdt: float
    arm_ttl_seconds: float
    rearm_interval_seconds: float
    max_restarts: int
    restart_window_seconds: float
    restart_backoff_seconds: float
    heartbeat_interval_seconds: float
    report_refresh_seconds: float
    shadow_dir: Path


def _require(data: dict, key: str):
    if key not in data:
        raise ShadowConfigError(f"shadow config is missing required key {key!r}")
    return data[key]


def _positive(value, key: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ShadowConfigError(f"shadow config {key!r} is not a number: {value!r}") from exc
    if not out > 0:
        raise ShadowConfigError(f"shadow config {key!r} must be positive: {value!r}")
    return out


def _positive_int(value, key: str) -> int:
    out = _positive(value, key)
    if int(out) != out:
        raise ShadowConfigError(f"shadow config {key!r} must be an integer: {value!r}")
    return int(out)


def load_shadow_config(
    settings: Settings, path: Path = DEFAULT_CONFIG_PATH
) -> ShadowConfig:
    """Load and validate the shadow config against the reviewed demo settings.

    Fails closed (raises :class:`ShadowConfigError`) when the file is missing,
    malformed, or any cap would loosen the corresponding reviewed setting.
    """
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError as exc:
        raise ShadowConfigError(f"shadow config not found at {path}") from exc
    except (OSError, ValueError) as exc:
        raise ShadowConfigError(f"shadow config unreadable/malformed at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ShadowConfigError("shadow config must be a JSON object")

    instrument = str(_require(data, "instrument"))
    if instrument not in settings.demo_instruments:
        raise ShadowConfigError(
            f"shadow instrument {instrument!r} is not in the approved demo "
            f"instruments {tuple(settings.demo_instruments)!r}"
        )

    # The strategy timeframe is persisted config (owner decision, June 12,
    # 2026: 1H per the clearance study). It must parse AND its candle channel
    # must be on the public-WS fail-closed allowlist; anything else refuses.
    timeframe = str(_require(data, "timeframe"))
    from app.exchange.okx_public_ws import SUPPORTED_CANDLE_CHANNELS
    from app.strategy.timeframes import parse_timeframe

    try:
        parse_timeframe(timeframe)
    except ValueError as exc:
        raise ShadowConfigError(f"shadow timeframe invalid: {exc}") from exc
    if f"candle{timeframe}" not in SUPPORTED_CANDLE_CHANNELS:
        raise ShadowConfigError(
            f"shadow timeframe {timeframe!r} has no approved public candle "
            f"channel (allowed: {SUPPORTED_CANDLE_CHANNELS})"
        )

    notional = _positive(_require(data, "max_order_notional_usdt"), "max_order_notional_usdt")
    if notional > settings.demo_max_order_notional:
        raise ShadowConfigError(
            "shadow max_order_notional_usdt may only tighten the reviewed cap "
            f"({notional} > {settings.demo_max_order_notional})"
        )
    open_positions = _positive_int(_require(data, "max_open_positions"), "max_open_positions")
    if open_positions > settings.demo_max_open_positions:
        raise ShadowConfigError(
            "shadow max_open_positions may only tighten the reviewed cap "
            f"({open_positions} > {settings.demo_max_open_positions})"
        )

    return ShadowConfig(
        instrument=instrument,
        timeframe=timeframe,
        max_order_notional_usdt=notional,
        max_open_positions=open_positions,
        max_entries_per_day=_positive_int(_require(data, "max_entries_per_day"), "max_entries_per_day"),
        max_daily_loss_usdt=_positive(_require(data, "max_daily_loss_usdt"), "max_daily_loss_usdt"),
        arm_ttl_seconds=_positive(_require(data, "arm_ttl_seconds"), "arm_ttl_seconds"),
        rearm_interval_seconds=_positive(_require(data, "rearm_interval_seconds"), "rearm_interval_seconds"),
        max_restarts=_positive_int(_require(data, "max_restarts"), "max_restarts"),
        restart_window_seconds=_positive(_require(data, "restart_window_seconds"), "restart_window_seconds"),
        restart_backoff_seconds=_positive(_require(data, "restart_backoff_seconds"), "restart_backoff_seconds"),
        heartbeat_interval_seconds=_positive(_require(data, "heartbeat_interval_seconds"), "heartbeat_interval_seconds"),
        report_refresh_seconds=_positive(_require(data, "report_refresh_seconds"), "report_refresh_seconds"),
        shadow_dir=Path(str(data.get("shadow_dir", "logs/shadow"))),
    )


def shadow_settings(settings: Settings, cfg: ShadowConfig) -> Settings:
    """Return the runtime settings for the shadow run.

    The strategy timeframe comes from the persisted shadow config (never a
    code constant). The replaced value flows into EVERY consumer — the
    driver's candle filter/interval/gap checks, the immutable account
    identity, the warmup loader, and the supervisor's shadow evaluation — so
    there is one timeframe everywhere (no mixed-timeframe logic).
    """
    return replace(settings, demo_timeframe=cfg.timeframe)
