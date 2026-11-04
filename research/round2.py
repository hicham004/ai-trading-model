"""Research round 2: three pre-registered hypotheses drawn from the R12 and R13 failure analyses (plan row R16, SIMULATION ONLY).

Plan section 5.3's research loop with the Sprint 2c discipline, as in round 1
(:mod:`research.round1`). Everything that defines the answer was fixed before
the first run — :data:`PREREGISTRATION` here, written to
``docs/research/research_round_2_preregistration.json`` with a hash the study
checks — and the hash goes into the results.

How the rules are run: exactly as in the replication study (plan row R12) and
round 1, ``scripts/run_research_v1c.py`` is loaded as a module and its own
``run_series`` runs every candidate with Sprint 2c's defaults (grids, brackets,
S0 filter, fixed policy sizing, regime gate, walk-forward windows, gates,
holdout rule). Round 2 needs no change to the runner at all: its rules use
only the market's own candles. Before any new rule is judged, the same code
path re-runs ``hold``, ``S1`` and ``S2`` on every market of the round and must
reproduce the stored numbers to 6 decimals — Sprint 2c's for BTC-USDT and
ETH-USDT, the replication study's for the other seven markets.

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

from research.markets import SPRINT_2C_INSTRUMENTS
from research.replication import DATA_END, load_ledger, load_v1c_runner, protocol_check, reproduction_check  # noqa: F401  (the ledger format is the replication study's)
from research.report_v1c import GATES, _row, holdout_verdict
from research.strategies import FIXED_RULES, ROUND2_BASES
from research.strategies.round1 import VOLUME_Z_DAYS, VOLUME_Z_MIN
from research.strategies.round2 import TREND_SMA_DAYS

ROOT = Path(__file__).resolve().parents[1]
V1C_RESULTS = ROOT / "docs" / "research" / "ensemble_v1c_results.json"
R12_RESULTS = ROOT / "docs" / "research" / "replication_v1d_results.json"
R12_PREREGISTRATION = ROOT / "docs" / "research" / "replication_v1d_preregistration.json"
PREREGISTRATION_PATH = ROOT / "docs" / "research" / "research_round_2_preregistration.json"
STUDY_LAKE_DIRNAME = "lake_research_round_2"
STUDY_TIMEFRAMES: Tuple[str, ...] = ("4H", "6H")
STUDY_MODES: Tuple[str, ...] = ("none", "gate")
CONTROL = "hold"
#: The Sprint 2c rules re-run on every market of the round: the reproduction set and the comparison lines.
REPRODUCTION_STRATEGIES: Tuple[str, ...] = (CONTROL, "S1", "S2")
STUDY_NAME = "R16 research round 2"
#: The replication study's markets, exactly as its pre-registration fixed them (checked against that file at load time).
REPLICATION_MARKETS: Tuple[str, ...] = ("XRP-USDT", "DOGE-USDT", "LINK-USDT", "TRX-USDT", "ADA-USDT", "LTC-USDT", "SOL-USDT")
#: The slow trend filter's markets: the Sprint 2c pair plus the three markets where the breakout rule passed walk-forward and the
#: untouched 12 months contradicted it in the replication study (plan row R12).
TREND_MARKETS: Tuple[str, ...] = ("BTC-USDT", "ETH-USDT", "ADA-USDT", "DOGE-USDT", "TRX-USDT")
ALL_MARKETS: Tuple[str, ...] = SPRINT_2C_INSTRUMENTS + REPLICATION_MARKETS
SIGN_TEST_ALPHA = 0.05
PATTERN_MIN_MARKETS = 5  # H4's pattern check: the 4H [gate] gain of round 1 counts as consistent on at least 5 of the 7 markets


class Round2Error(RuntimeError):
    """The study cannot be trusted (protocol mismatch, reproduction failure, a tampered pre-registration, a changed market list)."""


@dataclass(frozen=True)
class Hypothesis:
    key: str
    title: str
    candidate: str
    markets: Tuple[str, ...]

    @property
    def base(self) -> str:
        return ROUND2_BASES[self.candidate]

    @property
    def candidates(self) -> List[Tuple[str, str]]:
        return [(self.candidate, m) for m in self.markets]


HYPOTHESES: Tuple[Hypothesis, ...] = (
    Hypothesis("H4", "the volume (attention) confirmation on the replication markets", "S1+VC", REPLICATION_MARKETS),
    Hypothesis("H5", "a slow trend filter for the breakout rule", "S2+TF", TREND_MARKETS),
    Hypothesis("H6", "the slow trend filter as the exposure rule", "TF", TREND_MARKETS),
)
HYPOTHESIS_BY_KEY: Dict[str, Hypothesis] = {h.key: h for h in HYPOTHESES}
HYPOTHESIS_OF_CANDIDATE: Dict[str, str] = {h.candidate: h.key for h in HYPOTHESES}

PREREGISTRATION: Dict[str, Any] = {
    "fixed_on": "2026-11-04, before any run (plan row R16)",
    "question": ("Do the two ideas the replication study (R12) and research round 1 (R13) left as the credible next tests — the volume "
                 "(attention) confirmation on the seven replication markets, and a SLOW own-market trend filter (the close above its "
                 f"{TREND_SMA_DAYS:g}-day moving average) for the breakout rule and for the risk-managed exposure itself — give configurations "
                 "that pass the Sprint 2c gates on the walk-forward and are then confirmed by the untouched 12 months?"),
    "why": ("From the failure analyses. R13: the volume confirmation (H2 there) was confirmed once, on BTC-USDT 4H with the regime gate; it "
            "gained most where the base rule was weakest (the gated 4H rules) and lost on 6H, and the report named 'the attention idea on "
            "R12's markets, pre-registered and fixed a priori, never swept' as the candidate for this round — a test on seven markets the "
            "idea has never seen is the cleanest check of whether that one pass was luck. R12: the breakout family (S2) passed walk-forward "
            "on BTC in Sprint 2c and on ADA, DOGE and TRX, and the untouched 12 months — a bear year — contradicted it on every one of them; "
            "the HMM regime gate (a volatility-regime detector) did not keep it out, and R13's H1 showed a FAST trend condition (BTC's "
            "7/14/30-day momentum vote) changes little. Untested so far is the SLOW trend condition the literature has used since Faber "
            "(2007) — the close above its 200-day moving average — the plain answer to 'buy breakouts only in uptrends' (plan section 2.6: "
            "trend is the one robust family; drawdown control is the problem to solve). R12 and 2c also found hold + policy sizing the "
            "strongest control (beaten by more than 0.1 Calmar on only 4 of 14 series) yet a loser on every market's untouched 12 months; the "
            "Phase 7/8 product candidate is that risk-managed exposure, and the slow trend filter applied to it is the standard remedy for "
            "its bear-year losses and the benchmark that says whether the breakout adds anything to the filter. Not retested, per the R13 "
            "readings: the fast BTC-trend condition for ETH (changed little), dual momentum (churned), and the strictness of the volume "
            "confirmation on BTC/ETH (deferred: it would be a second look at the same months on the same markets with a near-identical rule; "
            "the forward fleet judges the z > 1 version first)."),
    "hypotheses": {
        "H4": {"title": "the volume (attention) confirmation on the replication markets",
               "rule": (f"S1+VC exactly as research round 1 registered it: S1 with Sprint 2c's parameters, grid and brackets, new entries allowed only "
                        f"on bars whose volume z-score over the trailing {VOLUME_Z_DAYS:g} days is above {VOLUME_Z_MIN:g} (the bar's own volume against "
                        "the trailing mean and standard deviation of the bars of that window); entries only, an open position is left to the base "
                        "rule's own exits and stop. The window and the threshold are fixed and never in a grid."),
               "candidates": ["S1+VC"], "markets": list(REPLICATION_MARKETS), "timeframes": list(STUDY_TIMEFRAMES), "regime_modes": list(STUDY_MODES),
               "comparison": "the same S1 configuration on the same market without the condition (the replication study's stored numbers, reproduced in this run)",
               "readings": (f"(a) per configuration, the v1c gates and the holdout rule; (b) a pre-registered directional reading: the attention effect "
                            f"'replicates in direction' when the condition raises Calmar beside S1 in at least k of the n judged configurations, k being "
                            f"the smallest count whose one-sided binomial(n, 1/2) tail is at most {SIGN_TEST_ALPHA:g} (19 of 28 when every configuration "
                            "runs; 14 would be expected by chance) — the configurations share markets across two timeframes and two modes, so this is "
                            f"indicative, not a test of independent trials; (c) the pattern check: round 1's gain was concentrated in the gated 4H "
                            f"configurations, so the same reading is 'consistent with round 1' when the condition raises Calmar in at least {PATTERN_MIN_MARKETS} "
                            "of the 7 markets' 4H [gate] configurations, otherwise 'not consistent'"),
               "why": "one confirmation among 20 comparisons on BTC/ETH; seven markets the idea has never seen are the honest replication"},
        "H5": {"title": "a slow trend filter for the breakout rule",
               "rule": (f"S2+TF: the Donchian breakout rule (S2) exactly as in Sprint 2c — parameters, grid and brackets — with new entries allowed only "
                        f"while the market's close is above its {TREND_SMA_DAYS:g}-day simple moving average ({TREND_SMA_DAYS:g} days in bars of the "
                        "timeframe: 1200 at 4H, 800 at 6H; the average needs that much history, so no entry is possible before it). Entries only: an "
                        "open position is left to the base rule's own exits and stop. The length is fixed and never in a grid."),
               "candidates": ["S2+TF"], "markets": list(TREND_MARKETS), "timeframes": list(STUDY_TIMEFRAMES), "regime_modes": list(STUDY_MODES),
               "comparison": "the same S2 configuration on the same market without the filter (Sprint 2c's stored numbers for BTC/ETH, the replication study's for ADA, DOGE and TRX, reproduced in this run)",
               "readings": ("(a) per configuration, the v1c gates and the holdout rule; (b) the directional reading as for H4 (Calmar beside S2 in at "
                            "least k of n, k at the 5 % tail); (c) for every S2 configuration that passed walk-forward and was contradicted by the "
                            "untouched 12 months in Sprint 2c or the replication study (taken from the stored results), whether S2+TF passes "
                            "walk-forward on that series and, if it does, what its holdout says — shown with the warning that the base rule's holdout "
                            "loss in a bear year is already known and a trend filter is expected to sit that year out, so this comparison carries no "
                            "verdict weight; (d) beside TF alone (H6) on the same series and mode: 'the breakout adds to the filter' where S2+TF's "
                            "Calmar exceeds TF's"),
               "why": "the breakout family's walk-forward passes were contradicted everywhere by a bear year the volatility gate did not detect; the slow trend is the untested regime definition"},
        "H6": {"title": "the slow trend filter as the exposure rule",
               "rule": (f"TF: long while the close is above its {TREND_SMA_DAYS:g}-day simple moving average, flat otherwise (Faber 2007's rule on a 24/7 "
                        "market, evaluated at every bar close); no stop — the rule's exit is the cross back below the average — under the same fixed "
                        "policy sizing, S0 no-trade filter and regime gate as every candidate, and the protocol's exit brackets (none / tp2 / trail1 / "
                        "time30: without a stop the take-profit and trailing brackets are inert, so the walk-forward's only choice is between no bracket "
                        f"and the 30-day time stop). The average's length is the rule's one parameter, fixed at {TREND_SMA_DAYS:g} days and never selected "
                        "(a single grid value), but perturbed by +-30 % (140 and 260 days) by the protocol's robustness replay like every rule's numeric "
                        "parameters. The protocol's selection rule (a bracket variant needs 20 train trades) applies unchanged: a window in which no "
                        "variant reaches 20 trades stays flat, and the report shows how many windows traded."),
               "candidates": ["TF"], "markets": list(TREND_MARKETS), "timeframes": list(STUDY_TIMEFRAMES), "regime_modes": list(STUDY_MODES),
               "comparison": ("hold + policy sizing on the same market and timeframe (the control; its one mode is 'none', so TF [gate] is compared with "
                              "the same control), and S2+TF (H5) on the same series and mode"),
               "readings": ("(a) per configuration, the v1c gates and the holdout rule; (b) Sprint 2c's acceptance-clause statistic: TF 'beats hold + "
                            "policy' on a series when its Calmar exceeds the control's by more than 0.1; (c) the directional reading as for H4, against "
                            "the control's Calmar"),
               "why": "hold + policy is the product candidate and the strongest control, and it lost on every market's untouched 12 months; the slow trend filter is the standard remedy and the benchmark for H5"},
    },
    "protocol": ("Sprint 2c's own runner (scripts/run_research_v1c.py loaded as a module, its run_series), unchanged, with Sprint 2c's defaults: the "
                 "candidates' grids and brackets (none/tp2/trail1/time30), the S0 filter with the FOMC calendar, the fixed policy sizing vt10/30 "
                 "crash15/90dh ladder (rebalance 0.25, ladder re-arm 30 days), the regime-v2 entry gate (3-state HMM, bear >= 0.5, fitted on every "
                 "window's train slice; modes none and gate), the walk-forward (train 540 d, purge 7 d, test 180 d, Sharpe with >= 20 train trades, "
                 "entries then bracket) and the v1c gates — checked against the stored Sprint 2c run before the study runs; the new rules need no "
                 "runner change (they use only the market's own candles)"),
    "data": (f"OKX public 1H and 4H spot candles of the nine markets (4H stored, 6H resampled from 1H), frozen in a study lake at Sprint 2c's data end "
             f"(bar close <= {DATA_END}) so the walk-forward and the untouched 12 months (2025-10-20 -> 2026-10-20) are the same calendar window as in "
             "Sprint 2c, R12 and R13; Binance public funding and open interest for the S0/S5 machinery as before (the new rules do not use them). "
             "The seven replication markets are exactly those the R12 pre-registration fixed (checked against that file); the five trend-filter "
             "markets are the Sprint 2c pair plus the three where the breakout rule was contradicted (ADA, DOGE, TRX)."),
    "reproduction": ("before any new rule is judged, the same code path re-runs hold, S1 and S2 on every market of the round (4H and 6H, modes none "
                     "and gate) and must give the stored walk-forward numbers to 6 decimals, the same trade counts, the same most-selected rules and "
                     "the same gate verdicts — Sprint 2c's for BTC-USDT and ETH-USDT, the replication study's for the seven other markets; "
                     "otherwise the study stops"),
    "gates": "the v1c gates unchanged (research/report_v1c.py GATES): PF > 1.2, max DD < 20 %, Sharpe > 0.7, Calmar > 0.5, >= 75 % of rolling 12-month windows positive, no calendar year below -10 %, >= 30 trades, >= 50 % of +-30 % neighbours profitable",
    "verdicts": ("a configuration passes when it passes every gate on the walk-forward; a hypothesis is 'confirmed' when at least one of its "
                 "configurations passes and is confirmed by its holdout, 'passed walk-forward, contradicted by the holdout' when some pass and none "
                 "is confirmed, and 'failed walk-forward' when none passes; the directional and pattern readings are reported beside the label and "
                 "never replace it; every failing hypothesis gets a failure analysis computed from the numbers beside its comparison line"),
    "holdout": ("the last 12 months (2025-10-20 -> 2026-10-20), opened once, only for a configuration that passes every walk-forward gate, only by "
                "the full pre-registered study (every hypothesis, market, timeframe and mode, with the reproduction, never --quick); the v1c verdict "
                "(positive return, PF > 1, >= 10 trades); every opening goes into an append-only ledger the report shows, and beside every opening "
                "the report names the earlier look at the same months by the configuration's comparison line (Sprint 2c's or the replication "
                "study's stored holdout), because a new rule on a market whose base rule already opened its holdout is a near-second look. CAVEAT, "
                "stated before the run: the holdout's falling direction is known for every market (hold + policy lost on all nine over those months, "
                "R12 and R5b/R9), every condition here reduces time in the market, and a slow trend filter in particular is expected to sit out a "
                "bear year; a confirmation is therefore necessary but not sufficient, and the paper fleet's forward record is the judge"),
    "fleet": ("a confirmed configuration is appended to the paper fleet's shortlist as a new account with a source tag (existing entries and running "
              "accounts untouched; a walk-forward pass alone adds nothing); the fleet must be able to load the amended shortlist, otherwise the file "
              "is restored and the report says so (the R12 rule); S1+VC on a replication market needs only that market's public candles, which the "
              "fleet already fetches; TF and S2+TF are registered candidates that use the market's own candles"),
    "no_changes_after_results": "no gate, parameter, condition, market, threshold or verdict rule changes after the results are in; if a gate looks wrong the report says so",
}


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# -- configuration ----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Round2Config:
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
        """(candidate, market) pairs of the requested hypotheses, in pre-registered order."""
        return [pair for h in HYPOTHESES if h.key in self.hypotheses for pair in h.candidates]

    @property
    def markets(self) -> List[str]:
        """The markets the requested hypotheses run on, in the round's fixed order."""
        wanted = {m for h in HYPOTHESES if h.key in self.hypotheses for m in h.markets}
        return [m for m in ALL_MARKETS if m in wanted]


