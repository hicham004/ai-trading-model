"""Trader Policy v1 (plan row R18, ``docs/TRADER_PLAN_2026-11-05.md`` sections 4 and 9), SIMULATION ONLY.

The policy pieces the research engine, the Sprint 2c runner and (later, plan
row R18b) the paper fleet share:

- :data:`TIERS` — the three fixed risk budgets of section 4.1 plus the
  information-only ``risk1.5`` rule: each a sizing spec
  (:data:`research.sizing.SIZING_TIERS`) and whether the Turtle ladder
  (:mod:`research.brakes`) applies. Reference is Sprint 2c's policy unchanged.
- :data:`VARIANTS` — the pre-registered position-management variants of
  section 4.2, each behind a flag and off by default: the +1 R add, the
  conviction split, the ``trail2`` / ``trail3`` exits, the wider stop, the
  +2 R half scale-out, and S1 SOL-USDT 6H without its 30-day time stop.
- the section 4.6 gates (:func:`acceptance_check_r18`), the size-neutral
  variant rule (:func:`variant_counts`), the brake-cost flag
  (:func:`brake_cost`), and the per-trade statistics the report shows
  (:func:`trade_stats`: expectancy in R, payoff ratio, gaps past the stop,
  re-entries within two bars of a stop-out, effective risk per trade, how
  often the cap binds, the adds' worst case).

Nothing here can reach an order or an account; every number produced with
these rules is a simulation. No tier, brake or variant touches the demo
shadow run, its caps or the 0.60 confidence floor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from research import features
from research.brakes import BRAKES_OFF, TRADER_BRAKES, TURTLE_LADDER_ONLY, BrakeSpec, TurtleLadder
from research.engine import EngineVariants
from research.report_v1c import GATES, _num
from research.sizing import SIZING_TIERS, SizingSpec, fraction_components
from research.strategies.base import FeatureContext, ResearchStrategy, days_to_bars
from research.strategies.round1 import VOLUME_Z_DAYS, VOLUME_Z_MIN
from research.strategies.s0_filters import NoTradeConfig
from research.sweep import Frames, build_frames

# -- the tiers ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyTier:
    """One risk budget: a sizing spec and whether the entries-only Turtle ladder applies."""

    name: str
    sizing: SizingSpec
    turtle_ladder: bool
    description: str

    @property
    def label(self) -> str:
        return self.sizing.label + (" turtle" if self.turtle_ladder else "")

    def brakes(self, *, on: bool, heat_cap: Optional[float] = None) -> Optional[BrakeSpec]:
        """The brake spec of this tier: its ladder alone (``on=False``) or every brake of section 4.3 (``on=True``)."""
        if on:
            spec = TRADER_BRAKES if heat_cap is None else BrakeSpec(heat_cap=heat_cap)
            return spec if self.turtle_ladder else BrakeSpec(**{**_fields(spec), "ladder": None})
        return TURTLE_LADDER_ONLY if self.turtle_ladder else None

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "label": self.label, "sizing": self.sizing.to_dict(), "turtle_ladder": self.turtle_ladder,
                "description": self.description}


def _fields(spec: BrakeSpec) -> Dict[str, Any]:
    import dataclasses

    return {f.name: getattr(spec, f.name) for f in dataclasses.fields(spec)}


TIERS: Mapping[str, PolicyTier] = {
    "reference": PolicyTier("reference", SIZING_TIERS["reference"], False,
                            "today's policy: 10 % volatility target, half size in a crash state, the Reference ladder (half at -5 %, flat at -10 %)"),
    "trader": PolicyTier("trader", SIZING_TIERS["trader"], True,
                         "20 % volatility target, at most 2 % of equity at risk on one stop, the same crash de-risking, the Turtle ladder on entries"),
    "aggressive": PolicyTier("aggressive", SIZING_TIERS["aggressive"], True,
                             "25 % volatility target, at most 2.5 % of equity at risk on one stop, the same crash de-risking, the Turtle ladder on entries"),
    "risk1.5": PolicyTier("risk1.5", SIZING_TIERS["risk1.5"], True,
                          "for information only: Kovner's rule, 1.5 % of equity at risk on every stop, the same crash de-risking, the Turtle ladder"),
}
def _sizing_fields(spec: SizingSpec) -> Dict[str, Any]:
    import dataclasses

    return {f.name: getattr(spec, f.name) for f in dataclasses.fields(spec)}


#: The comparison tiers of section 4.1 ("the higher tiers once with the Reference ladder") and the ladder-cost comparison.
COMPARISON_TIERS: Mapping[str, PolicyTier] = {
    "trader-reference-ladder": PolicyTier("trader-reference-ladder", SizingSpec(**{**_sizing_fields(SIZING_TIERS["trader"]), "ladder": True}), False,
                                          "the Trader tier's size rule under the Reference ladder instead of the Turtle ladder (comparison only)"),
    "aggressive-reference-ladder": PolicyTier("aggressive-reference-ladder", SizingSpec(**{**_sizing_fields(SIZING_TIERS["aggressive"]), "ladder": True}), False,
                                              "the Aggressive tier's size rule under the Reference ladder (comparison only)"),
    "trader-no-ladder": PolicyTier("trader-no-ladder", SIZING_TIERS["trader"], False, "the Trader tier's size rule with no ladder at all (the ladder's cost)"),
    "aggressive-no-ladder": PolicyTier("aggressive-no-ladder", SIZING_TIERS["aggressive"], False, "the Aggressive tier's size rule with no ladder at all (the ladder's cost)"),
}
ALL_TIERS: Mapping[str, PolicyTier] = {**TIERS, **COMPARISON_TIERS}
DEFAULT_TIER = "trader"  # the owner's decision of 2026-11-05: the tier added to the paper fleet


def tier(name: str) -> PolicyTier:
    try:
        return ALL_TIERS[name]
    except KeyError:
        raise ValueError(f"unknown tier {name!r}; known: {sorted(ALL_TIERS)}") from None


def tier_for(sizing: Mapping[str, Any], brakes: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The named tier a stored result's ``policy_sizing`` and brake spec describe, or None (used by the fleet loader, plan row R18b)."""
    lad = None if not brakes else brakes.get("ladder")
    for name, t in ALL_TIERS.items():
        if t.sizing.to_dict() != dict(sizing):
            continue
        if bool(lad) == bool(t.turtle_ladder) and (not lad or TurtleLadder.from_dict(lad) == TurtleLadder()):
            return name
    return None


