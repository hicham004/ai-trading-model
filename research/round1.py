"""Research round 1: three pre-registered hypotheses judged forward (plan row R13, SIMULATION ONLY).

Plan section 5.3's research loop with the Sprint 2c discipline. Everything
that defines the answer was fixed before the first run — :data:`PREREGISTRATION`
here, written to ``docs/research/research_round_1_preregistration.json`` with a
hash the study checks — and the hash goes into the results.

How the rules are run: exactly as in the replication study (plan row R12),
``scripts/run_research_v1c.py`` is loaded as a module and its own
``run_series`` runs every candidate with Sprint 2c's defaults (grids,
brackets, S0 filter, fixed policy sizing, regime gate, walk-forward windows,
gates, holdout rule). The one addition is the feature context: the loaded
runner's ``positioning_context`` is replaced by
:func:`cross_asset_positioning_context`, which returns the same funding and
open-interest frames plus the other Sprint 2c market's candles (a
:class:`research.strategies.round1.CrossAssetContext`), so the cross-asset
rules of round 1 can see them. Before any new rule is judged, the same patched
code path re-runs ``hold``, ``S1`` and ``S2`` on BTC-USDT and ETH-USDT and must
reproduce Sprint 2c's stored numbers to 6 decimals (:func:`reproduction_check`
of the replication study) — the proof that the context change moves nothing
for the existing rules.

H3 (dual momentum) is two mutually exclusive legs, ``DM-BTC`` on BTC-USDT and
``DM-ETH`` on ETH-USDT; the study judges their combined one-position curve
(:func:`combine_legs`), built bar by bar from the legs' stitched
out-of-sample returns, and opens the holdout for the legs only when the
combined curve passes walk-forward (:func:`leg_holdout`, the Sprint 2c holdout
steps, checked against the runner's own holdout in the tests).

Public data only; nothing here can reach an order; results never authorize trading.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.datalake.layout import LakeLayout
from research.data import bars_per_year, load_or_resample_candles, positioning_context, split_holdout
from research.engine import Costs
from research.gated_walkforward import gate_desired_matrix
from research.markets import SPRINT_2C_INSTRUMENTS
from research.metrics import equity_metrics, probabilistic_sharpe_ratio, return_moments, sharpe, trade_metrics, yearly_returns
from research.regime_v2 import bear_probability, entry_gate_mask, fit_regime, size_multiplier
from research.replication import DATA_END, load_ledger, load_v1c_runner, protocol_check, reproduction_check  # noqa: F401  (the ledger format is the replication study's)
from research.report_v1c import GATES, _row, acceptance_check_v1c, holdout_verdict, yearly_gate_v2
from research.sizing import LadderConfig, fraction_matrix
from research.strategies import ROUND1_BASES, get_candidate
from research.strategies.base import days_to_bars
from research.strategies.round1 import DUAL_MOMENTUM_DAYS, REFERENCE_TREND_PARAMS, VOLUME_Z_DAYS, VOLUME_Z_MIN, CrossAssetContext
from research.sweep import Frames, build_frames, simulate_sizing
from research.walkforward import WINDOW_INIT_CASH

ROOT = Path(__file__).resolve().parents[1]
V1C_RESULTS = ROOT / "docs" / "research" / "ensemble_v1c_results.json"
PREREGISTRATION_PATH = ROOT / "docs" / "research" / "research_round_1_preregistration.json"
STUDY_LAKE_DIRNAME = "lake_research_round_1"
STUDY_TIMEFRAMES: Tuple[str, ...] = ("4H", "6H")
STUDY_MODES: Tuple[str, ...] = ("none", "gate")
CONTROL = "hold"
#: The Sprint 2c rules re-run through the patched context: the reproduction set and the comparison lines.
REPRODUCTION_STRATEGIES: Tuple[str, ...] = (CONTROL, "S1", "S2")
COMBINED_KEY = "DM"
COMBINED_INSTRUMENT = "BTC+ETH"
STUDY_NAME = "R13 research round 1"


class Round1Error(RuntimeError):
    """The study cannot be trusted (protocol mismatch, reproduction failure, a tampered pre-registration, misaligned legs)."""


@dataclass(frozen=True)
class Hypothesis:
    key: str
    title: str
    candidates: Tuple[Tuple[str, str], ...]  # (candidate key, instrument it runs on)
    combined: bool = False  # judged as the one-position curve of its legs (H3)

    @property
    def keys(self) -> List[str]:
        return sorted({c for c, _ in self.candidates})

    @property
    def instruments(self) -> List[str]:
        return sorted({i for _, i in self.candidates})


HYPOTHESES: Tuple[Hypothesis, ...] = (
    Hypothesis("H1", "a BTC-trend condition for ETH entries", (("S1+BT", "ETH-USDT"), ("S2+BT", "ETH-USDT"))),
    Hypothesis("H2", "a volume (attention) confirmation for S1 entries", (("S1+VC", "BTC-USDT"), ("S1+VC", "ETH-USDT"))),
    Hypothesis("H3", "dual momentum between BTC and ETH", (("DM-BTC", "BTC-USDT"), ("DM-ETH", "ETH-USDT")), combined=True),
)
HYPOTHESIS_BY_KEY: Dict[str, Hypothesis] = {h.key: h for h in HYPOTHESES}
HYPOTHESIS_OF_CANDIDATE: Dict[str, str] = {c: h.key for h in HYPOTHESES for c, _ in h.candidates}

PREREGISTRATION: Dict[str, Any] = {
    "fixed_on": "2026-11-04, before any run (plan row R13)",
    "question": ("Does one new, pre-registered entry condition on top of an unchanged Sprint 2c rule give a configuration that passes the Sprint 2c "
                 "gates on BTC-USDT / ETH-USDT 4H and 6H and is then confirmed by the untouched 12 months — where the Sprint 2c rules themselves "
                 "passed in only 4 of 108 configurations and the holdout confirmed 1?"),
    "why": ("From the failure analyses: Sprint 2 (0 of 42) and 2b (0 of 28) found the edge of long-only timing on BTC/ETH thin and fragile; 2c "
            "(4 of 108, 1 confirmed) found the binding gates to be Calmar, Sharpe and the rolling-12-month consistency, that the HMM regime gate "
            "cost more return than it saved, and that ETH's rules were weaker than BTC's (no ETH configuration passed); R9 found the mirrored "
            "shorts no help; R12 found the families fragile across markets and the S2 breakout's edge not carrying into 2025-26 anywhere. The "
            "three conditions below each try to buy consistency by trading less, from the literature of plan section 2.6: cross-market trend "
            "(BTC leads the market), attention and volume (Liu & Tsyvinski 2018/2021: attention surges precede gains) and dual momentum "
            "(Antonacci: relative strength among trending assets)."),
    "hypotheses": {
        "H1": {"title": "a BTC-trend condition for ETH entries",
               "rule": ("ETH-USDT's S1 (time-series momentum) and S2 (Donchian breakout) rules, exactly Sprint 2c's parameters, grids and brackets, "
                        "with new entries allowed only while BTC-USDT's S1 trend is up — S1 with its Sprint 2 defaults on BTC's candles of the same "
                        "timeframe (lookbacks 7/14/30 days, at least 2 of 3 positive), aligned bar for bar. Entries only: an open ETH position is "
                        "left to the base rule's own exits and stop, as the regime gate and the S5 filter do. The condition's parameters are fixed "
                        "and never in a grid."),
               "candidates": ["S1+BT", "S2+BT"], "markets": ["ETH-USDT"], "timeframes": list(STUDY_TIMEFRAMES), "regime_modes": list(STUDY_MODES),
               "reference_trend": {k: (list(v) if isinstance(v, tuple) else v) for k, v in REFERENCE_TREND_PARAMS.items()},
               "comparison": "the same S1 / S2 configuration on ETH-USDT without the condition (Sprint 2c's stored numbers, reproduced in this run)",
               "why": "no ETH configuration passed in Sprint 2c; BTC's trend is the market's trend, and ETH's rules may be entering against it"},
        "H2": {"title": "a volume (attention) confirmation for S1 entries",
               "rule": (f"S1, exactly Sprint 2c's parameters, grid and brackets, on BTC-USDT and ETH-USDT, with new entries allowed only on bars whose "
                        f"volume z-score over the trailing {VOLUME_Z_DAYS:g} days (the bar's own volume against the trailing mean and standard deviation "
                        f"of the bars of that window) is above {VOLUME_Z_MIN:g}. Entries only, as above; a run of desired bars that never sees such a bar "
                        "is skipped. The window and the threshold are fixed and never in a grid."),
               "candidates": ["S1+VC"], "markets": ["BTC-USDT", "ETH-USDT"], "timeframes": list(STUDY_TIMEFRAMES), "regime_modes": list(STUDY_MODES),
               "comparison": "the same S1 configuration without the condition (Sprint 2c's stored numbers, reproduced in this run)",
               "why": "attention surges precede gains in the crypto literature; S1's losses in 2c came from many small whipsaw entries"},
        "H3": {"title": "dual momentum between BTC and ETH",
               "rule": (f"One position in the stronger {DUAL_MOMENTUM_DAYS:g}-day performer of BTC-USDT and ETH-USDT, only while BOTH markets' S1 trends "
                        "are up, as two mutually exclusive legs: DM-BTC on BTC-USDT is long only while BTC's and ETH's S1 trends (the leg's own S1 "
                        "parameters, from S1's grid, applied to both markets) are up AND BTC's simple return over the lookback is at least ETH's; "
                        "DM-ETH on ETH-USDT is the mirror with a strict comparison, so an exact tie goes to BTC. Each leg carries S1's ATR stop on "
                        "its own market and S1's brackets; a leg exits when its condition ends (the position moves to the other leg at the next "
                        "open) or on its stop. The lookback is fixed and never in a grid."),
               "candidates": ["DM-BTC", "DM-ETH"], "markets": ["BTC-USDT", "ETH-USDT"], "timeframes": list(STUDY_TIMEFRAMES), "regime_modes": list(STUDY_MODES),
               "judged_as": ("the combined one-position curve per timeframe and regime mode: the legs' stitched out-of-sample bar returns r_b and r_e "
                             "(identical windows, as the two markets' bar indices are identical) give the combined return (1 + r_b)(1 + r_e) - 1, "
                             "exact for a fraction-of-equity sizing because at most one leg is in the market at a bar close; the v1c gates on that curve "
                             "with the profit factor and trade count pooled over the legs' trades and the robustness share taken as the smaller of the "
                             "legs' shares; the legs are shown as components and are not judged on their own"),
               "comparison": "S1 on BTC-USDT and S1 on ETH-USDT without the condition (Sprint 2c's stored numbers, reproduced in this run), and the hold + policy controls",
               "why": "relative strength among trending assets is the one momentum variant the literature finds robust; it concentrates the one position where the trend is strongest"},
    },
    "protocol": ("Sprint 2c's own runner (scripts/run_research_v1c.py loaded as a module, its run_series), with Sprint 2c's defaults: the candidates' "
                 "grids and brackets (none/tp2/trail1/time30), the S0 filter with the FOMC calendar, the fixed policy sizing vt10/30 crash15/90dh "
                 "ladder (rebalance 0.25, ladder re-arm 30 days), the regime-v2 entry gate (3-state HMM, bear >= 0.5, fitted on every window's train "
                 "slice; modes none and gate), the walk-forward (train 540 d, purge 7 d, test 180 d, Sharpe with >= 20 train trades, entries then "
                 "bracket) and the v1c gates — checked against the stored Sprint 2c run before the study runs; the only change is a feature context "
                 "that also carries the other market's candles"),
    "data": (f"the same OKX public 1H and 4H spot candles as Sprint 2c (4H stored, 6H resampled from 1H), frozen at Sprint 2c's data end (bar close "
             f"<= {DATA_END}) so the walk-forward and the untouched 12 months (2025-10-20 -> 2026-10-20) are the same calendar window; Binance public "
             "funding and open interest for the S0/S5 machinery as in Sprint 2c (the new rules do not use them)"),
    "reproduction": ("before any new rule is judged, the same patched code path re-runs hold, S1 and S2 on BTC-USDT and ETH-USDT (4H and 6H, modes "
                     "none and gate) and must give Sprint 2c's stored walk-forward numbers to 6 decimals, the same trade counts, the same most-selected "
                     "rules and the same gate verdicts; otherwise the study stops"),
    "gates": "the v1c gates unchanged (research/report_v1c.py GATES): PF > 1.2, max DD < 20 %, Sharpe > 0.7, Calmar > 0.5, >= 75 % of rolling 12-month windows positive, no calendar year below -10 %, >= 30 trades, >= 50 % of +-30 % neighbours profitable",
    "verdicts": ("a configuration passes when it passes every gate on the walk-forward; a hypothesis is 'confirmed' when at least one of its "
                 "configurations passes and is confirmed by its holdout, 'contradicted by the holdout' when some pass and none is confirmed, and "
                 "'failed walk-forward' when none passes; every failing hypothesis gets a failure analysis computed from the numbers beside its base rule"),
    "holdout": ("the last 12 months (2025-10-20 -> 2026-10-20), opened once, only for a configuration that passes every walk-forward gate (for H3, the "
                "combined curve: then both legs' holdouts are simulated and combined the same way), only by the full pre-registered study (every "
                "hypothesis, timeframe and mode, with the reproduction, never --quick); the v1c verdict (positive return, PF > 1, >= 10 trades); every "
                "opening goes into an append-only ledger the report shows. CAVEAT, stated before the run: the holdout's falling direction is already "
                "known from the R5b and R9 reports (BTC about -26 %, ETH about -39 % over those months, hold + policy negative on every series), and all "
                "three conditions reduce time in the market, which flatters them there; a confirmation is therefore necessary but not sufficient, and "
                "the paper fleet's forward record is the judge"),
    "fleet": ("a confirmed configuration is appended to the paper fleet's shortlist as a new account with a source tag (existing entries and running "
              "accounts untouched; a walk-forward pass alone adds nothing); a confirmed H3 adds both legs, which together are the one position; the "
              "fleet must be able to load the amended shortlist, otherwise the file is restored and the report says so (the R12 rule)"),
    "no_changes_after_results": "no gate, parameter, condition, market, threshold or verdict rule changes after the results are in; if a gate looks wrong the report says so",
}


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# -- configuration ----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Round1Config:
    hypotheses: Tuple[str, ...] = tuple(h.key for h in HYPOTHESES)
    regime_modes: Tuple[str, ...] = STUDY_MODES
    timeframes: Tuple[str, ...] = STUDY_TIMEFRAMES
    reproduction: bool = True
    data_end: str = DATA_END
    quick: bool = False
    lake_dir: Optional[str] = None  # the frozen study lake the Sprint 2c runner reads

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        for k in ("hypotheses", "regime_modes", "timeframes"):
            out[k] = list(getattr(self, k))
        return out

    @property
    def new_candidates(self) -> List[Tuple[str, str]]:
        """(candidate, instrument) pairs of the requested hypotheses, in pre-registered order."""
        return [pair for h in HYPOTHESES if h.key in self.hypotheses for pair in h.candidates]


def preregistration_hash(cfg: Round1Config, prereg: Mapping[str, Any]) -> str:
    """One hash over the fixed text, the pre-registration file and the configuration."""
    return _sha256_json({"preregistration": PREREGISTRATION, "file": prereg, "config": cfg.to_dict()})


def full_study_requested(cfg: Round1Config) -> bool:
    """The holdout may only be opened by the complete pre-registered study."""
    return (not cfg.quick and cfg.reproduction and sorted(cfg.hypotheses) == sorted(h.key for h in HYPOTHESES)
            and sorted(cfg.regime_modes) == sorted(STUDY_MODES) and sorted(cfg.timeframes) == sorted(STUDY_TIMEFRAMES))


# -- the pre-registration file: written once, before the first run ----------------------------------------

def preregister(path: Path, *, now: Optional[datetime] = None, force: bool = False) -> Dict[str, Any]:
    """Write the fixed text (and the full-study configuration) with a hash; refuse a second write unless forced."""
    path = Path(path)
    if path.exists() and not force:
        raise Round1Error(f"{path} exists: the hypotheses were already fixed; a second write would be a second registration")
    written_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    payload: Dict[str, Any] = {
        "note": "Plan row R13. The hypotheses, rules, parameters, markets, timeframes, gates and verdict rules of research round 1, fixed BEFORE the first run. Never edited.",
        "written_at": written_at, "data_end": DATA_END, "gates": dict(GATES),
        "configuration": Round1Config().to_dict(), "preregistration": PREREGISTRATION,
    }
    payload["sha256"] = _sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return payload


def load_preregistration(path: Path = PREREGISTRATION_PATH) -> Dict[str, Any]:
    """The pre-registration file, checked: its hash, and that its text is the text in this module (neither may change after)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("preregistration"), dict):
        raise Round1Error(f"{path} is not a pre-registration file")
    expected = _sha256_json({k: v for k, v in data.items() if k != "sha256"})
    if data.get("sha256") != expected:
        raise Round1Error(f"{path} was edited after it was written (hash mismatch)")
    if data["preregistration"] != PREREGISTRATION:
        raise Round1Error("the pre-registration text in research/round1.py differs from the registered file; neither may change after registration")
    if data.get("gates") != dict(GATES):
        raise Round1Error("the gates differ from the registered ones")
    return data


