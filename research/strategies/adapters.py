"""Wrap a research candidate into the reviewed ``app.strategy.base.Strategy`` contract.

The adapter lets the event-driven simulator (and, after a reviewed PR, the
paper/demo runtimes) consume a candidate unchanged: one ``Signal`` per candle,
``LONG`` with a stop-loss price while the candidate wants to be long, ``FLAT``
otherwise. Confidence comes from a :class:`StrengthCalibrator` (historical
hit-rate buckets) or a fixed fallback — never from a made-up formula.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence

import numpy as np

from app.strategy.base import MarketCandle, Signal, SignalAction, Strategy
from research.calibration import StrengthCalibrator
from research.data import frame_from_candles
from research.strategies.base import FeatureContext, ResearchStrategy, gate_entries
from research.strategies.s0_filters import NoTradeConfig, tradeable_mask


class ResearchStrategyAdapter(Strategy):
    def __init__(
        self,
        candidate: ResearchStrategy,
        params: Mapping[str, Any],
        context: FeatureContext,
        *,
        calibrator: Optional[StrengthCalibrator] = None,
        fallback_confidence: float = 0.60,
        no_trade: Optional[NoTradeConfig] = NoTradeConfig(),
        fallback_stop_pct: float = 0.03,
    ) -> None:
        self.candidate = candidate
        self.params = candidate.params_with_defaults(params)
        self.context = context
        self.calibrator = calibrator
        self.fallback_confidence = float(fallback_confidence)
        self.no_trade = no_trade
        self.fallback_stop_pct = float(fallback_stop_pct)
        self.name = f"research_{candidate.key.replace('+', '_')}"

    def confidence_for(self, strength: float) -> float:
        if self.calibrator is not None and self.calibrator.fitted and np.isfinite(strength):
            return float(min(1.0, max(0.0, self.calibrator.confidence(strength))))
        return self.fallback_confidence

    def generate_signals(self, candles: Sequence[MarketCandle]) -> List[Signal]:
        if not candles:
            return []
        df = frame_from_candles(list(candles))
        frame = self.candidate.build(df, self.params, self.context)
        desired_s = frame.desired
        if self.no_trade is not None:
            ok = tradeable_mask(df, self.context.timeframe, self.context.periods_per_year, self.no_trade)
            desired_s = gate_entries(desired_s, ok)  # block entries only; keep open longs
        desired = desired_s.to_numpy(dtype=bool)
        stop_dist = frame.stop_distance.to_numpy(dtype=float)
        strength = frame.strength.to_numpy(dtype=float)
        signals: List[Signal] = []
        for i, candle in enumerate(candles):
            if desired[i]:
                dist = stop_dist[i]
                if not (np.isfinite(dist) and dist > 0):
                    dist = candle.close * self.fallback_stop_pct
                stop = max(candle.close - dist, candle.close * 0.01)
                signals.append(
                    Signal(
                        timestamp=candle.timestamp,
                        instrument=candle.instrument,
                        action=SignalAction.LONG,
                        confidence=self.confidence_for(strength[i]),
                        reason=f"{self.candidate.key}: desired long",
                        stop_loss=stop,
                    )
                )
            else:
                signals.append(self._flat(candle, reason=f"{self.candidate.key}: flat"))
        return self._validate_output(candles, signals)
