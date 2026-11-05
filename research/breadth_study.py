"""The breadth study (plan row R20, ``docs/TRADER_PLAN_2026-11-05.md`` section 6.1), SIMULATION ONLY.

Two pre-registered questions, fixed in :data:`PREREGISTRATION` before the first run (the
file ``docs/research/breadth_v1_preregistration.json`` carries a hash the study checks):

1. **The breadth book.** The S1 family (S1; S1+VC; S1+S5 where the market's funding
   covers at least 90 % of its in-sample bars, the replication study's rule) on the nine
   liquid OKX USDT markets the lake holds (BTC, ETH, SOL, XRP, DOGE, LINK, TRX, ADA, LTC),
   6H bars, no regime gate, as ONE account at the Trader tier with the section 4.3 brakes
   at book level and allocator v2's correlation cap (:func:`research.breadth.run_book`).
   Each sleeve's rule per walk-forward window is the one Sprint 2c's own runner selects
   (``scripts/run_research_v1c.py`` loaded as a module, as every study since R12), which
   also gives every sleeve's own verdict at the Trader cell and reproduces the stored
   numbers first. Judged at the portfolio level under the section 4.6 gates and the R5b
   candidate rule; the paper fleet's forward record is the judge.
2. **The rotation test.** ONE configuration: the top 3 of the nine by trailing 3-week
   return, equal weight, rebalanced weekly (decided at Sunday's close, filled Monday
   00:00 UTC), long only, only while BTC's close is above its 200-day average, sized by a
   20 % volatility target, 0.30 % a round trip plus 10 bps a side on altcoins; against
   holding BTC with the same sizing. Expected, before running, to fail to beat BTC.

Public data only; nothing here can reach an order; results never authorize trading.
"""

from __future__ import annotations

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
from research.brakes import TRADER_BRAKES, BrakeSpec
from research.breadth import (
    BasketConfig,
    BookConfig,
    BookResult,
    SleeveInput,
    basket_metrics,
    fixed_selector,
    run_book,
    run_weekly_basket,
    sleeve_contributions,
    sma_filter,
    top_n_selector,
)
from research.data import bars_per_year, load_or_resample_candles, positioning_context, split_holdout
from research.engine import Costs
from research.replication import DATA_END, load_ledger, load_v1c_runner, protocol_check, reproduction_check  # noqa: F401
from research.report_v1c import GATES, HOLDOUT_MIN_TRADES, holdout_verdict, yearly_gate_v2
from research.sizing import SIZING_TIERS, rule_fraction_matrix
from research.strategies import get_candidate
from research.strategies.base import days_to_bars
from research.strategies.s0_filters import NoTradeConfig
from research.sweep import build_frames
from research.trader_policy import PAYOFF_MIN, TIER_GATES, acceptance_check_r18, tier, trade_stats
from research.trader_policy_study import Cell
from research.walkforward import WalkForwardConfig, make_windows

ROOT = Path(__file__).resolve().parents[1]
V1C_RESULTS = ROOT / "docs" / "research" / "ensemble_v1c_results.json"
R12_RESULTS = ROOT / "docs" / "research" / "replication_v1d_results.json"
R13_RESULTS = ROOT / "docs" / "research" / "research_round_1_results.json"
R16_RESULTS = ROOT / "docs" / "research" / "research_round_2_results.json"
R18_RESULTS = ROOT / "docs" / "research" / "trader_policy_v1_results.json"
R19_RESULTS = ROOT / "docs" / "research" / "research_round_3_results.json"
R12_PREREGISTRATION = ROOT / "docs" / "research" / "replication_v1d_preregistration.json"
PREREGISTRATION_PATH = ROOT / "docs" / "research" / "breadth_v1_preregistration.json"
STUDY_LAKE_DIRNAME = "lake_breadth_v1"
STUDY_NAME = "R20 breadth v1"
CONTROL = "hold"
#: The nine liquid OKX USDT markets the lake holds (plan row R20), in the order that breaks same-bar ties among entries.
MARKETS: Tuple[str, ...] = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT", "LINK-USDT", "TRX-USDT", "ADA-USDT", "LTC-USDT")
MAJORS: Tuple[str, ...] = ("BTC-USDT", "ETH-USDT")
RULES: Tuple[str, ...] = ("S1", "S1+VC", "S1+S5")
TIMEFRAME = "6H"
MODE = "none"
FUNDING_COVERAGE_MIN = 0.90  # the replication study's rule (master plan Sprint 2b item 6): S1+S5 counts only where funding covers >= 90 % of in-sample bars
REFERENCE_CELL = Cell("reference", False)
JUDGED_CELL = Cell("trader", True)  # the paper fleet's cell (plan row R18): the sleeves' own verdicts are read here
CELLS: Tuple[Cell, ...] = (REFERENCE_CELL, JUDGED_CELL)
BOOK_TIER = "trader"
MAJOR_COSTS = Costs(fee_rate=0.0010, slippage_rate=0.0005)  # the engine's gate cost: 0.30 % a round trip
ALTCOIN_COSTS = Costs(fee_rate=0.0010, slippage_rate=0.0015)  # +10 bps a side: 0.50 % a round trip (plan section 4.2)
COST_SCENARIOS: Mapping[str, Tuple[float, float]] = {"measured_btc_eth": (0.0005, 0.0005), "altcoin": (0.0010, 0.0015)}
BOOK_CONFIG = BookConfig(brakes=TRADER_BRAKES, corr_cap=0.50, corr_lookback_days=60, corr_min_days=20, corr_threshold=0.70, rebalance_threshold=0.25)
#: Ablations of the book (diagnostics, never candidates): each switches one layer or replaces the costs.
ABLATIONS: Mapping[str, Dict[str, Any]] = {
    "heat_8pct": {"label": "the heat-cap variant of section 4.3: 8 % instead of 6 %", "brakes": "heat8"},
    "no_brakes": {"label": "every book brake off (the correlation cap and the cash constraint stay)", "brakes": None},
    "no_corr_cap": {"label": "the brakes on, allocator v2's correlation cap off", "corr_cap": None},
    "uniform_cost": {"label": "every market at the engine's 0.30 % round trip (no altcoin surcharge)", "uniform_cost": True},
    "raw": {"label": "no brake, no correlation cap: the sleeves share one equity and the cash constraint only", "brakes": None, "corr_cap": None},
}
#: Post-hoc diagnostics, NOT pre-registered (added after the first run, which showed the book halted for good by the hard stop): each a reading
#: beside the registered book, never a candidate, never a holdout; the pre-registered verdict ignores them.
POST_HOC: Mapping[str, Tuple[str, BrakeSpec]] = {
    "no_hard_stop": ("post hoc, not pre-registered: the hard stop off (the account re-arms at once instead of staying flat for good), everything else as registered",
                     BrakeSpec(hard_stop_dd=None)),
}
ROTATION_TOP_N = 3
ROTATION_LOOKBACK_DAYS = 21  # three weeks of daily closes
ROTATION_SMA_DAYS = 200
ROTATION_VOL_TARGET = 0.20
ROTATION_VOL_LOOKBACK_DAYS = 30
ROTATION_COSTS_PER_SIDE: Mapping[str, float] = {m: (0.0015 if m in MAJORS else 0.0025) for m in MARKETS}
BEATS_MARGIN_CALMAR = 0.1  # the Sprint 2c acceptance-clause margin (R12's beats_hold): "beats" means Calmar higher by more than this
CORRELATION_WINDOWS: Mapping[str, Tuple[str, Optional[str]]] = {"in_sample": ("2019-11-01", None), "recent": ("2024-01-01", None)}


class BreadthError(RuntimeError):
    """The study cannot be trusted (protocol mismatch, reproduction failure, a tampered pre-registration, a changed market list)."""


# -- the pre-registration -----------------------------------------------------------------------------------------------------