# -- the cross-asset context for the Sprint 2c runner --------------------------------------------------------

_REFERENCE_CACHE: Dict[Tuple[str, str, str], pd.DataFrame] = {}


def _reference_candles(layout: LakeLayout, instrument: str, timeframe: str) -> pd.DataFrame:
    key = (str(Path(layout.root).resolve()), instrument, timeframe)
    frame = _REFERENCE_CACHE.get(key)
    if frame is None:
        frame = load_or_resample_candles(layout, instrument, timeframe)
        _REFERENCE_CACHE[key] = frame
    return frame


def cross_asset_positioning_context(layout: LakeLayout, instrument: str, timeframe: str, *, source: str = "binance") -> CrossAssetContext:
    """Sprint 2c's positioning context plus the other Sprint 2c market's candles (same lake, same timeframe)."""
    base = positioning_context(layout, instrument, timeframe, source=source)
    refs = {other: _reference_candles(layout, other, timeframe) for other in SPRINT_2C_INSTRUMENTS if other != instrument}
    return CrossAssetContext(timeframe=base.timeframe, periods_per_year=base.periods_per_year, funding=base.funding,
                             open_interest=base.open_interest, instrument=instrument, references=refs)


def patched_runner():
    """The Sprint 2c runner module with its ``positioning_context`` replaced by the cross-asset one (idempotent, per process)."""
    v1c = load_v1c_runner()
    if getattr(v1c, "positioning_context", None) is not cross_asset_positioning_context:
        v1c._round1_original_positioning_context = v1c.positioning_context
        v1c.positioning_context = cross_asset_positioning_context
    return v1c


