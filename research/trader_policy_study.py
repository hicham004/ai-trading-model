"""The Trader Policy v1 study (plan row R18, ``docs/TRADER_PLAN_2026-11-05.md`` sections 4 and 9), SIMULATION ONLY.

The five confirmed configurations and the controls are re-judged at the three
fixed risk budgets of :mod:`research.trader_policy` (plus ``risk1.5`` for
information and the comparison ladders), with the section 4.3 brakes on and
off and each section 4.2 variant on alone, under the Sprint 2c walk-forward
run by ``scripts/run_research_v1c.py``'s own ``run_series`` (loaded as a module,
as the replication study, round 1 and round 2 did) and the section 4.6 gates.
Everything that defines the answer is fixed in :data:`PREREGISTRATION` before
the first run and hashed into the results.

The tier is a policy overlay: the per-window selection of the rule variants
(train Sharpe at full size, 20 train trades) never sees it, so every
configuration keeps the ATR multiple and the exit bracket its walk-forward
selected. Before any tier is judged, the Reference cell of every configuration
and control must reproduce the stored numbers (Sprint 2c's, the replication
study's, round 1's and round 2's) to 6 decimals; otherwise the study stops.

The protocol check is recorded honestly for every cell: a tier differs from the
stored Sprint 2c protocol in its ``policy_sizing`` (and in its brakes and
variant), and the results say so; the paper fleet's loader (plan row R18b) may
accept a row only when the differences are exactly a documented tier.

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
from research.replication import DATA_END, load_ledger, load_v1c_runner, protocol_check, reproduction_check  # noqa: F401
from research.report_v1c import GATES, _row, holdout_verdict
from research.trader_policy import (
    ALL_TIERS,
    DEFAULT_TIER,
    PAYOFF_MIN,
    TIER_GATES,
    TIERS,
    VARIANTS,
    PolicyTier,
    brake_cost,
    exposure_ratio,
    tier,
    variant_counts,
)

ROOT = Path(__file__).resolve().parents[1]
V1C_RESULTS = ROOT / "docs" / "research" / "ensemble_v1c_results.json"
R12_RESULTS = ROOT / "docs" / "research" / "replication_v1d_results.json"
R13_RESULTS = ROOT / "docs" / "research" / "research_round_1_results.json"
R16_RESULTS = ROOT / "docs" / "research" / "research_round_2_results.json"
PREREGISTRATION_PATH = ROOT / "docs" / "research" / "trader_policy_v1_preregistration.json"
STUDY_LAKE_DIRNAME = "lake_trader_policy_v1"
STUDY_NAME = "R18 Trader Policy v1"
CONTROL = "hold"
TF_CONTROL = "TF"
#: Per-side costs of the fixed replays (section 4.2: the engine's 0.30 % a round trip for the gates; 0.20 % measured for BTC/ETH;
#: 0.50 % for altcoins, +10 bps a side).
COST_SCENARIOS: Mapping[str, Tuple[float, float]] = {"measured_btc_eth": (0.0005, 0.0005), "altcoin": (0.0010, 0.0015)}
HOLDOUT_TIERS: Tuple[str, ...] = ("trader", "aggressive")  # the tiers whose brakes-on cell may open the holdout (the fleet-candidate form)
FLEET_TIER = DEFAULT_TIER  # the owner's decision of 2026-11-05: the Trader tier joins the fleet
TF_CONTROL_TIMEFRAMES: Tuple[str, ...] = ("6H",)  # the forward control's fleet rows (4H is reported, not proposed)


class TraderPolicyError(RuntimeError):
    """The study cannot be trusted (protocol mismatch beyond the tier, reproduction failure, a tampered pre-registration)."""


# -- the configurations and controls -----------------------------------------------------------------------

@dataclass(frozen=True)
class Configuration:
    key: str
    candidate: str
    instrument: str
    timeframe: str
    mode: str
    role: str  # "configuration" | "control" | "tf_control"
    source_study: str  # where the stored numbers come from (reproduction)
    source_results: str  # repository-relative path of that study's results file

    @property
    def name(self) -> str:
        return f"{self.candidate} {self.instrument} {self.timeframe} [{self.mode}]"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


CONFIGURATIONS: Tuple[Configuration, ...] = (
    Configuration("C1", "S1+S5", "BTC-USDT", "6H", "none", "configuration", "Sprint 2c", "docs/research/ensemble_v1c_results.json"),
    Configuration("C2", "S1", "SOL-USDT", "6H", "none", "configuration", "R12 replication", "docs/research/replication_v1d_results.json"),
    Configuration("C3", "S1+S5", "SOL-USDT", "6H", "none", "configuration", "R12 replication", "docs/research/replication_v1d_results.json"),
    Configuration("C4", "S1+VC", "BTC-USDT", "4H", "gate", "configuration", "R13 research round 1", "docs/research/research_round_1_results.json"),
    Configuration("C5", "S1+VC", "DOGE-USDT", "4H", "gate", "configuration", "R16 research round 2", "docs/research/research_round_2_results.json"),
)
CONTROLS: Tuple[Configuration, ...] = (
    Configuration("H1", CONTROL, "BTC-USDT", "4H", "none", "control", "Sprint 2c", "docs/research/ensemble_v1c_results.json"),
    Configuration("H2", CONTROL, "BTC-USDT", "6H", "none", "control", "Sprint 2c", "docs/research/ensemble_v1c_results.json"),
    Configuration("H3", CONTROL, "ETH-USDT", "4H", "none", "control", "Sprint 2c", "docs/research/ensemble_v1c_results.json"),
    Configuration("H4", CONTROL, "ETH-USDT", "6H", "none", "control", "Sprint 2c", "docs/research/ensemble_v1c_results.json"),
    Configuration("H5", CONTROL, "SOL-USDT", "6H", "none", "control", "R12 replication", "docs/research/replication_v1d_results.json"),
    Configuration("H6", CONTROL, "DOGE-USDT", "4H", "none", "control", "R12 replication", "docs/research/replication_v1d_results.json"),
)
TF_CONTROLS: Tuple[Configuration, ...] = (
    Configuration("T1", TF_CONTROL, "BTC-USDT", "4H", "none", "tf_control", "none (new forward control)", ""),
    Configuration("T2", TF_CONTROL, "BTC-USDT", "6H", "none", "tf_control", "none (new forward control)", ""),
    Configuration("T3", TF_CONTROL, "ETH-USDT", "4H", "none", "tf_control", "none (new forward control)", ""),
    Configuration("T4", TF_CONTROL, "ETH-USDT", "6H", "none", "tf_control", "none (new forward control)", ""),
)
ALL_RUNS: Tuple[Configuration, ...] = CONFIGURATIONS + CONTROLS + TF_CONTROLS
BY_KEY: Dict[str, Configuration] = {c.key: c for c in ALL_RUNS}
MARKETS: Tuple[str, ...] = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT")
TIMEFRAMES: Tuple[str, ...] = ("4H", "6H")


# -- the cells: tier x brakes x variant ----------------------------------------------------------------------

@dataclass(frozen=True)
class Cell:
    tier: str
    brakes: bool
    variant: str = "none"

    @property
    def key(self) -> str:
        return f"{self.tier}|{'brakes' if self.brakes else 'nobrakes'}|{self.variant}"

    @property
    def label(self) -> str:
        t = tier(self.tier)
        parts = [t.label, "brakes on" if self.brakes else "brakes off"]
        if self.variant != "none":
            parts.append(f"variant {self.variant}")
        return ", ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {"tier": self.tier, "brakes": self.brakes, "variant": self.variant, "key": self.key, "label": self.label}


REFERENCE_CELL = Cell("reference", False)
CORE_CELLS: Tuple[Cell, ...] = (
    REFERENCE_CELL, Cell("reference", True),
    Cell("trader", False), Cell("trader", True),
    Cell("aggressive", False), Cell("aggressive", True),
    Cell("risk1.5", False),
    Cell("trader-reference-ladder", False), Cell("aggressive-reference-ladder", False),
    Cell("trader-no-ladder", False), Cell("aggressive-no-ladder", False),
)
VARIANT_CELLS: Tuple[Cell, ...] = tuple(Cell(FLEET_TIER, True, v) for v in VARIANTS if v != "none")
CONTROL_CELLS: Tuple[Cell, ...] = (REFERENCE_CELL, Cell("reference", True), Cell("trader", False), Cell("trader", True), Cell("aggressive", False), Cell("aggressive", True))
FLEET_CELL = Cell(FLEET_TIER, True)


def cells_for(run: Configuration) -> Tuple[Cell, ...]:
    if run.role == "configuration":
        return CORE_CELLS + VARIANT_CELLS
    return CONTROL_CELLS


def holdout_cells() -> Tuple[Cell, ...]:
    """The cells that may open the untouched 12 months: the Reference reproduction and the brakes-on cell of each judged tier."""
    return (REFERENCE_CELL,) + tuple(Cell(t, True) for t in HOLDOUT_TIERS)


# -- the pre-registration -----------------------------------------------------------------------------------

def _tier_text() -> Dict[str, str]:
    return {name: f"{t.label}: {t.description}" for name, t in ALL_TIERS.items()}


PREREGISTRATION: Dict[str, Any] = {
    "fixed_on": "2026-11-05, before any run (plan row R18)",
    "question": ("At the three fixed risk budgets of Trader Policy v1 (Reference = today's 10 % volatility target with the Reference ladder; "
                 "Trader = a 20 % target capped so that no stop costs more than 2 % of equity, with the Turtle ladder; Aggressive = 25 % and "
                 "2.5 %), with the section 4.3 brakes on and off and each section 4.2 position-management variant on alone, do the five "
                 "confirmed configurations still pass the section 4.6 gates on the Sprint 2c walk-forward, what do the brakes and the variants "
                 "cost or add, where does each tier's realized volatility, risk per trade and probability of a 30 % drawdown land, and which "
                 "configurations therefore join the paper fleet at the Trader tier?"),
    "configurations": [c.name + f" (stored by {c.source_study})" for c in CONFIGURATIONS],
    "controls": [c.name for c in CONTROLS] + [c.name + " (new forward control: long above the 200-day average, policy sizing; fixed rule, no exit "
                                             "bracket, no 20-train-trade qualification; never judged)" for c in TF_CONTROLS],
    "tiers": _tier_text(),
    "brakes": {"on": TRADER_BRAKES.label,
               "off": "the tier's own ladder only (Turtle for Trader/Aggressive/risk1.5, the Reference ladder for Reference, none for the no-ladder comparisons)",
               "scope": ("entries only: no brake closes, reduces or otherwise touches an open position; the Reference ladder (which does reduce) is the "
                         "Reference tier's own rule and the comparison for the higher tiers"),
               "windows": ("the walk-forward's test windows restart flat from the same capital every 180 days, so the ladder's equity peak, the hard "
                           "stop and the loss windows restart with them, exactly as Sprint 2c's Reference ladder did; the stitched curve's drawdown can "
                           "exceed any window's, and the brakes' counts are per-window counts summed")},
    "variants": {name: v.description for name, v in VARIANTS.items() if name != "none"},
    "variant_rule": ("each variant runs alone at the Trader tier with the brakes on and is compared with the same sleeve without it; it counts "
                     "only with Sharpe >= the base's and Calmar >= the base's after scaling to the base's realized volatility (size-neutral); "
                     "the conviction split additionally needs expectancy in R of its 1.25 x trades above its 0.75 x trades with >= 30 trades each, "
                     "read per sleeve and pooled over the sleeves it applies to (S1+S5 BTC 6H, S1 and S1+S5 SOL 6H; not the S1+VC sleeves); "
                     "no variant joins the fleet in this row (the fleet account is the base rule, all variants off)"),
    "protocol": ("Sprint 2c's own runner (scripts/run_research_v1c.py loaded as a module, its run_series), with Sprint 2c's defaults for everything "
                 "the tier does not define: the candidates' grids and brackets (none/tp2/trail1/time30), the S0 filter with the FOMC calendar, the "
                 "regime-v2 entry gate where the configuration has one, the walk-forward (train 540 d, purge 7 d, test 180 d, Sharpe with >= 20 train "
                 "trades, entries then bracket) and the 0.25 reduce-only rebalance; the tier replaces only the policy sizing (and adds its brakes); the "
                 "per-window selection of the rule variants is unchanged and never sees the tier, so every configuration keeps the ATR multiple and "
                 "exit bracket its walk-forward selected (S1 SOL-USDT 6H's time30 included, also run once without it as a variant); the runner's "
                 "defaults are checked against the stored Sprint 2c run before the study runs and the protocol check of every cell is recorded in "
                 "the results (a tier is a recorded policy_sizing mismatch, never hidden); the TF control runs with --brackets none --min-trades 1, "
                 "a recorded deviation, because R16 showed the 20-train-trade qualification leaves this slow rule flat"),
    "data": (f"OKX public 1H and 4H spot candles of BTC-USDT, ETH-USDT, SOL-USDT and DOGE-USDT (4H stored, 6H resampled from 1H), frozen in a study "
             f"lake at Sprint 2c's data end (bar close <= {DATA_END}) so the walk-forward and the untouched 12 months (2025-10-20 -> 2026-10-20) are the "
             "same calendar window as in Sprint 2c, R12, R13 and R16; Binance public funding and open interest for the S5 filter as before"),
    "costs": ("the engine's 0.10 % fee + 0.05 % slippage a side (0.30 % a round trip) for the gates; the selected rule is also replayed, same windows "
              "and sizing, at 0.20 % a round trip (0.05 % + 0.05 % a side, the measured BTC/ETH cost) and at 0.50 % (0.10 % + 0.15 % a side, "
              "altcoins at +10 bps a side), reported, never gated"),
    "reproduction": ("before any tier is judged, the Reference cell (brakes off) of every configuration and hold control must give the stored "
                     "walk-forward numbers to 6 decimals, the same trade counts, the same most-selected rules and the same gate verdicts — Sprint 2c's "
                     "for BTC-USDT and ETH-USDT, the replication study's for SOL-USDT and DOGE-USDT, round 1's for S1+VC BTC-USDT 4H [gate], round 2's "
                     "for S1+VC DOGE-USDT 4H [gate]; otherwise the study stops"),
    "gates": (f"section 4.6: the Sprint 2c gates (PF > {GATES['profit_factor_min']}, Sharpe > {GATES['sharpe_min']}, Calmar > {GATES['calmar_min']}, "
              f">= {GATES['rolling_12m_positive_min'] * 100:.0f} % of rolling 12-month windows positive, >= {GATES['min_trades']} trades, >= "
              f"{GATES['robust_share_min'] * 100:.0f} % of +-30 % neighbours profitable) with max drawdown <= {TIER_GATES['reference']['max_drawdown_max'] * 100:.0f} % and worst "
              f"calendar year >= {TIER_GATES['reference']['worst_calendar_year_min'] * 100:.0f} % at the Reference tier, <= {TIER_GATES['higher']['max_drawdown_max'] * 100:.0f} % and >= "
              f"{TIER_GATES['higher']['worst_calendar_year_min'] * 100:.0f} % at the higher tiers, plus average win / average loss >= {PAYOFF_MIN:g} at every tier; expectancy in R "
              "(R = quantity x (entry fill - initial stop); under the add the first unit's R) is reported for every cell, not gated"),
    "brake_judgement": ("the brakes are judged by their trigger counts and their cost: the same sleeve with and without them, and the tier with its "
                        "ladder beside the same tier with no ladder and with the Reference ladder; a brake that costs more than 0.1 Calmar is "
                        "flagged for the owner; the loss limits and the heat cap are expected to count zero on one sleeve (they act in the "
                        "multi-market book, plan row R20); re-entries within two bars of a stop-out are the rule's own behaviour, counted, not changed"),
    "readings": ("per configuration and tier: realized yearly volatility, average allocation and its ratio to the Reference tier, the effective risk "
                 "per trade and how often the 2 % / 2.5 % cap binds, how often a tier put the whole account in one trade, trades whose loss exceeded "
                 "the stop distance (gaps), re-entries within two bars of a stop-out, and the bootstrap probability of touching -30 % (the hard stop), "
                 "beside section 4.1's expectations (Trader near 10-11 % realized volatility on the lead sleeve, about 1 in 30 for the hard stop; "
                 "Aggressive near 13 % and about 1 in 10)"),
    "holdout": ("the last 12 months (2025-10-20 -> 2026-10-20), opened only by the full pre-registered study (every configuration, control and cell, "
                "with the reproduction, never --quick), only for (a) the Reference reproduction, whose months the stored studies already opened and "
                "which must reproduce them, (b) the brakes-on cell of the Trader and Aggressive tiers when it passes every section 4.6 gate, and (c) the "
                "hold controls as the comparison line (as every study did); the v1c verdict (positive return, PF > 1, >= 10 trades); every opening goes "
                "into an append-only ledger the report shows. CAVEAT, stated before the run: a tier changes only the size of the same trades, so a "
                "holdout opened at a tier is a near-second look at months already opened at the Reference tier, and its falling direction was known "
                "for every market; a confirmation is necessary, not sufficient, and the paper fleet's forward record is the judge"),
    "fleet": (f"a configuration that passes every section 4.6 gate at the {FLEET_TIER} tier with the brakes on and whose holdout at that cell confirms "
              "joins the paper fleet's shortlist as a NEW account with a source tag naming this study, its tier, its brakes and 'no variant' — the "
              "base rule at the Trader tier (vt20, 2 % cap, Turtle ladder, hard stop and entry caps on, all variants off); the TF control on "
              f"BTC-USDT and ETH-USDT ({', '.join(TF_CONTROL_TIMEFRAMES)}) joins as a forward control at the Reference sizing; the rows are recorded "
              "in the results (shortlist_additions) and applied by plan row R18b once the fleet's loader can validate a tier-tagged row; existing "
              "accounts are untouched; nothing joins demo or live"),
    "no_changes_after_results": "no gate, tier, brake number, variant, market, threshold or verdict rule changes after the results are in; if a gate looks wrong the report says so",
}


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StudyConfig:
    runs: Tuple[str, ...] = tuple(c.key for c in ALL_RUNS)
    cells: Tuple[str, ...] = tuple(c.key for c in CORE_CELLS + VARIANT_CELLS)
    reproduction: bool = True
    data_end: str = DATA_END
    quick: bool = False
    lake_dir: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["runs"], out["cells"] = list(self.runs), list(self.cells)
        return out

    @property
    def markets(self) -> List[str]:
        wanted = {BY_KEY[k].instrument for k in self.runs}
        return [m for m in MARKETS if m in wanted]


def preregistration_hash(cfg: StudyConfig, prereg: Mapping[str, Any]) -> str:
    return _sha256_json({"preregistration": PREREGISTRATION, "file": prereg, "config": cfg.to_dict()})


def full_study_requested(cfg: StudyConfig) -> bool:
    return (not cfg.quick and cfg.reproduction and sorted(cfg.runs) == sorted(c.key for c in ALL_RUNS)
            and sorted(cfg.cells) == sorted(c.key for c in CORE_CELLS + VARIANT_CELLS))


def preregister(path: Path, *, now: Optional[datetime] = None, force: bool = False) -> Dict[str, Any]:
    path = Path(path)
    if path.exists() and not force:
        raise TraderPolicyError(f"{path} exists: the study was already fixed; a second write would be a second registration")
    written_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    payload: Dict[str, Any] = {
        "note": "Plan row R18. The configurations, tiers, brakes, variants, gates, costs and verdict rules of the Trader Policy v1 study, fixed BEFORE the first run. Never edited.",
        "written_at": written_at, "data_end": DATA_END, "gates": dict(GATES), "tier_gates": {k: dict(v) for k, v in TIER_GATES.items()}, "payoff_min": PAYOFF_MIN,
        "configurations": [c.to_dict() for c in ALL_RUNS], "cells": [c.to_dict() for c in CORE_CELLS + VARIANT_CELLS],
        "control_cells": [c.to_dict() for c in CONTROL_CELLS], "holdout_cells": [c.to_dict() for c in holdout_cells()],
        "tiers": {k: t.to_dict() for k, t in ALL_TIERS.items()}, "brakes_on": TRADER_BRAKES.to_dict(),
        "variants": {k: v.to_dict() for k, v in VARIANTS.items()}, "cost_scenarios": {k: list(v) for k, v in COST_SCENARIOS.items()},
        "configuration": StudyConfig().to_dict(), "preregistration": PREREGISTRATION,
    }
    payload["sha256"] = _sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return payload


def load_preregistration(path: Path = PREREGISTRATION_PATH) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("preregistration"), dict):
        raise TraderPolicyError(f"{path} is not a pre-registration file")
    expected = _sha256_json({k: v for k, v in data.items() if k != "sha256"})
    if data.get("sha256") != expected:
        raise TraderPolicyError(f"{path} was edited after it was written (hash mismatch)")
    if data["preregistration"] != PREREGISTRATION:
        raise TraderPolicyError("the pre-registration text in research/trader_policy_study.py differs from the registered file; neither may change after registration")
    if data.get("gates") != dict(GATES) or data.get("tier_gates") != {k: dict(v) for k, v in TIER_GATES.items()} or data.get("payoff_min") != PAYOFF_MIN:
        raise TraderPolicyError("the gates differ from the registered ones")
    if data.get("tiers") != {k: t.to_dict() for k, t in ALL_TIERS.items()} or data.get("brakes_on") != TRADER_BRAKES.to_dict():
        raise TraderPolicyError("the tiers or brakes differ from the registered ones")
    if data.get("variants") != {k: v.to_dict() for k, v in VARIANTS.items()}:
        raise TraderPolicyError("the variants differ from the registered ones")
    if [c["key"] for c in data.get("configurations", [])] != [c.key for c in ALL_RUNS]:
        raise TraderPolicyError("the configurations differ from the registered ones")
    return data


# -- the runner's arguments per cell ------------------------------------------------------------------------------

def runner():
    return load_v1c_runner()


def cell_argv(cell: Cell, run: Configuration, *, evaluate_holdout: bool, lake_dir: Optional[str], quick: bool) -> List[str]:
    """Sprint 2c's command line for one cell: the tier's sizing and brakes, the variant, the cost scenarios, the run's strategy and mode."""
    t: PolicyTier = tier(cell.tier)
    s = t.sizing
    argv: List[str] = ["--strategies", run.candidate, "--regime-modes", run.mode, "--timeframes", run.timeframe, "--tier", cell.tier]
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
    if cell.variant != "none":
        argv += ["--variant", cell.variant]
    argv += ["--cost-scenarios", *[f"{name}={fee:g}:{slip:g}" for name, (fee, slip) in COST_SCENARIOS.items()]]
    if run.role == "tf_control":
        argv += ["--brackets", "none", "--min-trades", "1"]  # the fixed-rule deviation, recorded by the protocol check
    if evaluate_holdout:
        argv.append("--evaluate-holdout")
    if quick:
        argv.append("--quick")
    if lake_dir:
        argv += ["--lake-dir", lake_dir]
    return argv


