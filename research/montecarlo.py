"""Monte Carlo robustness: trade-order bootstrap and slippage stress."""

from __future__ import annotations

from typing import Callable, Dict, Mapping, Sequence

import numpy as np

from research.engine import Costs
from research.metrics import max_drawdown


def trade_order_bootstrap(trade_returns: Sequence[float], *, n_paths: int = 1000, seed: int = 0) -> Dict[str, float]:
    """Resample the sequence of per-trade returns (with replacement) and study paths.

    Returns percentiles of terminal growth and maximum drawdown across paths.
    Compounded, all-in sizing (matches the sweep engine's default).
    """
    r = np.asarray([x for x in trade_returns if np.isfinite(x)], dtype=float)
    if r.size == 0:
        return {"n_trades": 0, "paths": 0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, r.size, size=(n_paths, r.size))
    growth = np.cumprod(1.0 + r[idx], axis=1)
    terminal = growth[:, -1]
    dds = np.array([max_drawdown(np.concatenate([[1.0], path])) for path in growth])
    return {
        "n_trades": int(r.size),
        "paths": int(n_paths),
        "terminal_p05": float(np.percentile(terminal, 5)),
        "terminal_p50": float(np.percentile(terminal, 50)),
        "terminal_p95": float(np.percentile(terminal, 95)),
        "prob_loss": float((terminal < 1.0).mean()),
        "max_dd_p50": float(np.percentile(dds, 50)),
        "max_dd_p95": float(np.percentile(dds, 95)),
        "max_dd_worst": float(dds.max()),
    }


def slippage_stress(run: Callable[[Costs], Mapping[str, float]], base: Costs, multipliers: Sequence[float] = (1.0, 2.0, 3.0), metric: str = "total_return") -> Dict[str, float]:
    """Re-run ``run`` with slippage scaled by each multiplier; report ``metric``."""
    out: Dict[str, float] = {}
    for m in multipliers:
        costs = Costs(fee_rate=base.fee_rate, slippage_rate=min(0.0999, base.slippage_rate * m))
        out[f"x{m:g}"] = float(run(costs).get(metric, float("nan")))
    return out
