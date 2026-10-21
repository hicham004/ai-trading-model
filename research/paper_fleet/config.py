"""The fleet manifest: one paper account per shortlist row, per control, plus the jointly sized portfolio.

Everything here is read from the two Sprint 2c files, nothing is re-selected:

- ``docs/research/paper_fleet_shortlist_v1c.json`` — the ten shortlisted
  configurations (candidate x instrument x timeframe x regime mode, with the
  rule parameters the walk-forward selected most often) and the controls
  (always-long with the policy sizing; plain buy-and-hold);
- ``docs/research/ensemble_v1c_results.json`` — the walk-forward and holdout
  numbers each account is compared with, and the six full-size sleeves of the
  jointly sized portfolio (per family and instrument the timeframe the research
  chose) with their parameters.

The rules every account runs are the Sprint 2c rules, fixed before the run:
fees 0.10 % + slippage 0.05 % per side, the S0 no-trade filter with the FOMC
calendar, the policy sizing ``vt10/30 crash15/90dh ladder`` with a 30-day
ladder recovery and the 0.25 reduce-only rebalance threshold, the regime-v2
entry gate (3-state HMM, bear >= 0.5) refitted on 540 days of history ending 7
days before every 180-day forward window, and the portfolio's 15 % vol target
with the 7.5/15 % ladder. The manifest's fingerprint is stored with the fleet:
a changed manifest refuses to resume (start a new fleet directory instead).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from research.engine import Costs
from research.regime_v2 import RegimeV2Config
from research.sizing import LadderConfig, SizingSpec
from research.strategies import get_candidate
from research.strategies.base import days_to_bars
from research.strategies.s0_filters import NoTradeConfig

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SHORTLIST = ROOT / "docs" / "research" / "paper_fleet_shortlist_v1c.json"
DEFAULT_RESULTS = ROOT / "docs" / "research" / "ensemble_v1c_results.json"
SHORTLIST_STATUS = "forward evidence only; nothing approved"

INSTRUMENTS: Tuple[str, ...] = ("BTC-USDT", "ETH-USDT")
TIMEFRAMES: Tuple[str, ...] = ("4H", "6H")
SOURCE_TIMEFRAME = "1H"

COSTS = Costs(fee_rate=0.0010, slippage_rate=0.0005)  # the research costs, per side
INIT_CASH = 10_000.0  # virtual USDT per account
NO_TRADE = NoTradeConfig(scheduled_events=True)  # S0 vol x3, spread p98, gap 3 bars, FOMC +-6 h (as in v1c)
REBALANCE_THRESHOLD = 0.25
POLICY_LADDER_RECOVERY_DAYS = 30.0
TRAIN_DAYS = 540.0  # regime fit window (the walk-forward train slice)
PURGE_DAYS = 7.0
TEST_WINDOW_DAYS = 180.0  # the walk-forward test window: sleeves restart flat this often, as each research window did
REFIT_DAYS = TEST_WINDOW_DAYS  # ... and the regime model is refitted at the same cadence
FALLBACK_CONFIDENCE = 0.60  # the adapter's fixed confidence (the research engine does not use it)

PORTFOLIO_TARGET_VOL = 0.15
PORTFOLIO_VOL_LOOKBACK_DAYS = 30
PORTFOLIO_WEIGHT_LOOKBACK_DAYS = 60
PORTFOLIO_LADDER = LadderConfig(half_dd=0.075, flat_dd=0.15, recovery_bars=30)  # days (one row per UTC day)
PORTFOLIO_WARMUP_DAYS = 120  # sleeve history simulated before the start to seed weights and the vol estimate
PORTFOLIO_NAME = "S1+S2+S4 x BTC+ETH — jointly sized, vol target 15%, ladder 7.5/15"
# Candidates whose own signal frame carries exits beyond the stop (S3's time stop): the fleet takes exits only from the
# rule's stop and the bracket, so it refuses them rather than silently dropping an exit (tested for every other candidate).
OWN_EXIT_CANDIDATES = frozenset({"S3"})


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _inst(instrument: str) -> str:
    return instrument.split("-")[0].lower()


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def account_fingerprint(account: "AccountSpec") -> str:
    """One account's trading rules (not its label or its expectations)."""
    return _sha(_canonical(account.rules_dict()))


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, float):
        return None if not math.isfinite(value) else round(value, 12)
    return value