def round1_args(cfg: Round1Config, strategies: Sequence[str], *, evaluate_holdout: bool) -> Dict[str, Any]:
    """Sprint 2c's own command-line defaults, narrowed to the given strategies, the study's modes and timeframes."""
    v1c = patched_runner()
    argv: List[str] = ["--strategies", *strategies, "--regime-modes", *cfg.regime_modes, "--timeframes", *cfg.timeframes]
    if cfg.quick:
        argv.append("--quick")
    if evaluate_holdout:
        argv.append("--evaluate-holdout")
    if cfg.lake_dir:
        argv += ["--lake-dir", cfg.lake_dir]
    return dict(vars(v1c.parse_args(argv)))


def protocol_check_round1(args: Mapping[str, Any], meta: Mapping[str, Any]) -> Dict[str, Any]:
    """The replication study's protocol check, with the round-1 candidates (new by design) set aside and listed."""
    stored = set(meta.get("strategies") or [])
    narrowed = dict(args, strategies=[s for s in args["strategies"] if s in stored])
    check = protocol_check(narrowed, meta)
    check["new_candidates"] = [s for s in args["strategies"] if s not in stored]
    check["note"] = "the round-1 candidates are new rules and are not in the stored Sprint 2c run by design; every protocol parameter is checked"
    return check


# -- jobs: one (instrument, timeframe, strategy group) per process ---------------------------------------------

SERIES_KEYS = ("instrument", "timeframe", "results", "failures", "benchmark", "span", "holdout_span", "positioning", "s0_blocked_share", "skipped")