PREREGISTRATION: Dict[str, Any] = {
    "fixed_on": "2026-11-05, before any run (plan row R20)",
    "question": ("(1) Does the S1 family (S1; S1+VC; S1+S5 where the market has funding data) on the nine liquid OKX USDT markets, run as ONE "
                 "account at the Trader tier under the section 4.3 brakes and allocator v2's correlation cap, pass the section 4.6 gates at the "
                 "portfolio level, how much of a smoother curve do the imperfectly correlated markets buy (the diversification gain in Calmar beside "
                 "the sleeves on their own, holding BTC with policy sizing and the equal-weight hold of the nine), how often does each book-level "
                 "brake act and what does it cost, and does the book qualify as a candidate under the R5b rule? (2) Does one fixed rotation rule "
                 "(the top 3 of the nine by trailing 3-week return, weekly, long only, under the BTC 200-day filter, 20 % volatility target) beat "
                 "holding BTC with the same sizing after costs?"),
    "markets": (f"the nine liquid OKX USDT spot markets the lake holds: {', '.join(MARKETS)} (BTC and ETH from Sprint 2c; the seven others exactly as the "
                "replication study fixed them, checked against docs/research/replication_v1d_preregistration.json), in this fixed order; 6H bars "
                "resampled from the stored 1H candles; no regime gate (mode 'none')"),
    "sleeves": ("per market the S1 family: S1 (time-series momentum, multi-lookback vote, ATR stop), S1+VC (S1 with new entries only on a 30-day "
                "volume z-score above 1, round 1) and S1+S5 (S1 with the positioning filter) - S1+S5 only where the market's Binance funding covers "
                f"at least {FUNDING_COVERAGE_MIN * 100:.0f} % of its in-sample bars (the replication study's rule; a market below it has its S1+S5 reported "
                "'run without S5' and left out of the book, never counted twice); so up to 27 sleeves. Each sleeve's rule in each walk-forward window "
                "is the one Sprint 2c's own runner selects on that market (train Sharpe at full size, at least 20 train trades, entries among "
                "bracket-free rules then the exit bracket among siblings, the S0 no-trade filter with the FOMC calendar), with Sprint 2c's grids and "
                "brackets (none / tp2 / trail1 / time30; none for S1+S5): nothing is retuned, nothing is swept for the book"),
    "sleeve_verdicts": ("every sleeve is also judged on its own at the Trader cell (vt20/30 crash15/90dh cap2, the Turtle ladder, the section 4.3 "
                        "brakes on one sleeve) by the section 4.6 gates, exactly as the Trader Policy study judged the five confirmed configurations; "
                        "the Reference cell runs beside it for the reproduction of the stored numbers and for information"),
    "book": ("ONE account: the sleeves share one equity from the first bar on which any sleeve's first walk-forward test window starts; a sleeve "
             "joins when its own first test window starts (SOL's history is shorter) and the book runs continuously to the in-sample end (the "
             "sleeves' own walk-forward verdicts restart flat every 180 days; the book does not, because the account's ladder, hard stop and loss "
             "limits are about a continuous equity). Each entry is sized by the Trader tier on the BOOK's equity marked at the previous close "
             "(20 % volatility target over 30 bars of that market, half size in that market's crash state, at most 2 % of equity at risk on the "
             "stop), takes at most the cash left (spot, no leverage: an open position is never sold to make room for a new one) and keeps the rule's "
             "own stop and exit, Sprint 2c's 0.25 reduce-only rebalance included. Several sleeves may hold the same market; they count as one bet"),
    "brakes": ("the section 4.3 brakes at BOOK level, entries only, with their fixed numbers: the Turtle ladder (x0.8 at -10 % from the book's "
               "equity peak, x0.64 at -20 %, restored on a new high); the hard stop (-30 %: no new entry until the simulated account ends); the entry "
               "caps - at most 1 new entry per MARKET per UTC day across the market's sleeves, 3 per day across the book, none in a market on the "
               "bar after an exit there (when more entries want the same bar than the caps allow, the rules' own strength decides, ties by the fixed "
               "market order, then the sleeve order S1, S1+VC, S1+S5); the loss limits on the book's equity (3 % over the trailing 24 hours blocks "
               "entries for the next 24 hours; 6 % from Monday 00:00 UTC until the next Monday; 10 % from the month's start until the next month); "
               "the heat cap (the current risk, price to current stop on current equity, of the open positions plus the entries wanted, at most 6 % "
               "in total and 3 % per bet, a bet being the sleeves whose markets' trailing 60-day daily-return correlation is 0.70 or more, or the same "
               "market; when the wanted entries would exceed it, every open and new position of the bet with a positive risk is sized down equally - "
               "an open position whose stop has moved above the price carries no risk and is left alone). The brakes are read from the same "
               "EntryBrakes state machine the single-sleeve studies ran (one column, the book's equity), so their arithmetic is R18's"),
    "allocator_v2": ("reused for its daily record and its correlation cap only: at the first bar of every UTC day the sleeves of one bet may hold at "
                     "most 50 % of equity at the previous close; above it the bet's positions are scaled down equally at the open and the bet's new "
                     "entries that day are scaled by the same factor (groups by the 60-day correlation >= 0.70, at least 20 days, as in R5b); its "
                     "portfolio volatility target and its weekly cash-out are OFF so the tier is not sized twice - the effective risk per position "
                     "(the per-entry risk after the ladder, heat and correlation multipliers and the cash constraint) is reported"),
    "costs": ("BTC-USDT and ETH-USDT at the engine's 0.10 % fee + 0.05 % slippage a side (0.30 % a round trip); the seven altcoins at 0.10 % + 0.15 % "
              "a side (0.50 % a round trip, plan section 4.2); the book is also replayed with every market at 0.30 % as an ablation"),
    "ablations": {k: v["label"] for k, v in ABLATIONS.items()},
    "ablation_rule": "ablations are diagnostics that explain the result; none is a candidate and none opens a holdout",
    "gates": (f"the plan's section 4.6 gates at the Trader tier on the book's continuous equity: profit factor > {GATES['profit_factor_min']} (pooled over the "
              f"book's trades), Sharpe > {GATES['sharpe_min']}, Calmar > {GATES['calmar_min']}, >= {GATES['rolling_12m_positive_min'] * 100:.0f} % of rolling 12-month "
              f"windows positive, >= {GATES['min_trades']} trades, max drawdown <= {TIER_GATES['higher']['max_drawdown_max'] * 100:.0f} %, worst calendar year >= "
              f"{TIER_GATES['higher']['worst_calendar_year_min'] * 100:.0f} %, average win / average loss >= {PAYOFF_MIN:g}; the +-30 % robustness gate is carried by the "
              "sleeves (the R5b construction) and counted as passed at the book level; expectancy in R is reported, not gated"),
    "candidate_rule": ("the R5b rule, pre-registered for portfolio studies: the book is a CANDIDATE only when it passes the gates AND (every sleeve in "
                       "it passes the section 4.6 gates on its own at the Trader cell, OR the book's own holdout confirms it); a book that passes the "
                       "gates but is not a candidate is 'passed, not a candidate' and nothing joins the fleet"),
    "comparison_lines": ("(a) holding BTC with policy sizing: the always-long control at the Trader cell on BTC-USDT 6H, run by the same runner "
                         "(the stored R19/R18 numbers must reproduce), and the same hold run as one sleeve through the book simulator (continuous, "
                         "no window restarts); (b) the equal-weight hold of the nine: 1/9 in every market with a close that day, re-sized weekly to "
                         "the 20 % volatility target of the basket (the rotation's own machinery, the same costs), and plain equal-weight buy-and-hold; "
                         "(c) each sleeve on its own at the Trader cell; (d) BTC buy-and-hold over the book's span"),
    "diversification_reading": ("the diversification gain in Calmar = the book's Calmar minus (i) the median Calmar of its sleeves at the Trader cell, "
                                "(ii) the Calmar of the best sleeve, (iii) the Calmar of holding BTC with policy sizing (the Trader-cell control); the "
                                "book's volatility beside the average sleeve volatility; the pairwise daily-return correlations of the nine markets over "
                                "the in-sample years and since 2024-01-01 (in-sample part only; the plan's own figure for the four confirmed markets is "
                                "0.73-0.82 for 2024-26), and the correlations of the sleeves' daily P&L contributions inside the book"),
    "brake_judgement": ("every book-level brake is judged by its trigger counts and its cost: the book beside each ablation (the same signals, one "
                        "layer off); a brake that costs more than 0.1 Calmar is flagged for the owner, never silently kept or dropped; the loss limits "
                        "and the heat cap, which cannot act on one sleeve, are read here for the first time"),
    "rotation": {
        "rule": (f"at every Sunday close (so the fill is Monday 00:00 UTC): rank the nine markets with at least {ROTATION_LOOKBACK_DAYS + 1} daily closes by "
                 f"their trailing {ROTATION_LOOKBACK_DAYS}-day close-to-close return, hold the top {ROTATION_TOP_N} at equal weight (ties by the fixed market order), "
                 f"long only; only while BTC's daily close is above its {ROTATION_SMA_DAYS}-day simple moving average - a BTC close below it at any day's close "
                 "sends the basket to cash at the next open and keeps it there until a Sunday on which BTC is above it again; no per-coin stop: the "
                 f"weekly rebalance and the filter are its only exits; sized at each rebalance by a {ROTATION_VOL_TARGET * 100:.0f} % volatility target: the scale is "
                 f"min(1, {ROTATION_VOL_TARGET * 100:.0f} % / the annualized standard deviation of the equal-weight basket's last {ROTATION_VOL_LOOKBACK_DAYS} daily returns); "
                 "costs on the traded notional at every fill: 0.15 % a side on BTC/ETH (0.30 % a round trip), 0.25 % a side on the altcoins (+10 bps); "
                 "one close per UTC day (the last 6H bar's close) and the next day's first open as the fill"),
        "comparison": ("holding BTC with the same policy sizing and machinery: always long BTC, re-sized every Monday to the same 20 % volatility target "
                       "of BTC's own trailing 30 daily returns, 0.15 % a side on the re-sizing; also the equal-weight hold of the nine with the same "
                       "sizing, plain BTC buy-and-hold, and the stored always-long BTC-USDT 6H control at the Trader cell"),
        "span": ("the in-sample period only: from the first Monday on which BTC's 200-day average, the 21-day lookback and the 30-day volatility are all "
                 "available (2020-07 on this data) to the in-sample end (the last full UTC day before the holdout split); every comparison line is run "
                 "over exactly the same days"),
        "pass_rule": (f"the rotation 'beats BTC' when, over that span, its Calmar exceeds the BTC comparison's by more than {BEATS_MARGIN_CALMAR:g}, its CAGR "
                      f"exceeds the BTC comparison's, and its max drawdown is at most {TIER_GATES['higher']['max_drawdown_max'] * 100:.0f} %"),
        "expectation": ("stated before the run: it does NOT beat BTC after costs (plan section 2.7: post-2020 long-only top-coin momentum has not "
                        "reliably beaten holding Bitcoin after costs; the 1-4 week effect lives in the largest coins and decays within weeks); if it "
                        "passes anyway its holdout is opened once and, if that confirms it (positive return and ahead of the BTC comparison over the "
                        "same days), it is recorded for the fleet as one account; if it fails the question is closed with our own numbers"),
    },
    "holdout": ("the last 12 months (2025-10-20 -> 2026-10-20), opened once, only by the full pre-registered study (every market, rule and cell, the "
                "book and the rotation, with the reproduction, never --quick): (a) by the runner for the sleeves that pass on their own at the Trader "
                "cell and for the hold controls (the comparison line, as in every study); (b) for the BOOK only when it passes the section 4.6 gates "
                "on the walk-forward years - the book runs over the untouched months with each sleeve's most-often-selected rule (the runner's own "
                "holdout construction), starting flat, the correlations warmed up on history; the v1c verdict (positive return, pooled profit factor "
                f"> 1, >= {HOLDOUT_MIN_TRADES} trades); (c) for the rotation only when it passes its in-sample rule. Every opening goes into an append-only "
                "ledger the report shows, beside the earlier looks at the same months (R12, R13, R16, R18, R19). CAVEAT, stated before the run: these "
                "months were opened before for every market (hold + policy lost on all nine) and for several of these very sleeves, so their falling "
                "direction is known; a confirmation is necessary, not sufficient, and the paper fleet's forward record is the judge"),
    "fleet": ("a book that is a candidate is RECORDED for the paper fleet as one portfolio account (a source-tagged row naming the study, the tier, "
              "the brakes, the correlation cap, the sleeves and their rules); a rotation that passes and is confirmed is recorded likewise. The fleet "
              "has no account type that runs a multi-market Trader-tier book or a weekly rotation, so nothing is appended to the shortlist by this "
              "row: applying a recorded row is the next plan row's work (the R18a/R18b precedent), through the R18 loader extension, never omitting "
              "the protocol check; existing accounts are untouched; nothing joins demo or live"),
    "protocol": ("Sprint 2c's own runner (scripts/run_research_v1c.py loaded as a module, its run_series) with Sprint 2c's defaults for everything "
                 "the cell does not define: the grids and brackets, the S0 filter with the FOMC calendar, the walk-forward (train 540 d, purge 7 d, test "
                 "180 d, Sharpe with >= 20 train trades, entries then bracket) and the 0.25 reduce-only rebalance; the tier replaces only the policy "
                 "sizing (and adds its brakes); every job's protocol check is recorded and the study stops on any mismatch the job does not explain "
                 "(a tier is a recorded policy_sizing mismatch, never hidden); the book is a replay of the selected rules, not a selection"),
    "data": (f"OKX public 1H spot candles of the nine markets (6H resampled from 1H), frozen in a study lake at Sprint 2c's data end (bar close <= "
             f"{DATA_END}) so the walk-forward and the untouched 12 months (2025-10-20 -> 2026-10-20) are the same calendar window as in Sprint 2c, "
             "R12, R13, R16, R18 and R19; Binance public funding (and open interest for BTC/ETH) for the S5 filter as before; one close per UTC day "
             "from the 6H bars for the correlations and the rotation"),
    "reproduction": ("before anything is judged, the same code path re-runs, at the Reference cell, hold / S1 / S1+S5 on every market (Sprint 2c's "
                     "stored numbers for BTC/ETH, the replication study's for the seven others) and S1+VC on every market (round 1's for BTC/ETH, round "
                     "2's for the seven), and, at the Trader cell, hold on every market (round 3's) and S1+S5 BTC-USDT 6H, S1 and S1+S5 SOL-USDT 6H (the "
                     "Trader Policy study's); each must give the stored walk-forward numbers to 6 decimals, the same trade counts, the same most-selected "
                     "rules and the same gate verdicts, otherwise the study stops"),
    "no_changes_after_results": "no gate, tier, brake number, cap, rule, market, cost, threshold or verdict rule changes after the results are in; if a gate looks wrong the report says so",
}


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def check_replication_markets(path: Path = R12_PREREGISTRATION) -> List[str]:
    """The seven altcoin markets must be exactly the replication study's fixed list (the R12 file is the authority)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    chosen = list(data.get("chosen") or [])
    expected = [m for m in MARKETS if m not in MAJORS]
    if sorted(chosen) != sorted(expected):
        raise BreadthError(f"the replication study's markets {sorted(chosen)} are not this study's altcoins {sorted(expected)}")
    return chosen


@dataclass(frozen=True)
class StudyConfig:
    markets: Tuple[str, ...] = MARKETS
    rules: Tuple[str, ...] = RULES
    cells: Tuple[str, ...] = tuple(c.key for c in CELLS)
    book: bool = True
    rotation: bool = True
    reproduction: bool = True
    data_end: str = DATA_END
    quick: bool = False
    lake_dir: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        for k in ("markets", "rules", "cells"):
            out[k] = list(getattr(self, k))
        return out

    @property
    def cell_objects(self) -> List[Cell]:
        return [c for c in CELLS if c.key in self.cells]


def config_from_dict(d: Mapping[str, Any]) -> StudyConfig:
    return StudyConfig(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items()})


def preregistration_hash(cfg: StudyConfig, prereg: Mapping[str, Any]) -> str:
    return _sha256_json({"preregistration": PREREGISTRATION, "file": prereg, "config": cfg.to_dict()})


def full_study_requested(cfg: StudyConfig) -> bool:
    """The holdout may only be opened by the complete pre-registered study."""
    return (not cfg.quick and cfg.reproduction and cfg.book and cfg.rotation and sorted(cfg.markets) == sorted(MARKETS)
            and sorted(cfg.rules) == sorted(RULES) and sorted(cfg.cells) == sorted(c.key for c in CELLS))


def preregister(path: Path, *, now: Optional[datetime] = None, force: bool = False, r12_path: Path = R12_PREREGISTRATION) -> Dict[str, Any]:
    """Write the fixed text, the numbers and the full-study configuration with a hash; refuse a second write unless forced."""
    path = Path(path)
    if path.exists() and not force:
        raise BreadthError(f"{path} exists: the study was already fixed; a second write would be a second registration")
    check_replication_markets(r12_path)
    written_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    payload: Dict[str, Any] = {
        "note": "Plan row R20. The markets, sleeves, book construction, brakes, caps, costs, gates, candidate rule, rotation rule, readings and verdict rules of the breadth study, fixed BEFORE the first run. Never edited.",
        "written_at": written_at, "data_end": DATA_END, "gates": dict(GATES), "tier_gates": {k: dict(v) for k, v in TIER_GATES.items()}, "payoff_min": PAYOFF_MIN,
        "markets": list(MARKETS), "rules": list(RULES), "timeframe": TIMEFRAME, "mode": MODE, "funding_coverage_min": FUNDING_COVERAGE_MIN,
        "cells": [c.to_dict() for c in CELLS], "judged_cell": JUDGED_CELL.to_dict(), "tier": tier(BOOK_TIER).to_dict(), "brakes_on": TRADER_BRAKES.to_dict(),
        "book_config": BOOK_CONFIG.to_dict(), "costs": {"majors": {"fee_rate": MAJOR_COSTS.fee_rate, "slippage_rate": MAJOR_COSTS.slippage_rate},
                                                        "altcoins": {"fee_rate": ALTCOIN_COSTS.fee_rate, "slippage_rate": ALTCOIN_COSTS.slippage_rate}},
        "ablations": {k: dict(v) for k, v in ABLATIONS.items()},
        "rotation": {"top_n": ROTATION_TOP_N, "lookback_days": ROTATION_LOOKBACK_DAYS, "sma_days": ROTATION_SMA_DAYS, "vol_target": ROTATION_VOL_TARGET,
                     "vol_lookback_days": ROTATION_VOL_LOOKBACK_DAYS, "costs_per_side": dict(ROTATION_COSTS_PER_SIDE), "beats_margin_calmar": BEATS_MARGIN_CALMAR},
        "cost_scenarios": {k: list(v) for k, v in COST_SCENARIOS.items()}, "configuration": StudyConfig().to_dict(), "preregistration": PREREGISTRATION,
    }
    payload["sha256"] = _sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return payload


def load_preregistration(path: Path = PREREGISTRATION_PATH) -> Dict[str, Any]:
    """The pre-registration file, checked: its hash, and that its text and numbers are those in this module."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("preregistration"), dict):
        raise BreadthError(f"{path} is not a pre-registration file")
    expected = _sha256_json({k: v for k, v in data.items() if k != "sha256"})
    if data.get("sha256") != expected:
        raise BreadthError(f"{path} was edited after it was written (hash mismatch)")
    if data["preregistration"] != PREREGISTRATION:
        raise BreadthError("the pre-registration text in research/breadth_study.py differs from the registered file; neither may change after registration")
    if data.get("gates") != dict(GATES) or data.get("tier_gates") != {k: dict(v) for k, v in TIER_GATES.items()} or data.get("payoff_min") != PAYOFF_MIN:
        raise BreadthError("the gates differ from the registered ones")
    if list(data.get("markets") or []) != list(MARKETS) or list(data.get("rules") or []) != list(RULES) or data.get("timeframe") != TIMEFRAME:
        raise BreadthError("the markets, rules or timeframe differ from the registered ones")
    if data.get("judged_cell") != JUDGED_CELL.to_dict() or data.get("brakes_on") != TRADER_BRAKES.to_dict() or data.get("book_config") != BOOK_CONFIG.to_dict():
        raise BreadthError("the cell, the brakes or the book configuration differ from the registered ones")
    rot = data.get("rotation") or {}
    if (rot.get("top_n"), rot.get("lookback_days"), rot.get("sma_days"), rot.get("vol_target"), rot.get("vol_lookback_days")) != (
            ROTATION_TOP_N, ROTATION_LOOKBACK_DAYS, ROTATION_SMA_DAYS, ROTATION_VOL_TARGET, ROTATION_VOL_LOOKBACK_DAYS) or rot.get("costs_per_side") != dict(ROTATION_COSTS_PER_SIDE):
        raise BreadthError("the rotation rule differs from the registered one")
    return data