def _params(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Shortlist/JSON parameters back to the types the candidates were built with (lists -> tuples)."""
    return {k: (tuple(v) if isinstance(v, list) else v) for k, v in raw.items()}


@dataclass(frozen=True)
class SleeveSpec:
    """One strategy sleeve: candidate, series, rule parameters (with the exit bracket) and its sizing."""

    candidate: str
    instrument: str
    timeframe: str
    params: Mapping[str, Any]
    regime: RegimeV2Config = RegimeV2Config(mode="none")
    sizing: Optional[SizingSpec] = None  # None = full size (100 % of cash per entry, no ladder)
    rebalance_threshold: Optional[float] = None

    def __post_init__(self) -> None:
        get_candidate(self.candidate)  # unknown candidate -> ValueError
        if self.candidate in OWN_EXIT_CANDIDATES:
            raise ValueError(f"{self.candidate} brings its own exits (time stop / target), which the fleet's decisions do not carry")
        if self.instrument not in INSTRUMENTS:
            raise ValueError(f"instrument {self.instrument!r} is not in the fleet ({INSTRUMENTS})")
        if self.timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe {self.timeframe!r} is not in the fleet ({TIMEFRAMES})")

    @property
    def bracket(self) -> str:
        return str(self.params.get("bracket", "none") or "none")

    @property
    def rule_params(self) -> Dict[str, Any]:
        return {k: v for k, v in self.params.items() if k != "bracket"}

    @property
    def series(self) -> Tuple[str, str]:
        return self.instrument, self.timeframe

    def ladder(self) -> Optional[LadderConfig]:
        if self.sizing is None or not self.sizing.ladder:
            return None
        return LadderConfig(recovery_bars=days_to_bars(POLICY_LADDER_RECOVERY_DAYS, self.timeframe))

    @property
    def uses_positioning(self) -> bool:
        return "S5" in self.candidate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate": self.candidate, "instrument": self.instrument, "timeframe": self.timeframe,
            "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.params.items()},
            "regime": self.regime.to_dict(), "sizing": None if self.sizing is None else self.sizing.to_dict(),
            "rebalance_threshold": self.rebalance_threshold,
            "ladder": None if self.ladder() is None else self.ladder().to_dict(),
        }


@dataclass(frozen=True)
class PortfolioSpec:
    sleeves: Tuple[Tuple[str, SleeveSpec], ...]  # (name like "S1/BTC/6H", full-size sleeve)
    target_vol: float = PORTFOLIO_TARGET_VOL
    vol_lookback_days: int = PORTFOLIO_VOL_LOOKBACK_DAYS
    weight_lookback_days: int = PORTFOLIO_WEIGHT_LOOKBACK_DAYS
    ladder: LadderConfig = PORTFOLIO_LADDER
    cap: float = 1.0
    warmup_days: int = PORTFOLIO_WARMUP_DAYS

    def to_dict(self) -> Dict[str, Any]:
        return {"sleeves": {name: s.to_dict() for name, s in self.sleeves}, "target_vol": self.target_vol,
                "vol_lookback_days": self.vol_lookback_days, "weight_lookback_days": self.weight_lookback_days,
                "ladder": self.ladder.to_dict(), "cap": self.cap, "warmup_days": self.warmup_days}


@dataclass(frozen=True)
class AccountSpec:
    """One paper account. ``kind``: ``sleeve`` | ``buy_and_hold`` | ``portfolio``; ``role``: ``candidate`` | ``control`` | ``portfolio``."""

    account_id: str
    role: str
    kind: str
    label: str
    sleeve: Optional[SleeveSpec] = None
    portfolio: Optional[PortfolioSpec] = None
    instrument: Optional[str] = None
    timeframe: Optional[str] = None
    shortlist_rank: Optional[int] = None
    expectations: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in ("sleeve", "buy_and_hold", "portfolio"):
            raise ValueError(f"unknown account kind {self.kind!r}")
        if self.role not in ("candidate", "control", "portfolio"):
            raise ValueError(f"unknown account role {self.role!r}")
        if (self.kind == "portfolio") != (self.portfolio is not None):
            raise ValueError("a portfolio account needs a portfolio spec (and only it)")
        if self.kind == "sleeve" and self.sleeve is None:
            raise ValueError("a sleeve account needs a sleeve spec")
        if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{1,63}", self.account_id):
            raise ValueError(f"unsafe account id {self.account_id!r}")

    @property
    def series(self) -> Optional[Tuple[str, str]]:
        if self.kind == "portfolio":
            return None
        return (self.instrument, self.timeframe)

    def rules_dict(self) -> Dict[str, Any]:
        """The trading rules only (no expectations): what the fingerprint covers."""
        return {"account_id": self.account_id, "role": self.role, "kind": self.kind, "instrument": self.instrument,
                "timeframe": self.timeframe, "sleeve": None if self.sleeve is None else self.sleeve.to_dict(),
                "portfolio": None if self.portfolio is None else self.portfolio.to_dict()}

    def to_dict(self) -> Dict[str, Any]:
        out = self.rules_dict()
        out.update({"label": self.label, "shortlist_rank": self.shortlist_rank, "expectations": self.expectations})
        return out


@dataclass(frozen=True)
class FleetManifest:
    accounts: Tuple[AccountSpec, ...]
    sources: Mapping[str, Any]
    costs: Costs = COSTS
    init_cash: float = INIT_CASH

    def __post_init__(self) -> None:
        ids = [a.account_id for a in self.accounts]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate account ids in the fleet manifest")

    def account(self, account_id: str) -> AccountSpec:
        for a in self.accounts:
            if a.account_id == account_id:
                return a
        raise KeyError(account_id)

    def series(self) -> List[Tuple[str, str]]:
        """Every (instrument, timeframe) the fleet trades, including the portfolio's sleeves."""
        out: List[Tuple[str, str]] = []
        for a in self.accounts:
            pairs = [s.series for _, s in a.portfolio.sleeves] if a.portfolio is not None else [a.series]
            for p in pairs:
                if p not in out:
                    out.append(p)
        return sorted(out)

    def fleet_rules(self) -> Dict[str, Any]:
        """Rules every account shares (costs, starting cash, the S0 filter, the regime geometry)."""
        return _canonical({
            "costs": {"fee_rate": self.costs.fee_rate, "slippage_rate": self.costs.slippage_rate},
            "init_cash": self.init_cash, "no_trade": NO_TRADE.label, "train_days": TRAIN_DAYS, "purge_days": PURGE_DAYS,
            "refit_days": REFIT_DAYS, "test_window_days": TEST_WINDOW_DAYS, "rebalance_threshold": REBALANCE_THRESHOLD,
        })

    def rules(self) -> Dict[str, Any]:
        return _canonical(dict(self.fleet_rules(), accounts=[a.rules_dict() for a in self.accounts]))

    def fleet_fingerprint(self) -> str:
        return _sha(self.fleet_rules())

    def fingerprint(self) -> str:
        """The whole fleet: shared rules and every account's rules."""
        return _sha(self.rules())

    def to_dict(self) -> Dict[str, Any]:
        return {"fingerprint": self.fingerprint(), "fleet_fingerprint": self.fleet_fingerprint(), "sources": dict(self.sources), "init_cash": self.init_cash,
                "costs": {"fee_rate": self.costs.fee_rate, "slippage_rate": self.costs.slippage_rate},
                "no_trade": NO_TRADE.label, "accounts": [a.to_dict() for a in self.accounts]}


# -- loading ---------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _regime(raw: Mapping[str, Any]) -> RegimeV2Config:
    keys = ("mode", "n_states", "vol_window_days", "bear_prob_max", "bear_scale", "n_iter", "tol", "min_train_bars")
    return RegimeV2Config(**{k: raw[k] for k in keys if k in raw})


def _sizing(raw: Optional[Mapping[str, Any]]) -> Optional[SizingSpec]:
    if raw is None:
        return None
    keys = ("kind", "fraction", "target_vol", "vol_lookback", "crash_dd", "crash_window_days", "crash_mode", "ladder", "cap")
    return SizingSpec(**{k: raw[k] for k in keys if k in raw})


def _result_for(results: Sequence[Mapping[str, Any]], candidate: str, instrument: str, timeframe: str, mode: str) -> Mapping[str, Any]:
    found = [r for r in results if r["candidate"] == candidate and r["instrument"] == instrument and r["timeframe"] == timeframe
             and r["regime"]["mode"] == mode]
    if len(found) != 1:
        raise ValueError(f"expected one research result for {candidate} {instrument} {timeframe} [{mode}], found {len(found)}")
    return found[0]


_WF_KEYS = ("cagr", "ann_vol", "sharpe", "sortino", "max_drawdown", "calmar", "profit_factor", "n_trades", "trades_per_year",
            "win_rate", "exposure", "avg_allocation", "fees_pct_per_year", "bars", "total_return")
_HOLDOUT_KEYS = ("total_return", "cagr", "ann_vol", "sharpe", "max_drawdown", "calmar", "profit_factor", "n_trades",
                 "trades_per_year", "win_rate", "bars", "avg_allocation")


def _expectations(result: Mapping[str, Any], timeframe: str) -> Dict[str, Any]:
    from research.data import bars_per_year

    oos = result.get("oos") or {}
    wf = {k: oos.get(k) for k in _WF_KEYS}
    wf["years"] = (oos.get("bars") or 0) / bars_per_year(timeframe)
    yg = result.get("yearly_gate") or {}
    wf["rolling_12m_positive_share"] = yg.get("rolling_positive_share")
    wf["worst_calendar_year_return"] = yg.get("worst_calendar_year_return")
    acc = result.get("acceptance") or {}
    out: Dict[str, Any] = {"walk_forward": wf, "passed_walk_forward": bool(acc.get("passed")), "failed_gates": list(acc.get("failed") or [])}
    hold = result.get("holdout")
    out["holdout"] = None if not hold else {k: hold.get(k) for k in _HOLDOUT_KEYS}
    return out


def load_manifest(shortlist_path: Path = DEFAULT_SHORTLIST, results_path: Path = DEFAULT_RESULTS) -> FleetManifest:
    """Build the fleet from the shortlist and the results file (fails loudly on any mismatch)."""
    shortlist = json.loads(Path(shortlist_path).read_text(encoding="utf-8"))
    results_doc = json.loads(Path(results_path).read_text(encoding="utf-8"))
    if shortlist.get("status") != SHORTLIST_STATUS:
        raise ValueError(f"the shortlist must be labelled {SHORTLIST_STATUS!r}")
    results = results_doc["results"]
    meta = results_doc.get("meta") or {}
    policy = _sizing(shortlist["sizing_proposal"])
    if meta.get("rebalance_threshold") not in (None, REBALANCE_THRESHOLD):
        raise ValueError("the research rebalance threshold differs from the fleet's")
    accounts: List[AccountSpec] = []

    for row in shortlist["configurations"]:
        regime = _regime(row["regime_config"])
        result = _result_for(results, row["candidate"], row["instrument"], row["timeframe"], regime.mode)
        params = _params(row["params"])
        if _params(result["selected_params"]) != params or not math.isclose(float(result["oos"]["cagr"]), float(row["cagr"]), abs_tol=1e-9):
            raise ValueError(f"shortlist row {row['rank']} does not match the results file")
        sleeve = SleeveSpec(row["candidate"], row["instrument"], row["timeframe"], params, regime, _sizing(row["sizing_config"]),
                            REBALANCE_THRESHOLD)
        aid = f"c{int(row['rank']):02d}-{_slug(row['candidate'])}-{_inst(row['instrument'])}-{row['timeframe'].lower()}-{regime.mode}"
        exp = _expectations(result, row["timeframe"])
        exp["holdout_confirmed"] = row.get("holdout_confirmed")
        accounts.append(AccountSpec(aid, "candidate", "sleeve", f"{row['candidate']} {row['instrument']} {row['timeframe']} ({regime.label})",
                                    sleeve=sleeve, instrument=row["instrument"], timeframe=row["timeframe"],
                                    shortlist_rank=int(row["rank"]), expectations=exp))

    for row in shortlist["controls"]:
        inst, tf = row["instrument"], row["timeframe"]
        if row["candidate"] == "hold":
            regime = _regime(row["regime_config"])
            result = _result_for(results, "hold", inst, tf, regime.mode)
            sleeve = SleeveSpec("hold", inst, tf, _params(row["params"]), regime, _sizing(row["sizing_config"]), REBALANCE_THRESHOLD)
            accounts.append(AccountSpec(f"ctl-hold-{_inst(inst)}-{tf.lower()}", "control", "sleeve",
                                        f"control: always long, policy sizing — {inst} {tf}", sleeve=sleeve, instrument=inst,
                                        timeframe=tf, expectations=_expectations(result, tf)))
        elif row["candidate"] == "buy_and_hold":
            wf = {k: row.get(k) for k in ("cagr", "sharpe", "calmar", "max_drawdown", "total_return")}
            accounts.append(AccountSpec(f"ctl-bh-{_inst(inst)}-{tf.lower()}", "control", "buy_and_hold",
                                        f"control: plain buy-and-hold — {inst} {tf}", instrument=inst, timeframe=tf,
                                        expectations={"walk_forward": wf, "holdout": None, "benchmark": True}))
        else:
            raise ValueError(f"unknown control {row['candidate']!r}")

    portfolio = _portfolio_from_results(results_doc)
    if portfolio is not None:
        spec, exp = portfolio
        accounts.append(AccountSpec("pf-s1s2s4-btceth-vt15", "portfolio", "portfolio", PORTFOLIO_NAME, portfolio=spec, expectations=exp))
    return FleetManifest(
        accounts=tuple(accounts),
        sources={"shortlist": str(Path(shortlist_path).as_posix()), "shortlist_sha256": _sha256(shortlist_path),
                 "results": str(Path(results_path).as_posix()), "results_sha256": _sha256(results_path),
                 "shortlist_generated_at": shortlist.get("generated_at"), "positioning_source_research": meta.get("positioning_source")},
    )


def _portfolio_from_results(results_doc: Mapping[str, Any]) -> Optional[Tuple[PortfolioSpec, Dict[str, Any]]]:
    """The jointly sized 15 % portfolio (no regime gate): its sleeves and its walk-forward numbers."""
    entries = [p for p in results_doc.get("portfolios", []) if p.get("regime") == "none" and (p.get("sizing") or {}).get("target_vol") == PORTFOLIO_TARGET_VOL]
    if not entries:
        return None
    entry = entries[0]
    sizing = entry["sizing"]
    if sizing.get("vol_lookback_days") != PORTFOLIO_VOL_LOOKBACK_DAYS or sizing.get("weight_lookback_days") != PORTFOLIO_WEIGHT_LOOKBACK_DAYS:
        raise ValueError("the research portfolio sizing differs from the fleet's")
    lad = sizing.get("ladder") or {}
    if not (math.isclose(lad.get("half_dd", -1), PORTFOLIO_LADDER.half_dd) and math.isclose(lad.get("flat_dd", -1), PORTFOLIO_LADDER.flat_dd)
            and int(lad.get("recovery_bars", -1)) == PORTFOLIO_LADDER.recovery_bars):
        raise ValueError("the research portfolio ladder differs from the fleet's")
    sleeves: List[Tuple[str, SleeveSpec]] = []
    instruments = {i.split("-")[0]: i for i in INSTRUMENTS}
    for name in sorted(entry["weights"]):
        family, short, tf = name.split("/")
        inst = instruments[short]
        result = _result_for(results_doc["results"], family, inst, tf, "none")
        sleeves.append((name, SleeveSpec(family, inst, tf, _params(result["selected_params"]), RegimeV2Config(mode="none"), None, None)))
    metrics = entry["metrics"]
    days = float(entry.get("days") or 0)
    wf = {k: metrics.get(k) for k in ("cagr", "ann_vol", "sharpe", "sortino", "max_drawdown", "calmar", "total_return")}
    wf["years"] = days / 365.25 if days else None
    wf["n_trades"] = entry.get("pooled_trades")
    wf["profit_factor"] = entry.get("pooled_profit_factor")
    wf["trades_per_year"] = (entry.get("pooled_trades") or 0) / (days / 365.25) if days else None
    yg = entry.get("yearly_gate") or {}
    wf["rolling_12m_positive_share"] = yg.get("rolling_positive_share")
    wf["worst_calendar_year_return"] = yg.get("worst_calendar_year_return")
    acc = entry.get("acceptance") or {}
    exp = {"walk_forward": wf, "holdout": None, "passed_walk_forward": bool(acc.get("passed")), "failed_gates": list(acc.get("failed") or []),
           "note": "built from out-of-sample sleeves with a mild timeframe selection; no holdout of its own"}
    return PortfolioSpec(sleeves=tuple(sleeves)), exp
