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

Plan row R5b adds a second portfolio account on the same six sleeves,
``pf-s1s2s4-btceth-vt15-alloc2``: allocator v2 (``research.allocator``, its
brakes fixed before the first run) with its expectations from
``docs/research/allocator_v2_results.json``. A portfolio spec without an
allocator is allocator v1 and keeps exactly the rules (and fingerprint) it had.

Plan row R12 (the replication study) may append configurations confirmed on
other OKX spot markets to the shortlist, each with a ``source`` tag naming the
study and its results file (``docs/research/replication_v1d_results.json``);
such a row is validated against that file exactly as a Sprint 2c row is
against ``ensemble_v1c_results.json``, and becomes one more sleeve account.
Existing accounts, the fleet's shared rules and their fingerprints do not
change; the fleet fetches public data for the markets its accounts need
(:meth:`FleetManifest.instruments`).

Plan row R18b (Trader Policy v1): a ``source``-tagged row may also name a
documented sizing tier and its brakes (``source.tier``, ``source.brakes``,
``source.variant``, ``source.protocol_variant``, ``source.cell``). Such a row
is matched in the study's results on the candidate / instrument / timeframe /
mode AND the cell (``results[].cell.key``), and accepted only when the recorded
protocol check of that cell has no unexplained mismatch, the tier named is the
one ``research.trader_policy.tier_for`` reads from the result's sizing and
brakes, the brakes recorded with the row are the brakes the cell ran with, no
variant was on, and the row's sizing is the result's. It becomes a NEW account
(its id carries the tier) whose sleeve runs that sizing and those brakes; a row
whose ``source.role`` is ``control`` (the "always long above the 200-day
average, policy sizing" forward control) becomes a control account. Everything
else about the loader, every existing account and the shared rules are
unchanged.

Plan row R19 (research round 3): a candidate row may also name the FIXED-RULE
protocol variant (``source.protocol_variant``: the exit bracket fixed and never
selected, no train-trade qualification) - only for a rule registered in
``research.strategies.FIXED_RULES``, only when the study's recorded protocol
check of that cell names the same variant, and with the same two explained
deviations (``brackets``, ``min_trades``) the slow-trend control already has.
Such a row becomes an ordinary tier-tagged candidate account; the fleet runs
the rule's one parameter set with the bracket the row carries.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from research.allocator import DEFAULT_ALLOCATOR_V2, AllocatorV2Config
from research.brakes import BrakeSpec
from research.engine import Costs
from research.markets import REPLICATION_CANDIDATES
from research.regime_v2 import RegimeV2Config
from research.sizing import LadderConfig, SizingSpec
from research.strategies import FIXED_RULES, get_candidate
from research.strategies.base import days_to_bars
from research.strategies.s0_filters import NoTradeConfig

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SHORTLIST = ROOT / "docs" / "research" / "paper_fleet_shortlist_v1c.json"
DEFAULT_RESULTS = ROOT / "docs" / "research" / "ensemble_v1c_results.json"
DEFAULT_ALLOCATOR_RESULTS = ROOT / "docs" / "research" / "allocator_v2_results.json"
SHORTLIST_STATUS = "forward evidence only; nothing approved"

INSTRUMENTS: Tuple[str, ...] = ("BTC-USDT", "ETH-USDT")  # the Sprint 2c markets: the controls and the portfolio live here
#: Markets an account may trade: the Sprint 2c pair plus the replication study's markets (plan row R12), whose public candle
#: path and swap names the fleet knows. This never widens the app's ``ALLOWED_INSTRUMENTS`` (demo and paper trading).
ALLOWED_INSTRUMENTS: Tuple[str, ...] = INSTRUMENTS + tuple(sorted(REPLICATION_CANDIDATES))
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
PORTFOLIO_ACCOUNT = "pf-s1s2s4-btceth-vt15"
ALLOCATOR_V2_ACCOUNT = "pf-s1s2s4-btceth-vt15-alloc2"
ALLOCATOR_V2_NAME = ("S1+S2+S4 x BTC+ETH — allocator v2: vol target 15%, ladder 7.5/15, correlation cap 50%, "
                     "weekly loss limit 5% with a 7-day cooldown")
# Candidates whose own signal frame carries exits beyond the stop (S3's time stop): the fleet takes exits only from the
# rule's stop and the bracket, so it refuses them rather than silently dropping an exit (tested for every other candidate).
OWN_EXIT_CANDIDATES = frozenset({"S3"})
#: Plan row R18b: the one study whose rows may name a tier, and the sizing tier of every account without a tag.
REFERENCE_TIER = "reference"
TF_CONTROL_CANDIDATE = "TF"  # the "always long above the 200-day average, policy sizing" forward control (research.strategies.round2)
# The protocol deviations a study may have recorded as explained for a row the fleet accepts: a tier replaces the policy sizing
# by design; the fixed-rule control runs without an exit bracket and without the 20-train-trade qualification. Anything else refuses.
_EXPLAINED_MISMATCHES_CANDIDATE = frozenset({"policy_sizing"})
_EXPLAINED_MISMATCHES_CONTROL = frozenset({"policy_sizing", "brackets", "min_trades"})
#: Plan row R19: a candidate row may name the fixed-rule protocol variant (the exit bracket fixed, no train-trade qualification) only for a
#: registered fixed rule (``research.strategies.FIXED_RULES``: one parameter set, nothing selected); it explains the same two deviations.
_EXPLAINED_MISMATCHES_FIXED_RULE = _EXPLAINED_MISMATCHES_CONTROL


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
    brakes: Optional[BrakeSpec] = None  # plan row R18b: a higher tier's entry brakes (None = no brake, the rules as they were)

    def __post_init__(self) -> None:
        get_candidate(self.candidate)  # unknown candidate -> ValueError
        if self.candidate in OWN_EXIT_CANDIDATES:
            raise ValueError(f"{self.candidate} brings its own exits (time stop / target), which the fleet's decisions do not carry")
        if self.instrument not in ALLOWED_INSTRUMENTS:
            raise ValueError(f"instrument {self.instrument!r} is not in the fleet's allowed markets ({ALLOWED_INSTRUMENTS})")
        if self.timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe {self.timeframe!r} is not in the fleet ({TIMEFRAMES})")
        if self.brakes is not None and self.sizing is None:
            raise ValueError("brakes belong to a sized sleeve (a tier); a full-size sleeve carries none")

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
        out = {
            "candidate": self.candidate, "instrument": self.instrument, "timeframe": self.timeframe,
            "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.params.items()},
            "regime": self.regime.to_dict(), "sizing": None if self.sizing is None else self.sizing.to_dict(),
            "rebalance_threshold": self.rebalance_threshold,
            "ladder": None if self.ladder() is None else self.ladder().to_dict(),
        }
        if self.brakes is not None:  # absent without brakes, so every existing account's rules (and fingerprint) are what they were
            out["brakes"] = {k: v for k, v in self.brakes.to_dict().items() if k != "label"}
        return out


@dataclass(frozen=True)
class PortfolioSpec:
    sleeves: Tuple[Tuple[str, SleeveSpec], ...]  # (name like "S1/BTC/6H", full-size sleeve)
    target_vol: float = PORTFOLIO_TARGET_VOL
    vol_lookback_days: int = PORTFOLIO_VOL_LOOKBACK_DAYS
    weight_lookback_days: int = PORTFOLIO_WEIGHT_LOOKBACK_DAYS
    ladder: LadderConfig = PORTFOLIO_LADDER
    cap: float = 1.0
    warmup_days: int = PORTFOLIO_WARMUP_DAYS
    allocator: Optional[AllocatorV2Config] = None  # None = allocator v1 (combine_sized); a config = allocator v2's brakes on top

    @property
    def sleeve_assets(self) -> Dict[str, str]:
        return {name: s.instrument for name, s in self.sleeves}

    def to_dict(self) -> Dict[str, Any]:
        out = {"sleeves": {name: s.to_dict() for name, s in self.sleeves}, "target_vol": self.target_vol,
               "vol_lookback_days": self.vol_lookback_days, "weight_lookback_days": self.weight_lookback_days,
               "ladder": self.ladder.to_dict(), "cap": self.cap, "warmup_days": self.warmup_days}
        if self.allocator is not None:  # absent for v1, so the v1 account's rules (and fingerprint) are what they were
            out["allocator"] = {k: v for k, v in self.allocator.to_dict().items() if k != "label"}
        return out


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
    tier: Optional[str] = None  # plan row R18b: the named sizing tier of a tier-tagged row (display; the rules carry the tier itself)

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
        if self.tier is not None:
            out["tier"] = self.tier
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

    def instruments(self) -> List[str]:
        """Every market the fleet needs public data for (the instruments of :meth:`series`)."""
        return sorted({inst for inst, _ in self.series()})

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
    # risk_cap / risk_fraction (plan row R18) appear only in a tier's sizing; a Sprint 2c row has neither and reads as it always did.
    keys = ("kind", "fraction", "target_vol", "vol_lookback", "crash_dd", "crash_window_days", "crash_mode", "ladder", "cap", "risk_cap", "risk_fraction")
    return SizingSpec(**{k: raw[k] for k in keys if k in raw})


def _result_for(results: Sequence[Mapping[str, Any]], candidate: str, instrument: str, timeframe: str, mode: str,
                cell: Optional[str] = None) -> Mapping[str, Any]:
    """The one stored result of a configuration; a study with several cells per configuration (plan row R18) needs the cell named."""
    found = [r for r in results if r["candidate"] == candidate and r["instrument"] == instrument and r["timeframe"] == timeframe
             and r["regime"]["mode"] == mode and (cell is None or ((r.get("cell") or {}).get("key") == cell))]
    if len(found) != 1:
        where = f" @ {cell}" if cell else ""
        raise ValueError(f"expected one research result for {candidate} {instrument} {timeframe} [{mode}]{where}, found {len(found)}")
    return found[0]


def _tier_checks(row: Mapping[str, Any], result: Mapping[str, Any], src: Mapping[str, Any]) -> Tuple[str, Optional[BrakeSpec]]:
    """Plan row R18b: accept a tier-tagged row only when the study's own record of that cell says exactly what the row says.

    Returns ``(tier, brakes)``. Refuses: a cell the study did not run; a recorded protocol check with any unexplained mismatch (or
    an explained one the fleet does not know); a tier name that is not what the result's sizing and brakes describe
    (``research.trader_policy.tier_for``); brakes that differ from the cell's; a variant; a sizing that is not the result's.
    """
    from research.trader_policy import tier_for  # imported late: the research policy module is heavier than the fleet's loader

    name = f"{row['candidate']} {row['instrument']} {row['timeframe']} [{(row.get('regime_config') or {}).get('mode')}]"
    tier = src.get("tier")
    if not tier:
        raise ValueError(f"{name}: a row that names a cell must name its tier")
    cell = result.get("cell") or {}
    if cell.get("key") != src.get("cell"):
        raise ValueError(f"{name}: the result's cell {cell.get('key')!r} is not the row's {src.get('cell')!r}")
    if str(src.get("variant") or "none") != "none" or str(cell.get("variant") or "none") != "none":
        raise ValueError(f"{name}: the fleet runs the base rule only; a variant ({src.get('variant')!r} / {cell.get('variant')!r}) is refused")
    check = result.get("protocol_check") or {}
    unexplained = check.get("unexplained_mismatches")
    if unexplained is None or unexplained or not check.get("ok_for_cell", False):
        raise ValueError(f"{name}: the study's protocol check of cell {src.get('cell')!r} is not clean ({unexplained!r})")
    fixed_rule = src.get("role") != "control" and bool(src.get("protocol_variant"))
    if fixed_rule and row["candidate"] not in FIXED_RULES:
        raise ValueError(f"{name}: a candidate row may carry a protocol variant only for a registered fixed rule ({sorted(FIXED_RULES)}), "
                         f"not {row['candidate']!r}")
    allowed = (_EXPLAINED_MISMATCHES_CONTROL if src.get("role") == "control" else
               _EXPLAINED_MISMATCHES_FIXED_RULE if fixed_rule else _EXPLAINED_MISMATCHES_CANDIDATE)
    explained = set((check.get("expected_mismatches") or {}).keys())
    if not explained <= allowed:
        raise ValueError(f"{name}: the study explained protocol mismatches the fleet does not accept ({sorted(explained - allowed)})")
    if src.get("role") == "control":
        if not src.get("protocol_variant"):
            raise ValueError(f"{name}: a control row needs its protocol variant named")
    elif fixed_rule:
        # Plan row R19: the study's own record of the cell must name the same protocol variant, and the row's bracket must be the one it fixed.
        recorded = check.get("protocol_variant")
        if recorded != src.get("protocol_variant"):
            raise ValueError(f"{name}: the row names the protocol variant {src.get('protocol_variant')!r}, the study recorded {recorded!r}")
        if {"brackets", "min_trades"} & explained != {"brackets", "min_trades"} & set(check.get("mismatches") or {}):
            raise ValueError(f"{name}: the fixed-rule protocol's recorded deviations do not match the study's protocol check")
    raw_brakes = src.get("brakes")
    ran_with = (result.get("r18") or {}).get("brakes")
    if raw_brakes != ran_with:
        raise ValueError(f"{name}: the brakes recorded with the row are not the brakes cell {src.get('cell')!r} ran with")
    sizing = result.get("policy_sizing")
    if dict(row.get("sizing_config") or {}) != dict(sizing or {}):
        raise ValueError(f"{name}: the row's sizing is not the result's policy sizing")
    read = tier_for(sizing, raw_brakes)
    if read != tier or cell.get("tier") != tier:
        raise ValueError(f"{name}: the row names tier {tier!r}, but the result's sizing and brakes describe {read!r} (cell tier {cell.get('tier')!r})")
    brakes = None if raw_brakes is None else BrakeSpec.from_dict(raw_brakes)
    if brakes is not None and brakes.to_dict() != dict(raw_brakes):
        raise ValueError(f"{name}: the recorded brakes do not round-trip through the fleet's brake spec")
    return str(tier), brakes


def _flat_results(doc: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """Sprint 2c's results file holds one flat ``results`` list; a study file (plan row R12) holds one list per series."""
    if isinstance(doc.get("results"), list):
        return list(doc["results"])
    return [r for s in doc.get("series", []) for r in s.get("results", [])]


def _source_results(source: Any, cache: Dict[Path, List[Mapping[str, Any]]]) -> Tuple[Path, List[Mapping[str, Any]]]:
    """The results of the study a ``source``-tagged shortlist row points at (a path relative to the repository root), read once.

    The study must have run Sprint 2c's protocol (its results carry the protocol check); anything else is refused, so a row can
    never bring rules the fleet does not share."""
    rel = source.get("results") if isinstance(source, Mapping) else None
    if not rel:
        raise ValueError("a source-tagged shortlist row needs its study's results file")
    path = Path(rel) if Path(rel).is_absolute() else ROOT / rel
    if path not in cache:
        doc = json.loads(path.read_text(encoding="utf-8"))
        check = (doc.get("meta") or {}).get("protocol_check")
        if check is not None and not check.get("ok"):
            raise ValueError(f"{rel}: the study did not run Sprint 2c's protocol ({check.get('mismatches')})")
        cache[path] = _flat_results(doc)
    return path, cache[path]


_WF_KEYS = ("cagr", "ann_vol", "sharpe", "sortino", "max_drawdown", "calmar", "profit_factor", "n_trades", "trades_per_year",
            "win_rate", "exposure", "avg_allocation", "fees_pct_per_year", "bars", "total_return")
_HOLDOUT_KEYS = ("total_return", "cagr", "ann_vol", "sharpe", "max_drawdown", "calmar", "profit_factor", "n_trades",
                 "trades_per_year", "win_rate", "bars", "avg_allocation")


def _expectations(result: Mapping[str, Any], timeframe: str, *, tier: Optional[str] = None) -> Dict[str, Any]:
    from research.data import bars_per_year

    oos = result.get("oos") or {}
    wf = {k: oos.get(k) for k in _WF_KEYS}
    wf["years"] = (oos.get("bars") or 0) / bars_per_year(timeframe)
    yg = result.get("yearly_gate") or {}
    wf["rolling_12m_positive_share"] = yg.get("rolling_positive_share")
    wf["worst_calendar_year_return"] = yg.get("worst_calendar_year_return")
    acc = result.get("acceptance") or {}
    gates = "Sprint 2c"
    if tier is not None and tier != REFERENCE_TIER and result.get("acceptance_r18"):
        acc = result["acceptance_r18"]  # a higher tier is judged by the plan's section 4.6 gates (drawdown / worst year at the tier's limits)
        gates = f"section 4.6 at the {tier} tier"
    out: Dict[str, Any] = {"walk_forward": wf, "passed_walk_forward": bool(acc.get("passed")), "failed_gates": list(acc.get("failed") or []), "gates": gates}
    hold = result.get("holdout")
    out["holdout"] = None if not hold else {k: hold.get(k) for k in _HOLDOUT_KEYS}
    if tier is not None:
        r18 = result.get("r18") or {}
        trades = r18.get("trades") or {}
        summary = r18.get("brake_summary") or {}
        years = wf["years"] or 0.0
        out["tier"] = {
            "name": tier, "sizing": (result.get("policy_sizing") or {}).get("label"), "brakes": (r18.get("brakes") or {}).get("label"),
            "risk_pct_mean": trades.get("risk_pct_mean"), "risk_pct_max": trades.get("risk_pct_max"),
            "cap_binding_share": (r18.get("cap") or {}).get("cap_binding_share"), "expectancy_r": trades.get("expectancy_r"),
            "payoff_ratio": trades.get("payoff_ratio"), "gap_trades": trades.get("gap_trades"),
            "brake_counts": dict(summary.get("counts") or {}), "brake_trips": dict(summary.get("trips") or {}),
            "brake_opportunities": summary.get("opportunities"), "brakes_per_year": None if not years else
            {k: float(v) / years for k, v in (summary.get("counts") or {}).items()},
        }
    return out


def load_manifest(shortlist_path: Path = DEFAULT_SHORTLIST, results_path: Path = DEFAULT_RESULTS,
                  allocator_results_path: Path = DEFAULT_ALLOCATOR_RESULTS) -> FleetManifest:
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
    source_docs: Dict[Path, List[Mapping[str, Any]]] = {}
    source_files: Dict[str, Path] = {}

    for row in shortlist["configurations"]:
        regime = _regime(row["regime_config"])
        src = row.get("source")
        tier: Optional[str] = None
        brakes: Optional[BrakeSpec] = None
        if src:
            path, pool = _source_results(src, source_docs)
            source_files[_slug(str(src.get("study") or "source"))] = path
            if src.get("role") not in (None, "candidate"):
                raise ValueError(f"shortlist row {row.get('rank')}: a {src.get('role')!r} row belongs under 'controls', not 'configurations'")
        else:
            pool = results
        result = _result_for(pool, row["candidate"], row["instrument"], row["timeframe"], regime.mode, cell=(src or {}).get("cell"))
        if src and (src.get("cell") or src.get("tier")):
            tier, brakes = _tier_checks(row, result, src)
        params = _params(row["params"])
        if _params(result["selected_params"]) != params or not math.isclose(float(result["oos"]["cagr"]), float(row["cagr"]), abs_tol=1e-9):
            raise ValueError(f"shortlist row {row['rank']} does not match the results file")
        sleeve = SleeveSpec(row["candidate"], row["instrument"], row["timeframe"], params, regime, _sizing(row["sizing_config"]),
                            REBALANCE_THRESHOLD, brakes)
        aid = f"c{int(row['rank']):02d}-{_slug(row['candidate'])}-{_inst(row['instrument'])}-{row['timeframe'].lower()}-{regime.mode}"
        if tier is not None and tier != REFERENCE_TIER:
            aid += f"-{_slug(tier)}"  # the same rule at another tier is another account; the Reference twin keeps its id
        exp = _expectations(result, row["timeframe"], tier=tier)
        exp["holdout_confirmed"] = row.get("holdout_confirmed")
        label = f"{row['candidate']} {row['instrument']} {row['timeframe']} ({regime.label})"
        if tier is not None and tier != REFERENCE_TIER:
            label += f" — {tier} tier ({sleeve.sizing.label}{', brakes on' if brakes is not None and brakes.active else ''})"
        if src:
            exp["source"] = dict(src)
            if src.get("protocol_variant"):  # plan row R19: a fixed rule under the fixed-rule protocol variant
                exp["protocol_variant"] = src.get("protocol_variant")
            label += f" — from {src.get('study')}"
        accounts.append(AccountSpec(aid, "candidate", "sleeve", label, sleeve=sleeve, instrument=row["instrument"], timeframe=row["timeframe"],
                                    shortlist_rank=int(row["rank"]), expectations=exp, tier=tier))

    for row in shortlist["controls"]:
        inst, tf = row["instrument"], row["timeframe"]
        src = row.get("source")
        if row["candidate"] == "hold":
            regime = _regime(row["regime_config"])
            result = _result_for(results, "hold", inst, tf, regime.mode)
            sleeve = SleeveSpec("hold", inst, tf, _params(row["params"]), regime, _sizing(row["sizing_config"]), REBALANCE_THRESHOLD)
            accounts.append(AccountSpec(f"ctl-hold-{_inst(inst)}-{tf.lower()}", "control", "sleeve",
                                        f"control: always long, policy sizing — {inst} {tf}", sleeve=sleeve, instrument=inst,
                                        timeframe=tf, expectations=_expectations(result, tf)))
        elif row["candidate"] == TF_CONTROL_CANDIDATE and src:
            # Plan row R18b: the slow-trend forward control, recorded by the Trader Policy study at the Reference sizing (fixed rule).
            if src.get("role") != "control":
                raise ValueError(f"control {row['candidate']} {inst} {tf}: its source tag must name the control role")
            path, pool = _source_results(src, source_docs)
            source_files[_slug(str(src.get("study") or "source"))] = path
            regime = _regime(row["regime_config"])
            result = _result_for(pool, row["candidate"], inst, tf, regime.mode, cell=src.get("cell"))
            tier, brakes = _tier_checks(row, result, src)
            if tier != REFERENCE_TIER or brakes is not None:
                raise ValueError(f"control {row['candidate']} {inst} {tf}: a forward control runs at the Reference sizing without brakes")
            params = _params(row["params"])
            if _params(result["selected_params"]) != params or not math.isclose(float(result["oos"]["cagr"]), float(row["cagr"]), abs_tol=1e-9):
                raise ValueError(f"control {row['candidate']} {inst} {tf} does not match the results file")
            sleeve = SleeveSpec(row["candidate"], inst, tf, params, regime, _sizing(row["sizing_config"]), REBALANCE_THRESHOLD)
            exp = _expectations(result, tf, tier=tier)
            exp["holdout_confirmed"] = row.get("holdout_confirmed")  # None: a control is never judged
            exp["source"] = dict(src)
            exp["protocol_variant"] = src.get("protocol_variant")
            label = row.get("control_label") or "always long above the 200-day average, policy sizing (forward control)"
            accounts.append(AccountSpec(f"ctl-{_slug(row['candidate'])}-{_inst(inst)}-{tf.lower()}", "control", "sleeve",
                                        f"control: {label} — {inst} {tf} — from {src.get('study')}", sleeve=sleeve, instrument=inst,
                                        timeframe=tf, expectations=exp, tier=tier))
        elif row["candidate"] == "buy_and_hold":
            wf = {k: row.get(k) for k in ("cagr", "sharpe", "calmar", "max_drawdown", "total_return")}
            accounts.append(AccountSpec(f"ctl-bh-{_inst(inst)}-{tf.lower()}", "control", "buy_and_hold",
                                        f"control: plain buy-and-hold — {inst} {tf}", instrument=inst, timeframe=tf,
                                        expectations={"walk_forward": wf, "holdout": None, "benchmark": True}))
        else:
            raise ValueError(f"unknown control {row['candidate']!r}")

    portfolio = _portfolio_from_results(results_doc)
    sources = {"shortlist": str(Path(shortlist_path).as_posix()), "shortlist_sha256": _sha256(shortlist_path),
               "results": str(Path(results_path).as_posix()), "results_sha256": _sha256(results_path),
               "shortlist_generated_at": shortlist.get("generated_at"), "positioning_source_research": meta.get("positioning_source")}
    for slug, path in sorted(source_files.items()):
        sources[f"results_{slug}"] = str(path.as_posix())
        sources[f"results_{slug}_sha256"] = _sha256(path)
    if portfolio is not None:
        spec, exp = portfolio
        accounts.append(AccountSpec(PORTFOLIO_ACCOUNT, "portfolio", "portfolio", PORTFOLIO_NAME, portfolio=spec, expectations=exp))
        # Plan row R5b: the same six sleeves under allocator v2 (a new account: the v1 account and its record are untouched).
        v2 = dataclasses.replace(spec, allocator=DEFAULT_ALLOCATOR_V2)
        accounts.append(AccountSpec(ALLOCATOR_V2_ACCOUNT, "portfolio", "portfolio", ALLOCATOR_V2_NAME, portfolio=v2,
                                    expectations=allocator_expectations(allocator_results_path, v2)))
        sources.update({"allocator_results": str(Path(allocator_results_path).as_posix()), "allocator_results_sha256": _sha256(allocator_results_path)})
    return FleetManifest(accounts=tuple(accounts), sources=sources)


def allocator_expectations(path: Path, spec: PortfolioSpec) -> Dict[str, Any]:
    """The allocator-v2 account's expectations, from the study of exactly its sleeves and its brakes (fails loudly otherwise)."""
    from research.allocator_study import expectations_from_results

    result = json.loads(Path(path).read_text(encoding="utf-8"))
    if not str(result.get("status", "")).startswith("SIMULATION ONLY"):
        raise ValueError("the allocator results must be labelled SIMULATION ONLY")
    meta = result.get("meta") or {}
    studied = {s["name"]: (s["candidate"], s["instrument"], s["timeframe"], _params(s["params"])) for s in meta.get("sleeves", [])}
    running = {name: (s.candidate, s.instrument, s.timeframe, dict(s.params)) for name, s in spec.sleeves}
    if studied != running:
        raise ValueError("the allocator results were computed on other sleeves than the fleet's portfolio")
    if spec.allocator is None or AllocatorV2Config.from_dict(meta.get("allocator_v2") or {}) != spec.allocator:
        raise ValueError("the allocator results were computed with other brakes than the fleet's allocator-v2 account")
    settings = meta.get("settings") or {}
    lad = settings.get("ladder") or {}
    if (settings.get("target_vol"), settings.get("vol_lookback_days"), settings.get("weight_lookback_days")) != (
            spec.target_vol, spec.vol_lookback_days, spec.weight_lookback_days) or not (
            math.isclose(lad.get("half_dd", -1), spec.ladder.half_dd) and math.isclose(lad.get("flat_dd", -1), spec.ladder.flat_dd)
            and int(lad.get("recovery_bars", -1)) == spec.ladder.recovery_bars):
        raise ValueError("the allocator results were computed with another vol target or ladder than the fleet's portfolio")
    return expectations_from_results(result)


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
