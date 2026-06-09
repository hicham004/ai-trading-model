"""A tiny registry so tools can build a strategy by name.

This keeps CLI scripts and future services decoupled from concrete strategy
classes, and gives one obvious place to register new strategies.
"""

from __future__ import annotations

from typing import Callable, Dict, List

from app.strategy.base import Strategy
from app.strategy.library import (
    Breakout,
    MovingAverageCrossover,
    RsiVwapMeanReversion,
)

# Map a short name -> a factory that builds the strategy with default params.
_REGISTRY: Dict[str, Callable[[], Strategy]] = {
    "ma_crossover": MovingAverageCrossover,
    "rsi_vwap": RsiVwapMeanReversion,
    "breakout": Breakout,
}


def available_strategies() -> List[str]:
    """Return the registered strategy names (sorted)."""
    return sorted(_REGISTRY)


def build_strategy(name: str) -> Strategy:
    """Build a strategy by registry name using its default parameters."""
    try:
        factory = _REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown strategy {name!r}. Available: {', '.join(available_strategies())}"
        ) from None
    return factory()
