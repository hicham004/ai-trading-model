"""Research round 3: the asymmetric setups of the Trader Plan (plan row R19, ``docs/TRADER_PLAN_2026-11-05.md`` section 5), SIMULATION ONLY.

Three questions, each fixed here in :data:`PREREGISTRATION` before the first run (the
file ``docs/research/research_round_3_preregistration.json`` carries a hash the study
checks, and the hash goes into the results):

- **H7 — trend-pullback continuation (S7)** and **H8 — the slow breakout (S8)**, each
  with its pre-registered variants, written as FIXED rules (one parameter set each,
  :mod:`research.strategies.round3`) and judged under a pre-registered **fixed-rule
  protocol variant**: the 20-train-trade qualification that silenced the round-2 slow
  rules is skipped (``--min-trades 0``: every walk-forward window runs the rule's test
  slice, there is nothing to select) and the exit bracket is fixed (``--brackets none``,
  or ``trail3`` for the S7 trail variant); the walk-forward windows, costs, the S0
  filter, the regime gate and the +-30 % robustness replay are Sprint 2c's, unchanged.
  Sizing is the Trader Policy's Trader tier with its brakes (plan row R18, the fleet
  cell ``trader|brakes|none``) and the gates are the plan's section 4.6 gates at that
  tier; the Reference cell runs beside it for information. BTC-USDT and ETH-USDT are
  the primary markets; the seven replication markets of plan row R12 are the
  replication, exactly as that study fixed them.
- **The bar-size comparison**: the S1 and S2 families (S1, S2, S1+S5, S2+S5, Sprint 2c's
  grids, brackets and selection) on 1D, 6H and 4H bars of BTC-USDT and ETH-USDT at the
  Trader tier, at the 0.30 % gate cost and the measured 0.20 % replay, one table, no
  new parameters; never a hypothesis, never a holdout.

How the rules are run: exactly as the replication study (R12), rounds 1 and 2 and the
Trader Policy study (R18a) did, ``scripts/run_research_v1c.py`` is loaded as a module
and its own ``run_series`` runs every job with Sprint 2c's defaults for everything the
cell and the fixed-rule protocol do not define; every job's protocol check is recorded
and the study stops on any mismatch the job does not explain. Before anything is
judged, the same code path re-runs the stored configurations it shares with Sprint 2c,
the replication study and the Trader Policy study and must reproduce their numbers to
6 decimals.

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

from research.brakes import TRADER_BRAKES
from research.markets import SPRINT_2C_INSTRUMENTS
from research.replication import DATA_END, load_ledger, load_v1c_runner, markets_needed, protocol_check, reproduction_check  # noqa: F401
from research.report_v1c import GATES, _row, holdout_verdict
from research.round2 import R12_PREREGISTRATION, REPLICATION_MARKETS, Round2Error, binomial_tail, sign_threshold
from research.round2 import check_replication_markets as _check_r12_markets
from research.strategies import FIXED_RULES, ROUND3_BASES, VARIANT_OF, get_candidate
from research.strategies.round3 import (
    BREAKOUT_ENTRY_DAYS,
    BREAKOUT_EXIT_DAYS,
    BREAKOUT_STOP_ATR,
    GARNER_ENTRY_DAYS,
    GARNER_EXIT_DAYS,
    PULLBACK_EMA_DAYS,
    PULLBACK_SMA_DAYS,
    STOP_FLOOR_ATR,
    STOP_FLOOR_ATR_WIDE,
    TRAIL_BRACKET,
    TREND_FAST_DAYS,
    TREND_SLOW_DAYS,
)
from research.trader_policy import PAYOFF_MIN, TIER_GATES, tier
from research.trader_policy_study import Cell

ROOT = Path(__file__).resolve().parents[1]
V1C_RESULTS = ROOT / "docs" / "research" / "ensemble_v1c_results.json"
R12_RESULTS = ROOT / "docs" / "research" / "replication_v1d_results.json"
R18_RESULTS = ROOT / "docs" / "research" / "trader_policy_v1_results.json"
PREREGISTRATION_PATH = ROOT / "docs" / "research" / "research_round_3_preregistration.json"
STUDY_LAKE_DIRNAME = "lake_research_round_3"
STUDY_NAME = "R19 research round 3"
CONTROL = "hold"
PRIMARY_MARKETS: Tuple[str, ...] = SPRINT_2C_INSTRUMENTS
ALL_MARKETS: Tuple[str, ...] = PRIMARY_MARKETS + REPLICATION_MARKETS
FIXED_TIMEFRAMES: Tuple[str, ...] = ("1D", "6H")  # the plan's expectation names daily bars and 6H for the slow rules
BARSIZE_TIMEFRAMES: Tuple[str, ...] = ("1D", "6H", "4H")
STUDY_MODES: Tuple[str, ...] = ("none", "gate")
FIXED_CANDIDATES: Tuple[str, ...] = ("S7", "S7e", "S7w", "S7t", "S8", "S8g")
BARSIZE_CANDIDATES: Tuple[str, ...] = ("S1", "S2", "S1+S5", "S2+S5")
FLEET_TIMEFRAMES: Tuple[str, ...] = ("4H", "6H")  # research/paper_fleet/config.py TIMEFRAMES: a 1D passer is recorded, never applied
TURNOVER_CEILING = 40.0  # plan section 4.2: a new rule that trades more than 40 times a year fails on costs before it is judged (a fleet condition here)
REFERENCE_CELL = Cell("reference", False)
JUDGED_CELL = Cell("trader", True)  # the Trader tier with the section 4.3 brakes: the paper fleet's cell (plan row R18)
CELLS: Tuple[Cell, ...] = (REFERENCE_CELL, JUDGED_CELL)
FIXED_RULE_PROTOCOL = "fixed rule: the exit bracket fixed, never selected; no train-trade qualification (min_trades 0)"
COST_SCENARIOS: Mapping[str, Tuple[float, float]] = {"measured_btc_eth": (0.0005, 0.0005), "altcoin": (0.0010, 0.0015)}
SIGN_TEST_ALPHA = 0.05
#: The plan's expected trade counts per year (section 5) on daily bars, reported beside the measured ones, never gated.
EXPECTED_TRADES_PER_YEAR: Mapping[str, Tuple[float, float]] = {"H7": (10.0, 25.0), "H8": (3.0, 6.0)}
#: Entries per year of each rule on the in-sample BTC-USDT / ETH-USDT candles (counts only, no returns), taken before the pre-registration
#: so that the expectations above could be judged honestly: S7 fires about 7-10 times a year on daily bars and 23-30 on 6H (the plan guessed
#: fewer on 6H); S8 about 2-3 a year, S8g 1-2 - under the 30-trade gate over the out-of-sample years by construction.
TRADE_COUNT_CHECK: Mapping[str, Mapping[str, float]] = {
    "BTC-USDT 1D": {"S7": 7.4, "S7e": 7.2, "S7w": 7.4, "S8": 2.2, "S8g": 1.5}, "BTC-USDT 6H": {"S7": 23.9, "S7e": 22.6, "S7w": 23.9, "S8": 2.4, "S8g": 1.7},
    "ETH-USDT 1D": {"S7": 10.5, "S7e": 10.3, "S7w": 10.5, "S8": 2.6, "S8g": 1.0}, "ETH-USDT 6H": {"S7": 30.1, "S7e": 26.3, "S7w": 30.1, "S8": 2.6, "S8g": 1.0},
}
JOB_KINDS: Tuple[str, ...] = ("control", "fixed", "fixed_trail", "barsize")
FIXED_KINDS: Tuple[str, ...] = ("fixed", "fixed_trail")


class Round3Error(RuntimeError):
    """The study cannot be trusted (protocol mismatch, reproduction failure, a tampered pre-registration, a changed market list)."""


def check_replication_markets(path: Path = R12_PREREGISTRATION) -> List[str]:
    """The replication study's fixed market list must be the one this round uses (the R12 file is the authority), as round 2 checked it."""
    try:
        return _check_r12_markets(path)
    except Round2Error as exc:
        raise Round3Error(str(exc)) from exc


@dataclass(frozen=True)
class Hypothesis:
    key: str
    title: str
    candidates: Tuple[str, ...]
    base: str  # the family's base rule (the variants are compared with it)

    @property
    def variants(self) -> Tuple[str, ...]:
        return tuple(c for c in self.candidates if c != self.base)


HYPOTHESES: Tuple[Hypothesis, ...] = (
    Hypothesis("H7", "trend-pullback continuation (S7)", ("S7", "S7e", "S7w", "S7t"), "S7"),
    Hypothesis("H8", "the slow breakout with wide stops (S8)", ("S8", "S8g"), "S8"),
)
HYPOTHESIS_BY_KEY: Dict[str, Hypothesis] = {h.key: h for h in HYPOTHESES}
HYPOTHESIS_OF_CANDIDATE: Dict[str, str] = {c: h.key for h in HYPOTHESES for c in h.candidates}
PARKED: Mapping[str, str] = {
    "opening-range breakout": "slippage kills it (two independent replications lose the edge at two cents a share or spread plus slippage) and it needs a wide stock universe (plan section 2.6)",
    "VCP (Minervini)": "no quantitative evidence; championship returns are top-of-distribution outcomes; a mechanical definition, if ever, is a later fleet test (plan section 2.6)",
    "naive dip buying": "anti-trend: more than 60 % of 196 buy-the-dip variants had a lower Sharpe than holding over 60 years (AQR 2025), and continuation beats reversal in BTC at every horizon (plan section 2.6)",
    "intraday rules": "no profitable intraday trend following in the BTC literature, and the fee budget (plan sections 2.6 and 2.9)",
}

