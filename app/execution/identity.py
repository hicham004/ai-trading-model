"""Stable, non-secret identity for one demo execution account."""

from __future__ import annotations

from app.config import Settings


def demo_identity_config(settings: Settings) -> dict:
    """Return every setting that can change Phase 5 execution behavior.

    Demo account ledgers are immutable. Changing any strategy, risk, transport,
    timing, or endpoint setting therefore requires a new account name instead
    of silently reusing history produced under different rules.
    """
    return {
        "strategy": settings.demo_strategy,
        "instruments": list(settings.demo_instruments),
        "timeframe": settings.demo_timeframe,
        "quote_ccy": settings.demo_quote_currency,
        "order_type": settings.demo_order_type,
        "strategy_window_size": settings.paper_window_size,
        "min_confidence": settings.demo_min_confidence,
        "max_risk_per_trade": settings.demo_max_risk_per_trade,
        "max_position_size": settings.demo_max_position_size,
        "max_total_exposure": settings.demo_max_total_exposure,
        "max_daily_loss": settings.demo_max_daily_loss,
        "max_open_positions": settings.demo_max_open_positions,
        "max_order_notional": settings.demo_max_order_notional,
        "max_quote_age_seconds": settings.demo_max_quote_age_seconds,
        "max_candle_age_seconds": settings.demo_max_candle_age_seconds,
        "price_band": settings.demo_price_band,
        "allowed_account_levels": list(settings.demo_allowed_acct_levels),
        "request_timeout": settings.demo_request_timeout,
        "max_retries": settings.demo_max_retries,
        "clock_drift_max_seconds": settings.demo_clock_drift_max_seconds,
        "rate_limit_per_2s": settings.demo_rate_limit_per_2s,
        "poll_seconds": settings.demo_poll_seconds,
        "lock_stale_seconds": settings.demo_lock_stale_seconds,
        "arm_ttl_seconds": settings.demo_arm_ttl_seconds,
        "heartbeat_seconds": settings.demo_heartbeat_seconds,
        "reconcile_interval_seconds": settings.demo_reconcile_interval_seconds,
        "private_stale_seconds": settings.demo_private_stale_seconds,
        "demo_rest_base_url": settings.okx_demo_rest_base_url,
        "demo_private_ws_url": settings.okx_demo_private_ws_url,
        "public_ws_url": settings.okx_public_ws_url,
        "business_ws_url": settings.okx_business_ws_url,
    }