def plan_jobs(cfg: Round1Config, *, evaluate_holdout: bool) -> List[Dict[str, Any]]:
    """The reproduction job (hold, S1, S2) per series, then one job per new candidate and series."""
    jobs: List[Dict[str, Any]] = []
    for tf in cfg.timeframes:
        for inst in SPRINT_2C_INSTRUMENTS:
            if cfg.reproduction:
                jobs.append({"cfg": cfg.to_dict(), "kind": "reproduction", "instrument": inst, "timeframe": tf,
                             "strategies": list(REPRODUCTION_STRATEGIES), "evaluate_holdout": bool(evaluate_holdout)})
            for cand, cand_inst in cfg.new_candidates:
                if cand_inst == inst:
                    jobs.append({"cfg": cfg.to_dict(), "kind": HYPOTHESIS_OF_CANDIDATE[cand], "instrument": inst, "timeframe": tf,
                                 "strategies": [cand], "evaluate_holdout": bool(evaluate_holdout)})
    return jobs


def run_job(job: Mapping[str, Any]) -> Dict[str, Any]:
    """Process-pool entry point: Sprint 2c's ``run_series`` (patched context) for one strategy group on one series."""
    cfg = Round1Config(**job["cfg"])
    v1c = patched_runner()
    args = round1_args(cfg, job["strategies"], evaluate_holdout=bool(job["evaluate_holdout"]))
    print(f"[{job['instrument']} {job['timeframe']}] {job['kind']}: {job['strategies']} x modes {list(cfg.regime_modes)} ...", flush=True)
    out = v1c.run_series(dict(args), job["instrument"], job["timeframe"])
    series: Dict[str, Any] = {k: out.get(k) for k in SERIES_KEYS}
    series["kind"] = job["kind"]
    series["strategies"] = list(job["strategies"])
    series["sleeves"] = {f"{k}|{m}": s for (k, m), s in (out.get("sleeves") or {}).items()}
    series["trades"] = {f"{k}|{m}": t for (k, m), t in (out.get("trades") or {}).items()}
    series["args"] = dict(args)
    return series