PREREGISTRATION: Dict[str, Any] = {
    "fixed_on": "2026-11-05, before any run (plan row R19)",
    "question": ("Do the two asymmetric setups of the Trader Plan, section 5 - the trend-pullback continuation rule S7 and the slow breakout S8, each "
                 "with its pre-registered variants, written as fixed rules and judged under the fixed-rule protocol variant at the Trader tier with "
                 "the section 4.3 brakes - pass the section 4.6 gates on the Sprint 2c walk-forward of BTC-USDT and ETH-USDT, replicate on the seven "
                 "R12 markets, and survive the untouched 12 months; and is 6H the cost-adjusted sweet spot for the S1 and S2 families among 1D, 6H "
                 "and 4H bars?"),
    "why": ("Plan section 2.6: dip buying has no stand-alone edge, and the only version the evidence supports is a pullback inside an uptrend entered "
            "when price turns back up with the stop under the dip (S7); the Donchian/Turtle family is the best-documented asymmetric design and the "
            "fewer-trades, wider-stop direction is the one that kept working in futures after 1990 and fits the fee budget (S8). Round 2 (R16) "
            "could not judge its slow rules because the protocol's selection step silences any window in which a variant traded fewer than 20 "
            "times in training (TF traded in 13 of 180 windows, S2+TF in 53); the owner's decision (docs/PLAN_STATUS.md, 'From R16', taken "
            "2026-11-05) answers it both ways - a forward control account (R18) and this pre-registered fixed-rule protocol variant. The bar-size "
            "question: one unreviewed 2026 preprint finds 6H bars the cost-adjusted sweet spot for crypto trend rules while our own record is "
            "mixed (the S1 family and the R12 confirmations favoured 6H, the S2 family and the volume-confirmation sleeves sit on 4H)."),
    "hypotheses": {
        "H7": {"title": "trend-pullback continuation (S7)",
               "rule": (f"S7: uptrend = the close above its {TREND_SLOW_DAYS}-day simple moving average and the {TREND_FAST_DAYS}-day average above the "
                        f"{TREND_SLOW_DAYS}-day; pullback = a close below the {PULLBACK_SMA_DAYS}-day simple moving average while the uptrend holds (it arms "
                        "the rule and starts the pullback low; every later bar's low lowers it, the entry bar's included); entry = a close above the "
                        "previous bar's high while the uptrend holds (armed on an earlier bar); stop = under the pullback low, floored at "
                        f"{STOP_FLOOR_ATR:g} x ATR(14) (the stop distance at the decision close is max(close - pullback low, {STOP_FLOOR_ATR:g} x ATR), "
                        f"fixed at entry as every rule's stop is); exit = a close below the {TREND_FAST_DAYS}-day average, or the stop; the uptrend "
                        "failing while armed disarms; an exit bar may arm a new pullback at once. No other parameters. Every lookback is in calendar "
                        "days converted to bars of the timeframe."),
               "variants": {"S7e": f"the pullback average is the {PULLBACK_EMA_DAYS}-day exponential average instead of the {PULLBACK_SMA_DAYS}-day simple one",
                            "S7w": f"the stop floor is {STOP_FLOOR_ATR_WIDE:g} x ATR(14) instead of {STOP_FLOOR_ATR:g} x",
                            "S7t": (f"the same rule under the protocol's {TRAIL_BRACKET} exit bracket (a trailing stop that activates once the running high is "
                                    "+1 R above the entry and then follows it at 3 R), applied through the bracket parameter by the runner and the fleet "
                                    "alike; its exit is the trailing stop, the fast-average cross or the initial stop, whichever comes first")},
               "candidates": ["S7", "S7e", "S7w", "S7t"], "markets": list(ALL_MARKETS), "primary_markets": list(PRIMARY_MARKETS),
               "replication_markets": list(REPLICATION_MARKETS), "timeframes": list(FIXED_TIMEFRAMES), "regime_modes": list(STUDY_MODES),
               "comparison": ("hold + policy sizing on the same market, timeframe and cell (the always-long control at the Trader tier with the brakes, "
                              "run in this study; its one mode is 'none', so the [gate] configurations compare with the same control); each variant "
                              "also beside the base S7 on the same series, mode and cell"),
               "expected_trades_per_year": list(EXPECTED_TRADES_PER_YEAR["H7"]),
               "why": "the only version of dip buying the evidence supports: a dip inside an uptrend, entered when price turns back up, stop under the dip"},
        "H8": {"title": "the slow breakout with wide stops (S8)",
               "rule": (f"S8: a slow Turtle System 2 breakout - entry on a close above the prior {BREAKOUT_ENTRY_DAYS}-day high (the channel excludes the "
                        f"current bar), exit on a close below the prior {BREAKOUT_EXIT_DAYS}-day low, Garner's {BREAKOUT_STOP_ATR:g} x ATR(14) stop fixed at "
                        "entry, no adds, no volume or volatility filter (unlike S2). No other parameters."),
               "variants": {"S8g": f"Garner's own channels: {GARNER_ENTRY_DAYS}-day high entry, {GARNER_EXIT_DAYS}-day low exit"},
               "candidates": ["S8", "S8g"], "markets": list(ALL_MARKETS), "primary_markets": list(PRIMARY_MARKETS),
               "replication_markets": list(REPLICATION_MARKETS), "timeframes": list(FIXED_TIMEFRAMES), "regime_modes": list(STUDY_MODES),
               "comparison": "as H7: hold + policy sizing on the same market, timeframe and cell; the variant beside the base S8",
               "expected_trades_per_year": list(EXPECTED_TRADES_PER_YEAR["H8"]),
               "trade_count_caveat": ("stated before the run: at 2-3 entries a year (the trade-count check below) S8 cannot reach the gate of 30 trades "
                                      "over the out-of-sample years on one market, so the 'at least 30 trades' gate will bind on every S8 configuration; "
                                      "the gate stays as the plan fixed it and the report says where it binds; the pooled reading across the nine "
                                      "markets (pooled trades, pooled profit factor, pooled average win / average loss, median Calmar beside hold + "
                                      "policy) is reported as information, never as a verdict and never as a fleet ticket"),
               "why": "the fewer-trades, wider-stop direction kept working in futures after 1990 and fits the fee budget; it could not be judged by the round-2 protocol"},
    },
    "protocol": ("Sprint 2c's own runner (scripts/run_research_v1c.py loaded as a module, its run_series) with Sprint 2c's defaults for everything the "
                 "cell and the fixed-rule protocol do not define - the S0 filter with the FOMC calendar, the regime-v2 entry gate (3-state HMM, bear >= "
                 "0.5, fitted on every window's train slice; modes none and gate), the walk-forward (train 540 d, purge 7 d, test 180 d), the "
                 "0.25 reduce-only rebalance, the +-30 % robustness replay of every grid parameter (the four S7 numbers, the three S8 numbers; the ATR "
                 "window is a default, as for S1/S2) and the trade-order bootstrap. The FIXED-RULE PROTOCOL VARIANT for S7/S8 and their variants: "
                 "every parameter is one pre-registered value (one combination), the exit bracket is fixed ('none': the rule's own exit and stop; "
                 f"'{TRAIL_BRACKET}' for S7t) and never selected, and the 20-train-trade qualification is skipped (min_trades 0: every walk-forward "
                 "window runs the rule's test slice - there is nothing to select, so no window is silenced). The runner's defaults are checked against "
                 "the stored Sprint 2c run before the study runs; every job's protocol check is recorded with its results and the study stops on any "
                 "mismatch the job does not explain (a tier is a recorded policy_sizing mismatch, the fixed-rule protocol recorded brackets / "
                 "min_trades mismatches, 1D bars a recorded timeframes mismatch, never hidden)."),
    "tier": ("the Trader Policy v1 Trader tier (plan row R18, section 4.1): a 20 % volatility target over 30 bars, half size in a crash state, at most "
             "2 % of equity at risk on one stop (the cap reads the rule's own stop distance at the decision close), the entries-only Turtle ladder, "
             "with the section 4.3 brakes on (the hard stop, the entry caps, the loss limits, the heat cap) - the paper fleet's cell "
             f"'{JUDGED_CELL.key}'. The Reference cell (today's vt10/30 crash15/90dh ladder, no brakes) runs beside it for information and for the "
             "reproduction of the stored numbers; it never opens a holdout for a new rule. CAVEAT, stated before the run: the tier's volatility "
             "window is 30 BARS (Sprint 2b's definition), i.e. 30 days on 1D bars and 5 days on 4H bars, so the bar-size comparison also compares "
             "volatility estimators; the crash window (90 days) and the ladder re-arm (30 days) are in days."),
    "brakes": TRADER_BRAKES.label,
    "markets": ("BTC-USDT and ETH-USDT first (the primary markets: the hypotheses are labelled on them), then the seven replication markets exactly as "
                "the R12 pre-registration fixed them (checked against that file): XRP, DOGE, LINK, TRX, ADA, LTC, SOL; a configuration that passes on "
                "a replication market opens its holdout there once and, if confirmed, joins the fleet as R12's did; the R12 reading applies to every "
                "configuration that passes on BTC-USDT or ETH-USDT: it 'replicates' when it passes on at least 4 of the 7 markets"),
    "timeframes": ("1D and 6H bars for S7 and S8 (the plan's expectation names daily bars and 6H for the slow rules); 1D bars are resampled from "
                   "the stored 1H candles at UTC midnight, exactly as 6H bars are resampled (OKX's own daily bars are UTC+8-aligned and are not "
                   "used); the S0 filter's one-day volatility leg is inert on 1D bars (a one-bar window), a protocol fact, not a change"),
    "bar_size": ("the S1 and S2 families - S1, S2, S1+S5, S2+S5 with Sprint 2c's grids, brackets (none/tp2/trail1/time30; none for the S5 families) "
                 "and selection (the 20-train-trade qualification applies: these are swept rules) - on 1D, 6H and 4H bars of BTC-USDT and ETH-USDT, "
                 "modes none and gate, at the Reference cell and at the Trader cell, at the gate cost (0.30 % a round trip) and the measured BTC/ETH "
                 "cost (0.20 %, the selected rule replayed with the same windows, gate and sizing), one table; the pre-registered reading: '6H is the "
                 "cost-adjusted sweet spot' holds when 6H has the highest Calmar of the three bar sizes in at least half of the (rule, market, mode) "
                 "comparisons at the Trader cell both at 0.30 % and at 0.20 %; the table also shows the Sharpe, the trades a year and the fees a year. "
                 "Never a hypothesis: no holdout is opened for it and nothing from it joins the fleet; a 1D configuration that passes the gates is "
                 "reported as 'passes walk-forward, holdout not opened' and is a candidate for a future pre-registered row"),
    "data": (f"OKX public 1H and 4H spot candles of the nine markets (4H stored; 6H and 1D resampled from 1H), frozen in a study lake at Sprint 2c's "
             f"data end (bar close <= {DATA_END}) so the walk-forward and the untouched 12 months (2025-10-20 -> 2026-10-20) are the same calendar "
             "window as in Sprint 2c, R12, R13, R16 and R18; Binance public funding and open interest for the S5 families and the S0 machinery as before"),
    "reproduction": ("before anything is judged, the same code path re-runs, at the Reference cell, hold / S1 / S2 / S1+S5 / S2+S5 on BTC-USDT and "
                     "ETH-USDT 4H and 6H (Sprint 2c's stored numbers) and hold on the seven replication markets at 6H (the replication study's), and, "
                     "at the Trader cell, S1+S5 BTC-USDT 6H [none] and the hold controls the Trader Policy study stored at that cell; each must give the "
                     "stored walk-forward numbers to 6 decimals, the same trade counts, the same most-selected rules and the same gate verdicts, "
                     "otherwise the study stops"),
    "gates": (f"the plan's section 4.6 gates at the Trader tier: PF > {GATES['profit_factor_min']}, Sharpe > {GATES['sharpe_min']}, Calmar > "
              f"{GATES['calmar_min']}, >= {GATES['rolling_12m_positive_min'] * 100:.0f} % of rolling 12-month windows positive, >= {GATES['min_trades']} trades "
              f"over the out-of-sample period, >= {GATES['robust_share_min'] * 100:.0f} % of +-30 % neighbours profitable, max drawdown <= "
              f"{TIER_GATES['higher']['max_drawdown_max'] * 100:.0f} %, worst calendar year >= {TIER_GATES['higher']['worst_calendar_year_min'] * 100:.0f} %, average win / "
              f"average loss >= {PAYOFF_MIN:g}; expectancy in R reported, not gated; at the Reference cell the Sprint 2c thresholds (20 % / -10 %) apply, "
              "for information"),
    "turnover": (f"plan section 4.2: a new rule or variant that trades more than {TURNOVER_CEILING:.0f} times a year fails on costs before it is judged; "
                 "here a fleet condition, not a gate on the verdict (the runner's holdout rule does not know it): a passer above the ceiling is flagged, "
                 "cannot join the fleet, and its holdout, if the runner opened it, stays in the ledger"),
    "verdicts": ("a configuration passes when it passes every section 4.6 gate at the Trader cell; a hypothesis is labelled on the primary markets - "
                 "'confirmed' when at least one of its configurations passes there and is confirmed by its holdout, 'passed walk-forward, contradicted "
                 "by the holdout' when some pass and none is confirmed, 'failed walk-forward' when none passes - and the replication markets get the "
                 "same label of their own; a confirmed passer anywhere joins the fleet (the R12 rule); the readings beside the label, never replacing "
                 "it: (a) the directional reading against hold + policy on the same cell (Calmar higher in at least k of n judged configurations, k "
                 f"at the one-sided binomial {SIGN_TEST_ALPHA:g} tail; indicative, the configurations share markets), on the primary and the "
                 "replication markets separately; (b) per variant, the same sign test against its base rule over every series, mode and cell; (c) the "
                 "R12 replication reading for every configuration that passed on a primary market; (d) trades a year beside the plan's expectation; "
                 "(e) H8's pooled reading; (f) the Trader cell beside the Reference cell (exposure ratio, risk per trade, cap binding, gaps, "
                 "re-entries); every hypothesis that does not end 'confirmed' gets a failure analysis computed from the numbers beside its comparison line"),
    "holdout": ("the last 12 months (2025-10-20 -> 2026-10-20), opened once, only for a configuration that passes every section 4.6 gate at the Trader "
                "cell, only by the full pre-registered study (every hypothesis, market, timeframe, mode and cell, the bar-size comparison, with the "
                "reproduction, never --quick); the v1c verdict (positive return, PF > 1, >= 10 trades); the hold + policy control's 12 months at the "
                "Trader cell on every series are the comparison line (never judged, as in every study); every opening goes into an append-only ledger "
                "the report shows, each beside the earlier look at the same months by the stored hold control of that market (6H when the opening is "
                "at 1D, where no stored look at that bar size exists). CAVEAT, stated before the run: the holdout's falling direction is known for "
                "every market (hold + policy lost on all nine over those months), and both rules sit out downtrends by construction; a confirmation is "
                "necessary, not sufficient, and the paper fleet's forward record is the judge"),
    "fleet": ("a confirmed passer at the Trader cell with at most 40 trades a year on a 4H or 6H series joins the paper fleet's shortlist as a NEW "
              "account with a source tag naming this study, the tier ('trader'), the brakes, 'no variant', the cell and the fixed-rule protocol "
              "variant, through the fleet loader's tier-tagged path (plan row R18b) extended to accept the fixed-rule protocol for registered fixed "
              "rules; the fleet must still load the amended shortlist, otherwise the file is restored and the report says so (the R12 rule); a 1D "
              "passer is RECORDED, not applied (the fleet runs 4H and 6H bars), as a decision for the owner; existing accounts are untouched; nothing "
              "joins demo or live"),
    "parked": dict(PARKED),
    "trade_count_check": dict(TRADE_COUNT_CHECK),
    "no_changes_after_results": "no gate, parameter, rule, market, threshold, cell or verdict rule changes after the results are in; if a gate looks wrong the report says so",
}


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# -- configuration -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Round3Config:
    hypotheses: Tuple[str, ...] = tuple(h.key for h in HYPOTHESES)
    markets: Tuple[str, ...] = ALL_MARKETS
    timeframes: Tuple[str, ...] = FIXED_TIMEFRAMES
    regime_modes: Tuple[str, ...] = STUDY_MODES
    cells: Tuple[str, ...] = tuple(c.key for c in CELLS)
    barsize: bool = True
    reproduction: bool = True
    data_end: str = DATA_END
    quick: bool = False
    lake_dir: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        for k in ("hypotheses", "markets", "timeframes", "regime_modes", "cells"):
            out[k] = list(getattr(self, k))
        return out

    @property
    def candidates(self) -> List[str]:
        return [c for h in HYPOTHESES if h.key in self.hypotheses for c in h.candidates]

    @property
    def cell_objects(self) -> List[Cell]:
        return [c for c in CELLS if c.key in self.cells]

    @property
    def all_markets(self) -> List[str]:
        """Every market a job runs on (the bar-size comparison adds the primary markets even when the hypotheses run elsewhere)."""
        out = list(self.markets)
        if self.barsize:
            out += [m for m in PRIMARY_MARKETS if m not in out]
        return [m for m in ALL_MARKETS if m in out]