# -- the variants ---------------------------------------------------------------------------------------

CONVICTION_HIGH = 1.25
CONVICTION_LOW = 0.75
WIDER_STOP_MIN = 4.0  # the wider-stop variant: max(4, the selected multiple + 1) x ATR (2 -> 4, 3 -> 4, 4 -> 5)
ADD_AT_R = 1.0
ADD_SIZE = 0.5
SCALE_OUT_AT_R = 2.0
SCALE_OUT_SHARE = 0.5


@dataclass(frozen=True)
class VariantSpec:
    name: str
    kind: str  # "none" | "engine" | "frames" | "fraction"
    description: str
    engine: Optional[EngineVariants] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "description": self.description,
                "engine": None if self.engine is None else self.engine.to_dict()}


VARIANTS: Mapping[str, VariantSpec] = {
    "none": VariantSpec("none", "none", "the base rule: no variant"),
    "add": VariantSpec("add", "engine", f"one add of {ADD_SIZE:g} x the initial quantity once the close is +{ADD_AT_R:g} R (first unit keeps its stop; "
                                        "the add gets the rule's own stop of the add bar; never after a loss)", EngineVariants(add_at_r=ADD_AT_R, add_size=ADD_SIZE)),
    "scale_out": VariantSpec("scale_out", "engine", f"a {SCALE_OUT_SHARE:g} scale-out once the close is +{SCALE_OUT_AT_R:g} R (the remainder keeps its stop; one trade, P&L pooled)",
                             EngineVariants(scale_out_at_r=SCALE_OUT_AT_R, scale_out_share=SCALE_OUT_SHARE)),
    "conviction": VariantSpec("conviction", "fraction", f"{CONVICTION_HIGH:g} x the tier's size when the {VOLUME_Z_DAYS:g}-day volume z-score is above {VOLUME_Z_MIN:g} at the "
                                                        f"entry bar, {CONVICTION_LOW:g} x otherwise, never above the tier's per-trade cap (not on the S1+VC sleeves)"),
    "trail2": VariantSpec("trail2", "frames", "a trailing exit that activates at +1 R and follows the running high at 2 R"),
    "trail3": VariantSpec("trail3", "frames", "a trailing exit that activates at +1 R and follows the running high at 3 R"),
    "wider_stop": VariantSpec("wider_stop", "frames", f"a wider initial stop: max({WIDER_STOP_MIN:g}, the selected multiple + 1) x ATR"),
    "no_time_stop": VariantSpec("no_time_stop", "frames", "the selected exit bracket without its time stop (S1 SOL-USDT 6H's time30)"),
}
VARIANT_NAMES: Tuple[str, ...] = tuple(VARIANTS)