def cell_args(cell: Cell, run: Configuration, *, evaluate_holdout: bool, lake_dir: Optional[str], quick: bool) -> Dict[str, Any]:
    v1c = runner()
    return dict(vars(v1c.parse_args(cell_argv(cell, run, evaluate_holdout=evaluate_holdout, lake_dir=lake_dir, quick=quick))))


def protocol_check_cell(args: Mapping[str, Any], meta: Mapping[str, Any], cell: Cell, run: Configuration) -> Dict[str, Any]:
    """The replication study's protocol check, with the cell's deliberate, documented differences named beside the raw mismatches."""
    narrowed = dict(args, strategies=[s for s in args["strategies"] if s in set(meta.get("strategies") or [])])
    check = protocol_check(narrowed, meta)
    expected: Dict[str, str] = {}
    if cell.tier != "reference":
        expected["policy_sizing"] = f"the {cell.tier} tier ({tier(cell.tier).label})"
    if run.role == "tf_control":
        expected["brackets"] = "the TF control runs without an exit bracket (fixed rule)"
        expected["min_trades"] = "the TF control skips the 20-train-trade qualification (fixed rule)"
    unexplained = {k: v for k, v in check["mismatches"].items() if k not in expected}
    check.update({
        "cell": cell.to_dict(), "expected_mismatches": expected, "unexplained_mismatches": unexplained,
        "ok_for_cell": not unexplained,
        "r18": {"tier": cell.tier, "brakes_on": cell.brakes, "brakes": None if not (cell.brakes or tier(cell.tier).turtle_ladder) else
                (TRADER_BRAKES.to_dict() if cell.brakes and tier(cell.tier).turtle_ladder else None), "variant": cell.variant},
        "new_candidates": [s for s in args["strategies"] if s not in set(meta.get("strategies") or [])],
        "note": ("the tier replaces Sprint 2c's policy sizing by design and the brakes / variant are additions the stored run did not have; every "
                 "other protocol parameter is checked; the TF control's two deviations are its fixed-rule protocol"),
    })
    return check