def preregistration_hash(cfg: Round3Config, prereg: Mapping[str, Any]) -> str:
    return _sha256_json({"preregistration": PREREGISTRATION, "file": prereg, "config": cfg.to_dict()})


def full_study_requested(cfg: Round3Config) -> bool:
    """The holdout may only be opened by the complete pre-registered study."""
    return (not cfg.quick and cfg.reproduction and cfg.barsize and sorted(cfg.hypotheses) == sorted(h.key for h in HYPOTHESES)
            and sorted(cfg.markets) == sorted(ALL_MARKETS) and sorted(cfg.timeframes) == sorted(FIXED_TIMEFRAMES)
            and sorted(cfg.regime_modes) == sorted(STUDY_MODES) and sorted(cfg.cells) == sorted(c.key for c in CELLS))


# -- the pre-registration file ---------------------------------------------------------------------------------

def preregister(path: Path, *, now: Optional[datetime] = None, force: bool = False, r12_path: Path = R12_PREREGISTRATION) -> Dict[str, Any]:
    """Write the fixed text (and the full-study configuration) with a hash; refuse a second write unless forced."""
    path = Path(path)
    if path.exists() and not force:
        raise Round3Error(f"{path} exists: the hypotheses were already fixed; a second write would be a second registration")
    check_replication_markets(r12_path)
    written_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    payload: Dict[str, Any] = {
        "note": "Plan row R19. The hypotheses, rules, variants, protocol variant, tier, markets, timeframes, gates, readings and verdict rules of research round 3, fixed BEFORE the first run. Never edited.",
        "written_at": written_at, "data_end": DATA_END, "gates": dict(GATES), "tier_gates": {k: dict(v) for k, v in TIER_GATES.items()}, "payoff_min": PAYOFF_MIN,
        "turnover_ceiling": TURNOVER_CEILING, "primary_markets": list(PRIMARY_MARKETS), "replication_markets": list(REPLICATION_MARKETS),
        "cells": [c.to_dict() for c in CELLS], "judged_cell": JUDGED_CELL.to_dict(), "tier": tier(JUDGED_CELL.tier).to_dict(), "brakes_on": TRADER_BRAKES.to_dict(),
        "fixed_rule_protocol": FIXED_RULE_PROTOCOL, "candidates": {c: {"label": get_candidate(c).label, "params": _canon(get_candidate(c).default_params),
                                                                        "grid": _canon(get_candidate(c).grid), "bracket": getattr(get_candidate(c), "fixed_bracket", "none")}
                                                                    for c in FIXED_CANDIDATES},
        "cost_scenarios": {k: list(v) for k, v in COST_SCENARIOS.items()}, "configuration": Round3Config().to_dict(), "preregistration": PREREGISTRATION,
    }
    payload["sha256"] = _sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return payload