def variant(name: str) -> VariantSpec:
    try:
        return VARIANTS[name]
    except KeyError:
        raise ValueError(f"unknown variant {name!r}; known: {list(VARIANTS)}") from None


def variant_applies(name: str, candidate_key: str, combos: Sequence[Mapping[str, Any]]) -> Tuple[bool, str]:
    """Whether a variant has anything to act on for this candidate (and why not)."""
    if name == "none":
        return True, ""
    v = variant(name)
    has_stop = candidate_key != "hold" and candidate_key != "TF"
    if not has_stop:
        return False, "the rule has no stop: R is undefined"
    if name == "conviction" and "+VC" in candidate_key:
        return False, "the volume condition is this rule's entry condition; plain S1 is its comparison"
    if name == "wider_stop" and not any("atr_mult" in c for c in combos):
        return False, "the rule has no ATR stop multiple"
    if name == "no_time_stop" and not any(str(c.get("bracket", "none")).startswith("time") for c in combos):
        return False, "no time stop among the rule's exit brackets"
    return True, ""


def conviction_multiplier(df: pd.DataFrame, timeframe: str) -> pd.Series:
    """1.25 where the trailing 30-day volume z-score is above 1 (the R13/R16 condition), 0.75 elsewhere (NaN while warming up -> 0.75)."""
    window = max(2, days_to_bars(VOLUME_Z_DAYS, timeframe))
    z = features.zscore(df["volume"].astype(float), window)
    high = (z > VOLUME_Z_MIN).fillna(False).astype(bool)
    return pd.Series(np.where(high, CONVICTION_HIGH, CONVICTION_LOW), index=df.index, dtype=float)