# -- the Sprint 2c runner and the jobs -----------------------------------------------------------------------------------------

def runner():
    return load_v1c_runner()


def costs_for(instrument: str) -> Costs:
    return MAJOR_COSTS if instrument in MAJORS else ALTCOIN_COSTS


def job_argv(cell: Cell, strategies: Sequence[str], *, evaluate_holdout: bool, lake_dir: Optional[str], quick: bool) -> List[str]:
    """Sprint 2c's command line for one job: the cell's sizing and brakes, this study's rules, the cost replays."""
    t = tier(cell.tier)
    s = t.sizing
    argv: List[str] = ["--strategies", *strategies, "--regime-modes", MODE, "--timeframes", TIMEFRAME, "--tier", cell.tier]
    if s.kind == "risk":
        argv += ["--policy-kind", "risk", "--policy-risk", f"{float(s.risk_fraction):g}"]
    else:
        argv += ["--policy-target-vol", f"{s.target_vol:g}", "--policy-lookback", str(int(s.vol_lookback))]
    if s.risk_cap is not None:
        argv += ["--policy-risk-cap", f"{float(s.risk_cap):g}"]
    if not s.ladder:
        argv.append("--policy-no-ladder")
    if t.turtle_ladder:
        argv.append("--turtle-ladder")
    if cell.brakes:
        argv.append("--brakes")
    argv += ["--cost-scenarios", *[f"{name}={fee:g}:{slip:g}" for name, (fee, slip) in COST_SCENARIOS.items()]]
    if evaluate_holdout:
        argv.append("--evaluate-holdout")
    if quick:
        argv.append("--quick")
    if lake_dir:
        argv += ["--lake-dir", lake_dir]
    return argv


def plan_jobs(cfg: StudyConfig, *, evaluate_holdout: bool) -> List[Dict[str, Any]]:
    """One job per (market, cell): the hold control and the study's rules through Sprint 2c's ``run_series``."""
    jobs: List[Dict[str, Any]] = []
    strategies = [CONTROL] + [r for r in RULES if r in cfg.rules]
    for inst in MARKETS:
        if inst not in cfg.markets:
            continue
        for cell in cfg.cell_objects:
            jobs.append({"cfg": cfg.to_dict(), "instrument": inst, "timeframe": TIMEFRAME, "cell": cell.to_dict(), "strategies": list(strategies),
                         "evaluate_holdout": bool(evaluate_holdout and cell == JUDGED_CELL)})
    return jobs


def job_args(job: Mapping[str, Any]) -> Dict[str, Any]:
    cfg = config_from_dict(job["cfg"])
    cell = Cell(job["cell"]["tier"], bool(job["cell"]["brakes"]), job["cell"].get("variant", "none"))
    argv = job_argv(cell, job["strategies"], evaluate_holdout=bool(job["evaluate_holdout"]), lake_dir=cfg.lake_dir, quick=cfg.quick)
    return dict(vars(runner().parse_args(argv)))


SERIES_KEYS = ("instrument", "timeframe", "results", "failures", "benchmark", "span", "holdout_span", "positioning", "s0_blocked_share", "skipped")


def run_job(job: Mapping[str, Any]) -> Dict[str, Any]:
    """Process-pool entry point: Sprint 2c's ``run_series`` for one job."""
    v1c = runner()
    args = job_args(job)
    print(f"[{job['instrument']} {job['timeframe']} @ {job['cell']['key']}] {job['strategies']} ...", flush=True)
    out = v1c.run_series(dict(args), job["instrument"], job["timeframe"])
    series: Dict[str, Any] = {k: out.get(k) for k in SERIES_KEYS}
    series.update({"cell": dict(job["cell"]), "strategies": list(job["strategies"]), "args": dict(args),
                   "trades": {f"{k}|{m}": t for (k, m), t in (out.get("trades") or {}).items()}})
    return series


def protocol_check_job(args: Mapping[str, Any], meta: Mapping[str, Any], cell: Cell) -> Dict[str, Any]:
    """The replication study's protocol check with the cell's deliberate, documented difference named beside the raw mismatches."""
    narrowed = dict(args, strategies=[s for s in args["strategies"] if s in set(meta.get("strategies") or [])])
    check = protocol_check(narrowed, meta)
    expected: Dict[str, str] = {}
    if cell.tier != "reference":
        expected["policy_sizing"] = f"the {cell.tier} tier ({tier(cell.tier).label})"
    unexplained = {k: v for k, v in check["mismatches"].items() if k not in expected}
    check.update({"cell": cell.to_dict(), "expected_mismatches": expected, "unexplained_mismatches": unexplained, "ok_for_cell": not unexplained,
                  "new_candidates": [s for s in args["strategies"] if s not in set(meta.get("strategies") or [])],
                  "r18": {"tier": cell.tier, "brakes_on": cell.brakes, "brakes": TRADER_BRAKES.to_dict() if (cell.brakes and tier(cell.tier).turtle_ladder) else None,
                          "variant": cell.variant},
                  "protocol_variant": None,
                  "note": "a tier replaces Sprint 2c's policy sizing by design; every other protocol parameter is checked"})
    return check


def result_key(candidate: str, instrument: str, cell_key: str) -> str:
    return f"{candidate}|{instrument}|{TIMEFRAME}|{MODE}|{cell_key}"


def configuration_name(candidate: str, instrument: str) -> str:
    return f"{candidate} {instrument} {TIMEFRAME} [{MODE}]"


def _mode(r: Mapping[str, Any]) -> Optional[str]:
    return (r.get("regime") or {}).get("mode")