def load_preregistration(path: Path = PREREGISTRATION_PATH) -> Dict[str, Any]:
    """The pre-registration file, checked: its hash, and that its text, gates, candidates and cells are those in this module."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("preregistration"), dict):
        raise Round3Error(f"{path} is not a pre-registration file")
    expected = _sha256_json({k: v for k, v in data.items() if k != "sha256"})
    if data.get("sha256") != expected:
        raise Round3Error(f"{path} was edited after it was written (hash mismatch)")
    if data["preregistration"] != PREREGISTRATION:
        raise Round3Error("the pre-registration text in research/round3.py differs from the registered file; neither may change after registration")
    if data.get("gates") != dict(GATES) or data.get("tier_gates") != {k: dict(v) for k, v in TIER_GATES.items()} or data.get("payoff_min") != PAYOFF_MIN:
        raise Round3Error("the gates differ from the registered ones")
    if list(data.get("primary_markets") or []) != list(PRIMARY_MARKETS) or list(data.get("replication_markets") or []) != list(REPLICATION_MARKETS):
        raise Round3Error("the markets differ from the registered ones")
    for c in FIXED_CANDIDATES:
        reg = (data.get("candidates") or {}).get(c) or {}
        cand = get_candidate(c)
        if reg.get("params") != _canon(cand.default_params) or reg.get("grid") != _canon(cand.grid) or reg.get("bracket") != getattr(cand, "fixed_bracket", "none"):
            raise Round3Error(f"the rule {c} differs from the registered one")
    if data.get("judged_cell") != JUDGED_CELL.to_dict() or data.get("brakes_on") != TRADER_BRAKES.to_dict() or data.get("fixed_rule_protocol") != FIXED_RULE_PROTOCOL:
        raise Round3Error("the cell, the brakes or the protocol variant differ from the registered ones")
    return data


def _canon(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return value


# -- the Sprint 2c runner and the jobs' arguments ---------------------------------------------------------------

def runner():
    return load_v1c_runner()


def job_argv(cell: Cell, kind: str, strategies: Sequence[str], timeframe: str, *, modes: Sequence[str], evaluate_holdout: bool,
             lake_dir: Optional[str], quick: bool) -> List[str]:
    """Sprint 2c's command line for one job: the cell's sizing and brakes, the fixed-rule protocol where the kind needs it, the cost replays."""
    if kind not in JOB_KINDS:
        raise ValueError(f"unknown job kind {kind!r}")
    t = tier(cell.tier)
    s = t.sizing
    argv: List[str] = ["--strategies", *strategies, "--regime-modes", *modes, "--timeframes", timeframe, "--tier", cell.tier]
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
    if kind in FIXED_KINDS:
        argv += ["--brackets", TRAIL_BRACKET if kind == "fixed_trail" else "none", "--min-trades", "0"]
    if evaluate_holdout:
        argv.append("--evaluate-holdout")
    if quick:
        argv.append("--quick")
    if lake_dir:
        argv += ["--lake-dir", lake_dir]
    return argv


def job_args(job: Mapping[str, Any]) -> Dict[str, Any]:
    cfg = config_from_dict(job["cfg"])
    cell = Cell(job["cell"]["tier"], bool(job["cell"]["brakes"]), job["cell"].get("variant", "none"))
    argv = job_argv(cell, job["kind"], job["strategies"], job["timeframe"], modes=cfg.regime_modes, evaluate_holdout=bool(job["evaluate_holdout"]),
                    lake_dir=cfg.lake_dir, quick=cfg.quick)
    return dict(vars(runner().parse_args(argv)))


def config_from_dict(d: Mapping[str, Any]) -> Round3Config:
    return Round3Config(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items()})


def protocol_check_job(args: Mapping[str, Any], meta: Mapping[str, Any], cell: Cell, kind: str, timeframe: str) -> Dict[str, Any]:
    """The replication study's protocol check with the job's deliberate, documented differences named beside the raw mismatches."""
    narrowed = dict(args, strategies=[s for s in args["strategies"] if s in set(meta.get("strategies") or [])])
    check = protocol_check(narrowed, meta)
    expected: Dict[str, str] = {}
    if cell.tier != "reference":
        expected["policy_sizing"] = f"the {cell.tier} tier ({tier(cell.tier).label})"
    if kind in FIXED_KINDS:
        expected["brackets"] = f"the fixed-rule protocol: the exit bracket is fixed ({'trail3' if kind == 'fixed_trail' else 'none'}), never selected"
        expected["min_trades"] = "the fixed-rule protocol: no train-trade qualification (min_trades 0)"
    if timeframe == "1D":
        expected["timeframes"] = "the bar-size question of this round: 1D bars resampled from 1H (Sprint 2c ran 4H and 6H)"
    unexplained = {k: v for k, v in check["mismatches"].items() if k not in expected}
    check.update({"cell": cell.to_dict(), "kind": kind, "timeframe": timeframe, "expected_mismatches": expected, "unexplained_mismatches": unexplained,
                  "ok_for_cell": not unexplained, "new_candidates": [s for s in args["strategies"] if s not in set(meta.get("strategies") or [])],
                  "r18": {"tier": cell.tier, "brakes_on": cell.brakes, "brakes": TRADER_BRAKES.to_dict() if (cell.brakes and tier(cell.tier).turtle_ladder) else None,
                          "variant": cell.variant},
                  "protocol_variant": FIXED_RULE_PROTOCOL if kind in FIXED_KINDS else None,
                  "note": ("a tier replaces Sprint 2c's policy sizing by design; the fixed-rule protocol fixes the bracket and skips the train-trade "
                           "qualification by design; 1D bars are the bar-size question; every other protocol parameter is checked")})
    return check


# -- stored results ------------------------------------------------------------------------------------------------

def stored_results(v1c_doc: Mapping[str, Any], r12_doc: Mapping[str, Any], r18_doc: Mapping[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """The stored numbers this study reproduces: Sprint 2c's and the replication study's (Reference cell) and the Trader Policy study's judged cell."""
    reference: List[Dict[str, Any]] = [dict(r, study_source="Sprint 2c") for r in v1c_doc.get("results") or []]
    for s in r12_doc.get("series") or []:
        for r in s.get("results") or []:
            reference.append(dict(r, study_source="R12 replication"))
    trader: List[Dict[str, Any]] = [dict(r, study_source="R18 Trader Policy v1") for r in r18_doc.get("results") or []
                                    if not r.get("skipped") and (r.get("cell") or {}).get("key") == JUDGED_CELL.key]
    return {"reference": reference, "trader": trader}


# -- jobs --------------------------------------------------------------------------------------------------------------

SERIES_KEYS = ("instrument", "timeframe", "results", "failures", "benchmark", "span", "holdout_span", "positioning", "s0_blocked_share", "skipped")


def plan_jobs(cfg: Round3Config, *, evaluate_holdout: bool) -> List[Dict[str, Any]]:
    """One job per (series, cell, kind): the control, the fixed rules (bracket none), the trail variant (bracket trail3), the bar-size families."""
    jobs: List[Dict[str, Any]] = []
    fixed = [c for c in cfg.candidates if c != "S7t"]
    trail = [c for c in cfg.candidates if c == "S7t"]

    def add(kind: str, strategies: Sequence[str], inst: str, tf: str, cell: Cell, opens: bool) -> None:
        if strategies:
            jobs.append({"cfg": cfg.to_dict(), "kind": kind, "instrument": inst, "timeframe": tf, "cell": cell.to_dict(), "strategies": list(strategies),
                         "evaluate_holdout": bool(opens)})

    for tf in cfg.timeframes:
        for inst in cfg.markets:
            for cell in cfg.cell_objects:
                judged = cell == JUDGED_CELL
                add("control", [CONTROL], inst, tf, cell, evaluate_holdout and judged)
                add("fixed", fixed, inst, tf, cell, evaluate_holdout and judged)
                add("fixed_trail", trail, inst, tf, cell, evaluate_holdout and judged)
    if cfg.barsize:
        for tf in BARSIZE_TIMEFRAMES:
            for inst in PRIMARY_MARKETS:
                for cell in cfg.cell_objects:
                    if not (tf in cfg.timeframes and inst in cfg.markets):  # the control for a series the hypotheses do not cover (4H, or a narrowed run)
                        add("control", [CONTROL], inst, tf, cell, False)
                    add("barsize", list(BARSIZE_CANDIDATES), inst, tf, cell, False)
    return jobs


def run_job(job: Mapping[str, Any]) -> Dict[str, Any]:
    """Process-pool entry point: Sprint 2c's ``run_series`` for one job."""
    v1c = runner()
    args = job_args(job)
    print(f"[{job['instrument']} {job['timeframe']} @ {job['cell']['key']}] {job['kind']}: {job['strategies']} ...", flush=True)
    out = v1c.run_series(dict(args), job["instrument"], job["timeframe"])
    series: Dict[str, Any] = {k: out.get(k) for k in SERIES_KEYS}
    series.update({"kind": job["kind"], "cell": dict(job["cell"]), "strategies": list(job["strategies"]), "args": dict(args),
                   "trades": {f"{k}|{m}": t for (k, m), t in (out.get("trades") or {}).items()}})
    return series


def result_key(candidate: str, instrument: str, timeframe: str, mode: Optional[str], cell_key: str) -> str:
    return f"{candidate}|{instrument}|{timeframe}|{mode}|{cell_key}"


def configuration_name(candidate: str, instrument: str, timeframe: str, mode: Optional[str]) -> str:
    return f"{candidate} {instrument} {timeframe} [{mode}]"


