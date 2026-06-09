"""Assemble a validated Phase 4 paper-trading run from settings + overrides.

A :class:`PaperRunConfig` is the single, validated description of one paper
run: which simulation-only strategy, instruments, and timeframe to use, the
starting virtual cash, the cost model, the risk limits, and the loop cadence.
It knows how to build the concrete (accepted) strategy, the Phase 4 risk
manager, the engine config, and a fresh virtual account, plus a JSON-able
snapshot for the audit ledger.

Defaults come from :class:`app.config.Settings`; the CLI runner overrides them.
Nothing here references credentials, private endpoints, or order APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from typing import Tuple

from app.config import Settings, get_settings
from app.okx.client import ALLOWED_INSTRUMENTS
from app.paper.account import PaperAccount
from app.paper.engine import PaperEngineConfig
from app.paper.risk import PaperRiskLimits, PaperRiskManager
from app.risk.manager import RiskLimits
from app.strategy.base import Strategy
from app.strategy.registry import available_strategies, build_strategy
from app.strategy.timeframes import parse_timeframe


@dataclass(frozen=True)
class PaperRunConfig:
    """Validated description of one paper-trading run (SIMULATION ONLY)."""

    account_name: str = "default"
    strategy_name: str = "ma_crossover"
    instruments: Tuple[str, ...] = ("BTC-USDT",)
    timeframe: str = "1m"
    starting_cash: float = 10_000.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    min_confidence: float = 0.60
    max_risk_per_trade: float = 0.01
    max_position_size: float = 0.25
    max_total_exposure: float = 0.50
    max_daily_loss: float = 0.05
    max_open_positions: int = 1
    max_quote_age_seconds: float = 10.0
    max_candle_age_seconds: float = 180.0
    poll_seconds: float = 1.0
    window_size: int = 300
    lock_stale_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.account_name.strip():
            raise ValueError("account_name must not be empty")
        if len(self.account_name) > 64:
            raise ValueError("account_name must be at most 64 characters")
        if self.strategy_name not in available_strategies():
            raise ValueError(
                f"unknown strategy {self.strategy_name!r}. "
                f"Available: {', '.join(available_strategies())}"
            )
        if not self.instruments:
            raise ValueError("at least one instrument is required")
        if len(set(self.instruments)) != len(self.instruments):
            raise ValueError("duplicate instruments are not allowed")
        for instrument in self.instruments:
            if instrument not in ALLOWED_INSTRUMENTS:
                raise ValueError(
                    f"instrument {instrument!r} is not allowed "
                    f"(allowed: {', '.join(ALLOWED_INSTRUMENTS)})"
                )
        # Validate the timeframe up front (fail closed on an unsupported value).
        parse_timeframe(self.timeframe)
        if self.timeframe != "1m":
            raise ValueError(
                "Phase 4 currently supports timeframe '1m' only because the "
                "approved live public candle feed is candle1m"
            )
        for label, value in (
            ("starting_cash", self.starting_cash),
            ("max_quote_age_seconds", self.max_quote_age_seconds),
            ("max_candle_age_seconds", self.max_candle_age_seconds),
            ("poll_seconds", self.poll_seconds),
            ("lock_stale_seconds", self.lock_stale_seconds),
        ):
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be a positive finite number")
        for label, value in (
            ("fee_rate", self.fee_rate),
            ("slippage_rate", self.slippage_rate),
        ):
            if not isfinite(value) or not 0.0 <= value < 1.0:
                raise ValueError(f"{label} must be in [0.0, 1.0)")
        for label, value in (
            ("min_confidence", self.min_confidence),
            ("max_risk_per_trade", self.max_risk_per_trade),
            ("max_position_size", self.max_position_size),
            ("max_total_exposure", self.max_total_exposure),
            ("max_daily_loss", self.max_daily_loss),
        ):
            if not isfinite(value) or not 0.0 < value <= 1.0:
                raise ValueError(f"{label} must be in (0.0, 1.0]")
        for label, value, minimum in (
            ("max_open_positions", self.max_open_positions, 1),
            ("window_size", self.window_size, 2),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{label} must be an integer >= {minimum}")

    # -- builders -----------------------------------------------------------

    def build_strategy(self) -> Strategy:
        return build_strategy(self.strategy_name)

    def build_engine_config(self) -> PaperEngineConfig:
        return PaperEngineConfig(
            instruments=tuple(self.instruments),
            timeframe=self.timeframe,
            fee_rate=self.fee_rate,
            slippage_rate=self.slippage_rate,
            window_size=self.window_size,
            max_candle_age=timedelta(seconds=self.max_candle_age_seconds),
        )

    def build_risk_manager(self) -> PaperRiskManager:
        base = RiskLimits(
            max_risk_per_trade=self.max_risk_per_trade,
            max_daily_loss=self.max_daily_loss,
            max_position_size=self.max_position_size,
            min_confidence=self.min_confidence,
            max_data_staleness=timedelta(seconds=self.max_candle_age_seconds),
            # max_leverage stays 1.0 (no leverage) and require_stop_loss True.
        )
        limits = PaperRiskLimits(
            base=base,
            max_total_exposure=self.max_total_exposure,
            max_open_positions=self.max_open_positions,
            max_quote_age=timedelta(seconds=self.max_quote_age_seconds),
        )
        return PaperRiskManager(limits)

    def build_account(self) -> PaperAccount:
        return PaperAccount(starting_cash=self.starting_cash)

    def config_snapshot(self) -> dict:
        """JSON-able config for the audit ledger (no secrets)."""
        return {
            "strategy": self.strategy_name,
            "instruments": list(self.instruments),
            "timeframe": self.timeframe,
            "starting_cash": self.starting_cash,
            "fee_rate": self.fee_rate,
            "slippage_rate": self.slippage_rate,
            "min_confidence": self.min_confidence,
            "max_risk_per_trade": self.max_risk_per_trade,
            "max_position_size": self.max_position_size,
            "max_total_exposure": self.max_total_exposure,
            "max_daily_loss": self.max_daily_loss,
            "max_open_positions": self.max_open_positions,
            "max_quote_age_seconds": self.max_quote_age_seconds,
            "max_candle_age_seconds": self.max_candle_age_seconds,
            "poll_seconds": self.poll_seconds,
            "window_size": self.window_size,
            "lock_stale_seconds": self.lock_stale_seconds,
            "simulation_only": True,
        }


def config_from_settings(settings: Settings | None = None, **overrides) -> PaperRunConfig:
    """Build a :class:`PaperRunConfig` from settings, applying any overrides.

    ``overrides`` whose value is ``None`` are ignored, so the CLI can pass
    ``None`` for unspecified flags and fall back to the configured defaults.
    """
    settings = settings or get_settings()
    base = dict(
        account_name=settings.paper_account_name,
        strategy_name=settings.paper_strategy,
        instruments=tuple(settings.paper_instruments),
        timeframe=settings.paper_timeframe,
        starting_cash=settings.paper_starting_cash,
        fee_rate=settings.paper_fee_rate,
        slippage_rate=settings.paper_slippage_rate,
        min_confidence=settings.paper_min_confidence,
        max_risk_per_trade=settings.paper_max_risk_per_trade,
        max_position_size=settings.paper_max_position_size,
        max_total_exposure=settings.paper_max_total_exposure,
        max_daily_loss=settings.paper_max_daily_loss,
        max_open_positions=settings.paper_max_open_positions,
        max_quote_age_seconds=settings.paper_max_quote_age_seconds,
        max_candle_age_seconds=settings.paper_max_candle_age_seconds,
        poll_seconds=settings.paper_poll_seconds,
        window_size=settings.paper_window_size,
        lock_stale_seconds=settings.paper_lock_stale_seconds,
    )
    for key, value in overrides.items():
        if value is not None:
            if key == "instruments":
                value = tuple(value)
            base[key] = value
    return PaperRunConfig(**base)