def variant_combos(name: str, combos: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The rule parameters the variant simulates the TEST slice with (the selection still runs on the originals)."""
    out = [dict(c) for c in combos]
    if name == "wider_stop":
        for c in out:
            if "atr_mult" in c:
                c["atr_mult"] = float(max(WIDER_STOP_MIN, float(c["atr_mult"]) + 1.0))
    return out


def variant_frames(name: str, candidate: ResearchStrategy, df: pd.DataFrame, combos: Sequence[Mapping[str, Any]], context: FeatureContext, *,
                   no_trade: Optional[NoTradeConfig]) -> Optional[Frames]:
    """Frames for the variant's TEST simulation, one column per combo; None when the variant changes no frame."""
    v = variant(name)
    if v.kind != "frames":
        return None
    frames = build_frames(candidate, df, variant_combos(name, combos), context, no_trade=no_trade)
    C = frames.n_combos
    if name in ("trail2", "trail3"):
        dist = 2.0 if name == "trail2" else 3.0
        return Frames(desired=frames.desired, stop=frames.stop, strength=frames.strength, time_stops=list(frames.time_stops), target=frames.target,
                      trail_activate=np.full(C, 1.0), trail_dist=np.full(C, dist))
    if name == "no_time_stop":
        return Frames(desired=frames.desired, stop=frames.stop, strength=frames.strength, time_stops=[None] * C, target=frames.target,
                      trail_activate=frames.trail_activate, trail_dist=frames.trail_dist)
    return frames  # wider_stop: the rebuilt frames


# -- gates (section 4.6) ---------------------------------------------------------------------------------

#: Section 4.6: the Sprint 2c gates, with two thresholds relaxed for the higher tiers because they scale with size, plus the payoff gate.
TIER_GATES: Mapping[str, Dict[str, float]] = {
    "reference": {"max_drawdown_max": GATES["max_drawdown_max"], "worst_calendar_year_min": GATES["worst_calendar_year_min"]},
    "higher": {"max_drawdown_max": 0.25, "worst_calendar_year_min": -0.15},
}
PAYOFF_MIN = 2.0  # average win / average loss
HOLDOUT_SAME_TRADES_NOTE = ("the tier changes only the size of the same trades, so a holdout opened here is a near-second look at the months the "
                            "Reference tier already opened; the ledger names the earlier look")


def gate_thresholds(tier_name: str) -> Dict[str, float]:
    return dict(TIER_GATES["reference"] if tier_name == "reference" else TIER_GATES["higher"])


def acceptance_check_r18(oos: Mapping[str, Any], yearly: Mapping[str, Any], robust: Mapping[str, Any], tier_name: str) -> Dict[str, Any]:
    """The Sprint 2c gates at the tier's drawdown / worst-year thresholds, plus average win / average loss >= 2."""
    thr = gate_thresholds(tier_name)
    worst = yearly.get("worst_calendar_year_return")
    worst_ok = worst is not None and not (isinstance(worst, float) and math.isnan(worst)) and worst >= thr["worst_calendar_year_min"]
    payoff = payoff_ratio(oos)
    checks = {
        "pf_gt_1_2": bool(_num(oos.get("profit_factor")) > GATES["profit_factor_min"]),
        "max_dd_within_tier": bool(_num(oos.get("max_drawdown"), 1.0) <= thr["max_drawdown_max"]),
        "sharpe_gt_0_7": bool(_num(oos.get("sharpe")) > GATES["sharpe_min"]),
        "calmar_gt_0_5": bool(_num(oos.get("calmar")) > GATES["calmar_min"]),
        "rolling_12m_75pct_positive": bool(int(_num(yearly.get("rolling_windows"))) >= 4 and _num(yearly.get("rolling_positive_share")) >= GATES["rolling_12m_positive_min"]),
        "worst_calendar_year_within_tier": bool(worst_ok),
        "enough_trades": bool(int(_num(oos.get("n_trades"))) >= GATES["min_trades"]),
        "robust_pm30pct": bool(_num(robust.get("share_above_threshold")) >= GATES["robust_share_min"]),
        "payoff_ge_2": bool(payoff is not None and payoff >= PAYOFF_MIN),
    }
    checks["passed"] = all(checks.values())
    checks["failed"] = [k for k, v in checks.items() if isinstance(v, bool) and not v and k != "passed"]
    checks["rolling_positive_share"] = _num(yearly.get("rolling_positive_share"))
    checks["worst_calendar_year_return"] = None if worst is None else _num(worst)
    checks["payoff_ratio"] = payoff
    checks["thresholds"] = {"max_drawdown_max": thr["max_drawdown_max"], "worst_calendar_year_min": thr["worst_calendar_year_min"], "payoff_min": PAYOFF_MIN}
    checks["tier"] = tier_name
    return checks


GATE_LABELS_R18 = {
    "pf_gt_1_2": "profit factor above 1.2",
    "max_dd_within_tier": "max drawdown within the tier's limit (20 % Reference, 25 % higher tiers)",
    "sharpe_gt_0_7": "Sharpe above 0.7",
    "calmar_gt_0_5": "Calmar above 0.5",
    "rolling_12m_75pct_positive": "75% of rolling 12-month windows positive",
    "worst_calendar_year_within_tier": "no calendar year below the tier's limit (-10 % Reference, -15 % higher tiers)",
    "enough_trades": "at least 30 trades",
    "robust_pm30pct": "robust to +-30% parameter changes",
    "payoff_ge_2": "average win at least 2 x average loss",
}


def payoff_ratio(oos: Mapping[str, Any]) -> Optional[float]:
    """Average win / average loss (absolute), None without both."""
    win, loss = _num(oos.get("avg_win")), _num(oos.get("avg_loss"))
    if win <= 0 or loss >= 0:
        return None
    return float(win / abs(loss))


# -- the size-neutral variant rule and the brake-cost flag ----------------------------------------------------

BRAKE_COST_FLAG = 0.1  # Calmar


def variant_counts(base: Mapping[str, Any], var: Mapping[str, Any]) -> Dict[str, Any]:
    """Section 4.6: a variant counts only with Sharpe >= the base's and Calmar >= the base's after scaling to the base's realized vol.

    Scaling: a return stream scaled by k = base vol / variant vol has CAGR ~ k x CAGR and max drawdown ~ k x drawdown to first
    order, so the Calmar ratio is scale-free to first order; we report it on the vol-matched return (CAGR x k) over the vol-matched
    drawdown (max DD x k), which is the variant's own Calmar when both scale linearly, and keep the raw Calmar beside it.
    """
    b_sharpe, v_sharpe = _num(base.get("sharpe")), _num(var.get("sharpe"))
    b_vol, v_vol = _num(base.get("ann_vol")), _num(var.get("ann_vol"))
    k = (b_vol / v_vol) if (b_vol > 0 and v_vol > 0) else 1.0
    v_cagr, v_dd = _num(var.get("cagr")), _num(var.get("max_drawdown"))
    scaled_cagr, scaled_dd = v_cagr * k, v_dd * k
    scaled_calmar = (scaled_cagr / scaled_dd) if scaled_dd > 0 else _num(var.get("calmar"))
    b_calmar = _num(base.get("calmar"))
    return {"base_sharpe": b_sharpe, "variant_sharpe": v_sharpe, "base_calmar": b_calmar, "variant_calmar": _num(var.get("calmar")),
            "vol_scale": k, "variant_calmar_vol_matched": scaled_calmar, "variant_cagr_vol_matched": scaled_cagr, "variant_max_dd_vol_matched": scaled_dd,
            "sharpe_ok": bool(v_sharpe >= b_sharpe - 1e-12), "calmar_ok": bool(scaled_calmar >= b_calmar - 1e-12),
            "counts": bool(v_sharpe >= b_sharpe - 1e-12 and scaled_calmar >= b_calmar - 1e-12)}


def brake_cost(without: Mapping[str, Any], with_brakes: Mapping[str, Any]) -> Dict[str, Any]:
    """The brakes' cost in Calmar beside the same sleeve without them; flagged for the owner above 0.1 Calmar."""
    a, b = _num(without.get("calmar")), _num(with_brakes.get("calmar"))
    return {"calmar_without": a, "calmar_with": b, "cost_calmar": a - b, "flagged": bool(a - b > BRAKE_COST_FLAG),
            "cagr_without": _num(without.get("cagr")), "cagr_with": _num(with_brakes.get("cagr")),
            "max_dd_without": _num(without.get("max_drawdown")), "max_dd_with": _num(with_brakes.get("max_drawdown"))}


# -- per-trade statistics ---------------------------------------------------------------------------------------

def trade_stats(trades: pd.DataFrame, *, slippage_rate: float, reentry_bars: int = 2) -> Dict[str, Any]:
    """Expectancy in R, the payoff ratio, gaps past the stop, re-entries within ``reentry_bars`` of a stop-out, risk per trade, adds, scale-outs.

    R is ``quantity x (entry fill - initial stop)`` of the first unit (the engine's ``risk`` column). A gap: a stop-loss exit
    filled below the initial stop (the open gapped through it). Re-entries are counted within one walk-forward window (the
    ``window`` column when present), after a stop-loss exit of the same column.
    """
    n = int(len(trades))
    out: Dict[str, Any] = {"n_trades": n, "n_with_risk": 0, "expectancy_r": None, "expectancy_r_median": None, "payoff_ratio": None,
                           "gap_trades": 0, "gap_share": None, "gap_loss_r_mean": None, "reentries_within_2_bars_of_stop": 0, "reentry_share_of_stops": None,
                           "stop_outs": 0, "risk_pct_mean": None, "risk_pct_median": None, "risk_pct_max": None, "full_allocation_share": None,
                           "size_fraction_mean": None, "adds": 0, "add_worst_case_r_mean": None, "add_worst_case_r_max": None, "scale_outs": 0,
                           "win_rate": None, "avg_win_r": None, "avg_loss_r": None}
    if n == 0:
        return out
    pnl = trades["pnl"].to_numpy(dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    out["win_rate"] = float(len(wins) / n)
    if wins.size and losses.size and losses.mean() < 0:
        out["payoff_ratio"] = float(wins.mean() / abs(losses.mean()))
    risk = trades["risk"].to_numpy(dtype=float) if "risk" in trades else np.full(n, np.nan)
    ok = np.isfinite(risk) & (risk > 0)
    out["n_with_risk"] = int(ok.sum())
    if ok.any():
        r_mult = pnl[ok] / risk[ok]
        out["expectancy_r"] = float(r_mult.mean())
        out["expectancy_r_median"] = float(np.median(r_mult))
        w, lo = r_mult[r_mult > 0], r_mult[r_mult <= 0]
        out["avg_win_r"] = float(w.mean()) if w.size else None
        out["avg_loss_r"] = float(lo.mean()) if lo.size else None
    if "risk_pct" in trades:
        rp = trades["risk_pct"].to_numpy(dtype=float)
        rp = rp[np.isfinite(rp)]
        if rp.size:
            out.update({"risk_pct_mean": float(rp.mean()), "risk_pct_median": float(np.median(rp)), "risk_pct_max": float(rp.max())})
    sf = trades["size_fraction"].to_numpy(dtype=float)
    out["size_fraction_mean"] = float(np.nanmean(sf)) if sf.size else None
    out["full_allocation_share"] = float((sf >= 0.999).mean()) if sf.size else None
    reason = trades["exit_reason"].astype(str).to_numpy()
    stops = reason == "stop_loss"
    out["stop_outs"] = int(stops.sum())
    if "stop_price" in trades:
        sp = trades["stop_price"].to_numpy(dtype=float)
        ex = trades["exit_price"].to_numpy(dtype=float)
        gap = stops & np.isfinite(sp) & (ex < sp * (1.0 - float(slippage_rate)) * (1.0 - 1e-9))
        out["gap_trades"] = int(gap.sum())
        out["gap_share"] = float(gap.sum() / n)
        if gap.any() and ok[gap].any():
            out["gap_loss_r_mean"] = float((pnl[gap & ok] / risk[gap & ok]).mean())
    # Re-entries: the next trade of the same column (and window) that enters within ``reentry_bars`` bars of a stop-loss exit.
    cols = ["combo"] + (["window"] if "window" in trades else [])
    reentries = 0
    for _, g in trades.sort_values(cols + ["entry_i"]).groupby(cols, sort=False):
        e = g["entry_i"].to_numpy(dtype=int)
        x = g["exit_i"].to_numpy(dtype=int)
        rs = g["exit_reason"].astype(str).to_numpy()
        for k in range(len(g) - 1):
            if rs[k] == "stop_loss" and 0 <= e[k + 1] - x[k] <= reentry_bars:
                reentries += 1
    out["reentries_within_2_bars_of_stop"] = int(reentries)
    out["reentry_share_of_stops"] = float(reentries / stops.sum()) if stops.any() else None
    if "adds" in trades:
        adds = trades["adds"].to_numpy(dtype=int)
        out["adds"] = int(adds.sum())
        wc = trades["add_worst_case_r"].to_numpy(dtype=float)
        wc = wc[np.isfinite(wc)]
        if wc.size:
            out["add_worst_case_r_mean"] = float(wc.mean())
            out["add_worst_case_r_max"] = float(wc.max())
    if "scale_outs" in trades:
        out["scale_outs"] = int(trades["scale_outs"].to_numpy(dtype=int).sum())
    return out


def cap_binding_stats(trades: pd.DataFrame, df: pd.DataFrame, rule_of_window: Mapping[int, int], stop_matrix: np.ndarray, spec: SizingSpec,
                      timeframe: str, periods_per_year: float, *, multiplier: Optional[pd.Series] = None) -> Dict[str, Any]:
    """How often the per-trade cap was the binding constraint at the trades' decision bars (None for a spec without a cap)."""
    if spec.risk_cap is None or len(trades) == 0 or "entry_time" not in trades:
        return {"cap_binding_share": None, "n_entries": int(len(trades))}
    pos = {ts: k for k, ts in enumerate(df.index)}
    comps: Dict[int, np.ndarray] = {}
    binds = []
    for _, t in trades.iterrows():
        rule = rule_of_window.get(int(t["window"])) if "window" in trades else None
        if rule is None:
            continue
        if rule not in comps:
            comps[rule] = fraction_components(df, spec, timeframe, periods_per_year, stop_distance=stop_matrix[:, rule], multiplier=multiplier)["cap_binds"].to_numpy()
        k = pos.get(pd.Timestamp(t["entry_time"]))
        if k is None or k < 1:
            continue
        binds.append(bool(comps[rule][k - 1]))
    return {"cap_binding_share": float(np.mean(binds)) if binds else None, "n_entries": int(len(binds))}


def conviction_test(trades: pd.DataFrame, df: pd.DataFrame, timeframe: str, *, min_trades: int = 30) -> Dict[str, Any]:
    """The pre-registered test of the conviction split: expectancy in R of the 1.25 x trades against the 0.75 x trades (>= 30 each)."""
    out: Dict[str, Any] = {"n_high": 0, "n_low": 0, "expectancy_r_high": None, "expectancy_r_low": None, "enough_trades": False, "high_beats_low": None,
                           "min_trades": min_trades}
    if len(trades) == 0 or "entry_time" not in trades:
        return out
    mult = conviction_multiplier(df, timeframe)
    pos = {ts: k for k, ts in enumerate(df.index)}
    high_r: List[float] = []
    low_r: List[float] = []
    for _, t in trades.iterrows():
        k = pos.get(pd.Timestamp(t["entry_time"]))
        risk = float(t.get("risk", float("nan")))
        if k is None or k < 1 or not (math.isfinite(risk) and risk > 0):
            continue
        r = float(t["pnl"]) / risk
        (high_r if mult.iloc[k - 1] >= CONVICTION_HIGH else low_r).append(r)
    out.update({"n_high": len(high_r), "n_low": len(low_r), "expectancy_r_high": float(np.mean(high_r)) if high_r else None,
                "expectancy_r_low": float(np.mean(low_r)) if low_r else None})
    out["enough_trades"] = bool(len(high_r) >= min_trades and len(low_r) >= min_trades)
    if out["enough_trades"]:
        out["high_beats_low"] = bool(out["expectancy_r_high"] > out["expectancy_r_low"])
    return out


def exposure_ratio(oos: Mapping[str, Any], reference: Optional[Mapping[str, Any]]) -> Optional[float]:
    """Average allocation of a tier beside the Reference tier's on the same sleeve."""
    if not reference:
        return None
    a, b = _num(oos.get("avg_allocation")), _num(reference.get("avg_allocation"))
    return float(a / b) if b > 0 else None


def brake_spec_from_args(turtle_ladder: bool, brakes_on: bool, heat_cap: Optional[float] = None) -> Optional[BrakeSpec]:
    """The brake spec the Sprint 2c runner builds from its R18 arguments (None = the engine's default path)."""
    if brakes_on:
        spec = TRADER_BRAKES if heat_cap in (None, TRADER_BRAKES.heat_cap) else BrakeSpec(heat_cap=float(heat_cap))
        if not turtle_ladder:
            spec = BrakeSpec(**{**_fields(spec), "ladder": None})
        return spec
    return TURTLE_LADDER_ONLY if turtle_ladder else None


__all__ = [
    "ALL_TIERS", "BRAKES_OFF", "COMPARISON_TIERS", "DEFAULT_TIER", "GATE_LABELS_R18", "PAYOFF_MIN", "PolicyTier", "TIERS", "TIER_GATES", "VARIANTS",
    "VARIANT_NAMES", "VariantSpec", "acceptance_check_r18", "brake_cost", "brake_spec_from_args", "cap_binding_stats", "conviction_multiplier",
    "conviction_test", "exposure_ratio", "gate_thresholds", "payoff_ratio", "tier", "tier_for", "trade_stats", "variant", "variant_applies",
    "variant_combos", "variant_counts", "variant_frames",
]