def merge_series(outputs: Sequence[Mapping[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Job outputs merged per (instrument, timeframe): results and failures concatenated, sleeves and trades joined."""
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for o in outputs:
        key = (o["instrument"], o["timeframe"])
        if key not in merged:
            merged[key] = {k: o.get(k) for k in SERIES_KEYS}
            merged[key].update({"results": [], "failures": [], "sleeves": {}, "trades": {}, "kinds": [], "args": o.get("args")})
        m = merged[key]
        if o.get("skipped"):
            m["skipped"] = o["skipped"]
            continue
        m["results"].extend(o.get("results") or [])
        m["failures"].extend(o.get("failures") or [])
        m["sleeves"].update(o.get("sleeves") or {})
        m["trades"].update(o.get("trades") or {})
        m["kinds"].append(o.get("kind"))
        for k in ("benchmark", "span", "holdout_span", "positioning", "s0_blocked_share"):
            if m.get(k) is None and o.get(k) is not None:
                m[k] = o[k]
    return merged


# -- bookkeeping on the results ----------------------------------------------------------------------------------

def _num(v: Any, default: float = float("nan")) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x


def _finite_num(v: Any) -> Optional[float]:
    x = _num(v)
    return None if (math.isnan(x) or math.isinf(x)) else x


def _metrics_of(r: Mapping[str, Any]) -> Dict[str, Any]:
    oos = r.get("oos") or {}
    acc = r.get("acceptance") or {}
    return {"cagr": oos.get("cagr"), "sharpe": oos.get("sharpe"), "max_drawdown": oos.get("max_drawdown"), "calmar": oos.get("calmar"),
            "profit_factor": oos.get("profit_factor"), "n_trades": oos.get("n_trades"), "trades_per_year": oos.get("trades_per_year"),
            "total_return": oos.get("total_return"), "exposure": oos.get("exposure"), "avg_allocation": oos.get("avg_allocation"),
            "fees_pct_per_year": oos.get("fees_pct_per_year"), "win_rate": oos.get("win_rate"),
            "rolling_12m_positive_share": acc.get("rolling_positive_share"), "worst_calendar_year_return": acc.get("worst_calendar_year_return"),
            "yearly": {str(k): v for k, v in (r.get("yearly") or {}).items()},
            "passed": bool(acc.get("passed")), "failed": list(acc.get("failed") or [])}


def _delta(a: Any, b: Any) -> Optional[float]:
    x, y = _num(a), _num(b)
    return None if (math.isnan(x) or math.isnan(y)) else x - y


def compare_with_base(r: Mapping[str, Any], base: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The new configuration beside its base rule (same instrument, timeframe, mode): levels and deltas."""
    if base is None:
        return {"available": False}
    m, b = _metrics_of(r), _metrics_of(base)
    years = sorted(set(m["yearly"]) | set(b["yearly"]))
    yearly = {y: {"variant": m["yearly"].get(y), "base": b["yearly"].get(y), "delta": _delta(m["yearly"].get(y), b["yearly"].get(y))} for y in years}
    n_var, n_base = _num(m["n_trades"]), _num(b["n_trades"])
    return {
        "available": True, "base_candidate": base["candidate"], "base_configuration": base.get("configuration") or f"{base['candidate']} {base['timeframe']} [{(base.get('regime') or {}).get('mode')}]",
        "variant": m, "base": b,
        "delta": {k: _delta(m[k], b[k]) for k in ("calmar", "cagr", "sharpe", "max_drawdown", "profit_factor", "n_trades", "trades_per_year",
                                                   "avg_allocation", "exposure", "fees_pct_per_year", "rolling_12m_positive_share", "worst_calendar_year_return")},
        "trades_removed_share": None if (math.isnan(n_var) or math.isnan(n_base) or n_base <= 0) else max(0.0, 1.0 - n_var / n_base),
        "yearly": yearly, "base_passed": b["passed"],
    }


def annotate_result(r: Dict[str, Any], base: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    cand = r["candidate"]
    mode = (r.get("regime") or {}).get("mode")
    r["hypothesis"] = HYPOTHESIS_OF_CANDIDATE.get(cand)
    r["base_candidate"] = ROUND1_BASES.get(cand)
    r["configuration"] = f"{cand} {r['instrument']} {r['timeframe']} [{mode}]"
    hyp = HYPOTHESIS_BY_KEY.get(r["hypothesis"] or "")
    r["role"] = "control" if cand == CONTROL else ("reproduction" if cand in REPRODUCTION_STRATEGIES else ("leg" if (hyp and hyp.combined) else "configuration"))
    r["judged"] = r["role"] == "configuration"
    r["holdout_confirmed"] = holdout_verdict(r) if r.get("holdout") else None
    r["comparison"] = compare_with_base(r, base) if r["hypothesis"] else {"available": False}
    return r


def _find(results: Sequence[Mapping[str, Any]], candidate: str, instrument: str, timeframe: str, mode: str) -> Optional[Mapping[str, Any]]:
    for r in results:
        if r["candidate"] == candidate and r["instrument"] == instrument and r["timeframe"] == timeframe and (r.get("regime") or {}).get("mode") == mode:
            return r
    return None


def annotate_all(merged: Mapping[Tuple[str, str], Dict[str, Any]], stored: Sequence[Mapping[str, Any]]) -> None:
    """Every result gets its hypothesis, role and the comparison with its base rule (from this run's reproduction, else the stored Sprint 2c result)."""
    all_results = [r for s in merged.values() for r in (s.get("results") or [])]
    for s in merged.values():
        for r in s.get("results") or []:
            base_key = ROUND1_BASES.get(r["candidate"])
            base = None
            if base_key:
                mode = (r.get("regime") or {}).get("mode")
                base = _find(all_results, base_key, r["instrument"], r["timeframe"], mode) or _find(stored, base_key, r["instrument"], r["timeframe"], mode)
                if base is not None and "configuration" not in base:
                    base = dict(base, configuration=f"{base['candidate']} {base['instrument']} {base['timeframe']} [{mode}]")
            annotate_result(r, base)


# -- H3: the legs combined into one position ---------------------------------------------------------------------

def _window_returns_from_equity(equity: np.ndarray, init_cash: float, index: pd.Index) -> pd.Series:
    return pd.Series(np.concatenate([[equity[0] / init_cash - 1.0], equity[1:] / equity[:-1] - 1.0]), index=index)


def combined_returns(r_b: pd.Series, r_e: pd.Series) -> pd.Series:
    """The one-position curve's bar returns from two mutually exclusive legs: (1 + r_b)(1 + r_e) - 1 on identical indices."""
    if len(r_b) != len(r_e) or not r_b.index.equals(r_e.index):
        raise Round1Error("the two dual-momentum legs do not share their bars (the markets' bar indices differ); the combined curve is undefined")
    return (1.0 + r_b.astype(float).fillna(0.0)) * (1.0 + r_e.astype(float).fillna(0.0)) - 1.0


def combine_legs(leg_b: Mapping[str, Any], leg_e: Mapping[str, Any], r_b: pd.Series, r_e: pd.Series, t_b: pd.DataFrame, t_e: pd.DataFrame,
                 periods_per_year: float, *, timeframe: str, mode: str, n_regime_modes: int = 1) -> Dict[str, Any]:
    """The H3 result: metrics, yearly gate, pooled trades, robustness as the smaller leg share, DSR, the v1c acceptance."""
    rc = combined_returns(r_b, r_e)
    equity = (1.0 + rc).cumprod()
    metrics = equity_metrics(np.concatenate([[1.0], equity.to_numpy()]), periods_per_year)
    trades = pd.concat([t for t in (t_b, t_e) if t is not None and len(t)], ignore_index=True) if any(t is not None and len(t) for t in (t_b, t_e)) else pd.DataFrame()
    metrics.update(trade_metrics(trades, init_cash=WINDOW_INIT_CASH, n_bars=len(rc), periods_per_year=periods_per_year))
    ob, oe = leg_b.get("oos") or {}, leg_e.get("oos") or {}
    metrics["exposure"] = min(1.0, _num(ob.get("exposure"), 0.0) + _num(oe.get("exposure"), 0.0))
    metrics["avg_allocation"] = min(1.0, _num(ob.get("avg_allocation"), 0.0) + _num(oe.get("avg_allocation"), 0.0))
    metrics["traded_bars_share"] = max(_num(ob.get("traded_bars_share"), 0.0), _num(oe.get("traded_bars_share"), 0.0))
    metrics["windows"] = max(int(_num(ob.get("windows"), 0)), int(_num(oe.get("windows"), 0)))
    metrics["windows_traded"] = max(int(_num(ob.get("windows_traded"), 0)), int(_num(oe.get("windows_traded"), 0)))
    metrics["gate_blocked_share"] = float(np.mean([_num(ob.get("gate_blocked_share"), 0.0), _num(oe.get("gate_blocked_share"), 0.0)]))
    metrics.update({f"ret_{k}": v for k, v in return_moments(rc.to_numpy()).items()})
    metrics["legs_switches"] = int(len(trades))
    yearly = {int(k): float(v) for k, v in yearly_returns(equity).items()}
    yg = yearly_gate_v2(equity)
    rb_b, rb_e = leg_b.get("robustness") or {}, leg_e.get("robustness") or {}
    robust = {"share_above_threshold": min(_num(rb_b.get("share_above_threshold"), 0.0), _num(rb_e.get("share_above_threshold"), 0.0)),
              "n_neighbours": int(_num(rb_b.get("n_neighbours"), 0) + _num(rb_e.get("n_neighbours"), 0)),
              "legs": {"DM-BTC": rb_b.get("share_above_threshold"), "DM-ETH": rb_e.get("share_above_threshold")},
              "rule": "the smaller of the two legs' shares of profitable +-30% neighbours"}
    observed = sharpe(rc.to_numpy(), 1.0)
    db, de = leg_b.get("dsr") or {}, leg_e.get("dsr") or {}
    sr0 = max(_num(db.get("expected_max_sr"), 0.0), _num(de.get("expected_max_sr"), 0.0))
    mom = return_moments(rc.to_numpy())
    dsr = {"n_trials": int(_num(db.get("n_trials"), 0) + _num(de.get("n_trials"), 0)), "expected_max_sr": sr0, "observed_sr": observed,
           "dsr": probabilistic_sharpe_ratio(observed, sr0, len(rc), mom["skew"], mom["kurt"]),
           "rule": "PSR of the combined curve against the larger of the legs' expected maximum Sharpe (zero skill)"}
    acceptance = acceptance_check_v1c(metrics, yg, robust)
    oos = {k: _finite_or_999(v, k) for k, v in metrics.items()}
    return {
        "candidate": COMBINED_KEY, "label": "dual momentum BTC/ETH — one position in the stronger 90-day performer while both S1 trends are up",
        "instrument": COMBINED_INSTRUMENT, "timeframe": timeframe, "regime": dict(leg_b.get("regime") or {"mode": mode}),
        "policy_sizing": leg_b.get("policy_sizing"), "hypothesis": "H3", "base_candidate": "S1", "role": "configuration", "judged": True,
        "configuration": f"{COMBINED_KEY} {COMBINED_INSTRUMENT} {timeframe} [{mode}]",
        "legs": [leg_b.get("configuration"), leg_e.get("configuration")],
        "selected_params": {"DM-BTC": leg_b.get("selected_params"), "DM-ETH": leg_e.get("selected_params")},
        "oos": oos, "yearly": yearly, "yearly_gate": yg, "robustness": robust, "dsr": dsr, "acceptance": acceptance,
        "holdout_confirmed": None, "notes": ["combined from the two legs' stitched out-of-sample returns: (1 + r_b)(1 + r_e) - 1 per bar; "
                                             "profit factor and trades pooled over both legs; the drawdown ladder acted on each leg's own equity"],
    }


def _finite_or_999(value: Any, key: str = "") -> Any:
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return 999.0 if (key == "profit_factor" and value > 0) else None
    if isinstance(value, np.generic):
        return value.item()
    return value


def leg_holdout(args: Mapping[str, Any], layout: LakeLayout, df_all: pd.DataFrame, instrument: str, timeframe: str, key: str, mode: str,
                selected: Mapping[str, Any]) -> Tuple[pd.Series, pd.DataFrame, Dict[str, Any]]:
    """One leg's untouched 12 months, simulated exactly as the Sprint 2c runner does it for a passer (checked in the tests):
    the most-selected rule with its bracket, the policy sizing, a regime model fitted on the whole in-sample span.

    Returns ``(bar returns over the holdout, trades, metrics)``."""
    v1c = patched_runner()
    ns = argparse.Namespace(**dict(args))
    candidate = get_candidate(key)
    context = v1c.positioning_context(layout, instrument, timeframe, source=ns.positioning_source)
    ppy = context.periods_per_year
    df_in, df_hold = split_holdout(df_all, holdout_months=ns.holdout_months)
    if not len(df_hold):
        raise Round1Error(f"{instrument} {timeframe}: no holdout bars")
    regime_cfg = v1c._regime_cfg(ns, mode)
    policy = v1c._policy_spec(ns)
    no_trade = v1c._no_trade(ns)
    ladder = LadderConfig(recovery_bars=days_to_bars(ns.ladder_recovery_days, timeframe))
    rebalance = v1c._rebalance(ns)
    costs = Costs(fee_rate=ns.fee, slippage_rate=ns.slippage)
    full_frames = build_frames(candidate, df_all, [dict(selected)], context, no_trade=no_trade)
    full_fracs = fraction_matrix(df_all, [policy], timeframe, ppy)
    if regime_cfg.active:
        fitted = fit_regime(df_in, timeframe, ppy, regime_cfg)
        bear = bear_probability(fitted, df_all, timeframe, ppy, regime_cfg)
        ok = entry_gate_mask(bear, regime_cfg).to_numpy(dtype=bool)
        mult = size_multiplier(bear, regime_cfg).to_numpy(dtype=float)
        full_frames = Frames(desired=gate_desired_matrix(full_frames.desired, ok), stop=full_frames.stop, strength=full_frames.strength,
                             time_stops=full_frames.time_stops, target=full_frames.target, trail_activate=full_frames.trail_activate,
                             trail_dist=full_frames.trail_dist)
        full_fracs = full_fracs * mult[:, None]
    hold_slice = slice(len(df_in), len(df_all))
    res = simulate_sizing(df_all, full_frames, 0, hold_slice, full_fracs, costs=costs, ladder=ladder, ladder_mask=np.array([policy.ladder]),
                          rebalance_threshold=rebalance)
    hm = equity_metrics(res.equity[:, 0], ppy)
    hm.update(trade_metrics(res.trades, init_cash=res.init_cash, n_bars=res.n_bars, periods_per_year=ppy))
    hm["avg_allocation"] = float(res.avg_allocation[0])
    returns = _window_returns_from_equity(res.equity[:, 0], res.init_cash, df_hold.index)
    return returns, res.trades, {k: _finite_or_999(v, k) for k, v in hm.items()}


def combined_holdout(r_b: pd.Series, r_e: pd.Series, t_b: pd.DataFrame, t_e: pd.DataFrame, periods_per_year: float) -> Dict[str, Any]:
    rc = combined_returns(r_b, r_e)
    equity = np.concatenate([[1.0], (1.0 + rc).cumprod().to_numpy()])
    hm = equity_metrics(equity, periods_per_year)
    trades = pd.concat([t for t in (t_b, t_e) if t is not None and len(t)], ignore_index=True) if any(t is not None and len(t) for t in (t_b, t_e)) else pd.DataFrame()
    hm.update(trade_metrics(trades, init_cash=WINDOW_INIT_CASH, n_bars=len(rc), periods_per_year=periods_per_year))
    return {k: _finite_or_999(v, k) for k, v in hm.items()}


def build_combined_results(merged: Mapping[Tuple[str, str], Dict[str, Any]], cfg: Round1Config, *, evaluate_holdout: bool,
                           layout: Optional[LakeLayout] = None, log=print) -> List[Dict[str, Any]]:
    """H3's combined results per timeframe and mode (from the legs' stitched returns); their holdout when they pass and it is requested."""
    out: List[Dict[str, Any]] = []
    if "H3" not in cfg.hypotheses:
        return out
    for tf in cfg.timeframes:
        sb, se = merged.get(("BTC-USDT", tf)), merged.get(("ETH-USDT", tf))
        if not sb or not se or sb.get("skipped") or se.get("skipped"):
            continue
        for mode in cfg.regime_modes:
            leg_b = _find(sb.get("results") or [], "DM-BTC", "BTC-USDT", tf, mode)
            leg_e = _find(se.get("results") or [], "DM-ETH", "ETH-USDT", tf, mode)
            r_b, r_e = sb["sleeves"].get(f"DM-BTC|{mode}"), se["sleeves"].get(f"DM-ETH|{mode}")
            if leg_b is None or leg_e is None or r_b is None or r_e is None:
                log(f"H3 {tf} [{mode}]: a leg is missing; the combined curve is not built")
                continue
            ppy = _ppy(tf)
            combined = combine_legs(leg_b, leg_e, r_b, r_e, sb["trades"].get(f"DM-BTC|{mode}"), se["trades"].get(f"DM-ETH|{mode}"), ppy,
                                    timeframe=tf, mode=mode)
            combined["comparison"] = {"available": False}
            if combined["acceptance"]["passed"] and evaluate_holdout and layout is not None:
                args = sb["args"]
                hb, tb, _ = leg_holdout(args, layout, load_or_resample_candles(layout, "BTC-USDT", tf), "BTC-USDT", tf, "DM-BTC", mode, leg_b["selected_params"])
                he, te, _ = leg_holdout(args, layout, load_or_resample_candles(layout, "ETH-USDT", tf), "ETH-USDT", tf, "DM-ETH", mode, leg_e["selected_params"])
                combined["holdout"] = combined_holdout(hb, he, tb, te, ppy)
                combined["holdout_confirmed"] = holdout_verdict(combined)
                log(f"H3 {tf} [{mode}] passed walk-forward: holdout opened -> {combined['holdout'].get('total_return'):+.4f}, "
                    f"PF {combined['holdout'].get('profit_factor')}, trades {combined['holdout'].get('n_trades')}")
            out.append(combined)
    return out


def _ppy(timeframe: str) -> float:
    return bars_per_year(timeframe)


# -- verdicts (pre-registered) ---------------------------------------------------------------------------------

def judged_results(merged: Mapping[Tuple[str, str], Mapping[str, Any]], combined: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    rows = [r for s in merged.values() for r in (s.get("results") or []) if r.get("judged")]
    return rows + [c for c in combined if c.get("judged")]


def _median(values: Sequence[Any]) -> Optional[float]:
    xs = sorted(float(v) for v in values if v is not None and isinstance(v, (int, float)) and math.isfinite(float(v)))
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else 0.5 * (xs[m - 1] + xs[m])


def hypothesis_verdicts(merged: Mapping[Tuple[str, str], Mapping[str, Any]], combined: Sequence[Mapping[str, Any]], cfg: Round1Config,
                        stored: Sequence[Mapping[str, Any]] = ()) -> List[Dict[str, Any]]:
    """Per hypothesis: its judged configurations, how many pass, the holdout outcome, the pre-registered label, the failure facts."""
    out: List[Dict[str, Any]] = []
    all_results = [r for s in merged.values() for r in (s.get("results") or [])]
    for h in HYPOTHESES:
        if h.key not in cfg.hypotheses:
            continue
        rows = [r for r in judged_results(merged, combined) if r.get("hypothesis") == h.key]
        legs = [r for r in all_results if r.get("hypothesis") == h.key and r.get("role") == "leg"]
        passed = [r for r in rows if (r.get("acceptance") or {}).get("passed")]
        confirmed = [r for r in passed if r.get("holdout_confirmed") is True]
        contradicted = [r for r in passed if r.get("holdout_confirmed") is False]
        unevaluated = [r for r in passed if r.get("holdout_confirmed") is None]
        if confirmed:
            label = "confirmed"
        elif passed and not unevaluated:
            label = "passed walk-forward, contradicted by the holdout"
        elif passed:
            label = "passed walk-forward, holdout not opened"
        elif rows:
            label = "failed walk-forward"
        else:
            label = "not run"
        counts: Dict[str, int] = {}
        for r in rows:
            for g in (r.get("acceptance") or {}).get("failed", []):
                counts[g] = counts.get(g, 0) + 1
        out.append({
            "hypothesis": h.key, "title": h.title, "label": label, "combined": h.combined,
            "n_configurations": len(rows), "n_passed": len(passed), "n_confirmed": len(confirmed), "n_contradicted": len(contradicted),
            "n_unevaluated": len(unevaluated),
            "configurations": [r["configuration"] for r in rows], "passed": [r["configuration"] for r in passed],
            "confirmed": [r["configuration"] for r in confirmed], "contradicted": [r["configuration"] for r in contradicted],
            "binding_gates": sorted(counts.items(), key=lambda kv: -kv[1]),
            "best": _best(rows), "failure_facts": failure_facts(h, rows, legs, all_results, stored),
        })
    return out


def _best(rows: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    best = max(rows, key=lambda r: _num((r.get("oos") or {}).get("calmar"), -9.0))
    return {"configuration": best["configuration"], **_metrics_of(best)}


def failure_facts(h: Hypothesis, rows: Sequence[Mapping[str, Any]], legs: Sequence[Mapping[str, Any]], all_results: Sequence[Mapping[str, Any]],
                  stored: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    """The numbers a failure analysis is written from: the condition's effect beside the base rule, over the hypothesis's configurations.

    The comparison lines (S1, hold) come from this run's reproduction; a run without one (a smoke run) falls back to the stored Sprint 2c results."""
    facts: Dict[str, Any] = {"n": len(rows)}
    if h.combined:
        # H3: compare the combined curve with S1 on each market (same timeframe and mode) and with the hold controls.
        comps = []
        for c in rows:
            tf, mode = c["timeframe"], (c.get("regime") or {}).get("mode")
            s1b = _find(all_results, "S1", "BTC-USDT", tf, mode) or _find(stored, "S1", "BTC-USDT", tf, mode)
            s1e = _find(all_results, "S1", "ETH-USDT", tf, mode) or _find(stored, "S1", "ETH-USDT", tf, mode)
            hb = _find(all_results, CONTROL, "BTC-USDT", tf, "none") or _find(stored, CONTROL, "BTC-USDT", tf, "none")
            he = _find(all_results, CONTROL, "ETH-USDT", tf, "none") or _find(stored, CONTROL, "ETH-USDT", tf, "none")
            m = _metrics_of(c)
            lb = _find(legs, "DM-BTC", "BTC-USDT", tf, mode)
            le = _find(legs, "DM-ETH", "ETH-USDT", tf, mode)
            comps.append({
                "configuration": c["configuration"], "combined": m,
                "s1_btc": None if s1b is None else _metrics_of(s1b), "s1_eth": None if s1e is None else _metrics_of(s1e),
                "hold_btc": None if hb is None else _metrics_of(hb), "hold_eth": None if he is None else _metrics_of(he),
                "leg_btc": None if lb is None else _metrics_of(lb), "leg_eth": None if le is None else _metrics_of(le),
                "best_s1_calmar": max([_num((_metrics_of(x) or {}).get("calmar"), -9.0) for x in (s1b, s1e) if x is not None] or [float("nan")]),
            })
        facts["comparisons"] = comps
        facts["median_calmar"] = _median([c["combined"]["calmar"] for c in comps])
        facts["median_best_s1_calmar"] = _median([c["best_s1_calmar"] for c in comps])
        facts["median_trades_per_year"] = _median([c["combined"]["trades_per_year"] for c in comps])
        facts["median_s1_trades_per_year"] = _median([x["s1_btc"]["trades_per_year"] for x in comps if x["s1_btc"]] + [x["s1_eth"]["trades_per_year"] for x in comps if x["s1_eth"]])
        facts["median_exposure"] = _median([c["combined"]["exposure"] for c in comps])
        facts["median_s1_exposure"] = _median([x["s1_btc"]["exposure"] for x in comps if x["s1_btc"]] + [x["s1_eth"]["exposure"] for x in comps if x["s1_eth"]])
        facts["beats_best_s1"] = sum(1 for c in comps if _num(c["combined"]["calmar"], -9.0) > _num(c["best_s1_calmar"], -9.0))
        facts["beats_hold"] = sum(1 for c in comps if c["hold_btc"] and c["hold_eth"] and _num(c["combined"]["calmar"], -9.0) > max(_num(c["hold_btc"]["calmar"], -9.0), _num(c["hold_eth"]["calmar"], -9.0)))
        facts["median_2022"] = _median([c["combined"]["yearly"].get("2022") for c in comps])
        facts["median_s1_2022"] = _median([x["s1_btc"]["yearly"].get("2022") for x in comps if x["s1_btc"]] + [x["s1_eth"]["yearly"].get("2022") for x in comps if x["s1_eth"]])
        facts["legs"] = [{"configuration": l["configuration"], **_metrics_of(l)} for l in legs]
        return facts
    comps = [r["comparison"] for r in rows if (r.get("comparison") or {}).get("available")]
    facts["n_compared"] = len(comps)
    if not comps:
        return facts
    d = lambda k: [c["delta"].get(k) for c in comps]  # noqa: E731
    facts.update({
        "calmar_improved": sum(1 for c in comps if _num(c["delta"].get("calmar"), 0.0) > 0.0),
        "sharpe_improved": sum(1 for c in comps if _num(c["delta"].get("sharpe"), 0.0) > 0.0),
        "drawdown_fell": sum(1 for c in comps if _num(c["delta"].get("max_drawdown"), 0.0) < 0.0),
        "return_fell": sum(1 for c in comps if _num(c["delta"].get("cagr"), 0.0) < 0.0),
        "rolling_improved": sum(1 for c in comps if _num(c["delta"].get("rolling_12m_positive_share"), 0.0) > 0.0),
        "median_delta_calmar": _median(d("calmar")), "median_delta_cagr": _median(d("cagr")), "median_delta_sharpe": _median(d("sharpe")),
        "median_delta_max_drawdown": _median(d("max_drawdown")), "median_delta_rolling": _median(d("rolling_12m_positive_share")),
        "median_delta_fees": _median(d("fees_pct_per_year")),
        "median_trades_removed_share": _median([c["trades_removed_share"] for c in comps]),
        "median_delta_exposure": _median(d("exposure")),
        "median_variant_calmar": _median([c["variant"]["calmar"] for c in comps]), "median_base_calmar": _median([c["base"]["calmar"] for c in comps]),
        "median_variant_cagr": _median([c["variant"]["cagr"] for c in comps]), "median_base_cagr": _median([c["base"]["cagr"] for c in comps]),
        "median_variant_dd": _median([c["variant"]["max_drawdown"] for c in comps]), "median_base_dd": _median([c["base"]["max_drawdown"] for c in comps]),
        "median_variant_trades": _median([c["variant"]["n_trades"] for c in comps]), "median_base_trades": _median([c["base"]["n_trades"] for c in comps]),
        "median_variant_rolling": _median([c["variant"]["rolling_12m_positive_share"] for c in comps]),
        "median_base_rolling": _median([c["base"]["rolling_12m_positive_share"] for c in comps]),
        "median_2022_variant": _median([c["yearly"].get("2022", {}).get("variant") for c in comps]),
        "median_2022_base": _median([c["yearly"].get("2022", {}).get("base") for c in comps]),
        "base_passed_any": any(c.get("base_passed") for c in comps),
        "by_mode": {mode: {"calmar_improved": sum(1 for r in rows if (r.get("regime") or {}).get("mode") == mode and _num((r.get("comparison") or {}).get("delta", {}).get("calmar"), 0.0) > 0.0),
                           "n": sum(1 for r in rows if (r.get("regime") or {}).get("mode") == mode)} for mode in sorted({(r.get("regime") or {}).get("mode") for r in rows})},
    })
    return facts


def overall_summary(verdicts: Sequence[Mapping[str, Any]], merged: Mapping[Tuple[str, str], Mapping[str, Any]], combined: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = judged_results(merged, combined)
    passed = [r for r in rows if (r.get("acceptance") or {}).get("passed")]
    counts: Dict[str, int] = {}
    for r in rows:
        for g in (r.get("acceptance") or {}).get("failed", []):
            counts[g] = counts.get(g, 0) + 1
    return {"n_judged": len(rows), "n_passed": len(passed), "n_confirmed": sum(1 for r in passed if r.get("holdout_confirmed") is True),
            "n_contradicted": sum(1 for r in passed if r.get("holdout_confirmed") is False),
            "n_unevaluated": sum(1 for r in passed if r.get("holdout_confirmed") is None),
            "labels": {v["hypothesis"]: v["label"] for v in verdicts}, "binding_gates": sorted(counts.items(), key=lambda kv: -kv[1]),
            "passed": [{"configuration": r["configuration"], "calmar": (r.get("oos") or {}).get("calmar"), "holdout_confirmed": r.get("holdout_confirmed")} for r in passed]}


# -- the holdout ledger -----------------------------------------------------------------------------------------

LEDGER_NOTE = ("Every opening of the untouched 12 months by research round 1 (plan row R13), in order; entries are appended, never edited. "
               "The report shows all of them. The hold + policy control's 12 months are a comparison line, not a configuration under test.")


def holdout_openings(merged: Mapping[Tuple[str, str], Mapping[str, Any]], combined: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in merged.values():
        for r in s.get("results") or []:
            h = r.get("holdout")
            if not h:
                continue
            out.append({"configuration": r["configuration"], "role": r.get("role"), "selected_params": _canon(r.get("selected_params")),
                        "span": s.get("holdout_span"), "total_return": h.get("total_return"), "max_drawdown": h.get("max_drawdown"),
                        "profit_factor": h.get("profit_factor"), "n_trades": h.get("n_trades"),
                        "confirmed": None if r["candidate"] == CONTROL else holdout_verdict(r)})
    for c in combined:
        h = c.get("holdout")
        if not h:
            continue
        out.append({"configuration": c["configuration"], "role": "configuration", "selected_params": _canon(c.get("selected_params")),
                    "span": next((s.get("holdout_span") for s in merged.values() if s.get("holdout_span")), None),
                    "total_return": h.get("total_return"), "max_drawdown": h.get("max_drawdown"), "profit_factor": h.get("profit_factor"),
                    "n_trades": h.get("n_trades"), "confirmed": holdout_verdict(c)})
    return out


def _canon(params: Any) -> Any:
    if isinstance(params, dict):
        return {k: _canon(v) for k, v in params.items()}
    if isinstance(params, tuple):
        return list(params)
    return params


def guard_second_look(ledger: Sequence[Mapping[str, Any]], openings: Sequence[Mapping[str, Any]], *, evaluate_holdout: bool) -> List[str]:
    if not evaluate_holdout:
        return []
    seen = {o["configuration"] for e in ledger for o in e.get("openings", []) if o.get("role") != "control"}
    return sorted(o["configuration"] for o in openings if o["role"] != "control" and o["configuration"] in seen)


def write_round1_ledger(path: str, entries: List[Dict[str, Any]]) -> None:
    Path(path).write_text(json.dumps({"note": LEDGER_NOTE, "entries": entries}, indent=1) + "\n", encoding="utf-8")


# -- the paper-fleet shortlist ------------------------------------------------------------------------------------

def shortlist_additions(merged: Mapping[Tuple[str, str], Mapping[str, Any]], combined: Sequence[Mapping[str, Any]], *, source: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Confirmed passers as shortlist rows with a ``source`` tag; a confirmed H3 adds both legs (together the one position)."""
    rows: List[Dict[str, Any]] = []
    all_results = [r for s in merged.values() for r in (s.get("results") or [])]
    for r in all_results:
        if r.get("judged") and (r.get("acceptance") or {}).get("passed") and r.get("holdout_confirmed") is True:
            row = _row(r)
            row["source"] = dict(source, hypothesis=r.get("hypothesis"))
            rows.append(row)
    for c in combined:
        if (c.get("acceptance") or {}).get("passed") and c.get("holdout_confirmed") is True:
            tf, mode = c["timeframe"], (c.get("regime") or {}).get("mode")
            for key, inst in (("DM-BTC", "BTC-USDT"), ("DM-ETH", "ETH-USDT")):
                leg = _find(all_results, key, inst, tf, mode)
                if leg is None:
                    continue
                row = _row(leg)
                row["holdout"] = c.get("holdout")
                row["holdout_confirmed"] = True
                row["source"] = dict(source, hypothesis="H3", note=f"one leg of the confirmed combined configuration {c['configuration']}; the two legs together are one position")
                rows.append(row)
    rows.sort(key=lambda x: (-_num(x.get("calmar"), -9.0), -_num(x.get("sharpe"), -9.0)))
    return rows