def preregistration_hash(cfg: Round2Config, prereg: Mapping[str, Any]) -> str:
    """One hash over the fixed text, the pre-registration file and the configuration."""
    return _sha256_json({"preregistration": PREREGISTRATION, "file": prereg, "config": cfg.to_dict()})


def full_study_requested(cfg: Round2Config) -> bool:
    """The holdout may only be opened by the complete pre-registered study."""
    return (not cfg.quick and cfg.reproduction and sorted(cfg.hypotheses) == sorted(h.key for h in HYPOTHESES)
            and sorted(cfg.regime_modes) == sorted(STUDY_MODES) and sorted(cfg.timeframes) == sorted(STUDY_TIMEFRAMES))


# -- the pre-registration file: written once, before the first run ----------------------------------------

def check_replication_markets(path: Path = R12_PREREGISTRATION) -> List[str]:
    """The replication study's fixed market list must be the one this round uses (the R12 file is the authority)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    chosen = list(data.get("chosen") or [])
    if sorted(chosen) != sorted(REPLICATION_MARKETS):
        raise Round2Error(f"the replication markets of this round {list(REPLICATION_MARKETS)} differ from the R12 pre-registration {chosen}")
    return chosen


def preregister(path: Path, *, now: Optional[datetime] = None, force: bool = False, r12_path: Path = R12_PREREGISTRATION) -> Dict[str, Any]:
    """Write the fixed text (and the full-study configuration) with a hash; refuse a second write unless forced."""
    path = Path(path)
    if path.exists() and not force:
        raise Round2Error(f"{path} exists: the hypotheses were already fixed; a second write would be a second registration")
    check_replication_markets(r12_path)
    written_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    payload: Dict[str, Any] = {
        "note": "Plan row R16. The hypotheses, rules, parameters, markets, timeframes, gates and verdict rules of research round 2, fixed BEFORE the first run. Never edited.",
        "written_at": written_at, "data_end": DATA_END, "gates": dict(GATES),
        "replication_markets": list(REPLICATION_MARKETS), "trend_markets": list(TREND_MARKETS),
        "configuration": Round2Config().to_dict(), "preregistration": PREREGISTRATION,
    }
    payload["sha256"] = _sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return payload


def load_preregistration(path: Path = PREREGISTRATION_PATH) -> Dict[str, Any]:
    """The pre-registration file, checked: its hash, and that its text is the text in this module (neither may change after)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("preregistration"), dict):
        raise Round2Error(f"{path} is not a pre-registration file")
    expected = _sha256_json({k: v for k, v in data.items() if k != "sha256"})
    if data.get("sha256") != expected:
        raise Round2Error(f"{path} was edited after it was written (hash mismatch)")
    if data["preregistration"] != PREREGISTRATION:
        raise Round2Error("the pre-registration text in research/round2.py differs from the registered file; neither may change after registration")
    if data.get("gates") != dict(GATES):
        raise Round2Error("the gates differ from the registered ones")
    if list(data.get("replication_markets") or []) != list(REPLICATION_MARKETS) or list(data.get("trend_markets") or []) != list(TREND_MARKETS):
        raise Round2Error("the markets differ from the registered ones")
    return data