def _mode(r: Mapping[str, Any]) -> Optional[str]:
    return (r.get("regime") or {}).get("mode")


def merge_results(outputs: Sequence[Mapping[str, Any]], stored_meta: Mapping[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Every job's results keyed ``candidate|instrument|timeframe|mode|cell``, each with its cell, kind, role and protocol check; plus per-series info."""
    merged: Dict[str, Dict[str, Any]] = {}
    series_info: Dict[str, Dict[str, Any]] = {}
    for o in outputs:
        cell = Cell(o["cell"]["tier"], bool(o["cell"]["brakes"]), o["cell"].get("variant", "none"))
        skey = f"{o['instrument']} {o['timeframe']}"
        info = series_info.setdefault(skey, {"instrument": o["instrument"], "timeframe": o["timeframe"], "failures": [], "skipped": None})
        if o.get("skipped"):
            info["skipped"] = o["skipped"]
            continue
        for k in ("benchmark", "span", "holdout_span", "positioning", "s0_blocked_share"):
            if info.get(k) is None and o.get(k) is not None:
                info[k] = o[k]
        info["failures"].extend(o.get("failures") or [])
        check = protocol_check_job(o["args"], stored_meta, cell, o["kind"], o["timeframe"])
        for r in o.get("results") or []:
            r = dict(r)
            cand = r["candidate"]
            r.update({"cell": cell.to_dict(), "kind": o["kind"], "configuration": configuration_name(cand, r["instrument"], r["timeframe"], _mode(r)),
                      "protocol_check": check, "holdout_confirmed": holdout_verdict(r) if r.get("holdout") else None})
            merged[result_key(cand, r["instrument"], r["timeframe"], _mode(r), cell.key)] = r
    return merged, series_info


def result_of(merged: Mapping[str, Mapping[str, Any]], candidate: str, instrument: str, timeframe: str, mode: Optional[str], cell: Cell) -> Optional[Mapping[str, Any]]:
    return merged.get(result_key(candidate, instrument, timeframe, mode, cell.key))


# -- the reproduction ----------------------------------------------------------------------------------------------------

def reproduction_checks(merged: Mapping[str, Mapping[str, Any]], stored: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    """Every result with a stored counterpart: the Reference cell against Sprint 2c / the replication study, the Trader cell against the Trader Policy study."""
    checks: List[Dict[str, Any]] = []
    for cell, pool_name in ((REFERENCE_CELL, "reference"), (JUDGED_CELL, "trader")):
        pool = list(stored.get(pool_name) or [])
        rows = [r for r in merged.values() if r["cell"]["key"] == cell.key
                and any(s["candidate"] == r["candidate"] and s["instrument"] == r["instrument"] and s["timeframe"] == r["timeframe"] and _mode(s) == _mode(r) for s in pool)]
        if not rows:
            continue
        for c in reproduction_check({"results": rows}, pool):
            exp = next(s for s in pool if s["candidate"] == c["candidate"] and s["instrument"] == c["instrument"] and s["timeframe"] == c["timeframe"] and _mode(s) == c["regime"])
            c.update({"cell": cell.key, "study": exp.get("study_source"), "configuration": configuration_name(c["candidate"], c["instrument"], c["timeframe"], c["regime"])})
            checks.append(c)
    return checks


# -- bookkeeping on the results -------------------------------------------------------------------------------------------

def _num(v: Any, default: float = float("nan")) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x


def _finite(v: Any) -> Optional[float]:
    x = _num(v)
    return None if (math.isnan(x) or math.isinf(x)) else x


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


def _delta(a: Any, b: Any) -> Optional[float]:
    x, y = _num(a), _num(b)
    return None if (math.isnan(x) or math.isnan(y)) else x - y


def compare_with(r: Mapping[str, Any], base: Optional[Mapping[str, Any]], *, line: str) -> Dict[str, Any]:
    """The configuration beside a comparison line (hold + policy at the same cell, or the variant's base rule): levels and deltas."""
    if base is None:
        return {"available": False, "line": line}
    m, b = _metrics_of(r), _metrics_of(base)
    years = sorted(set(m["yearly"]) | set(b["yearly"]))
    return {"available": True, "line": line, "base_configuration": base.get("configuration"), "base_candidate": base["candidate"], "variant": m, "base": b,
            "delta": {k: _delta(m[k], b[k]) for k in ("calmar", "cagr", "sharpe", "max_drawdown", "profit_factor", "n_trades", "trades_per_year", "exposure",
                                                       "fees_pct_per_year", "rolling_12m_positive_share", "worst_calendar_year_return", "payoff_ratio")},
            "beats_base_by_0_1": bool(_num(m["calmar"], -9.0) > _num(b["calmar"], -9.0) + 0.1),
            "yearly": {y: {"variant": m["yearly"].get(y), "base": b["yearly"].get(y), "delta": _delta(m["yearly"].get(y), b["yearly"].get(y))} for y in years},
            "base_passed": b["passed"]}


def annotate_all(merged: Mapping[str, Dict[str, Any]]) -> None:
    """Every result gets its role, hypothesis, the comparisons (hold at the same cell; the variant's base; the Reference cell) and the fleet readings."""
    for r in merged.values():
        cand, inst, tf, mode = r["candidate"], r["instrument"], r["timeframe"], _mode(r)
        cell = Cell(r["cell"]["tier"], bool(r["cell"]["brakes"]), r["cell"].get("variant", "none"))
        r["hypothesis"] = HYPOTHESIS_OF_CANDIDATE.get(cand)
        r["role"] = "control" if cand == CONTROL else ("configuration" if r["hypothesis"] else "barsize")
        r["judged"] = bool(r["role"] == "configuration" and cell == JUDGED_CELL)
        r["primary"] = inst in PRIMARY_MARKETS
        r["fixed_rule"] = cand in FIXED_RULES
        r["variant_of"] = VARIANT_OF.get(cand)
        r["fixed_bracket"] = getattr(get_candidate(cand), "fixed_bracket", "none") if cand != CONTROL else "none"
        tpy = _finite((r.get("oos") or {}).get("trades_per_year"))
        r["trades_per_year"] = tpy
        r["turnover_ok"] = bool(tpy is not None and tpy <= TURNOVER_CEILING)
        band = EXPECTED_TRADES_PER_YEAR.get(r["hypothesis"] or "")
        r["expected_trades"] = None if band is None or tpy is None else ("within" if band[0] <= tpy <= band[1] else ("below" if tpy < band[0] else "above"))
        hold = result_of(merged, CONTROL, inst, tf, "none", cell) if cand != CONTROL else None
        r["comparison"] = compare_with(r, hold, line="hold + policy sizing at the same cell") if r["role"] != "control" else {"available": False}
        base = result_of(merged, r["variant_of"], inst, tf, mode, cell) if r["variant_of"] else None
        r["variant_comparison"] = compare_with(r, base, line=f"the base rule {r['variant_of']}") if r["variant_of"] else {"available": False}
        ref = result_of(merged, cand, inst, tf, mode, REFERENCE_CELL) if cell != REFERENCE_CELL else None
        r["reference"] = None if ref is None else _reference_reading(r, ref)
        r["fleet_eligible"] = bool(r["judged"] and (r.get("acceptance_r18") or {}).get("passed") and r.get("holdout_confirmed") is True and r["turnover_ok"]
                                   and tf in FLEET_TIMEFRAMES)
        reasons: List[str] = []
        if r["judged"] and (r.get("acceptance_r18") or {}).get("passed") and r.get("holdout_confirmed") is True:
            if not r["turnover_ok"]:
                reasons.append(f"above the plan's turnover ceiling ({TURNOVER_CEILING:.0f} trades a year)")
            if tf not in FLEET_TIMEFRAMES:
                reasons.append(f"the fleet runs {' and '.join(FLEET_TIMEFRAMES)} bars, not {tf}")
        r["fleet_blockers"] = reasons


def _reference_reading(r: Mapping[str, Any], ref: Mapping[str, Any]) -> Dict[str, Any]:
    o, ro = r.get("oos") or {}, ref.get("oos") or {}
    a, b = _num(o.get("avg_allocation")), _num(ro.get("avg_allocation"))
    return {"calmar": ro.get("calmar"), "cagr": ro.get("cagr"), "max_drawdown": ro.get("max_drawdown"), "sharpe": ro.get("sharpe"), "ann_vol": ro.get("ann_vol"),
            "n_trades": ro.get("n_trades"), "passed": bool((ref.get("acceptance_r18") or {}).get("passed")), "failed": list((ref.get("acceptance_r18") or {}).get("failed") or []),
            "exposure_ratio": (a / b) if (b > 0 and not math.isnan(a)) else None, "holdout": ref.get("holdout")}


# -- readings ------------------------------------------------------------------------------------------------------------

def directional_reading(rows: Sequence[Mapping[str, Any]], *, key: str = "comparison", alpha: float = SIGN_TEST_ALPHA) -> Dict[str, Any]:
    """How many configurations raised Calmar beside their comparison line, against the one-sided sign-test threshold (indicative)."""
    comps = [r[key] for r in rows if (r.get(key) or {}).get("available")]
    n = len(comps)
    improved = sum(1 for c in comps if _num(c["delta"].get("calmar"), 0.0) > 0.0)
    threshold = sign_threshold(n, alpha)
    return {"n": n, "improved": improved, "threshold": threshold, "alpha": alpha, "p_value": binomial_tail(improved, n) if n else None,
            "expected_by_chance": n / 2.0, "replicates_in_direction": bool(threshold is not None and improved >= threshold),
            "beats_by_0_1": sum(1 for c in comps if c.get("beats_base_by_0_1")),
            "configurations_improved": [r["configuration"] for r in rows if (r.get(key) or {}).get("available") and _num(r[key]["delta"].get("calmar"), 0.0) > 0.0]}


def judged_results(merged: Mapping[str, Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    return [r for r in merged.values() if r.get("judged")]


def replication_of_primary_passers(merged: Mapping[str, Mapping[str, Any]], h: Hypothesis) -> List[Dict[str, Any]]:
    """The R12 reading: every configuration (candidate, timeframe, mode) that passed on a primary market, on each replication market."""
    needed = markets_needed(len(REPLICATION_MARKETS))
    out: List[Dict[str, Any]] = []
    seen = set()
    for r in judged_results(merged):
        if r.get("hypothesis") != h.key or not r["primary"] or not (r.get("acceptance_r18") or {}).get("passed"):
            continue
        key = (r["candidate"], r["timeframe"], _mode(r))
        if key in seen:
            continue
        seen.add(key)
        per_market = []
        for m in REPLICATION_MARKETS:
            x = result_of(merged, r["candidate"], m, r["timeframe"], _mode(r), JUDGED_CELL)
            if x is None:
                per_market.append({"instrument": m, "ran": False})
                continue
            per_market.append({"instrument": m, "ran": True, "passed": bool((x.get("acceptance_r18") or {}).get("passed")), "failed": list((x.get("acceptance_r18") or {}).get("failed") or []),
                               "calmar": (x.get("oos") or {}).get("calmar"), "n_trades": (x.get("oos") or {}).get("n_trades"), "holdout": x.get("holdout"),
                               "holdout_confirmed": x.get("holdout_confirmed")})
        n_pass = sum(1 for e in per_market if e.get("passed"))
        n_ran = sum(1 for e in per_market if e.get("ran"))
        out.append({"candidate": r["candidate"], "timeframe": r["timeframe"], "mode": _mode(r), "configuration": f"{r['candidate']} {r['timeframe']} [{_mode(r)}]",
                    "passed_on": [m for m in PRIMARY_MARKETS if (result_of(merged, r["candidate"], m, r["timeframe"], _mode(r), JUDGED_CELL) or {}).get("acceptance_r18", {}).get("passed")],
                    "markets": per_market, "n_pass": n_pass, "n_ran": n_ran, "needed": needed, "replicated": bool(n_ran > 0 and n_pass >= needed)})
    return out


def variant_readings(merged: Mapping[str, Mapping[str, Any]], h: Hypothesis) -> List[Dict[str, Any]]:
    """Each variant beside its base rule over every series, mode and cell (the sign test), with the medians."""
    out: List[Dict[str, Any]] = []
    for v in h.variants:
        rows = [r for r in merged.values() if r["candidate"] == v and (r.get("variant_comparison") or {}).get("available")]
        d = directional_reading(rows, key="variant_comparison")
        comps = [r["variant_comparison"] for r in rows]
        out.append({"variant": v, "base": h.base, "label": get_candidate(v).label, "n": len(rows), "directional": d,
                    "median_delta_calmar": _median([c["delta"].get("calmar") for c in comps]), "median_delta_cagr": _median([c["delta"].get("cagr") for c in comps]),
                    "median_delta_max_drawdown": _median([c["delta"].get("max_drawdown") for c in comps]),
                    "median_delta_payoff": _median([c["delta"].get("payoff_ratio") for c in comps]),
                    "median_delta_trades_per_year": _median([c["delta"].get("trades_per_year") for c in comps]),
                    "judged_passed": sum(1 for r in rows if r.get("judged") and (r.get("acceptance_r18") or {}).get("passed")),
                    "judged_n": sum(1 for r in rows if r.get("judged"))})
    return out


def pooled_reading(merged: Mapping[str, Mapping[str, Any]], h: Hypothesis, trades: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """H8's information reading: per (candidate, timeframe, mode) at the judged cell, the trades pooled over the nine markets."""
    import numpy as np

    out: List[Dict[str, Any]] = []
    for cand in h.candidates:
        for tf in FIXED_TIMEFRAMES:
            for mode in STUDY_MODES:
                rows = [r for r in judged_results(merged) if r["candidate"] == cand and r["timeframe"] == tf and _mode(r) == mode]
                if not rows:
                    continue
                pnl: List[float] = []
                risk: List[float] = []
                for r in rows:
                    t = trades.get(result_key(cand, r["instrument"], tf, mode, JUDGED_CELL.key))
                    if t is None or len(t) == 0:
                        continue
                    pnl.extend(float(x) for x in t["pnl"].to_numpy(dtype=float))
                    risk.extend(float(x) for x in (t["risk"].to_numpy(dtype=float) if "risk" in t else np.full(len(t), np.nan)))
                arr = np.asarray(pnl, dtype=float)
                rk = np.asarray(risk, dtype=float)
                wins, losses = arr[arr > 0], arr[arr <= 0]
                gross_loss = float(-losses.sum())
                ok = np.isfinite(rk) & (rk > 0)
                out.append({"candidate": cand, "timeframe": tf, "mode": mode, "n_markets": len(rows), "pooled_trades": int(arr.size),
                            "pooled_profit_factor": (float(wins.sum() / gross_loss) if gross_loss > 0 else (None if not wins.size else 999.0)),
                            "pooled_payoff_ratio": (float(wins.mean() / abs(losses.mean())) if (wins.size and losses.size and losses.mean() < 0) else None),
                            "pooled_win_rate": float(wins.size / arr.size) if arr.size else None,
                            "pooled_expectancy_r": float((arr[ok] / rk[ok]).mean()) if ok.any() else None,
                            "median_calmar": _median([(r.get("oos") or {}).get("calmar") for r in rows]),
                            "median_calmar_hold": _median([((r.get("comparison") or {}).get("base") or {}).get("calmar") for r in rows if (r.get("comparison") or {}).get("available")]),
                            "calmar_above_hold": sum(1 for r in rows if _num(((r.get("comparison") or {}).get("delta") or {}).get("calmar"), 0.0) > 0.0),
                            "passed": sum(1 for r in rows if (r.get("acceptance_r18") or {}).get("passed"))})
    return out


def _median(values: Sequence[Any]) -> Optional[float]:
    xs = sorted(float(v) for v in values if v is not None and isinstance(v, (int, float)) and math.isfinite(float(v)))
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else 0.5 * (xs[m - 1] + xs[m])


def _best(rows: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    best = max(rows, key=lambda r: _num((r.get("oos") or {}).get("calmar"), -9.0))
    return {"configuration": best["configuration"], **_metrics_of(best)}


def failure_facts(h: Hypothesis, rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The numbers a failure analysis is written from: the rules beside hold + policy at the same cell, per market, timeframe and mode."""
    facts: Dict[str, Any] = {"n": len(rows), "base_candidate": CONTROL}
    comps = [r["comparison"] for r in rows if (r.get("comparison") or {}).get("available")]
    facts["n_compared"] = len(comps)
    facts["median_n_trades"] = _median([(r.get("oos") or {}).get("n_trades") for r in rows])
    facts["median_trades_per_year"] = _median([r.get("trades_per_year") for r in rows])
    facts["expected_trades_per_year"] = list(EXPECTED_TRADES_PER_YEAR.get(h.key, (None, None)))
    facts["median_payoff"] = _median([(r.get("acceptance_r18") or {}).get("payoff_ratio") for r in rows])
    facts["median_expectancy_r"] = _median([((r.get("r18") or {}).get("trades") or {}).get("expectancy_r") for r in rows])
    facts["median_win_rate"] = _median([(r.get("oos") or {}).get("win_rate") for r in rows])
    facts["median_exposure"] = _median([(r.get("oos") or {}).get("exposure") for r in rows])
    facts["windows_traded_total"] = int(sum(_num((r.get("oos") or {}).get("windows_traded"), 0.0) for r in rows))
    facts["windows_total"] = int(sum(_num((r.get("oos") or {}).get("windows"), 0.0) for r in rows))
    facts["per_market"] = {}
    if not comps:
        return facts

    def d(k: str) -> List[Any]:
        return [c["delta"].get(k) for c in comps]

    facts.update({
        "calmar_improved": sum(1 for c in comps if _num(c["delta"].get("calmar"), 0.0) > 0.0), "sharpe_improved": sum(1 for c in comps if _num(c["delta"].get("sharpe"), 0.0) > 0.0),
        "drawdown_fell": sum(1 for c in comps if _num(c["delta"].get("max_drawdown"), 0.0) < 0.0), "return_fell": sum(1 for c in comps if _num(c["delta"].get("cagr"), 0.0) < 0.0),
        "beats_base_by_0_1": sum(1 for c in comps if c.get("beats_base_by_0_1")),
        "median_delta_calmar": _median(d("calmar")), "median_delta_cagr": _median(d("cagr")), "median_delta_max_drawdown": _median(d("max_drawdown")),
        "median_variant_calmar": _median([c["variant"]["calmar"] for c in comps]), "median_base_calmar": _median([c["base"]["calmar"] for c in comps]),
        "median_variant_cagr": _median([c["variant"]["cagr"] for c in comps]), "median_base_cagr": _median([c["base"]["cagr"] for c in comps]),
        "median_variant_dd": _median([c["variant"]["max_drawdown"] for c in comps]), "median_base_dd": _median([c["base"]["max_drawdown"] for c in comps]),
        "median_variant_rolling": _median([c["variant"]["rolling_12m_positive_share"] for c in comps]), "median_base_rolling": _median([c["base"]["rolling_12m_positive_share"] for c in comps]),
        "median_variant_sharpe": _median([c["variant"]["sharpe"] for c in comps]), "median_base_sharpe": _median([c["base"]["sharpe"] for c in comps]),
        "median_base_exposure": _median([c["base"]["exposure"] for c in comps]),
        "median_2022_variant": _median([c["yearly"].get("2022", {}).get("variant") for c in comps]), "median_2022_base": _median([c["yearly"].get("2022", {}).get("base") for c in comps]),
        "by_mode": {mode: {"calmar_improved": sum(1 for r in rows if _mode(r) == mode and _num(((r.get("comparison") or {}).get("delta") or {}).get("calmar"), 0.0) > 0.0),
                           "n": sum(1 for r in rows if _mode(r) == mode)} for mode in sorted({_mode(r) for r in rows if _mode(r)})},
        "by_timeframe": {tf: {"calmar_improved": sum(1 for r in rows if r["timeframe"] == tf and _num(((r.get("comparison") or {}).get("delta") or {}).get("calmar"), 0.0) > 0.0),
                              "n": sum(1 for r in rows if r["timeframe"] == tf), "median_calmar": _median([(r.get("oos") or {}).get("calmar") for r in rows if r["timeframe"] == tf]),
                              "median_trades_per_year": _median([r.get("trades_per_year") for r in rows if r["timeframe"] == tf])}
                         for tf in sorted({r["timeframe"] for r in rows})},
    })
    per_market: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        c = r.get("comparison") or {}
        if not c.get("available"):
            continue
        e = per_market.setdefault(r["instrument"], {"calmar_improved": 0, "n": 0, "passed": 0})
        e["n"] += 1
        e["calmar_improved"] += int(_num(c["delta"].get("calmar"), 0.0) > 0.0)
        e["passed"] += int(bool((r.get("acceptance_r18") or {}).get("passed")))
    facts["per_market"] = per_market
    return facts


def _label(rows: Sequence[Mapping[str, Any]]) -> Tuple[str, List[Mapping[str, Any]], List[Mapping[str, Any]], List[Mapping[str, Any]]]:
    passed = [r for r in rows if (r.get("acceptance_r18") or {}).get("passed")]
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
    return label, passed, confirmed, contradicted


def hypothesis_verdicts(merged: Mapping[str, Mapping[str, Any]], cfg: Round3Config, trades: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """Per hypothesis: the primary label, the replication label, the readings, the failure facts (the pre-registered rules)."""
    out: List[Dict[str, Any]] = []
    for h in HYPOTHESES:
        if h.key not in cfg.hypotheses:
            continue
        rows = [r for r in judged_results(merged) if r.get("hypothesis") == h.key]
        primary = [r for r in rows if r["primary"]]
        repl = [r for r in rows if not r["primary"]]
        label, passed, confirmed, contradicted = _label(primary)
        r_label, r_passed, r_confirmed, r_contradicted = _label(repl)
        counts: Dict[str, int] = {}
        for r in rows:
            for g in (r.get("acceptance_r18") or {}).get("failed", []):
                counts[g] = counts.get(g, 0) + 1
        v: Dict[str, Any] = {
            "hypothesis": h.key, "title": h.title, "candidates": list(h.candidates), "base": h.base, "label": label, "replication_label": r_label if repl else "not run",
            "n_configurations": len(rows), "n_primary": len(primary), "n_replication": len(repl),
            "n_passed": len(passed), "n_confirmed": len(confirmed), "n_contradicted": len(contradicted),
            "n_passed_replication": len(r_passed), "n_confirmed_replication": len(r_confirmed), "n_contradicted_replication": len(r_contradicted),
            "passed": [r["configuration"] for r in passed], "confirmed": [r["configuration"] for r in confirmed], "contradicted": [r["configuration"] for r in contradicted],
            "passed_replication": [r["configuration"] for r in r_passed], "confirmed_replication": [r["configuration"] for r in r_confirmed],
            "contradicted_replication": [r["configuration"] for r in r_contradicted],
            "binding_gates": sorted(counts.items(), key=lambda kv: -kv[1]), "best_primary": _best(primary), "best_replication": _best(repl),
            "directional_primary": directional_reading(primary), "directional_replication": directional_reading(repl), "directional_all": directional_reading(rows),
            "replication": replication_of_primary_passers(merged, h), "variants": variant_readings(merged, h),
            "failure_facts": failure_facts(h, rows), "failure_facts_primary": failure_facts(h, primary),
            "fleet_eligible": [r["configuration"] for r in rows if r.get("fleet_eligible")],
            "recorded_only": [{"configuration": r["configuration"], "reasons": r.get("fleet_blockers")} for r in rows if r.get("acceptance_r18", {}).get("passed")
                              and r.get("holdout_confirmed") is True and not r.get("fleet_eligible")],
            "turnover_flagged": [r["configuration"] for r in rows if not r.get("turnover_ok")],
        }
        if h.key == "H8" and trades is not None:
            v["pooled"] = pooled_reading(merged, h, trades)
        out.append(v)
    return out


def overall_summary(verdicts: Sequence[Mapping[str, Any]], merged: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    rows = judged_results(merged)
    passed = [r for r in rows if (r.get("acceptance_r18") or {}).get("passed")]
    counts: Dict[str, int] = {}
    for r in rows:
        for g in (r.get("acceptance_r18") or {}).get("failed", []):
            counts[g] = counts.get(g, 0) + 1
    return {"n_judged": len(rows), "n_primary": sum(1 for r in rows if r["primary"]), "n_passed": len(passed),
            "n_confirmed": sum(1 for r in passed if r.get("holdout_confirmed") is True), "n_contradicted": sum(1 for r in passed if r.get("holdout_confirmed") is False),
            "n_unevaluated": sum(1 for r in passed if r.get("holdout_confirmed") is None), "expected_passes_by_chance": round(len(rows) * 4.0 / 108.0, 1),
            "labels": {v["hypothesis"]: v["label"] for v in verdicts}, "replication_labels": {v["hypothesis"]: v["replication_label"] for v in verdicts},
            "binding_gates": sorted(counts.items(), key=lambda kv: -kv[1]),
            "passed": [{"configuration": r["configuration"], "calmar": (r.get("oos") or {}).get("calmar"), "holdout_confirmed": r.get("holdout_confirmed"),
                        "fleet_eligible": r.get("fleet_eligible"), "blockers": r.get("fleet_blockers")} for r in passed],
            "fleet_eligible": [r["configuration"] for r in rows if r.get("fleet_eligible")]}


# -- the bar-size comparison ------------------------------------------------------------------------------------------------

def barsize_table(merged: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """The S1 / S2 families on 1D, 6H and 4H bars at both cells, the 0.20 % replay beside the 0.30 % gate cost, and the pre-registered reading."""
    rows: List[Dict[str, Any]] = []
    for cand in BARSIZE_CANDIDATES:
        for inst in PRIMARY_MARKETS:
            for mode in STUDY_MODES:
                for tf in BARSIZE_TIMEFRAMES:
                    for cell in CELLS:
                        r = result_of(merged, cand, inst, tf, mode, cell)
                        if r is None:
                            continue
                        o = r.get("oos") or {}
                        acc = r.get("acceptance_r18") or {}
                        scen = ((r.get("r18") or {}).get("cost_scenarios") or {}).get("measured_btc_eth") or {}
                        hold = result_of(merged, CONTROL, inst, tf, "none", cell)
                        windows_traded = int(_num(o.get("windows_traded"), 0.0))
                        # A bar size on which no walk-forward window qualified a rule (the 20-train-trade step silenced every window) has no trade and
                        # no Calmar to compare: it is UNTESTED there, and the 0.20 % replay (which would replay the default parameters) is not shown.
                        untested = windows_traded == 0
                        measured_all = {k: scen.get(k) for k in ("calmar", "cagr", "sharpe", "max_drawdown", "total_return", "profit_factor")} if scen else None
                        rows.append({"candidate": cand, "instrument": inst, "mode": mode, "timeframe": tf, "cell": cell.key, "tier": cell.tier,
                                     "bracket": (r.get("selected_params") or {}).get("bracket"), "cagr": o.get("cagr"), "sharpe": o.get("sharpe"), "max_drawdown": o.get("max_drawdown"),
                                     "calmar": o.get("calmar"), "profit_factor": o.get("profit_factor"), "n_trades": o.get("n_trades"), "trades_per_year": o.get("trades_per_year"),
                                     "fees_pct_per_year": o.get("fees_pct_per_year"), "exposure": o.get("exposure"), "ann_vol": o.get("ann_vol"), "passed": bool(acc.get("passed")),
                                     "failed": list(acc.get("failed") or []), "holdout": r.get("holdout"), "windows_traded": windows_traded, "windows": o.get("windows"),
                                     "untested": untested, "measured": None if untested else measured_all, "measured_literal": measured_all,
                                     "hold_calmar": ((hold or {}).get("oos") or {}).get("calmar"), "hold_cagr": ((hold or {}).get("oos") or {}).get("cagr"),
                                     "hold_max_drawdown": ((hold or {}).get("oos") or {}).get("max_drawdown")})
    # The reading: for each (rule, market, mode) at the Trader cell, which bar size has the highest Calmar at 0.30 % and at 0.20 %. Taken literally
    # (the pre-registered rule) an untested bar size counts with its 0.00; the clarified reading sets it aside - both are reported.
    best: List[Dict[str, Any]] = []
    for cand in BARSIZE_CANDIDATES:
        for inst in PRIMARY_MARKETS:
            for mode in STUDY_MODES:
                trader = [x for x in rows if x["candidate"] == cand and x["instrument"] == inst and x["mode"] == mode and x["tier"] == JUDGED_CELL.tier]
                if len(trader) < 2:
                    continue
                tested = [x for x in trader if not x["untested"]]
                gate_literal = max(trader, key=lambda x: _num(x["calmar"], -9.0))
                gate = max(tested, key=lambda x: _num(x["calmar"], -9.0)) if len(tested) >= 2 else None
                with_measured_literal = [x for x in trader if x.get("measured_literal") and x["measured_literal"].get("calmar") is not None]
                meas_literal = max(with_measured_literal, key=lambda x: _num(x["measured_literal"]["calmar"], -9.0)) if with_measured_literal else None
                with_measured = [x for x in tested if x.get("measured") and x["measured"].get("calmar") is not None]
                meas = max(with_measured, key=lambda x: _num(x["measured"]["calmar"], -9.0)) if len(with_measured) >= 2 else None
                best.append({"candidate": cand, "instrument": inst, "mode": mode, "family": "S2" if cand.startswith("S2") else "S1", "n_bar_sizes": len(trader),
                             "untested_timeframes": [x["timeframe"] for x in trader if x["untested"]],
                             "best_at_gate_cost_literal": gate_literal["timeframe"], "best_at_measured_cost_literal": None if meas_literal is None else meas_literal["timeframe"],
                             "best_at_gate_cost": None if gate is None else gate["timeframe"], "best_at_measured_cost": None if meas is None else meas["timeframe"],
                             "calmar_by_timeframe": {x["timeframe"]: x["calmar"] for x in trader},
                             "calmar_measured_by_timeframe": {x["timeframe"]: (x["measured"] or {}).get("calmar") for x in trader}})
    n = len(best)
    six_gate = sum(1 for b in best if b["best_at_gate_cost_literal"] == "6H")
    six_meas = sum(1 for b in best if b["best_at_measured_cost_literal"] == "6H")
    six_gate_clarified = sum(1 for b in best if b["best_at_gate_cost"] == "6H")
    six_meas_clarified = sum(1 for b in best if b["best_at_measured_cost"] == "6H")
    counts = {tf: {"gate_cost": sum(1 for b in best if b["best_at_gate_cost_literal"] == tf), "measured_cost": sum(1 for b in best if b["best_at_measured_cost_literal"] == tf),
                   "gate_cost_clarified": sum(1 for b in best if b["best_at_gate_cost"] == tf), "measured_cost_clarified": sum(1 for b in best if b["best_at_measured_cost"] == tf)}
              for tf in BARSIZE_TIMEFRAMES}
    families = {}
    for fam in ("S1", "S2"):
        sub = [b for b in best if b["family"] == fam]
        families[fam] = {"n": len(sub), "untested": sum(1 for b in sub if b["untested_timeframes"]),
                         "best_counts": {tf: {"gate_cost": sum(1 for b in sub if b["best_at_gate_cost"] == tf), "measured_cost": sum(1 for b in sub if b["best_at_measured_cost"] == tf)}
                                         for tf in BARSIZE_TIMEFRAMES}}
    untested_rows = sorted({f"{x['candidate']} {x['instrument']} {x['timeframe']} [{x['mode']}]" for x in rows if x["untested"] and x["tier"] == JUDGED_CELL.tier})
    medians = {tf: {"calmar_reference": _median([x["calmar"] for x in rows if x["timeframe"] == tf and x["tier"] == "reference"]),
                    "calmar_trader": _median([x["calmar"] for x in rows if x["timeframe"] == tf and x["tier"] == JUDGED_CELL.tier]),
                    "calmar_trader_measured": _median([(x["measured"] or {}).get("calmar") for x in rows if x["timeframe"] == tf and x["tier"] == JUDGED_CELL.tier]),
                    "sharpe_trader": _median([x["sharpe"] for x in rows if x["timeframe"] == tf and x["tier"] == JUDGED_CELL.tier]),
                    "trades_per_year": _median([x["trades_per_year"] for x in rows if x["timeframe"] == tf and x["tier"] == JUDGED_CELL.tier]),
                    "fees_pct_per_year": _median([x["fees_pct_per_year"] for x in rows if x["timeframe"] == tf and x["tier"] == JUDGED_CELL.tier]),
                    "passed_trader": sum(1 for x in rows if x["timeframe"] == tf and x["tier"] == JUDGED_CELL.tier and x["passed"]),
                    "n_trader": sum(1 for x in rows if x["timeframe"] == tf and x["tier"] == JUDGED_CELL.tier)} for tf in BARSIZE_TIMEFRAMES}
    needed = math.ceil(n / 2.0) if n else None
    reading = {"n_comparisons": n, "six_h_best_at_gate_cost": six_gate, "six_h_best_at_measured_cost": six_meas, "needed": needed,
               "holds": bool(n > 0 and six_gate >= needed and six_meas >= needed),
               "six_h_best_at_gate_cost_clarified": six_gate_clarified, "six_h_best_at_measured_cost_clarified": six_meas_clarified,
               "holds_clarified": bool(n > 0 and six_gate_clarified >= needed and six_meas_clarified >= needed),
               "best_counts": counts, "families": families, "untested": untested_rows, "medians_by_timeframe": medians}
    return {"rows": rows, "best": best, "reading": reading}


def rebuild_merged(results: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The study's results keyed as :func:`merge_results` keys them (to recompute a derived table from a saved results file)."""
    return {result_key(r["candidate"], r["instrument"], r["timeframe"], _mode(r), r["cell"]["key"]): dict(r) for r in results}


# -- the holdout ledger and the earlier looks ---------------------------------------------------------------------------------

LEDGER_NOTE = ("Every opening of the untouched 12 months by research round 3 (plan row R19), in order; entries are appended, never edited. The report "
               "shows all of them, each beside the earlier look at the same months by the stored hold + policy control of its market. The hold + policy "
               "control's 12 months at the Trader cell are a comparison line, not a configuration under test.")


def holdout_openings(merged: Mapping[str, Mapping[str, Any]], series_info: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in merged.values():
        h = r.get("holdout")
        if not h:
            continue
        span = (series_info.get(f"{r['instrument']} {r['timeframe']}") or {}).get("holdout_span")
        out.append({"configuration": r["configuration"], "cell": r["cell"]["key"], "role": r.get("role"), "selected_params": _canon(r.get("selected_params")),
                    "span": span, "total_return": h.get("total_return"), "max_drawdown": h.get("max_drawdown"), "profit_factor": h.get("profit_factor"),
                    "n_trades": h.get("n_trades"), "confirmed": None if r["candidate"] == CONTROL else holdout_verdict(r)})
    out.sort(key=lambda x: (x["role"] != "configuration", x["configuration"], x["cell"]))
    return out


def earlier_looks(merged: Mapping[str, Mapping[str, Any]], stored: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    """For every configuration whose holdout this run opened: the stored hold + policy control's look at the same months on that market."""
    out: List[Dict[str, Any]] = []
    pool = list(stored.get("reference") or [])
    for r in merged.values():
        if not r.get("holdout") or r.get("role") != "configuration":
            continue
        tf = r["timeframe"] if r["timeframe"] in ("4H", "6H") else "6H"
        base = next((s for s in pool if s["candidate"] == CONTROL and s["instrument"] == r["instrument"] and s["timeframe"] == tf and _mode(s) == "none"), None)
        entry: Dict[str, Any] = {"configuration": r["configuration"], "cell": r["cell"]["key"],
                                 "earlier_configuration": None if base is None else configuration_name(CONTROL, r["instrument"], tf, "none"),
                                 "earlier_study": None if base is None else base.get("study_source"), "same_bar_size": tf == r["timeframe"]}
        if base is not None and base.get("holdout"):
            h = base["holdout"]
            entry.update({"earlier_opened": True, "earlier_total_return": h.get("total_return"), "earlier_profit_factor": h.get("profit_factor"),
                          "earlier_n_trades": h.get("n_trades")})
        else:
            entry["earlier_opened"] = False
        out.append(entry)
    out.sort(key=lambda x: (x["configuration"], x["cell"]))
    return out


def guard_second_look(ledger: Sequence[Mapping[str, Any]], openings: Sequence[Mapping[str, Any]], *, evaluate_holdout: bool) -> List[str]:
    if not evaluate_holdout:
        return []
    seen = {(o["configuration"], o.get("cell")) for e in ledger for o in e.get("openings", []) if o.get("role") == "configuration"}
    return sorted(f"{o['configuration']} @ {o['cell']}" for o in openings if o["role"] == "configuration" and (o["configuration"], o.get("cell")) in seen)


def write_round3_ledger(path: str, entries: List[Dict[str, Any]]) -> None:
    Path(path).write_text(json.dumps({"note": LEDGER_NOTE, "entries": entries}, indent=1) + "\n", encoding="utf-8")


# -- the paper-fleet shortlist ----------------------------------------------------------------------------------------------------

def shortlist_additions(merged: Mapping[str, Mapping[str, Any]], *, source: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """``(applied, recorded_only)``: fleet-eligible confirmed passers as tier-tagged shortlist rows naming the fixed-rule protocol, and the confirmed
    passers the fleet cannot run (1D bars, or above the turnover ceiling), recorded with their reasons."""
    rows: List[Dict[str, Any]] = []
    recorded: List[Dict[str, Any]] = []
    for r in judged_results(merged):
        if not ((r.get("acceptance_r18") or {}).get("passed") and r.get("holdout_confirmed") is True):
            continue
        row = _row(r)
        row["passed"] = bool((r.get("acceptance_r18") or {}).get("passed"))  # the section 4.6 verdict at the tier (the v1c thresholds differ)
        row["failed_gates"] = list((r.get("acceptance_r18") or {}).get("failed") or [])
        row["sizing"] = tier(JUDGED_CELL.tier).label
        row["sizing_config"] = r.get("policy_sizing")
        row["source"] = dict(source, tier=JUDGED_CELL.tier, brakes=((r.get("r18") or {}).get("brakes")), variant="none", cell=JUDGED_CELL.key,
                             protocol_variant=FIXED_RULE_PROTOCOL, role="candidate", hypothesis=r.get("hypothesis"), fixed_bracket=r.get("fixed_bracket"))
        if r.get("fleet_eligible"):
            rows.append(row)
        else:
            recorded.append(dict(row, reasons=list(r.get("fleet_blockers") or [])))
    rows.sort(key=lambda x: (-_num(x.get("calmar"), -9.0), -_num(x.get("sharpe"), -9.0)))
    recorded.sort(key=lambda x: (-_num(x.get("calmar"), -9.0), -_num(x.get("sharpe"), -9.0)))
    return rows, recorded