def merge_results(outputs: Sequence[Mapping[str, Any]], stored_meta: Mapping[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Every job's results keyed ``candidate|instrument|6H|none|cell`` with their cell and protocol check; plus per-series info."""
    merged: Dict[str, Dict[str, Any]] = {}
    series_info: Dict[str, Dict[str, Any]] = {}
    for o in outputs:
        cell = Cell(o["cell"]["tier"], bool(o["cell"]["brakes"]), o["cell"].get("variant", "none"))
        info = series_info.setdefault(o["instrument"], {"instrument": o["instrument"], "timeframe": o["timeframe"], "failures": [], "skipped": None})
        if o.get("skipped"):
            info["skipped"] = o["skipped"]
            continue
        for k in ("benchmark", "span", "holdout_span", "positioning", "s0_blocked_share"):
            if info.get(k) is None and o.get(k) is not None:
                info[k] = o[k]
        info["failures"].extend(o.get("failures") or [])
        cov = float(((o.get("positioning") or {}).get("funding_coverage")) or 0.0)
        info["funding_coverage"] = cov
        info["s5_active"] = bool(cov >= FUNDING_COVERAGE_MIN)
        check = protocol_check_job(o["args"], stored_meta, cell)
        for r in o.get("results") or []:
            r = dict(r)
            cand = r["candidate"]
            r.update({"cell": cell.to_dict(), "configuration": configuration_name(cand, r["instrument"]), "protocol_check": check,
                      "holdout_confirmed": holdout_verdict(r) if r.get("holdout") else None, "role": "control" if cand == CONTROL else "sleeve",
                      "funding_coverage": cov, "s5_applies": ("S5" not in cand) or info["s5_active"]})
            r["in_book"] = bool(r["role"] == "sleeve" and r["s5_applies"] and cell == JUDGED_CELL)
            r["display_candidate"] = cand if r["s5_applies"] else f"{cand} (run without S5: funding covers {cov * 100:.0f}% of the in-sample bars)"
            merged[result_key(cand, r["instrument"], cell.key)] = r
    return merged, series_info


def result_of(merged: Mapping[str, Mapping[str, Any]], candidate: str, instrument: str, cell: Cell) -> Optional[Mapping[str, Any]]:
    return merged.get(result_key(candidate, instrument, cell.key))


def rebuild_merged(results: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {result_key(r["candidate"], r["instrument"], r["cell"]["key"]): dict(r) for r in results}


# -- stored results and the reproduction -------------------------------------------------------------------------------------------

def _flat(doc: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    if isinstance(doc.get("results"), list):
        return list(doc["results"])
    return [r for s in doc.get("series", []) for r in s.get("results", [])]


def stored_results(docs: Mapping[str, Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """The stored numbers this study reproduces, per cell: Sprint 2c / R12 / R13 / R16 (Reference), R18 / R19 (Trader)."""
    reference: List[Dict[str, Any]] = []
    trader: List[Dict[str, Any]] = []
    for name, doc in docs.items():
        for r in _flat(doc):
            if r.get("skipped") or r.get("timeframe") != TIMEFRAME or _mode(r) != MODE:
                continue
            cell = (r.get("cell") or {}).get("key")
            if cell is None or cell == REFERENCE_CELL.key:
                if cell is None and name in ("R18 Trader Policy v1", "R19 research round 3"):
                    continue
                reference.append(dict(r, study_source=name))
            elif cell == JUDGED_CELL.key:
                trader.append(dict(r, study_source=name))
    return {"reference": reference, "trader": trader}


def _dedupe(pool: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """One stored result per configuration (the earliest study wins: Sprint 2c before round 1, the replication study before round 2)."""
    seen: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    for r in pool:
        key = (r["candidate"], r["instrument"])
        seen.setdefault(key, r)
    return list(seen.values())


def reproduction_checks(merged: Mapping[str, Mapping[str, Any]], stored: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    """Every result with a stored counterpart at its cell, against that stored result (6 decimals, trades, rule, verdict)."""
    checks: List[Dict[str, Any]] = []
    for cell, pool_name in ((REFERENCE_CELL, "reference"), (JUDGED_CELL, "trader")):
        pool = _dedupe(stored.get(pool_name) or [])
        rows = [r for r in merged.values() if r["cell"]["key"] == cell.key and any(s["candidate"] == r["candidate"] and s["instrument"] == r["instrument"] for s in pool)]
        if not rows:
            continue
        for c in reproduction_check({"results": rows}, pool):
            exp = next(s for s in pool if s["candidate"] == c["candidate"] and s["instrument"] == c["instrument"])
            c.update({"cell": cell.key, "study": exp.get("study_source"), "configuration": configuration_name(c["candidate"], c["instrument"])})
            checks.append(c)
    return checks


# -- the sleeves ---------------------------------------------------------------------------------------------------------------------

def _num(v: Any, default: float = float("nan")) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x


def _finite(v: Any) -> Optional[float]:
    x = _num(v)
    return None if (math.isnan(x) or math.isinf(x)) else x


def _median(values: Sequence[Any]) -> Optional[float]:
    xs = sorted(float(v) for v in values if v is not None and isinstance(v, (int, float)) and math.isfinite(float(v)))
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else 0.5 * (xs[m - 1] + xs[m])


def _metrics_of(r: Mapping[str, Any]) -> Dict[str, Any]:
    oos = r.get("oos") or {}
    acc = r.get("acceptance_r18") or r.get("acceptance") or {}
    trades = ((r.get("r18") or {}).get("trades") or {})
    return {"cagr": oos.get("cagr"), "sharpe": oos.get("sharpe"), "max_drawdown": oos.get("max_drawdown"), "calmar": oos.get("calmar"),
            "profit_factor": oos.get("profit_factor"), "n_trades": oos.get("n_trades"), "trades_per_year": oos.get("trades_per_year"),
            "total_return": oos.get("total_return"), "exposure": oos.get("exposure"), "avg_allocation": oos.get("avg_allocation"), "ann_vol": oos.get("ann_vol"),
            "fees_pct_per_year": oos.get("fees_pct_per_year"), "win_rate": oos.get("win_rate"), "windows": oos.get("windows"), "windows_traded": oos.get("windows_traded"),
            "rolling_12m_positive_share": acc.get("rolling_positive_share"), "worst_calendar_year_return": acc.get("worst_calendar_year_return"),
            "payoff_ratio": acc.get("payoff_ratio") if "payoff_ratio" in acc else trades.get("payoff_ratio"), "expectancy_r": trades.get("expectancy_r"),
            "risk_pct_mean": trades.get("risk_pct_mean"), "yearly": {str(k): v for k, v in (r.get("yearly") or {}).items()},
            "passed": bool(acc.get("passed")), "failed": list(acc.get("failed") or [])}


def sleeve_table(merged: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Per market and rule: both cells' numbers, the own verdict at the Trader cell, the holdout, whether the sleeve is in the book."""
    rows: List[Dict[str, Any]] = []
    for inst in MARKETS:
        for cand in RULES:
            tr = result_of(merged, cand, inst, JUDGED_CELL)
            ref = result_of(merged, cand, inst, REFERENCE_CELL)
            if tr is None and ref is None:
                continue
            base = tr or ref
            hold = result_of(merged, CONTROL, inst, JUDGED_CELL)
            rows.append({"instrument": inst, "candidate": cand, "configuration": configuration_name(cand, inst), "display_candidate": base.get("display_candidate"),
                         "in_book": bool(tr is not None and tr.get("in_book")), "s5_applies": bool(base.get("s5_applies", True)), "funding_coverage": base.get("funding_coverage"),
                         "trader": None if tr is None else _metrics_of(tr), "reference": None if ref is None else _metrics_of(ref),
                         "passed_own": bool(tr is not None and (tr.get("acceptance_r18") or {}).get("passed")),
                         "holdout": None if tr is None else tr.get("holdout"), "holdout_confirmed": None if tr is None else tr.get("holdout_confirmed"),
                         "selected_params": None if tr is None else tr.get("selected_params"), "rule_frequency": None if tr is None else tr.get("rule_frequency"),
                         "hold_calmar_trader": ((hold or {}).get("oos") or {}).get("calmar"),
                         "brake_counts": None if tr is None else ((tr.get("r18") or {}).get("brake_summary") or {}).get("counts")})
    return rows


# -- the book's inputs from the sleeves' selected rules -----------------------------------------------------------------------------------

@dataclass
class MarketData:
    instrument: str
    df_all: pd.DataFrame
    df_in: pd.DataFrame
    df_hold: pd.DataFrame
    windows: list
    ppy: float


def walk_forward_config() -> WalkForwardConfig:
    v1c = runner()
    args = v1c.parse_args(["--timeframes", TIMEFRAME])
    return v1c._wf_config(args, TIMEFRAME)


def no_trade_config() -> NoTradeConfig:
    v1c = runner()
    return v1c._no_trade(v1c.parse_args([]))


def load_market(layout: LakeLayout, instrument: str, *, holdout_months: int = 12) -> MarketData:
    df_all = load_or_resample_candles(layout, instrument, TIMEFRAME)
    if len(df_all) < 1000:
        raise BreadthError(f"only {len(df_all)} {TIMEFRAME} bars for {instrument} in the study lake")
    df_in, df_hold = split_holdout(df_all, holdout_months=holdout_months)
    return MarketData(instrument, df_all, df_in, df_hold, make_windows(len(df_in), walk_forward_config()), bars_per_year(TIMEFRAME))


def _canon_params(p: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: (tuple(v) if isinstance(v, list) else v) for k, v in p.items()}


def _params_key(p: Mapping[str, Any]) -> str:
    return json.dumps({k: (list(v) if isinstance(v, tuple) else v) for k, v in sorted(p.items())}, sort_keys=True)


def sleeve_arrays(layout: LakeLayout, md: MarketData, result: Mapping[str, Any], *, holdout: bool = False) -> Dict[str, np.ndarray]:
    """One sleeve's bar-by-bar arrays over the market's own bars (in-sample, or the whole series with the most-often rule for the holdout).

    In the in-sample replay bar ``i`` carries the rule the walk-forward selected for the test window ``i`` falls in (nothing before the first
    test window, nothing in a window where no rule qualified); the Trader fraction reads that rule's stop. For the holdout the runner's own
    construction is used: the most-often-selected rule over the whole series (indicators warm), live only on the holdout bars.
    """
    cand = get_candidate(result["candidate"])
    ctx = positioning_context(layout, md.instrument, TIMEFRAME, source="binance")
    no_trade = no_trade_config()
    df = md.df_all if holdout else md.df_in
    n = len(df)
    windows_rules: List[Tuple[slice, Optional[Dict[str, Any]]]] = []
    if holdout:
        sel = _canon_params(result.get("selected_params") or {})
        windows_rules.append((slice(len(md.df_in), len(md.df_all)), sel if sel else None))
    else:
        stored_windows = {int(w["idx"]): w for w in (result.get("windows") or [])}
        for w in md.windows:
            sw = stored_windows.get(int(w.idx))
            rule = _canon_params(sw["rule"]) if (sw and sw.get("rule")) else None
            windows_rules.append((w.test, rule))
    distinct: Dict[str, Dict[str, Any]] = {}
    for _, rule in windows_rules:
        if rule:
            distinct.setdefault(_params_key(rule), rule)
    out = {"desired": np.zeros(n, dtype=bool), "stop": np.full(n, np.nan), "fraction": np.full(n, np.nan), "strength": np.full(n, np.nan),
           "target": np.full(n, np.nan), "time_stop": np.full(n, np.nan), "trail_activate": np.full(n, np.nan), "trail_r": np.full(n, np.nan)}
    if not distinct:
        return out
    combos = list(distinct.values())
    frames = build_frames(cand, df, combos, ctx, no_trade=no_trade)
    fracs = rule_fraction_matrix(df, SIZING_TIERS[BOOK_TIER], frames.stop, TIMEFRAME, md.ppy)
    col_of = {_params_key(c): j for j, c in enumerate(combos)}
    for sl, rule in windows_rules:
        if not rule:
            continue
        j = col_of[_params_key(rule)]
        out["desired"][sl] = frames.desired[sl, j]
        out["stop"][sl] = frames.stop[sl, j]
        out["fraction"][sl] = fracs[sl, j]
        out["strength"][sl] = frames.strength[sl, j]
        if frames.target is not None:
            out["target"][sl] = frames.target[sl, j]
        ts = frames.time_stops[j]
        if ts is not None:
            out["time_stop"][sl] = float(ts)
        if frames.trail_activate is not None and np.isfinite(frames.trail_dist[j]):
            out["trail_activate"][sl] = float(frames.trail_activate[j])
            out["trail_r"][sl] = float(frames.trail_dist[j])
    return out


def hold_arrays(md: MarketData, *, holdout: bool = False) -> Dict[str, np.ndarray]:
    """The always-long control as a sleeve: long from its first test window on (or over the holdout), the Trader fraction with no stop."""
    df = md.df_all if holdout else md.df_in
    n = len(df)
    desired = np.zeros(n, dtype=bool)
    if holdout:
        desired[len(md.df_in):] = True
    elif md.windows:
        desired[md.windows[0].test.start:] = True
    fracs = rule_fraction_matrix(df, SIZING_TIERS[BOOK_TIER], np.full((n, 1), np.nan), TIMEFRAME, md.ppy)[:, 0]
    return {"desired": desired, "stop": np.full(n, np.nan), "fraction": fracs, "strength": np.full(n, np.nan), "target": np.full(n, np.nan),
            "time_stop": np.full(n, np.nan), "trail_activate": np.full(n, np.nan), "trail_r": np.full(n, np.nan)}


def book_clock(data: Mapping[str, MarketData], *, holdout: bool = False) -> pd.DatetimeIndex:
    """The union of the markets' bars (the whole series for the holdout, the in-sample bars otherwise); the book trades from :func:`book_start`."""
    idx = None
    for md in data.values():
        part = md.df_all.index if holdout else md.df_in.index
        idx = part if idx is None else idx.union(part)
    return pd.DatetimeIndex(idx).sort_values()


def book_start(data: Mapping[str, MarketData], clock: pd.DatetimeIndex, instruments: Sequence[str], *, holdout: bool = False) -> int:
    """The first bar the book trades: the earliest first test window of its markets (the first holdout bar for the holdout); earlier bars warm up."""
    starts = []
    for inst in instruments:
        md = data[inst]
        if holdout:
            starts.append(md.df_all.index[len(md.df_in)])
        elif md.windows:
            starts.append(md.df_in.index[md.windows[0].test.start])
    if not starts:
        raise BreadthError("no market has a walk-forward test window")
    return int(clock.get_indexer([min(starts)])[0])


def _reindex(arrays: Mapping[str, np.ndarray], index: pd.Index, clock: pd.DatetimeIndex) -> Dict[str, np.ndarray]:
    out: Dict[str, np.ndarray] = {}
    for k, v in arrays.items():
        s = pd.Series(np.asarray(v, dtype=float), index=index).reindex(clock).to_numpy(dtype=float)
        out[k] = (np.nan_to_num(s, nan=0.0) > 0.5) if k == "desired" else s
    return out


def build_book_inputs(layout: LakeLayout, data: Mapping[str, MarketData], merged: Mapping[str, Mapping[str, Any]], *, rules: Sequence[str] = RULES,
                      holdout: bool = False) -> Tuple[pd.DatetimeIndex, Dict[str, pd.DataFrame], List[SleeveInput], List[Dict[str, Any]]]:
    """The book's clock, the markets' frames on it, the sleeves (every S1-family rule in the book) and a note per sleeve."""
    clock = book_clock(data, holdout=holdout)
    markets = {m: (md.df_all if holdout else md.df_in).reindex(clock) for m, md in data.items()}
    sleeves: List[SleeveInput] = []
    notes: List[Dict[str, Any]] = []
    start = book_start(data, clock, [m for m in MARKETS if m in data], holdout=holdout)
    for inst in MARKETS:
        if inst not in data:
            continue
        md = data[inst]
        src = md.df_all if holdout else md.df_in
        for cand in RULES:
            if cand not in rules:
                continue
            r = result_of(merged, cand, inst, JUDGED_CELL)
            if r is None or not r.get("in_book"):
                if r is not None:
                    notes.append({"sleeve": f"{cand}/{inst.split('-')[0]}", "instrument": inst, "candidate": cand, "in_book": False,
                                  "reason": "funding covers less than the pre-registered share of in-sample bars (run without S5)"})
                continue
            arrays = _reindex(sleeve_arrays(layout, md, r, holdout=holdout), src.index, clock)
            name = f"{cand}/{inst.split('-')[0]}"
            sleeves.append(SleeveInput(name, inst, cand, arrays["desired"], arrays["stop"], arrays["fraction"], arrays["strength"], arrays["target"],
                                       arrays["time_stop"], arrays["trail_activate"], arrays["trail_r"]))
            first = int(np.argmax(arrays["desired"])) if arrays["desired"].any() else None
            windows_rules = [w.get("rule") for w in (r.get("windows") or [])]
            joins = md.df_all.index[len(md.df_in)] if holdout else (md.df_in.index[md.windows[0].test.start] if md.windows else None)
            notes.append({"sleeve": name, "instrument": inst, "candidate": cand, "in_book": True, "first_signal_bar": None if first is None else str(clock[first]),
                          "joins": None if joins is None else str(joins), "windows": len(windows_rules), "windows_with_rule": sum(1 for w in windows_rules if w),
                          "selected_params": r.get("selected_params"), "passed_own": bool((r.get("acceptance_r18") or {}).get("passed"))})
    return clock, markets, sleeves, notes, start


def hold_book_inputs(data: Mapping[str, MarketData], instrument: str, *, holdout: bool = False) -> Tuple[pd.DatetimeIndex, Dict[str, pd.DataFrame], List[SleeveInput], int]:
    clock = book_clock({instrument: data[instrument]}, holdout=holdout)
    md = data[instrument]
    src = md.df_all if holdout else md.df_in
    arrays = _reindex(hold_arrays(md, holdout=holdout), src.index, clock)
    sleeve = SleeveInput(f"hold/{instrument.split('-')[0]}", instrument, CONTROL, arrays["desired"], arrays["stop"], arrays["fraction"], None)
    return clock, {instrument: src.reindex(clock)}, [sleeve], book_start({instrument: md}, clock, [instrument], holdout=holdout)


# -- running the book and judging it -----------------------------------------------------------------------------------------------------

def book_costs(markets: Sequence[str], *, uniform: bool = False) -> Dict[str, Costs]:
    return {m: (MAJOR_COSTS if uniform else costs_for(m)) for m in markets}


def ablation_config(name: str) -> Tuple[BookConfig, bool]:
    """The book configuration of one ablation and whether it uses the uniform cost."""
    spec = ABLATIONS[name]
    brakes: Optional[BrakeSpec] = BOOK_CONFIG.brakes
    if "brakes" in spec:
        brakes = None if spec["brakes"] is None else (BrakeSpec(heat_cap=0.08) if spec["brakes"] == "heat8" else BOOK_CONFIG.brakes)
    corr_cap = spec["corr_cap"] if "corr_cap" in spec else BOOK_CONFIG.corr_cap
    cfg = BookConfig(brakes=brakes, corr_cap=corr_cap, corr_lookback_days=BOOK_CONFIG.corr_lookback_days, corr_min_days=BOOK_CONFIG.corr_min_days,
                     corr_threshold=BOOK_CONFIG.corr_threshold, rebalance_threshold=BOOK_CONFIG.rebalance_threshold, init_cash=BOOK_CONFIG.init_cash)
    return cfg, bool(spec.get("uniform_cost", False))


def judge_book(result: BookResult, ppy: float, *, tier_name: str = BOOK_TIER, slippage_rate: float = MAJOR_COSTS.slippage_rate) -> Dict[str, Any]:
    """Metrics, the yearly gate, the section 4.6 gates at the tier (robustness carried by the sleeves), the per-trade statistics."""
    oos = result.metrics(ppy)
    equity_index = result.equity / result.init_cash
    yg = yearly_gate_v2(equity_index)
    acc = acceptance_check_r18(oos, yg, {"share_above_threshold": 1.0}, tier_name)
    acc["note"] = "the +-30 % robustness gate is carried by the sleeves (the R5b construction); the profit factor and the trade count are the book's own, pooled over its trades"
    trades = result.trades
    stats = trade_stats(trades.assign(combo=trades["combo"].astype(int)) if len(trades) else trades, slippage_rate=slippage_rate) if len(trades) else trade_stats(trades, slippage_rate=slippage_rate)
    per_sleeve: Dict[str, Dict[str, Any]] = {}
    if len(trades):
        for name, g in trades.groupby("sleeve"):
            pnl = g["pnl"].to_numpy(dtype=float)
            wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
            per_sleeve[str(name)] = {"n_trades": int(len(g)), "pnl_pct_of_start": float(pnl.sum() / result.init_cash), "win_rate": float((pnl > 0).mean()),
                                     "profit_factor": float(wins.sum() / -losses.sum()) if losses.size and losses.sum() < 0 else None,
                                     "risk_pct_mean": _finite(np.nanmean(g["risk_pct"].to_numpy(dtype=float))) if g["risk_pct"].notna().any() else None,
                                     "funded_multiplier_mean": float(g["funded_multiplier"].astype(float).mean()), "cash_bound": int(g["cash_bound"].astype(bool).sum())}
    yearly = {int(k): float(v) for k, v in yearly_gate_v2(equity_index)["calendar_years"].items()}
    return {"oos": {k: _finite(v) if isinstance(v, (int, float, np.floating, np.integer)) else v for k, v in oos.items()}, "yearly_gate": yg, "yearly": yearly,
            "acceptance_r18": acc, "trades": stats, "per_sleeve": per_sleeve, "brakes": result.brakes, "days": len(result.daily),
            "first_bar": str(result.clock[0]), "last_bar": str(result.clock[-1]), "n_sleeves": len(result.sleeves)}


def brake_cost_line(base: Mapping[str, Any], other: Mapping[str, Any], *, flag: float = 0.1) -> Dict[str, Any]:
    """The book beside one ablation: what the switched layer cost or added, in Calmar, CAGR and drawdown (flagged above ``flag`` Calmar)."""
    a, b = _num(base.get("calmar")), _num(other.get("calmar"))
    return {"calmar_book": _finite(a), "calmar_ablation": _finite(b), "cost_calmar": _finite(b - a), "flagged": bool(math.isfinite(a) and math.isfinite(b) and (b - a) > flag),
            "cagr_book": _finite(base.get("cagr")), "cagr_ablation": _finite(other.get("cagr")), "max_dd_book": _finite(base.get("max_drawdown")),
            "max_dd_ablation": _finite(other.get("max_drawdown")), "n_trades_book": base.get("n_trades"), "n_trades_ablation": other.get("n_trades")}


def candidate_verdict(book_judged: Mapping[str, Any], sleeves: Sequence[Mapping[str, Any]], holdout_confirmed: Optional[bool]) -> Dict[str, Any]:
    """The R5b rule: a candidate only when the book passes AND (every sleeve passes on its own OR the holdout confirms)."""
    passed = bool((book_judged.get("acceptance_r18") or {}).get("passed"))
    in_book = [s for s in sleeves if s.get("in_book")]
    own = [s for s in in_book if s.get("passed_own")]
    all_own = bool(in_book) and len(own) == len(in_book)
    candidate = bool(passed and (all_own or holdout_confirmed is True))
    if not passed:
        reason = "fails the section 4.6 gates at the Trader tier: " + ", ".join((book_judged.get("acceptance_r18") or {}).get("failed") or [])
    elif all_own:
        reason = "passes the gates and every sleeve passes on its own"
    elif holdout_confirmed is True:
        reason = f"passes the gates; {len(own)} of {len(in_book)} sleeves pass on their own; the holdout confirms"
    elif holdout_confirmed is False:
        reason = f"passes the gates; {len(own)} of {len(in_book)} sleeves pass on their own; the holdout contradicts it"
    else:
        reason = f"passes the gates; {len(own)} of {len(in_book)} sleeves pass on their own; holdout not opened"
    return {"passed": passed, "sleeves_in_book": len(in_book), "sleeves_passing_own": len(own), "sleeves_passing_own_names": [s["configuration"] for s in own],
            "all_sleeves_pass_own": all_own, "holdout_confirmed": holdout_confirmed, "candidate": candidate, "reason": reason}


def diversification(book_judged: Mapping[str, Any], sleeves: Sequence[Mapping[str, Any]], hold_btc: Optional[Mapping[str, Any]], hold_book: Optional[Mapping[str, Any]],
                    ew_nine: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The diversification gain in Calmar beside the sleeves and the comparison lines (the pre-registered reading)."""
    o = book_judged.get("oos") or {}
    in_book = [s for s in sleeves if s.get("in_book") and s.get("trader")]
    calmars = [_num(s["trader"].get("calmar")) for s in in_book]
    vols = [_num(s["trader"].get("ann_vol")) for s in in_book]
    best = max(in_book, key=lambda s: _num(s["trader"].get("calmar"), -9.0)) if in_book else None
    book_calmar = _num(o.get("calmar"))
    return {"book_calmar": _finite(book_calmar), "book_cagr": _finite(o.get("cagr")), "book_max_drawdown": _finite(o.get("max_drawdown")), "book_ann_vol": _finite(o.get("ann_vol")),
            "sleeves_median_calmar": _median(calmars), "sleeves_mean_calmar": _finite(np.nanmean(calmars)) if calmars else None,
            "sleeves_median_ann_vol": _median(vols), "sleeves_passing_own": sum(1 for s in in_book if s.get("passed_own")), "n_sleeves": len(in_book),
            "best_sleeve": None if best is None else {"configuration": best["configuration"], "calmar": best["trader"].get("calmar"), "cagr": best["trader"].get("cagr"),
                                                     "max_drawdown": best["trader"].get("max_drawdown")},
            "gain_vs_sleeves_median": _finite(book_calmar - (_median(calmars) or float("nan"))),
            "gain_vs_best_sleeve": None if best is None else _finite(book_calmar - _num(best["trader"].get("calmar"))),
            "hold_btc_trader": None if hold_btc is None else {k: hold_btc.get(k) for k in ("calmar", "cagr", "max_drawdown", "ann_vol", "sharpe")},
            "gain_vs_hold_btc": None if hold_btc is None else _finite(book_calmar - _num(hold_btc.get("calmar"))),
            "hold_btc_book_sim": None if hold_book is None else {k: hold_book.get(k) for k in ("calmar", "cagr", "max_drawdown", "ann_vol", "sharpe")},
            "equal_weight_nine": None if ew_nine is None else {k: ew_nine.get(k) for k in ("calmar", "cagr", "max_drawdown", "ann_vol", "sharpe")},
            "gain_vs_equal_weight_nine": None if ew_nine is None else _finite(book_calmar - _num(ew_nine.get("calmar")))}


def market_correlations(data: Mapping[str, MarketData], *, end: Optional[pd.Timestamp] = None) -> Dict[str, Any]:
    """Pairwise correlations of the nine markets' daily returns over the pre-registered windows (in-sample bars only)."""
    closes = {}
    for m, md in data.items():
        c = md.df_in["close"]
        closes[m] = c.groupby(c.index.floor("D")).last()
    frame = pd.DataFrame(closes).sort_index()
    if end is not None:
        frame = frame[frame.index <= end]
    rets = frame.pct_change()
    out: Dict[str, Any] = {}
    for name, (start, stop) in CORRELATION_WINDOWS.items():
        sub = rets[rets.index >= pd.Timestamp(start, tz="UTC")]
        if stop:
            sub = sub[sub.index <= pd.Timestamp(stop, tz="UTC")]
        corr = sub.corr(min_periods=60)
        pairs = [float(corr.iloc[i, j]) for i in range(len(corr)) for j in range(i + 1, len(corr)) if math.isfinite(corr.iloc[i, j])]
        confirmed = [m for m in ("BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT") if m in corr.columns]
        cpairs = [float(corr.loc[a, b]) for i, a in enumerate(confirmed) for b in confirmed[i + 1:] if math.isfinite(corr.loc[a, b])]
        out[name] = {"start": str(sub.index[0].date()) if len(sub) else None, "end": str(sub.index[-1].date()) if len(sub) else None, "days": int(len(sub)),
                     "matrix": {a: {b: _finite(corr.loc[a, b]) for b in corr.columns} for a in corr.columns},
                     "median_pairwise": _median(pairs), "min_pairwise": min(pairs) if pairs else None, "max_pairwise": max(pairs) if pairs else None,
                     "confirmed_four_min": min(cpairs) if cpairs else None, "confirmed_four_max": max(cpairs) if cpairs else None,
                     "btc_vs_each": {b: _finite(corr.loc["BTC-USDT", b]) for b in corr.columns if b != "BTC-USDT"} if "BTC-USDT" in corr.columns else {}}
    return out


def sleeve_correlations(result: BookResult) -> Dict[str, Any]:
    contrib = sleeve_contributions(result)
    active = contrib.loc[:, (contrib != 0).any(axis=0)] if len(contrib) else contrib
    if active.shape[1] < 2:
        return {"n_sleeves": int(active.shape[1]), "median_pairwise": None}
    corr = active.corr()
    pairs = [float(corr.iloc[i, j]) for i in range(len(corr)) for j in range(i + 1, len(corr)) if math.isfinite(corr.iloc[i, j])]
    return {"n_sleeves": int(active.shape[1]), "median_pairwise": _median(pairs), "max_pairwise": max(pairs) if pairs else None, "min_pairwise": min(pairs) if pairs else None,
            "note": "closed-trade P&L booked on the exit day as a share of the book's equity; days without an exit are zero"}


def run_book_study(layout: LakeLayout, data: Mapping[str, MarketData], merged: Mapping[str, Mapping[str, Any]], *, rules: Sequence[str] = RULES,
                   evaluate_holdout: bool = False, log=print) -> Dict[str, Any]:
    """The book in its pre-registered configuration, its ablations, the comparison lines, the readings, the holdout rule."""
    ppy = bars_per_year(TIMEFRAME)
    clock, markets, sleeves, notes, start = build_book_inputs(layout, data, merged, rules=rules)
    if not sleeves:
        raise BreadthError("no sleeve qualifies for the book")
    insts = sorted({s.instrument for s in sleeves}, key=MARKETS.index)
    log(f"book: {len(sleeves)} sleeves on {len(insts)} markets, {len(clock) - start} bars {clock[start]:%Y-%m-%d} -> {clock[-1]:%Y-%m-%d} ({start} warm-up bars before)")
    main = run_book(clock, markets, sleeves, costs=book_costs(insts), cfg=BOOK_CONFIG, market_order=MARKETS, start=start)
    judged = judge_book(main, ppy)
    log(f"book: CAGR {judged['oos'].get('cagr')} maxDD {judged['oos'].get('max_drawdown')} Calmar {judged['oos'].get('calmar')} trades {judged['oos'].get('n_trades')} "
        f"pass4.6={judged['acceptance_r18']['passed']} failed={judged['acceptance_r18']['failed']} halted_from={judged['brakes'].get('halted_from')}")
    ablations: Dict[str, Any] = {}
    for name in ABLATIONS:
        cfg, uniform = ablation_config(name)
        res = run_book(clock, markets, sleeves, costs=book_costs(insts, uniform=uniform), cfg=cfg, market_order=MARKETS, start=start)
        j = judge_book(res, ppy)
        ablations[name] = {"label": ABLATIONS[name]["label"], "config": cfg.to_dict(), "uniform_cost": uniform, "oos": j["oos"], "acceptance_r18": j["acceptance_r18"],
                           "brakes": j["brakes"], "yearly": j["yearly"], "versus_book": brake_cost_line(judged["oos"], j["oos"])}
        log(f"  ablation {name}: Calmar {j['oos'].get('calmar')} CAGR {j['oos'].get('cagr')} maxDD {j['oos'].get('max_drawdown')} trades {j['oos'].get('n_trades')}")
    # Post-hoc diagnostics (NOT pre-registered; added after the first run showed the hard stop ending the book's entries for good): readings for the
    # owner, never candidates, never a holdout; the pre-registered verdict above does not use them.
    post_hoc: Dict[str, Any] = {}
    for name, (label, spec) in POST_HOC.items():
        cfg = BookConfig(brakes=spec, corr_cap=BOOK_CONFIG.corr_cap, corr_lookback_days=BOOK_CONFIG.corr_lookback_days, corr_min_days=BOOK_CONFIG.corr_min_days,
                         corr_threshold=BOOK_CONFIG.corr_threshold, rebalance_threshold=BOOK_CONFIG.rebalance_threshold, init_cash=BOOK_CONFIG.init_cash)
        res = run_book(clock, markets, sleeves, costs=book_costs(insts), cfg=cfg, market_order=MARKETS, start=start)
        j = judge_book(res, ppy)
        post_hoc[name] = {"label": label, "pre_registered": False, "config": cfg.to_dict(), "oos": j["oos"], "acceptance_r18": j["acceptance_r18"], "brakes": j["brakes"],
                          "yearly": j["yearly"], "versus_book": brake_cost_line(judged["oos"], j["oos"]), "per_sleeve": j["per_sleeve"], "trades_stats": j["trades"]}
        log(f"  post-hoc {name}: Calmar {j['oos'].get('calmar')} CAGR {j['oos'].get('cagr')} maxDD {j['oos'].get('max_drawdown')} trades {j['oos'].get('n_trades')}")
    # Comparison lines: the stored-and-reproduced Trader-cell hold control, the hold through the book simulator, buy-and-hold BTC over the span.
    hold_tr = result_of(merged, CONTROL, "BTC-USDT", JUDGED_CELL)
    hold_btc = None if hold_tr is None else _metrics_of(hold_tr)
    hold_book = None
    if "BTC-USDT" in data:
        hclock, hmarkets, hsleeves, hstart = hold_book_inputs(data, "BTC-USDT")
        hres = run_book(hclock, hmarkets, hsleeves, costs=book_costs(["BTC-USDT"]), cfg=BOOK_CONFIG, market_order=MARKETS, start=hstart)
        hold_book = judge_book(hres, ppy)["oos"]
    bh = None
    if "BTC-USDT" in data:
        sub = data["BTC-USDT"].df_in.loc[clock[start]:clock[-1]]
        if len(sub):
            eq = sub["close"].to_numpy(dtype=float) / float(sub["open"].iloc[0])
            from research.metrics import equity_metrics as _em
            bh = {k: _finite(v) for k, v in _em(np.concatenate([[1.0], eq]), ppy).items()}
    sleeves_tab = sleeve_table(merged)
    table_in_book = [s for s in sleeves_tab if s["in_book"]]
    verdict = candidate_verdict(judged, table_in_book, None)
    out: Dict[str, Any] = {
        "clock": {"first_bar": str(clock[start]), "last_bar": str(clock[-1]), "bars": int(len(clock) - start), "days": len(main.daily), "warmup_bars": int(start),
                  "warmup_from": str(clock[0])},
        "sleeves": notes, "n_sleeves": len(sleeves), "markets": insts, "config": BOOK_CONFIG.to_dict(), "costs": {m: {"fee_rate": book_costs(insts)[m].fee_rate, "slippage_rate": book_costs(insts)[m].slippage_rate} for m in insts},
        "judged": judged, "ablations": ablations, "post_hoc": post_hoc, "hold_btc_trader": hold_btc, "hold_btc_book_sim": hold_book, "btc_buy_and_hold_span": bh,
        "trades": _trades_records(main.trades), "daily": main.daily, "verdict": verdict,
        "sleeve_correlations": sleeve_correlations(main), "monthly_positions": _positions_profile(main),
        "holdout": {"evaluated": False, "reason": "the book did not pass the section 4.6 gates; the holdout stays untouched"} if not judged["acceptance_r18"]["passed"] else
                   {"evaluated": False, "reason": "not requested (run the full pre-registered study with --evaluate-holdout)"},
    }
    if judged["acceptance_r18"]["passed"] and evaluate_holdout:
        out["holdout"] = run_book_holdout(layout, data, merged, rules=rules, log=log)
        out["verdict"] = candidate_verdict(judged, table_in_book, out["holdout"].get("confirmed"))
    return out


def _trades_records(trades: pd.DataFrame) -> List[Dict[str, Any]]:
    if trades.empty:
        return []
    out: List[Dict[str, Any]] = []
    for row in trades.to_dict("records"):
        rec = {}
        for k, v in row.items():
            if isinstance(v, (pd.Timestamp, datetime)):
                rec[k] = v.isoformat()
            elif isinstance(v, (np.floating, float)):
                rec[k] = None if not math.isfinite(float(v)) else round(float(v), 8)
            elif isinstance(v, (np.integer,)):
                rec[k] = int(v)
            elif isinstance(v, (np.bool_,)):
                rec[k] = bool(v)
            else:
                rec[k] = v
        out.append(rec)
    return out


def _positions_profile(result: BookResult) -> Dict[str, Any]:
    pos = result.position.sum(axis=1)
    share = result.value_share.sum(axis=1)
    return {"bars_flat_share": float((pos == 0).mean()) if len(pos) else None, "positions_mean": float(pos.mean()) if len(pos) else None,
            "positions_max": int(pos.max()) if len(pos) else None, "invested_share_mean": float(share.mean()) if len(share) else None,
            "invested_share_max": float(share.max()) if len(share) else None,
            "positions_histogram": {str(int(k)): int(v) for k, v in pos.value_counts().sort_index().items()} if len(pos) else {}}


def run_book_holdout(layout: LakeLayout, data: Mapping[str, MarketData], merged: Mapping[str, Mapping[str, Any]], *, rules: Sequence[str] = RULES, log=print) -> Dict[str, Any]:
    """The book over the untouched months with each sleeve's most-often-selected rule, starting flat (the runner's own holdout construction)."""
    ppy = bars_per_year(TIMEFRAME)
    clock, markets, sleeves, notes, start = build_book_inputs(layout, data, merged, rules=rules, holdout=True)
    if not sleeves or len(clock) == 0 or start >= len(clock) - 1:
        return {"evaluated": False, "reason": "no holdout bars for the book"}
    insts = sorted({s.instrument for s in sleeves}, key=MARKETS.index)
    res = run_book(clock, markets, sleeves, costs=book_costs(insts), cfg=BOOK_CONFIG, market_order=MARKETS, start=start)
    j = judge_book(res, ppy)
    o = j["oos"]
    confirmed = bool(_num(o.get("total_return"), 0.0) > 0 and _num(o.get("profit_factor"), 0.0) > 1.0 and int(_num(o.get("n_trades"), 0)) >= HOLDOUT_MIN_TRADES)
    hold_tr = result_of(merged, CONTROL, "BTC-USDT", JUDGED_CELL)
    log(f"book holdout: return {o.get('total_return')} PF {o.get('profit_factor')} trades {o.get('n_trades')} confirmed={confirmed}")
    return {"evaluated": True, "first_bar": str(clock[start]), "last_bar": str(clock[-1]), "bars": int(len(clock) - start), "oos": o, "yearly": j["yearly"], "trades_stats": j["trades"],
            "brakes": j["brakes"], "per_sleeve": j["per_sleeve"], "confirmed": confirmed, "trades": _trades_records(res.trades),
            "hold_btc_trader_holdout": None if hold_tr is None else hold_tr.get("holdout"),
            "note": ("each sleeve runs its most-often-selected rule over the whole series so its indicators are warm, is live only on the holdout bars, "
                     "and the book starts flat; the correlations are warmed up on the history; the brakes start fresh")}


# -- the rotation test ------------------------------------------------------------------------------------------------------------------

def daily_frames(data: Mapping[str, MarketData], *, holdout: bool = False) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """One close (the day's last bar) and one open (the day's first bar) per UTC day and market, from the 6H bars."""
    closes: Dict[str, pd.Series] = {}
    opens: Dict[str, pd.Series] = {}
    for m, md in data.items():
        df = md.df_all if holdout else md.df_in
        days = df.index.floor("D")
        closes[m] = df["close"].groupby(days).last()
        opens[m] = df["open"].groupby(days).first()
    c = pd.DataFrame(closes).sort_index()
    o = pd.DataFrame(opens).sort_index().reindex(c.index)
    c.index.name = o.index.name = "day"
    return c, o


def rotation_span(closes: pd.DataFrame, *, start_floor: Optional[pd.Timestamp] = None) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """From the first Monday on which BTC's 200-day average, the lookback and the volatility window are available, to the last full day."""
    btc = closes["BTC-USDT"].dropna()
    needed = max(ROTATION_SMA_DAYS, ROTATION_LOOKBACK_DAYS + 1, ROTATION_VOL_LOOKBACK_DAYS + 1)
    if len(btc) <= needed:
        raise BreadthError("not enough BTC history for the rotation test")
    first_ok = btc.index[needed]
    if start_floor is not None:
        first_ok = max(first_ok, start_floor)
    days = closes.index[closes.index >= first_ok]
    mondays = [d for d in days if d.weekday() == 0]
    if not mondays:
        raise BreadthError("no Monday in the rotation span")
    return mondays[0], closes.index[-1]


def run_rotation_study(data: Mapping[str, MarketData], *, evaluate_holdout: bool = False, log=print) -> Dict[str, Any]:
    """The rotation, its benchmarks over the same days, the pass rule, the holdout only if it passes."""
    closes, opens = daily_frames(data)
    order = [m for m in MARKETS if m in closes.columns]
    closes, opens = closes[order], opens[order]
    start, end = rotation_span(closes)
    # The last in-sample day may be a part day (the split falls inside it); every line books the same days, so it is harmless to all alike.
    cfg = BasketConfig(vol_target=ROTATION_VOL_TARGET, vol_lookback_days=ROTATION_VOL_LOOKBACK_DAYS, costs_per_side=dict(ROTATION_COSTS_PER_SIDE))
    allowed = sma_filter(closes["BTC-USDT"], ROTATION_SMA_DAYS)
    runs = {
        "rotation": run_weekly_basket(closes, opens, top_n_selector(ROTATION_LOOKBACK_DAYS, ROTATION_TOP_N, order), cfg=cfg, start=start, end=end, allowed=allowed),
        "btc_vt20": run_weekly_basket(closes, opens, fixed_selector({"BTC-USDT": 1.0}), cfg=cfg, start=start, end=end),
        "equal_weight_nine_vt20": run_weekly_basket(closes, opens, fixed_selector({m: 1.0 for m in order}), cfg=cfg, start=start, end=end),
        "btc_buy_and_hold": run_weekly_basket(closes, opens, fixed_selector({"BTC-USDT": 1.0}), cfg=BasketConfig(vol_target=None, costs_per_side=dict(ROTATION_COSTS_PER_SIDE)),
                                              start=start, end=end),
        "equal_weight_nine_buy_and_hold": run_weekly_basket(closes, opens, fixed_selector({m: 1.0 for m in order}),
                                                            cfg=BasketConfig(vol_target=None, costs_per_side=dict(ROTATION_COSTS_PER_SIDE)), start=start, end=end),
        "rotation_no_filter": run_weekly_basket(closes, opens, top_n_selector(ROTATION_LOOKBACK_DAYS, ROTATION_TOP_N, order), cfg=cfg, start=start, end=end),
    }
    lines = {name: basket_metrics(r) for name, r in runs.items()}
    rot, btc = lines["rotation"], lines["btc_vt20"]
    passed = bool(_num(rot["calmar"]) > _num(btc["calmar"]) + BEATS_MARGIN_CALMAR and _num(rot["cagr"]) > _num(btc["cagr"])
                  and _num(rot["max_drawdown"]) <= TIER_GATES["higher"]["max_drawdown_max"])
    checks = {"calmar_beats_btc_by_margin": bool(_num(rot["calmar"]) > _num(btc["calmar"]) + BEATS_MARGIN_CALMAR), "cagr_above_btc": bool(_num(rot["cagr"]) > _num(btc["cagr"])),
              "max_drawdown_within_tier": bool(_num(rot["max_drawdown"]) <= TIER_GATES["higher"]["max_drawdown_max"]), "passed": passed}
    selections = [r["selected"] for r in runs["rotation"].records if r["rebalanced"] or r["selected"]]
    counts: Dict[str, int] = {}
    for sel in runs["rotation"].records:
        for m in (sel.get("selected") or {}):
            counts[m] = counts.get(m, 0) + 1
    whipsaws = _whipsaws(runs["rotation"].records)
    log(f"rotation: CAGR {rot['cagr']:.4f} maxDD {rot['max_drawdown']:.4f} Calmar {rot['calmar']:.3f} vs BTC vt20 CAGR {btc['cagr']:.4f} maxDD {btc['max_drawdown']:.4f} "
        f"Calmar {btc['calmar']:.3f} -> {'PASS' if passed else 'fail'}")
    out: Dict[str, Any] = {"span": {"start": str(start.date()), "end": str(end.date()), "days": int(len(runs['rotation'].equity))}, "config": cfg.to_dict(),
                           "lines": lines, "checks": checks, "passed": passed, "expected_to_fail": True, "selection_counts": counts, "n_rebalances": sum(1 for s in selections if s),
                           "whipsaws": whipsaws, "filter_days_off_share": rot.get("days_filtered_out_share"),
                           "yearly": {name: lines[name].get("yearly") for name in lines},
                           "equity": {name: _series(r.equity / r.init_cash) for name, r in runs.items()},
                           "holdout": {"evaluated": False, "reason": "the rotation did not beat BTC in sample; the holdout stays untouched"} if not passed else
                                      {"evaluated": False, "reason": "not requested (run the full pre-registered study with --evaluate-holdout)"}}
    if passed and evaluate_holdout:
        out["holdout"] = run_rotation_holdout(data, cfg, log=log)
    return out


def _whipsaws(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Filter exits followed by a re-entry within 30 days (the plan's whipsaw reading)."""
    exits = [i for i, r in enumerate(records) if r.get("filter_exit")]
    reentries = 0
    for i in exits:
        for j in range(i + 1, min(i + 31, len(records))):
            if records[j].get("rebalanced") and records[j].get("invested_share", 0) > 0:
                reentries += 1
                break
    return {"filter_exits": len(exits), "reentered_within_30_days": reentries}


def run_rotation_holdout(data: Mapping[str, MarketData], cfg: BasketConfig, *, log=print) -> Dict[str, Any]:
    closes, opens = daily_frames(data, holdout=True)
    order = [m for m in MARKETS if m in closes.columns]
    closes, opens = closes[order], opens[order]
    first_hold = min(md.df_all.index[len(md.df_in)] for md in data.values()).floor("D") + pd.Timedelta(days=1)
    days = closes.index[closes.index >= first_hold]
    mondays = [d for d in days if d.weekday() == 0]
    if not mondays:
        return {"evaluated": False, "reason": "no Monday in the holdout"}
    start, end = mondays[0], closes.index[-2] if len(closes) > 1 else closes.index[-1]
    allowed = sma_filter(closes["BTC-USDT"], ROTATION_SMA_DAYS)
    rot = run_weekly_basket(closes, opens, top_n_selector(ROTATION_LOOKBACK_DAYS, ROTATION_TOP_N, order), cfg=cfg, start=start, end=end, allowed=allowed)
    btc = run_weekly_basket(closes, opens, fixed_selector({"BTC-USDT": 1.0}), cfg=cfg, start=start, end=end)
    mr, mb = basket_metrics(rot), basket_metrics(btc)
    confirmed = bool(_num(mr["total_return"]) > 0 and _num(mr["total_return"]) > _num(mb["total_return"]))
    log(f"rotation holdout: {mr['total_return']:.4f} vs BTC vt20 {mb['total_return']:.4f} confirmed={confirmed}")
    return {"evaluated": True, "span": {"start": str(start.date()), "end": str(end.date()), "days": int(len(rot.equity))}, "rotation": mr, "btc_vt20": mb, "confirmed": confirmed}


def _series(equity: pd.Series) -> Dict[str, float]:
    return {str(d.date()): round(float(v), 8) for d, v in equity.items()}


# -- the ledger, the earlier looks and the recorded fleet rows ----------------------------------------------------------------------------

LEDGER_NOTE = ("Every opening of the untouched 12 months by the breadth study (plan row R20), in order; entries are appended, never edited. The report "
               "shows all of them, each beside the earlier looks at the same months by the stored studies. The hold + policy controls at the Trader cell "
               "are a comparison line, not a configuration under test.")


def holdout_openings(merged: Mapping[str, Mapping[str, Any]], series_info: Mapping[str, Mapping[str, Any]], book: Optional[Mapping[str, Any]],
                     rotation: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in merged.values():
        h = r.get("holdout")
        if not h:
            continue
        span = (series_info.get(r["instrument"]) or {}).get("holdout_span")
        out.append({"configuration": r["configuration"], "cell": r["cell"]["key"], "role": r.get("role"), "selected_params": r.get("selected_params"), "span": span,
                    "total_return": h.get("total_return"), "max_drawdown": h.get("max_drawdown"), "profit_factor": h.get("profit_factor"), "n_trades": h.get("n_trades"),
                    "confirmed": None if r["candidate"] == CONTROL else holdout_verdict(r)})
    if book and (book.get("holdout") or {}).get("evaluated"):
        h = book["holdout"]
        o = h.get("oos") or {}
        out.append({"configuration": f"breadth book ({book.get('n_sleeves')} sleeves, {len(book.get('markets') or [])} markets)", "cell": JUDGED_CELL.key, "role": "book",
                    "span": f"{h.get('first_bar', '')[:10]}->{h.get('last_bar', '')[:10]}", "total_return": o.get("total_return"), "max_drawdown": o.get("max_drawdown"),
                    "profit_factor": o.get("profit_factor"), "n_trades": o.get("n_trades"), "confirmed": h.get("confirmed")})
    if rotation and (rotation.get("holdout") or {}).get("evaluated"):
        h = rotation["holdout"]
        out.append({"configuration": "rotation top-3 / 3-week / BTC 200-day filter / vt20", "cell": "daily basket", "role": "rotation", "span": f"{h['span']['start']}->{h['span']['end']}",
                    "total_return": h["rotation"].get("total_return"), "max_drawdown": h["rotation"].get("max_drawdown"), "profit_factor": None, "n_trades": None,
                    "confirmed": h.get("confirmed")})
    out.sort(key=lambda x: (x["role"] not in ("sleeve", "book", "rotation"), x["configuration"], x["cell"]))
    return out


def earlier_looks(merged: Mapping[str, Mapping[str, Any]], stored: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    """For every sleeve whose holdout this run opened: the stored looks at the same months (the same sleeve at either cell, the hold control)."""
    out: List[Dict[str, Any]] = []
    pools = {"reference": list(stored.get("reference") or []), "trader": list(stored.get("trader") or [])}
    for r in merged.values():
        if not r.get("holdout") or r.get("role") != "sleeve":
            continue
        looks = []
        for cell_name, pool in pools.items():
            for s in pool:
                if s["candidate"] == r["candidate"] and s["instrument"] == r["instrument"] and s.get("holdout"):
                    h = s["holdout"]
                    looks.append({"study": s.get("study_source"), "cell": cell_name, "configuration": configuration_name(s["candidate"], s["instrument"]),
                                  "total_return": h.get("total_return"), "profit_factor": h.get("profit_factor"), "n_trades": h.get("n_trades"), "confirmed": holdout_verdict(s)})
            for s in pool:
                if s["candidate"] == CONTROL and s["instrument"] == r["instrument"] and s.get("holdout"):
                    h = s["holdout"]
                    looks.append({"study": s.get("study_source"), "cell": cell_name, "configuration": configuration_name(CONTROL, s["instrument"]),
                                  "total_return": h.get("total_return"), "profit_factor": h.get("profit_factor"), "n_trades": h.get("n_trades"), "confirmed": None})
        out.append({"configuration": r["configuration"], "cell": r["cell"]["key"], "earlier_opened": bool(looks), "earlier_looks": looks})
    out.sort(key=lambda x: (x["configuration"], x["cell"]))
    return out


def guard_second_look(ledger: Sequence[Mapping[str, Any]], openings: Sequence[Mapping[str, Any]], *, evaluate_holdout: bool) -> List[str]:
    if not evaluate_holdout:
        return []
    seen = {(o["configuration"], o.get("cell")) for e in ledger for o in e.get("openings", []) if o.get("role") in ("sleeve", "book", "rotation")}
    return sorted(f"{o['configuration']} @ {o['cell']}" for o in openings if o["role"] in ("sleeve", "book", "rotation") and (o["configuration"], o.get("cell")) in seen)


def write_breadth_ledger(path: str, entries: List[Dict[str, Any]]) -> None:
    Path(path).write_text(json.dumps({"note": LEDGER_NOTE, "entries": entries}, indent=1) + "\n", encoding="utf-8")


def fleet_rows(book: Optional[Mapping[str, Any]], rotation: Optional[Mapping[str, Any]], *, source: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The rows RECORDED for the paper fleet (never applied here: the fleet has no book or rotation account type; see the pre-registration)."""
    rows: List[Dict[str, Any]] = []
    if book and (book.get("verdict") or {}).get("candidate"):
        j = book["judged"]
        rows.append({"kind": "breadth_book", "label": f"breadth book: the S1 family on {len(book.get('markets') or [])} markets at the Trader tier, book-level brakes, correlation cap",
                     "instruments": list(book.get("markets") or []), "timeframe": TIMEFRAME, "regime_mode": MODE,
                     "sleeves": [{"sleeve": s["sleeve"], "instrument": s["instrument"], "candidate": s["candidate"], "selected_params": s.get("selected_params")} for s in book.get("sleeves", []) if s.get("in_book")],
                     "sizing": tier(BOOK_TIER).label, "sizing_config": tier(BOOK_TIER).sizing.to_dict(), "book_config": book.get("config"),
                     "cagr": j["oos"].get("cagr"), "sharpe": j["oos"].get("sharpe"), "calmar": j["oos"].get("calmar"), "max_drawdown": j["oos"].get("max_drawdown"),
                     "profit_factor": j["oos"].get("profit_factor"), "n_trades": j["oos"].get("n_trades"), "passed": bool(j["acceptance_r18"].get("passed")),
                     "failed_gates": list(j["acceptance_r18"].get("failed") or []), "holdout": (book.get("holdout") or {}).get("oos"), "holdout_confirmed": (book.get("holdout") or {}).get("confirmed"),
                     "source": dict(source, tier=BOOK_TIER, brakes=TRADER_BRAKES.to_dict(), variant="none", cell=JUDGED_CELL.key, protocol_variant="multi-market book (plan row R20)",
                                    role="candidate", account_kind="breadth_book"),
                     "note": "recorded only: the fleet needs a book account type before this row can be applied (the next plan row's work)"})
    if rotation and rotation.get("passed") and (rotation.get("holdout") or {}).get("confirmed"):
        rows.append({"kind": "rotation", "label": "rotation: top 3 of the nine by trailing 3-week return, weekly, BTC 200-day filter, 20 % volatility target",
                     "instruments": list(MARKETS), "config": rotation.get("config"), "lines": {k: {m: v.get(m) for m in ("cagr", "sharpe", "calmar", "max_drawdown")} for k, v in (rotation.get("lines") or {}).items()},
                     "passed": True, "holdout": rotation.get("holdout"),
                     "source": dict(source, tier="rotation vt20", brakes=None, variant="none", cell="daily basket", protocol_variant="weekly rotation (plan row R20)", role="candidate",
                                    account_kind="rotation"),
                     "note": "recorded only: the fleet needs a rotation account type before this row can be applied (the next plan row's work)"})
    return rows


def overall_summary(reproduction: Sequence[Mapping[str, Any]], sleeves: Sequence[Mapping[str, Any]], book: Optional[Mapping[str, Any]], rotation: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    in_book = [s for s in sleeves if s.get("in_book")]
    out: Dict[str, Any] = {
        "reproductions": len(reproduction), "reproductions_ok": sum(1 for c in reproduction if c.get("ok")),
        "n_sleeves_run": len(sleeves), "n_sleeves_in_book": len(in_book), "sleeves_passing_own": sum(1 for s in in_book if s.get("passed_own")),
        "sleeves_passing_own_names": [s["configuration"] for s in in_book if s.get("passed_own")],
        "sleeves_holdout_confirmed": [s["configuration"] for s in in_book if s.get("holdout_confirmed") is True],
        "sleeves_holdout_contradicted": [s["configuration"] for s in in_book if s.get("holdout_confirmed") is False],
    }
    if book:
        j = book["judged"]
        out.update({"book_passed": bool(j["acceptance_r18"].get("passed")), "book_failed_gates": list(j["acceptance_r18"].get("failed") or []),
                    "book_candidate": bool((book.get("verdict") or {}).get("candidate")), "book_reason": (book.get("verdict") or {}).get("reason"),
                    "book_calmar": j["oos"].get("calmar"), "book_cagr": j["oos"].get("cagr"), "book_max_drawdown": j["oos"].get("max_drawdown"),
                    "book_holdout": (book.get("holdout") or {}).get("confirmed"),
                    "brake_flags": [k for k, a in (book.get("ablations") or {}).items() if (a.get("versus_book") or {}).get("flagged")]})
    if rotation:
        out.update({"rotation_passed": bool(rotation.get("passed")), "rotation_checks": rotation.get("checks"), "rotation_holdout": (rotation.get("holdout") or {}).get("confirmed")})
    return out