# -- the Sprint 2c runner, unchanged ---------------------------------------------------------------------------

def runner():
    """The Sprint 2c runner module (no patch: round 2's rules use only the market's own candles)."""
    return load_v1c_runner()


def round2_args(cfg: Round2Config, strategies: Sequence[str], *, evaluate_holdout: bool) -> Dict[str, Any]:
    """Sprint 2c's own command-line defaults, narrowed to the given strategies, the study's modes and timeframes."""
    v1c = runner()
    argv: List[str] = ["--strategies", *strategies, "--regime-modes", *cfg.regime_modes, "--timeframes", *cfg.timeframes]
    if cfg.quick:
        argv.append("--quick")
    if evaluate_holdout:
        argv.append("--evaluate-holdout")
    if cfg.lake_dir:
        argv += ["--lake-dir", cfg.lake_dir]
    return dict(vars(v1c.parse_args(argv)))


def protocol_check_round2(args: Mapping[str, Any], meta: Mapping[str, Any]) -> Dict[str, Any]:
    """The replication study's protocol check, with the round-2 candidates (new by design) set aside and listed."""
    stored = set(meta.get("strategies") or [])
    narrowed = dict(args, strategies=[s for s in args["strategies"] if s in stored])
    check = protocol_check(narrowed, meta)
    check["new_candidates"] = [s for s in args["strategies"] if s not in stored]
    check["note"] = "the round-2 candidates are new rules and are not in the stored Sprint 2c run by design; every protocol parameter is checked"
    return check