# -- stored results ----------------------------------------------------------------------------------------------

def _flat(doc: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    if isinstance(doc.get("results"), list):
        return list(doc["results"])
    return [r for s in doc.get("series", []) for r in s.get("results", [])]


def stored_results(docs: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The stored results of the four studies, each tagged with its study name (the reproduction targets and the earlier holdout looks)."""
    out: List[Dict[str, Any]] = []
    for study, doc in docs.items():
        for r in _flat(doc):
            out.append(dict(r, study_source=study))
    return out


def stored_for(run: Configuration, stored: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    for r in stored:
        if (r.get("study_source") == run.source_study and r["candidate"] == run.candidate and r["instrument"] == run.instrument
                and r["timeframe"] == run.timeframe and (r.get("regime") or {}).get("mode") == run.mode):
            return r
    return None


# -- jobs --------------------------------------------------------------------------------------------------------------

SERIES_KEYS = ("instrument", "timeframe", "results", "failures", "benchmark", "span", "holdout_span", "positioning", "s0_blocked_share", "skipped")


def plan_jobs(cfg: StudyConfig, *, evaluate_holdout: bool) -> List[Dict[str, Any]]:
    """One job per (run, cell): the runner's run_series for one strategy, one mode, one series, one policy."""
    jobs: List[Dict[str, Any]] = []
    wanted_cells = set(cfg.cells)
    for key in cfg.runs:
        run = BY_KEY[key]
        for cell in cells_for(run):  # a configuration: every core and variant cell; a control: the six control cells
            if cell.key not in wanted_cells:
                continue
            # The runner opens the holdout only for passers and the hold controls; the TF forward control is never judged and never opens it
            # (the study's first two runs let the runner's passer rule open TF BTC-USDT's months at the Trader and Aggressive cells; the ledger
            # keeps those openings and the report names them).
            opens = bool(evaluate_holdout) and cell in holdout_cells() and run.role != "tf_control"
            jobs.append({"cfg": cfg.to_dict(), "run": key, "cell": cell.to_dict(), "evaluate_holdout": opens})
    return jobs


def run_job(job: Mapping[str, Any]) -> Dict[str, Any]:
    """Process-pool entry point."""
    cfg = StudyConfig(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in job["cfg"].items()})
    run = BY_KEY[job["run"]]
    cell = Cell(job["cell"]["tier"], bool(job["cell"]["brakes"]), job["cell"].get("variant", "none"))
    v1c = runner()
    args = cell_args(cell, run, evaluate_holdout=bool(job["evaluate_holdout"]), lake_dir=cfg.lake_dir, quick=cfg.quick)
    print(f"[{run.key} {run.name}] {cell.label} ...", flush=True)
    out = v1c.run_series(dict(args), run.instrument, run.timeframe)
    series: Dict[str, Any] = {k: out.get(k) for k in SERIES_KEYS}
    series["run"] = run.key
    series["cell"] = cell.to_dict()
    series["args"] = dict(args)
    series["trades"] = {f"{k}|{m}": t for (k, m), t in (out.get("trades") or {}).items()}
    return series


def merge_results(outputs: Sequence[Mapping[str, Any]], stored_meta: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Every job's single result, keyed ``"<run>|<cell key>"``, annotated with its run, cell, role and protocol check."""
    merged: Dict[str, Dict[str, Any]] = {}
    for o in outputs:
        run = BY_KEY[o["run"]]
        cell = Cell(o["cell"]["tier"], bool(o["cell"]["brakes"]), o["cell"].get("variant", "none"))
        key = f"{run.key}|{cell.key}"
        if o.get("skipped") or not o.get("results"):
            merged[key] = {"run": run.to_dict(), "cell": cell.to_dict(), "skipped": o.get("skipped") or "no result", "failures": o.get("failures") or [],
                           "configuration": run.name, "role": run.role}
            continue
        r = dict(o["results"][0])
        r.update({"run": run.to_dict(), "cell": cell.to_dict(), "configuration": run.name, "role": run.role, "study_source": run.source_study,
                  "holdout_confirmed": holdout_verdict(r) if r.get("holdout") else None,
                  "protocol_check": protocol_check_cell(o["args"], stored_meta, cell, run), "failures": o.get("failures") or [],
                  "span": o.get("span"), "holdout_span": o.get("holdout_span"), "benchmark": o.get("benchmark")})
        merged[key] = r
    return merged


def result_of(merged: Mapping[str, Mapping[str, Any]], run_key: str, cell: Cell) -> Optional[Mapping[str, Any]]:
    r = merged.get(f"{run_key}|{cell.key}")
    return None if r is None or r.get("skipped") else r


# -- the reproduction ---------------------------------------------------------------------------------------------------

def reproduction_checks(merged: Mapping[str, Mapping[str, Any]], stored: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The Reference cell of every configuration and hold control against its stored numbers (the TF controls have none)."""
    checks: List[Dict[str, Any]] = []
    for run in CONFIGURATIONS + CONTROLS:
        r = result_of(merged, run.key, REFERENCE_CELL)
        exp = stored_for(run, stored)
        if r is None:
            checks.append({"run": run.key, "configuration": run.name, "study": run.source_study, "ok": False, "note": "the Reference cell did not run"})
            continue
        if exp is None:
            checks.append({"run": run.key, "configuration": run.name, "study": run.source_study, "ok": False, "note": "no stored result for this configuration"})
            continue
        row = reproduction_check({"results": [r]}, [exp])[0]
        row.update({"run": run.key, "configuration": run.name, "study": run.source_study})
        checks.append(row)
    return checks


# -- per-configuration analyses ---------------------------------------------------------------------------------------------

def _oos(r: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return dict((r or {}).get("oos") or {})


def _r18(r: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return dict((r or {}).get("r18") or {})


def tier_table(merged: Mapping[str, Mapping[str, Any]], run: Configuration) -> List[Dict[str, Any]]:
    """One row per cell of a run: the headline numbers, the R18 readings, the gates and the holdout."""
    rows: List[Dict[str, Any]] = []
    ref = result_of(merged, run.key, REFERENCE_CELL)
    for cell in cells_for(run):
        r = result_of(merged, run.key, cell)
        if r is None:
            continue
        o, x = _oos(r), _r18(r)
        acc = r.get("acceptance_r18") or {}
        mc = r.get("montecarlo") or {}
        trades = x.get("trades") or {}
        rows.append({
            "cell": cell.to_dict(), "tier": cell.tier, "brakes": cell.brakes, "variant": cell.variant,
            "cagr": o.get("cagr"), "total_return": o.get("total_return"), "sharpe": o.get("sharpe"), "max_drawdown": o.get("max_drawdown"), "calmar": o.get("calmar"),
            "profit_factor": o.get("profit_factor"), "n_trades": o.get("n_trades"), "trades_per_year": o.get("trades_per_year"), "win_rate": o.get("win_rate"),
            "ann_vol": o.get("ann_vol"), "avg_allocation": o.get("avg_allocation"), "exposure": o.get("exposure"), "fees_pct_per_year": o.get("fees_pct_per_year"),
            "exposure_ratio": exposure_ratio(o, _oos(ref)) if cell != REFERENCE_CELL else 1.0,
            "payoff_ratio": acc.get("payoff_ratio"), "expectancy_r": trades.get("expectancy_r"), "risk_pct_mean": trades.get("risk_pct_mean"),
            "risk_pct_max": trades.get("risk_pct_max"), "full_allocation_share": trades.get("full_allocation_share"),
            "cap_binding_share": (x.get("cap") or {}).get("cap_binding_share"), "gap_trades": trades.get("gap_trades"), "gap_share": trades.get("gap_share"),
            "reentries": trades.get("reentries_within_2_bars_of_stop"), "stop_outs": trades.get("stop_outs"),
            "prob_dd_30": mc.get("prob_max_dd_ge_30"), "mc_dd_p50": mc.get("max_dd_p50"), "mc_dd_p95": mc.get("max_dd_p95"),
            "passed": bool(acc.get("passed")), "failed": list(acc.get("failed") or []), "passed_v1c": bool((r.get("acceptance") or {}).get("passed")),
            "holdout": r.get("holdout"), "holdout_confirmed": r.get("holdout_confirmed"),
            "yearly": {str(k): v for k, v in (r.get("yearly") or {}).items()}, "worst_calendar_year_return": acc.get("worst_calendar_year_return"),
            "rolling_positive_share": acc.get("rolling_positive_share"), "selected_params": r.get("selected_params"), "rule_frequency": r.get("rule_frequency"),
            "brake_summary": x.get("brake_summary") or {}, "cost_scenarios": x.get("cost_scenarios") or {}, "notes": r.get("notes") or [],
            "protocol_ok_for_cell": bool((r.get("protocol_check") or {}).get("ok_for_cell")),
        })
    return rows


def brake_analysis(merged: Mapping[str, Mapping[str, Any]], run: Configuration) -> List[Dict[str, Any]]:
    """Per tier: the brakes' trigger counts (brakes-on cell) and their cost beside the brakes-off cell; the ladder's cost beside no ladder."""
    out: List[Dict[str, Any]] = []
    for t in ("reference", "trader", "aggressive"):
        on, off = result_of(merged, run.key, Cell(t, True)), result_of(merged, run.key, Cell(t, False))
        if on is None or off is None:
            continue
        summ = _r18(on).get("brake_summary") or {}
        entry = {"tier": t, "counts": summ.get("counts") or {}, "trips": summ.get("trips") or {}, "entries_at": summ.get("entries_at") or {},
                 "opportunities": summ.get("opportunities"), "bars_blocked": summ.get("bars_blocked"), "bars": summ.get("bars"),
                 "cost": brake_cost(_oos(off), _oos(on)), "n_trades_on": _oos(on).get("n_trades"), "n_trades_off": _oos(off).get("n_trades")}
        if t != "reference":
            nolad = result_of(merged, run.key, Cell(f"{t}-no-ladder", False))
            reflad = result_of(merged, run.key, Cell(f"{t}-reference-ladder", False))
            entry["ladder_cost"] = brake_cost(_oos(nolad), _oos(off)) if nolad is not None else None  # Turtle ladder (off cell = ladder only) vs no ladder
            entry["reference_ladder"] = None if reflad is None else {"calmar": _oos(reflad).get("calmar"), "cagr": _oos(reflad).get("cagr"),
                                                                     "max_drawdown": _oos(reflad).get("max_drawdown"), "sharpe": _oos(reflad).get("sharpe"),
                                                                     "n_trades": _oos(reflad).get("n_trades"), "passed": bool((reflad.get("acceptance_r18") or {}).get("passed"))}
            entry["ladder_bars"] = (_r18(off).get("brake_summary") or {}).get("ladder_bars") or {}
        out.append(entry)
    return out


def variant_analysis(merged: Mapping[str, Mapping[str, Any]], run: Configuration) -> List[Dict[str, Any]]:
    """Each variant beside the base rule in the same cell (Trader tier, brakes on): the size-neutral rule and the variant's own readings."""
    base = result_of(merged, run.key, FLEET_CELL)
    out: List[Dict[str, Any]] = []
    for cell in VARIANT_CELLS:
        r = result_of(merged, run.key, cell)
        if r is None or base is None:
            continue
        x = _r18(r)
        v = x.get("variant") or {}
        applies = bool(v.get("applies", True))
        entry: Dict[str, Any] = {"variant": cell.variant, "applies": applies, "why_not": v.get("why_not", ""), "description": VARIANTS[cell.variant].description,
                                 "base": {k: _oos(base).get(k) for k in ("cagr", "sharpe", "max_drawdown", "calmar", "profit_factor", "n_trades", "ann_vol", "win_rate")},
                                 "variant_metrics": {k: _oos(r).get(k) for k in ("cagr", "sharpe", "max_drawdown", "calmar", "profit_factor", "n_trades", "ann_vol", "win_rate")},
                                 "rule": variant_counts(_oos(base), _oos(r)) if applies else None, "trades": x.get("trades"), "conviction": x.get("conviction"),
                                 "payoff_ratio": (r.get("acceptance_r18") or {}).get("payoff_ratio"), "base_payoff_ratio": (base.get("acceptance_r18") or {}).get("payoff_ratio"),
                                 "passed": bool((r.get("acceptance_r18") or {}).get("passed")), "failed": list((r.get("acceptance_r18") or {}).get("failed") or [])}
        if applies and cell.variant == "conviction":
            c = x.get("conviction") or {}
            entry["counts"] = bool(entry["rule"]["counts"] and c.get("enough_trades") and c.get("high_beats_low"))
            entry["conviction_note"] = ("enough trades on both sides" if c.get("enough_trades") else
                                        f"too few trades for the pre-registered test ({c.get('n_high')} high, {c.get('n_low')} low; 30 each needed)")
        elif applies:
            entry["counts"] = bool(entry["rule"]["counts"])
        else:
            entry["counts"] = None
        out.append(entry)
    return out


def cost_table(merged: Mapping[str, Mapping[str, Any]], run: Configuration) -> List[Dict[str, Any]]:
    """The selected rule at the three tiers (brakes on) under the gate cost and the two replayed cost pairs."""
    out: List[Dict[str, Any]] = []
    for t in ("reference", "trader", "aggressive"):
        r = result_of(merged, run.key, Cell(t, True))
        if r is None:
            continue
        o = _oos(r)
        scen = (_r18(r).get("cost_scenarios") or {})
        out.append({"tier": t, "gate_cost": {"round_trip": 0.003, "total_return": o.get("total_return"), "cagr": o.get("cagr"), "calmar": o.get("calmar"),
                                             "sharpe": o.get("sharpe"), "max_drawdown": o.get("max_drawdown"), "profit_factor": o.get("profit_factor")},
                    **{name: scen.get(name) for name in COST_SCENARIOS}})
    return out


def configuration_verdict(merged: Mapping[str, Mapping[str, Any]], run: Configuration) -> Dict[str, Any]:
    """Passes per tier (section 4.6), the fleet-candidate decision (Trader tier, brakes on, holdout confirmed) and the readings."""
    rows = {row["cell"]["key"]: row for row in tier_table(merged, run)}
    per_tier = {}
    for t in ("reference", "trader", "aggressive", "risk1.5"):
        for brakes in (False, True):
            row = rows.get(Cell(t, brakes).key)
            if row is None:
                continue
            per_tier[Cell(t, brakes).key] = {"passed": row["passed"], "failed": row["failed"], "holdout_confirmed": row["holdout_confirmed"],
                                              "calmar": row["calmar"], "cagr": row["cagr"], "max_drawdown": row["max_drawdown"], "ann_vol": row["ann_vol"],
                                              "prob_dd_30": row["prob_dd_30"], "exposure_ratio": row["exposure_ratio"], "risk_pct_mean": row["risk_pct_mean"]}
    fleet_row = rows.get(FLEET_CELL.key)
    fleet_candidate = bool(fleet_row and fleet_row["passed"] and fleet_row["holdout_confirmed"] is True)
    if fleet_row is None:
        reason = "the Trader cell did not run"
    elif not fleet_row["passed"]:
        reason = "fails at the Trader tier: " + ", ".join(fleet_row["failed"])
    elif fleet_row["holdout_confirmed"] is None:
        reason = "passes at the Trader tier; holdout not opened"
    elif fleet_row["holdout_confirmed"] is False:
        reason = "passes at the Trader tier; the holdout contradicted it"
    else:
        reason = "passes every section 4.6 gate at the Trader tier with the brakes on and the holdout confirms"
    return {"run": run.key, "configuration": run.name, "role": run.role, "per_tier": per_tier, "fleet_candidate": fleet_candidate, "fleet_reason": reason,
            "fleet_cell": FLEET_CELL.to_dict()}


def overall_summary(merged: Mapping[str, Mapping[str, Any]], verdicts: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    confs = [v for v in verdicts if v["role"] == "configuration"]
    out: Dict[str, Any] = {"n_configurations": len(confs), "fleet_candidates": [v["configuration"] for v in confs if v["fleet_candidate"]]}
    for t in ("reference", "trader", "aggressive"):
        for brakes in (False, True):
            k = Cell(t, brakes).key
            cells = [v["per_tier"].get(k) for v in confs if v["per_tier"].get(k)]
            out[f"passed_{k}"] = sum(1 for c in cells if c["passed"])
            out[f"n_{k}"] = len(cells)
    # Brakes: trigger counts summed over the configurations' brakes-on cells per tier, and the flagged costs.
    counts: Dict[str, Dict[str, int]] = {}
    flagged: List[str] = []
    ladder_flagged: List[str] = []
    for run in CONFIGURATIONS:
        for b in brake_analysis(merged, run):
            agg = counts.setdefault(b["tier"], {})
            for name, n in (b.get("counts") or {}).items():
                agg[name] = agg.get(name, 0) + int(n)
            if (b.get("cost") or {}).get("flagged"):
                flagged.append(f"{run.name} at {b['tier']}")
            if (b.get("ladder_cost") or {}).get("flagged"):
                ladder_flagged.append(f"{run.name} at {b['tier']}")
    out["brake_counts"] = counts
    out["brake_cost_flagged"] = flagged
    out["ladder_cost_flagged"] = ladder_flagged
    # Variants: which count, per configuration.
    counting: Dict[str, List[str]] = {}
    for run in CONFIGURATIONS:
        for v in variant_analysis(merged, run):
            if v.get("counts"):
                counting.setdefault(v["variant"], []).append(run.name)
    out["variants_counting"] = counting
    return out


# -- the holdout ledger and the earlier looks --------------------------------------------------------------------------------

LEDGER_NOTE = ("Every opening of the untouched 12 months by the Trader Policy v1 study (plan row R18), in order; entries are appended, never edited. "
               "A tier changes only the size of the same trades, so an opening at a tier is a near-second look at months the stored studies already "
               "opened at the Reference tier; the report names the earlier look beside each opening. The hold controls' 12 months are a comparison line.")


def holdout_openings(merged: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key, r in merged.items():
        h = r.get("holdout")
        if not h or r.get("skipped"):
            continue
        out.append({"configuration": r["configuration"], "cell": r["cell"]["key"], "role": r["role"], "selected_params": r.get("selected_params"),
                    "span": r.get("holdout_span"), "total_return": h.get("total_return"), "max_drawdown": h.get("max_drawdown"),
                    "profit_factor": h.get("profit_factor"), "n_trades": h.get("n_trades"),
                    "confirmed": None if r["role"] != "configuration" else holdout_verdict(r)})
    out.sort(key=lambda x: (x["configuration"], x["cell"]))
    return out


def earlier_looks(merged: Mapping[str, Mapping[str, Any]], stored: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in merged.values():
        if r.get("skipped") or not r.get("holdout") or r["role"] != "configuration":
            continue
        run = BY_KEY[r["run"]["key"]]
        exp = stored_for(run, stored)
        entry = {"configuration": r["configuration"], "cell": r["cell"]["key"], "earlier_study": run.source_study, "earlier_opened": bool(exp and exp.get("holdout"))}
        if exp and exp.get("holdout"):
            h = exp["holdout"]
            entry.update({"earlier_total_return": h.get("total_return"), "earlier_profit_factor": h.get("profit_factor"), "earlier_n_trades": h.get("n_trades"),
                          "earlier_confirmed": holdout_verdict(exp)})
        out.append(entry)
    out.sort(key=lambda x: (x["configuration"], x["cell"]))
    return out


def guard_second_look(ledger: Sequence[Mapping[str, Any]], openings: Sequence[Mapping[str, Any]], *, evaluate_holdout: bool) -> List[str]:
    if not evaluate_holdout:
        return []
    seen = {(o["configuration"], o["cell"]) for e in ledger for o in e.get("openings", []) if o.get("role") == "configuration"}
    return sorted(f"{o['configuration']} @ {o['cell']}" for o in openings if o["role"] == "configuration" and (o["configuration"], o["cell"]) in seen)


def write_ledger(path: str, entries: List[Dict[str, Any]]) -> None:
    Path(path).write_text(json.dumps({"note": LEDGER_NOTE, "entries": entries}, indent=1) + "\n", encoding="utf-8")


# -- the fleet rows (recorded here, applied by plan row R18b) ----------------------------------------------------------------

def shortlist_additions(merged: Mapping[str, Mapping[str, Any]], verdicts: Sequence[Mapping[str, Any]], *, source: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Shortlist rows for the fleet candidates (the base rule at the Trader tier, brakes on, no variant) and the TF forward controls."""
    rows: List[Dict[str, Any]] = []
    for v in verdicts:
        if v["role"] != "configuration" or not v["fleet_candidate"]:
            continue
        r = result_of(merged, v["run"], FLEET_CELL)
        if r is None:
            continue
        row = _row(r)
        row["sizing"] = tier(FLEET_CELL.tier).label
        row["sizing_config"] = r.get("policy_sizing")
        row["source"] = dict(source, tier=FLEET_CELL.tier, brakes=(_r18(r).get("brakes")), variant="none", cell=FLEET_CELL.key,
                             protocol_variant=None, role="candidate")
        rows.append(row)
    for run in TF_CONTROLS:
        if run.timeframe not in TF_CONTROL_TIMEFRAMES:
            continue
        r = result_of(merged, run.key, REFERENCE_CELL)
        if r is None:
            continue
        row = _row(r)
        row["source"] = dict(source, tier="reference", brakes=None, variant="none", cell=REFERENCE_CELL.key,
                             protocol_variant="fixed rule: no exit bracket, no 20-train-trade qualification", role="control")
        row["control_label"] = "always long above the 200-day average, policy sizing (forward control)"
        rows.append(row)
    rows.sort(key=lambda x: (x["source"].get("role") != "candidate", -float(x.get("calmar") or -9.0)))
    return rows


def pooled_conviction_test(merged: Mapping[str, Mapping[str, Any]], *, min_trades: int = 30) -> Dict[str, Any]:
    """The conviction split's pre-registered test pooled over the configurations it applies to (trade counts and R-weighted means)."""
    cell = Cell(FLEET_TIER, True, "conviction")
    n_high = n_low = 0
    sum_high = sum_low = 0.0
    sleeves: List[str] = []
    for run in CONFIGURATIONS:
        r = result_of(merged, run.key, cell)
        c = (_r18(r).get("conviction") or {}) if r is not None else {}
        v = _r18(r).get("variant") or {}
        if r is None or not v.get("applies", False) or not c:
            continue
        sleeves.append(run.name)
        nh, nl = int(c.get("n_high") or 0), int(c.get("n_low") or 0)
        if nh and c.get("expectancy_r_high") is not None:
            n_high += nh
            sum_high += float(c["expectancy_r_high"]) * nh
        if nl and c.get("expectancy_r_low") is not None:
            n_low += nl
            sum_low += float(c["expectancy_r_low"]) * nl
    high = sum_high / n_high if n_high else None
    low = sum_low / n_low if n_low else None
    enough = bool(n_high >= min_trades and n_low >= min_trades)
    return {"sleeves": sleeves, "n_high": n_high, "n_low": n_low, "expectancy_r_high": high, "expectancy_r_low": low, "enough_trades": enough,
            "high_beats_low": (bool(high > low) if (enough and high is not None and low is not None) else None), "min_trades": min_trades}


def finite(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None