# -- the stored results the round reproduces and compares with ---------------------------------------------------

def stored_results(v1c_doc: Mapping[str, Any], r12_doc: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Sprint 2c's flat results plus the replication study's per-series results, each tagged with the study it comes from."""
    out: List[Dict[str, Any]] = []
    for r in v1c_doc.get("results") or []:
        out.append(dict(r, study_source="Sprint 2c"))
    for s in r12_doc.get("series") or []:
        for r in s.get("results") or []:
            out.append(dict(r, study_source="R12 replication"))
    return out


# -- jobs: one (market, timeframe, strategy group) per process ---------------------------------------------------

SERIES_KEYS = ("instrument", "timeframe", "results", "failures", "benchmark", "span", "holdout_span", "positioning", "s0_blocked_share", "skipped")


def plan_jobs(cfg: Round2Config, *, evaluate_holdout: bool) -> List[Dict[str, Any]]:
    """The reproduction job (hold, S1, S2) per series, then one job per new candidate and series."""
    jobs: List[Dict[str, Any]] = []
    for tf in cfg.timeframes:
        for inst in cfg.markets:
            if cfg.reproduction:
                jobs.append({"cfg": cfg.to_dict(), "kind": "reproduction", "instrument": inst, "timeframe": tf,
                             "strategies": list(REPRODUCTION_STRATEGIES), "evaluate_holdout": bool(evaluate_holdout)})
            for cand, cand_inst in cfg.new_candidates:
                if cand_inst == inst:
                    jobs.append({"cfg": cfg.to_dict(), "kind": HYPOTHESIS_OF_CANDIDATE[cand], "instrument": inst, "timeframe": tf,
                                 "strategies": [cand], "evaluate_holdout": bool(evaluate_holdout)})
    return jobs


def run_job(job: Mapping[str, Any]) -> Dict[str, Any]:
    """Process-pool entry point: Sprint 2c's ``run_series`` for one strategy group on one series."""
    cfg = Round2Config(**job["cfg"])
    v1c = runner()
    args = round2_args(cfg, job["strategies"], evaluate_holdout=bool(job["evaluate_holdout"]))
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


def _mode(r: Mapping[str, Any]) -> Optional[str]:
    return (r.get("regime") or {}).get("mode")


def _metrics_of(r: Mapping[str, Any]) -> Dict[str, Any]:
    oos = r.get("oos") or {}
    acc = r.get("acceptance") or {}
    return {"cagr": oos.get("cagr"), "sharpe": oos.get("sharpe"), "max_drawdown": oos.get("max_drawdown"), "calmar": oos.get("calmar"),
            "profit_factor": oos.get("profit_factor"), "n_trades": oos.get("n_trades"), "trades_per_year": oos.get("trades_per_year"),
            "total_return": oos.get("total_return"), "exposure": oos.get("exposure"), "avg_allocation": oos.get("avg_allocation"),
            "fees_pct_per_year": oos.get("fees_pct_per_year"), "win_rate": oos.get("win_rate"),
            "windows": oos.get("windows"), "windows_traded": oos.get("windows_traded"),
            "rolling_12m_positive_share": acc.get("rolling_positive_share"), "worst_calendar_year_return": acc.get("worst_calendar_year_return"),
            "yearly": {str(k): v for k, v in (r.get("yearly") or {}).items()},
            "passed": bool(acc.get("passed")), "failed": list(acc.get("failed") or [])}


def _delta(a: Any, b: Any) -> Optional[float]:
    x, y = _num(a), _num(b)
    return None if (math.isnan(x) or math.isnan(y)) else x - y


def configuration_name(candidate: str, instrument: str, timeframe: str, mode: Optional[str]) -> str:
    return f"{candidate} {instrument} {timeframe} [{mode}]"


def compare_with_base(r: Mapping[str, Any], base: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The new configuration beside its comparison line: levels and deltas."""
    if base is None:
        return {"available": False}
    m, b = _metrics_of(r), _metrics_of(base)
    years = sorted(set(m["yearly"]) | set(b["yearly"]))
    yearly = {y: {"variant": m["yearly"].get(y), "base": b["yearly"].get(y), "delta": _delta(m["yearly"].get(y), b["yearly"].get(y))} for y in years}
    n_var, n_base = _num(m["n_trades"]), _num(b["n_trades"])
    return {
        "available": True, "base_candidate": base["candidate"],
        "base_configuration": configuration_name(base["candidate"], base["instrument"], base["timeframe"], _mode(base)),
        "base_study": base.get("study_source", "this run"),
        "variant": m, "base": b,
        "delta": {k: _delta(m[k], b[k]) for k in ("calmar", "cagr", "sharpe", "max_drawdown", "profit_factor", "n_trades", "trades_per_year",
                                                   "avg_allocation", "exposure", "fees_pct_per_year", "rolling_12m_positive_share", "worst_calendar_year_return")},
        "trades_removed_share": None if (math.isnan(n_var) or math.isnan(n_base) or n_base <= 0) else max(0.0, 1.0 - n_var / n_base),
        "beats_base_by_0_1": bool(_num(m["calmar"], -9.0) > _num(b["calmar"], -9.0) + 0.1),
        "yearly": yearly, "base_passed": b["passed"],
    }


def annotate_result(r: Dict[str, Any], base: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    cand = r["candidate"]
    r["hypothesis"] = HYPOTHESIS_OF_CANDIDATE.get(cand)
    r["base_candidate"] = ROUND2_BASES.get(cand) if r["hypothesis"] else None
    r["configuration"] = configuration_name(cand, r["instrument"], r["timeframe"], _mode(r))
    r["role"] = "control" if cand == CONTROL else ("reproduction" if cand in REPRODUCTION_STRATEGIES else "configuration")
    r["judged"] = r["role"] == "configuration"
    r["fixed_rule"] = cand in FIXED_RULES
    r["holdout_confirmed"] = holdout_verdict(r) if r.get("holdout") else None
    r["comparison"] = compare_with_base(r, base) if r["hypothesis"] else {"available": False}
    return r


def _find(results: Sequence[Mapping[str, Any]], candidate: str, instrument: str, timeframe: str, mode: Optional[str]) -> Optional[Mapping[str, Any]]:
    for r in results:
        if r["candidate"] == candidate and r["instrument"] == instrument and r["timeframe"] == timeframe and _mode(r) == mode:
            return r
    return None


def base_mode(candidate: str, mode: Optional[str]) -> Optional[str]:
    """The comparison line's regime mode: the control has one mode ('none'); every other base runs the same mode as the new rule."""
    return "none" if ROUND2_BASES.get(candidate) == CONTROL else mode


def find_base(r: Mapping[str, Any], all_results: Sequence[Mapping[str, Any]], stored: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    """The comparison line of a round-2 result: from this run's reproduction first, else the stored studies."""
    base_key = ROUND2_BASES.get(r["candidate"])
    if not base_key:
        return None
    mode = base_mode(r["candidate"], _mode(r))
    return _find(all_results, base_key, r["instrument"], r["timeframe"], mode) or _find(stored, base_key, r["instrument"], r["timeframe"], mode)


def annotate_all(merged: Mapping[Tuple[str, str], Dict[str, Any]], stored: Sequence[Mapping[str, Any]]) -> None:
    """Every result gets its hypothesis, role and the comparison with its base rule (from this run's reproduction, else the stored studies)."""
    all_results = [r for s in merged.values() for r in (s.get("results") or [])]
    for s in merged.values():
        for r in s.get("results") or []:
            annotate_result(r, find_base(r, all_results, stored) if r["candidate"] in HYPOTHESIS_OF_CANDIDATE else None)


# -- the directional reading: a one-sided sign test ----------------------------------------------------------------

def binomial_tail(k: int, n: int) -> float:
    """P(X >= k) for X ~ binomial(n, 1/2)."""
    if n <= 0:
        return 1.0
    k = max(0, min(int(k), n + 1))
    return sum(math.comb(n, j) for j in range(k, n + 1)) / float(2 ** n)


def sign_threshold(n: int, alpha: float = SIGN_TEST_ALPHA) -> Optional[int]:
    """The smallest k with P(X >= k) <= alpha under binomial(n, 1/2); None when even k = n is not enough (n < 5 at 5 %)."""
    for k in range(0, n + 1):
        if binomial_tail(k, n) <= alpha:
            return k
    return None


def directional_reading(rows: Sequence[Mapping[str, Any]], *, alpha: float = SIGN_TEST_ALPHA) -> Dict[str, Any]:
    """How many judged configurations raised Calmar beside their comparison line, against the pre-registered 5 % sign-test threshold."""
    comps = [r["comparison"] for r in rows if (r.get("comparison") or {}).get("available")]
    n = len(comps)
    improved = sum(1 for c in comps if _num(c["delta"].get("calmar"), 0.0) > 0.0)
    threshold = sign_threshold(n, alpha)
    return {"n": n, "improved": improved, "threshold": threshold, "alpha": alpha, "p_value": binomial_tail(improved, n) if n else None,
            "expected_by_chance": n / 2.0, "replicates_in_direction": bool(threshold is not None and improved >= threshold),
            "configurations_improved": [r["configuration"] for r in rows if (r.get("comparison") or {}).get("available")
                                        and _num(r["comparison"]["delta"].get("calmar"), 0.0) > 0.0]}


def pattern_check(rows: Sequence[Mapping[str, Any]], *, timeframe: str = "4H", mode: str = "gate", min_markets: int = PATTERN_MIN_MARKETS) -> Dict[str, Any]:
    """H4: does round 1's pattern (the gain concentrated in the gated 4H configurations) hold on the replication markets?"""
    sub = [r for r in rows if r["timeframe"] == timeframe and _mode(r) == mode and (r.get("comparison") or {}).get("available")]
    improved = [r["instrument"] for r in sub if _num(r["comparison"]["delta"].get("calmar"), 0.0) > 0.0]
    return {"timeframe": timeframe, "mode": mode, "n": len(sub), "improved": len(improved), "markets_improved": improved, "min_markets": min_markets,
            "consistent_with_round_1": bool(len(sub) > 0 and len(improved) >= min_markets)}


# -- H5: the contradicted breakout configurations; H5/H6: the breakout beside the filter alone --------------------

def contradicted_base_configurations(stored: Sequence[Mapping[str, Any]], candidate: str, markets: Sequence[str],
                                     timeframes: Sequence[str] = STUDY_TIMEFRAMES, modes: Sequence[str] = STUDY_MODES) -> List[Dict[str, Any]]:
    """The stored configurations of ``candidate`` that passed walk-forward and whose holdout did not confirm them (contradicted or too few trades)."""
    out: List[Dict[str, Any]] = []
    for r in stored:
        if (r["candidate"] == candidate and r["instrument"] in markets and r["timeframe"] in timeframes and _mode(r) in modes
                and (r.get("acceptance") or {}).get("passed") and r.get("holdout") and holdout_verdict(r) is False):
            h = r["holdout"]
            out.append({"configuration": configuration_name(candidate, r["instrument"], r["timeframe"], _mode(r)), "instrument": r["instrument"],
                        "timeframe": r["timeframe"], "mode": _mode(r), "study": r.get("study_source", "stored"),
                        "holdout": {k: h.get(k) for k in ("total_return", "max_drawdown", "profit_factor", "n_trades")}, "calmar": (r.get("oos") or {}).get("calmar")})
    out.sort(key=lambda x: (x["instrument"], x["timeframe"], x["mode"]))
    return out


def contradicted_outcomes(merged: Mapping[Tuple[str, str], Mapping[str, Any]], stored: Sequence[Mapping[str, Any]], *, candidate: str = "S2+TF") -> List[Dict[str, Any]]:
    """For every contradicted base configuration: what the filtered rule did on that series (walk-forward verdict; holdout only if opened)."""
    all_results = [r for s in merged.values() for r in (s.get("results") or [])]
    base_key = ROUND2_BASES[candidate]
    markets = HYPOTHESIS_BY_KEY[HYPOTHESIS_OF_CANDIDATE[candidate]].markets
    out: List[Dict[str, Any]] = []
    for c in contradicted_base_configurations(stored, base_key, markets):
        r = _find(all_results, candidate, c["instrument"], c["timeframe"], c["mode"])
        entry = dict(c, filtered_configuration=configuration_name(candidate, c["instrument"], c["timeframe"], c["mode"]), ran=r is not None)
        if r is not None:
            entry.update({"filtered_passed": bool((r.get("acceptance") or {}).get("passed")), "filtered_failed_gates": list((r.get("acceptance") or {}).get("failed") or []),
                          "filtered_calmar": (r.get("oos") or {}).get("calmar"), "filtered_n_trades": (r.get("oos") or {}).get("n_trades"),
                          "filtered_holdout": r.get("holdout"), "filtered_holdout_confirmed": r.get("holdout_confirmed")})
        out.append(entry)
    return out


def exposure_comparisons(merged: Mapping[Tuple[str, str], Mapping[str, Any]], stored: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """H6 beside the control and beside H5: per TF configuration, hold + policy's numbers, 'beats hold by 0.1 Calmar', and S2+TF on the same series/mode."""
    all_results = [r for s in merged.values() for r in (s.get("results") or [])]
    out: List[Dict[str, Any]] = []
    for r in all_results:
        if r["candidate"] != "TF":
            continue
        hold = find_base(r, all_results, stored)
        s2tf = _find(all_results, "S2+TF", r["instrument"], r["timeframe"], _mode(r))
        s2 = _find(all_results, "S2", r["instrument"], r["timeframe"], _mode(r)) or _find(stored, "S2", r["instrument"], r["timeframe"], _mode(r))
        tf_calmar = _num((r.get("oos") or {}).get("calmar"), -9.0)
        out.append({
            "configuration": r["configuration"], "instrument": r["instrument"], "timeframe": r["timeframe"], "mode": _mode(r),
            "tf": _metrics_of(r), "hold": None if hold is None else _metrics_of(hold),
            "beats_hold": None if hold is None else bool(tf_calmar > _num((hold.get("oos") or {}).get("calmar"), -9.0) + 0.1),
            "s2tf": None if s2tf is None else _metrics_of(s2tf), "s2": None if s2 is None else _metrics_of(s2),
            "breakout_adds": None if s2tf is None else bool(_num((s2tf.get("oos") or {}).get("calmar"), -9.0) > tf_calmar),
        })
    out.sort(key=lambda x: (x["instrument"], x["timeframe"], x["mode"]))
    return out


# -- verdicts (pre-registered) ---------------------------------------------------------------------------------

def judged_results(merged: Mapping[Tuple[str, str], Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    return [r for s in merged.values() for r in (s.get("results") or []) if r.get("judged")]


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
    """The numbers a failure analysis is written from: the condition's (or rule's) effect beside its comparison line."""
    facts: Dict[str, Any] = {"n": len(rows), "base_candidate": h.base}
    comps = [r["comparison"] for r in rows if (r.get("comparison") or {}).get("available")]
    facts["n_compared"] = len(comps)
    windows = [(_num((r.get("oos") or {}).get("windows_traded")), _num((r.get("oos") or {}).get("windows"))) for r in rows]
    facts["windows_traded_total"] = int(sum(w for w, _ in windows if not math.isnan(w)))
    facts["windows_total"] = int(sum(n for _, n in windows if not math.isnan(n)))
    facts["median_n_trades"] = _median([(r.get("oos") or {}).get("n_trades") for r in rows])
    facts["per_market_improved"] = {}
    if not comps:
        return facts
    d = lambda k: [c["delta"].get(k) for c in comps]  # noqa: E731
    facts.update({
        "calmar_improved": sum(1 for c in comps if _num(c["delta"].get("calmar"), 0.0) > 0.0),
        "sharpe_improved": sum(1 for c in comps if _num(c["delta"].get("sharpe"), 0.0) > 0.0),
        "drawdown_fell": sum(1 for c in comps if _num(c["delta"].get("max_drawdown"), 0.0) < 0.0),
        "return_fell": sum(1 for c in comps if _num(c["delta"].get("cagr"), 0.0) < 0.0),
        "rolling_improved": sum(1 for c in comps if _num(c["delta"].get("rolling_12m_positive_share"), 0.0) > 0.0),
        "beats_base_by_0_1": sum(1 for c in comps if c.get("beats_base_by_0_1")),
        "median_delta_calmar": _median(d("calmar")), "median_delta_cagr": _median(d("cagr")), "median_delta_sharpe": _median(d("sharpe")),
        "median_delta_max_drawdown": _median(d("max_drawdown")), "median_delta_rolling": _median(d("rolling_12m_positive_share")),
        "median_delta_fees": _median(d("fees_pct_per_year")),
        "median_trades_removed_share": _median([c["trades_removed_share"] for c in comps]),
        "median_delta_exposure": _median(d("exposure")),
        "median_variant_calmar": _median([c["variant"]["calmar"] for c in comps]), "median_base_calmar": _median([c["base"]["calmar"] for c in comps]),
        "median_variant_cagr": _median([c["variant"]["cagr"] for c in comps]), "median_base_cagr": _median([c["base"]["cagr"] for c in comps]),
        "median_variant_dd": _median([c["variant"]["max_drawdown"] for c in comps]), "median_base_dd": _median([c["base"]["max_drawdown"] for c in comps]),
        "median_variant_trades": _median([c["variant"]["n_trades"] for c in comps]), "median_base_trades": _median([c["base"]["n_trades"] for c in comps]),
        "median_variant_exposure": _median([c["variant"]["exposure"] for c in comps]), "median_base_exposure": _median([c["base"]["exposure"] for c in comps]),
        "median_variant_rolling": _median([c["variant"]["rolling_12m_positive_share"] for c in comps]),
        "median_base_rolling": _median([c["base"]["rolling_12m_positive_share"] for c in comps]),
        "median_2022_variant": _median([c["yearly"].get("2022", {}).get("variant") for c in comps]),
        "median_2022_base": _median([c["yearly"].get("2022", {}).get("base") for c in comps]),
        "base_passed_any": any(c.get("base_passed") for c in comps),
        "by_mode": {mode: {"calmar_improved": sum(1 for r in rows if _mode(r) == mode and _num((r.get("comparison") or {}).get("delta", {}).get("calmar"), 0.0) > 0.0),
                           "n": sum(1 for r in rows if _mode(r) == mode)} for mode in sorted({_mode(r) for r in rows if _mode(r)})},
        "by_timeframe": {tf: {"calmar_improved": sum(1 for r in rows if r["timeframe"] == tf and _num((r.get("comparison") or {}).get("delta", {}).get("calmar"), 0.0) > 0.0),
                              "n": sum(1 for r in rows if r["timeframe"] == tf)} for tf in sorted({r["timeframe"] for r in rows})},
    })
    per_market: Dict[str, Dict[str, int]] = {}
    for r in rows:
        c = r.get("comparison") or {}
        if not c.get("available"):
            continue
        e = per_market.setdefault(r["instrument"], {"calmar_improved": 0, "n": 0})
        e["n"] += 1
        e["calmar_improved"] += int(_num(c["delta"].get("calmar"), 0.0) > 0.0)
    facts["per_market_improved"] = per_market
    return facts


def hypothesis_verdicts(merged: Mapping[Tuple[str, str], Mapping[str, Any]], cfg: Round2Config, stored: Sequence[Mapping[str, Any]] = ()) -> List[Dict[str, Any]]:
    """Per hypothesis: its judged configurations, how many pass, the holdout outcome, the pre-registered label, the readings, the failure facts."""
    out: List[Dict[str, Any]] = []
    for h in HYPOTHESES:
        if h.key not in cfg.hypotheses:
            continue
        rows = [r for r in judged_results(merged) if r.get("hypothesis") == h.key]
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
        verdict: Dict[str, Any] = {
            "hypothesis": h.key, "title": h.title, "candidate": h.candidate, "base_candidate": h.base, "markets": list(h.markets), "label": label,
            "n_configurations": len(rows), "n_passed": len(passed), "n_confirmed": len(confirmed), "n_contradicted": len(contradicted),
            "n_unevaluated": len(unevaluated),
            "configurations": [r["configuration"] for r in rows], "passed": [r["configuration"] for r in passed],
            "confirmed": [r["configuration"] for r in confirmed], "contradicted": [r["configuration"] for r in contradicted],
            "binding_gates": sorted(counts.items(), key=lambda kv: -kv[1]),
            "best": _best(rows), "failure_facts": failure_facts(h, rows), "directional": directional_reading(rows),
        }
        if h.key == "H4":
            verdict["pattern"] = pattern_check(rows)
        if h.key == "H5":
            verdict["contradicted_outcomes"] = contradicted_outcomes(merged, stored, candidate=h.candidate)
        if h.key == "H6":
            verdict["exposure"] = exposure_comparisons(merged, stored)
        out.append(verdict)
    return out


def overall_summary(verdicts: Sequence[Mapping[str, Any]], merged: Mapping[Tuple[str, str], Mapping[str, Any]]) -> Dict[str, Any]:
    rows = judged_results(merged)
    passed = [r for r in rows if (r.get("acceptance") or {}).get("passed")]
    counts: Dict[str, int] = {}
    for r in rows:
        for g in (r.get("acceptance") or {}).get("failed", []):
            counts[g] = counts.get(g, 0) + 1
    return {"n_judged": len(rows), "n_passed": len(passed), "n_confirmed": sum(1 for r in passed if r.get("holdout_confirmed") is True),
            "n_contradicted": sum(1 for r in passed if r.get("holdout_confirmed") is False),
            "n_unevaluated": sum(1 for r in passed if r.get("holdout_confirmed") is None),
            "labels": {v["hypothesis"]: v["label"] for v in verdicts}, "binding_gates": sorted(counts.items(), key=lambda kv: -kv[1]),
            "directional": {v["hypothesis"]: v.get("directional") for v in verdicts},
            "passed": [{"configuration": r["configuration"], "calmar": (r.get("oos") or {}).get("calmar"), "holdout_confirmed": r.get("holdout_confirmed")} for r in passed]}


# -- the holdout ledger and the earlier looks ----------------------------------------------------------------------

LEDGER_NOTE = ("Every opening of the untouched 12 months by research round 2 (plan row R16), in order; entries are appended, never edited. "
               "The report shows all of them, each beside the earlier look at the same months by its comparison line. The hold + policy control's "
               "12 months are a comparison line, not a configuration under test.")


def _canon(params: Any) -> Any:
    if isinstance(params, dict):
        return {k: _canon(v) for k, v in params.items()}
    if isinstance(params, tuple):
        return list(params)
    return params


def holdout_openings(merged: Mapping[Tuple[str, str], Mapping[str, Any]]) -> List[Dict[str, Any]]:
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
    return out


def earlier_looks(merged: Mapping[Tuple[str, str], Mapping[str, Any]], stored: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """For every new configuration whose holdout this run opened: the stored holdout of its comparison line on the same series (a near-second look)."""
    out: List[Dict[str, Any]] = []
    for s in merged.values():
        for r in s.get("results") or []:
            if not r.get("holdout") or r.get("role") != "configuration":
                continue
            base_key = ROUND2_BASES.get(r["candidate"])
            mode = base_mode(r["candidate"], _mode(r))
            base = _find(stored, base_key, r["instrument"], r["timeframe"], mode) if base_key else None
            entry: Dict[str, Any] = {"configuration": r["configuration"], "earlier_configuration": None if base is None else
                                     configuration_name(base_key, r["instrument"], r["timeframe"], mode), "earlier_study": None if base is None else base.get("study_source")}
            if base is not None and base.get("holdout"):
                h = base["holdout"]
                entry.update({"earlier_opened": True, "earlier_total_return": h.get("total_return"), "earlier_profit_factor": h.get("profit_factor"),
                              "earlier_n_trades": h.get("n_trades"), "earlier_confirmed": None if base_key == CONTROL else holdout_verdict(base)})
            else:
                entry["earlier_opened"] = False
            out.append(entry)
    return out


def guard_second_look(ledger: Sequence[Mapping[str, Any]], openings: Sequence[Mapping[str, Any]], *, evaluate_holdout: bool) -> List[str]:
    if not evaluate_holdout:
        return []
    seen = {o["configuration"] for e in ledger for o in e.get("openings", []) if o.get("role") != "control"}
    return sorted(o["configuration"] for o in openings if o["role"] != "control" and o["configuration"] in seen)


def write_round2_ledger(path: str, entries: List[Dict[str, Any]]) -> None:
    Path(path).write_text(json.dumps({"note": LEDGER_NOTE, "entries": entries}, indent=1) + "\n", encoding="utf-8")


# -- the paper-fleet shortlist ------------------------------------------------------------------------------------

def shortlist_additions(merged: Mapping[Tuple[str, str], Mapping[str, Any]], *, source: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Confirmed passers as shortlist rows with a ``source`` tag naming the study and the hypothesis."""
    rows: List[Dict[str, Any]] = []
    for s in merged.values():
        for r in s.get("results") or []:
            if r.get("judged") and (r.get("acceptance") or {}).get("passed") and r.get("holdout_confirmed") is True:
                row = _row(r)
                row["source"] = dict(source, hypothesis=r.get("hypothesis"))
                rows.append(row)
    rows.sort(key=lambda x: (-_num(x.get("calmar"), -9.0), -_num(x.get("sharpe"), -9.0)))
    return rows
