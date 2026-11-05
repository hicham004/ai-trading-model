"""Replication study: the Sprint 2c rule families on OKX spot markets they were never tuned on (plan row R12, SIMULATION ONLY).

The question: do the Sprint 2c rules hold on other large OKX spot USDT markets,
or are they BTC-specific? Everything that defines the answer was fixed before
the first run — :data:`PREREGISTRATION` here, the market snapshot in
``docs/research/replication_v1d_preregistration.json`` — and the hash of both
goes into the results.

How the rules are run: this module does not copy Sprint 2c's logic. It loads
``scripts/run_research_v1c.py`` as a module (:func:`load_v1c_runner`) and calls
its ``run_series`` with Sprint 2c's own defaults for every market, after
:func:`protocol_check` has compared those defaults with the stored Sprint 2c
run (``docs/research/ensemble_v1c_results.json``) and after the same code path
has reproduced Sprint 2c's BTC-USDT and ETH-USDT numbers to 6 decimals
(:func:`reproduction_check`; the study stops otherwise). Public data only;
nothing here can reach an order; results never authorize trading.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
import pyarrow.compute as pc

from app.datalake.layout import LakeLayout
from app.datalake.okx_public_rest import OKXPublicRest
from app.datalake.parquet_store import CANDLE_SCHEMA, read_candles, write_partitioned
from research.markets import ALWAYS_INCLUDED, HISTORY_CUTOFF, RANKED_PICKS, REPLICATION_CANDIDATES, SPRINT_2C_INSTRUMENTS, research_symbol_for
from research.replication_data import BAR_MS, COLLECTED_BARS, TICKERS_PATH, candle_history_start
from research.report_v1c import _row, holdout_verdict

ROOT = Path(__file__).resolve().parents[1]
V1C_SCRIPT = ROOT / "scripts" / "run_research_v1c.py"
V1C_RESULTS = ROOT / "docs" / "research" / "ensemble_v1c_results.json"
PREREGISTRATION_PATH = ROOT / "docs" / "research" / "replication_v1d_preregistration.json"
STUDY_FAMILIES: Tuple[str, ...] = ("S1", "S1+S5", "S2", "S2+S5")
CONTROL = "hold"
STUDY_STRATEGIES: Tuple[str, ...] = (CONTROL, *STUDY_FAMILIES)
STUDY_MODES: Tuple[str, ...] = ("none", "gate")
STUDY_TIMEFRAMES: Tuple[str, ...] = ("4H", "6H")
#: Every market's candles end where Sprint 2c's BTC/ETH candles ended (bar close <= this instant), so the untouched
#: 12 months are the same calendar window as in Sprint 2c and R9: 2025-10-20 -> 2026-10-20.
DATA_END = "2026-10-20T10:00:00+00:00"
FUNDING_COVERAGE_MIN = 0.90  # master plan Sprint 2b item 6: S5 was re-run "with >= 90 % in-sample coverage"
STUDY_LAKE_DIRNAME = "lake_replication_v1d"


class ReplicationError(RuntimeError):
    """The study cannot be trusted (protocol mismatch, reproduction failure, missing data, a second look at a holdout)."""


PREREGISTRATION: Dict[str, Any] = {
    "fixed_on": "2026-11-04, before any candle of a new market was collected (plan row R12)",
    "question": "Do the Sprint 2c rule families hold on large OKX spot USDT markets they were never tuned on, or are they BTC-specific?",
    "markets": (f"the top {RANKED_PICKS} of the candidates with public 1H candles from before {HISTORY_CUTOFF} (XRP, LTC, ADA, LINK, BCH, DOGE, TRX, "
                f"ETC, XLM, ATOM, ALGO), ranked by public 24-hour quote volume (OKX {TICKERS_PATH}, SPOT, volCcy24h) at one snapshot taken before "
                f"any collection, plus {', '.join(ALWAYS_INCLUDED)}; the snapshot, the ranking and the chosen list are stored in "
                "docs/research/replication_v1d_preregistration.json"),
    "configurations": ("exactly Sprint 2c's: S1, S1+S5, S2, S2+S5 x 4H/6H x regime none/gate = 16 judged configurations per market; "
                       "hold + policy sizing and plain buy-and-hold as the controls (never judged, as in Sprint 2c); parameters, grids, brackets "
                       "(none/tp2/trail1/time30; none for the S5 families), the S0 filter with the FOMC calendar, the fixed policy sizing "
                       "vt10/30 crash15/90dh ladder (rebalance 0.25, ladder re-arm 30 days), the regime-v2 entry gate (3-state HMM on returns and "
                       "7-day vol, bear >= 0.5, fitted on every window's train slice), the walk-forward (train 540 d, purge 7 d, test 180 d, Sharpe "
                       "with >= 20 train trades, entries then bracket) and the v1c gates — run by scripts/run_research_v1c.py's own run_series, "
                       "not by a copy of it"),
    "data": (f"OKX public 1H and 4H spot candles through the GET-only lake client (4H stored, 6H resampled from 1H, as Sprint 2c's BTC/ETH data); "
             f"every market's candles end where Sprint 2c's did (bar close <= {DATA_END}), so the untouched 12 months are the same calendar "
             "window, 2025-10-20 -> 2026-10-20; Binance public funding of the market's USDT perpetual as the S5 feature, through the research "
             "symbol table; the new markets have no open-interest history, so that leg of the S5 filter passes (as it does wherever data is "
             f"missing); a market whose funding covers less than {FUNDING_COVERAGE_MIN * 100:.0f} % of its in-sample bars (Sprint 2b item 6) has its "
             "S5 configurations reported as 'run without S5' and never counted for the S1+S5 / S2+S5 families"),
    "reproduction": ("before any new market is judged, the same code path re-runs BTC-USDT and ETH-USDT (the 16 configurations and the hold control) "
                     "and must give Sprint 2c's stored walk-forward numbers to 6 decimals, the same trade counts, the same most-selected rules "
                     "and the same gate verdicts; otherwise the study stops"),
    "primary_test": ("the configurations that passed every gate on BTC-USDT in Sprint 2c (taken from the stored results: S2 4H gate, S2+S5 4H gate, "
                     "S1+S5 6H none) run unchanged on every new market; a configuration 'replicates' when it passes all v1c gates on at least half "
                     "of the new markets"),
    "family_verdicts": ("per family (S1, S1+S5, S2, S2+S5), a market counts when any of the family's four configurations passes all gates there: "
                        "'robust across markets' = at least half of the new markets; 'fragile' = at least one but fewer than half; "
                        "'BTC-specific' = none, for a family that passed on BTC in Sprint 2c; 'fails everywhere' = none, and it did not pass on BTC either"),
    "overall_verdict": ("'robust across markets' if any family is robust; 'fragile' if some configuration passes on a new market but no family is "
                        "robust; 'BTC-specific' if no configuration passes on any new market"),
    "holdout": ("each new market's last 12 months (2025-10-20 -> 2026-10-20), opened once, only for a configuration that passes every walk-forward "
                "gate on that market, and only by the full pre-registered study (every chosen market, family, timeframe and mode, no --quick); the "
                "v1c verdict (positive return, PF > 1, >= 10 trades); the hold + policy control's 12 months are evaluated on every market as the "
                "comparison line, as Sprint 2c did (a reference, not a configuration under test); every opening goes into an append-only ledger the "
                "report shows; the new markets' price moves over those months were not looked at before the run"),
    "gates": "the v1c gates unchanged (research/report_v1c.py GATES)",
    "fleet": ("a configuration confirmed by its holdout on a new market is added to the paper fleet's shortlist as a new account with a source tag "
              "(existing entries and running accounts untouched); a walk-forward pass alone adds nothing"),
    "no_changes_after_results": "no gate, parameter, market, threshold or verdict rule changes after the results are in; if a gate looks wrong the report says so",
}


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# -- configuration ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReplicationConfig:
    strategies: Tuple[str, ...] = STUDY_STRATEGIES
    regime_modes: Tuple[str, ...] = STUDY_MODES
    timeframes: Tuple[str, ...] = STUDY_TIMEFRAMES
    funding_coverage_min: float = FUNDING_COVERAGE_MIN
    data_end: str = DATA_END
    quick: bool = False
    lake_dir: Optional[str] = None  # the frozen study lake the Sprint 2c runner reads

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        for k in ("strategies", "regime_modes", "timeframes"):
            out[k] = list(getattr(self, k))
        return out

    @property
    def families(self) -> List[str]:
        return [s for s in self.strategies if s != CONTROL]


def preregistration_hash(cfg: ReplicationConfig, prereg: Mapping[str, Any]) -> str:
    """One hash over the fixed text, the market snapshot file and the configuration."""
    return _sha256_json({"preregistration": PREREGISTRATION, "snapshot": prereg, "config": cfg.to_dict()})


def full_study_requested(cfg: ReplicationConfig, markets: Sequence[str], chosen: Sequence[str]) -> bool:
    """The holdout may only be opened by the complete pre-registered set of configurations on every chosen market."""
    return (not cfg.quick and sorted(cfg.strategies) == sorted(STUDY_STRATEGIES) and sorted(cfg.regime_modes) == sorted(STUDY_MODES)
            and sorted(cfg.timeframes) == sorted(STUDY_TIMEFRAMES) and sorted(markets) == sorted(chosen) and len(chosen) > 0)


# -- the pre-registration step: markets chosen before any result --------------------------------

@dataclass(frozen=True)
class MarketPick:
    instrument: str
    quote_volume_24h: float
    history_before_cutoff: Optional[str]  # newest public 1H candle before HISTORY_CUTOFF (None = history starts later)
    rank: Optional[int]  # rank among the eligible ranked candidates by 24-hour quote volume
    chosen: bool
    reason: str


def rank_candidates(tickers: Sequence[Mapping[str, Any]], history: Mapping[str, Optional[str]], *, n: int = RANKED_PICKS,
                    always: Sequence[str] = ALWAYS_INCLUDED) -> List[MarketPick]:
    """Apply the pre-registered rule to a ticker snapshot: the top ``n`` eligible candidates by quote volume, plus ``always``."""
    volume: Dict[str, float] = {}
    for t in tickers:
        if isinstance(t, dict) and isinstance(t.get("instId"), str):
            try:
                volume[t["instId"]] = float(t.get("volCcy24h") or 0.0)
            except (TypeError, ValueError):
                volume[t["instId"]] = 0.0
    eligible = [i for i in REPLICATION_CANDIDATES if i not in always and history.get(i) is not None]
    ranked = sorted(eligible, key=lambda i: (-volume.get(i, 0.0), i))
    picks: List[MarketPick] = []
    for rank, inst in enumerate(ranked, start=1):
        chosen = rank <= n
        picks.append(MarketPick(inst, volume.get(inst, 0.0), history.get(inst), rank, chosen,
                                f"rank {rank} of {len(ranked)} by 24-hour quote volume" + ("" if chosen else f" (not in the top {n})")))
    for inst in always:
        picks.append(MarketPick(inst, volume.get(inst, 0.0), history.get(inst), None, True, REPLICATION_CANDIDATES.get(inst, "always included")))
    for inst in REPLICATION_CANDIDATES:
        if inst not in always and history.get(inst) is None:
            picks.append(MarketPick(inst, volume.get(inst, 0.0), None, None, False, f"no public 1H candle before {HISTORY_CUTOFF}"))
    return picks


def chosen_markets(picks: Sequence[MarketPick]) -> List[str]:
    ranked = [p.instrument for p in picks if p.chosen and p.rank is not None]
    rest = [p.instrument for p in picks if p.chosen and p.rank is None]
    return ranked + rest


def preregister(rest: OKXPublicRest, path: Path, *, now: Optional[datetime] = None, force: bool = False) -> Dict[str, Any]:
    """Take the public ticker snapshot, check the history condition, fix the markets, write the file (never twice unless forced)."""
    path = Path(path)
    if path.exists() and not force:
        raise ReplicationError(f"{path} exists: the markets were already fixed; a second snapshot would be a second choice")
    snapshot_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    tickers = rest.get(TICKERS_PATH, {"instType": "SPOT"})
    history = {inst: candle_history_start(rest, inst, "1H", before=HISTORY_CUTOFF) for inst in REPLICATION_CANDIDATES}
    picks = rank_candidates(tickers, history)
    payload: Dict[str, Any] = {
        "note": "Plan row R12. The markets of the replication study, fixed from one public snapshot BEFORE any candle of a new market was collected. Never edited.",
        "snapshot_at": snapshot_at, "tickers_endpoint": f"{TICKERS_PATH}?instType=SPOT", "volume_field": "volCcy24h (24-hour volume in the quote currency, USDT)",
        "history_condition": f"a public 1H candle before {HISTORY_CUTOFF} (probed with /api/v5/market/history-candles, one GET per candidate)",
        "rule": f"the top {RANKED_PICKS} eligible candidates by 24-hour quote volume plus {', '.join(ALWAYS_INCLUDED)}",
        "data_end": DATA_END, "chosen": chosen_markets(picks), "picks": [asdict(p) for p in picks],
        "preregistration": PREREGISTRATION,
    }
    payload["sha256"] = _sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return payload


def load_preregistration(path: Path = PREREGISTRATION_PATH) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("chosen"), list) or not data["chosen"]:
        raise ReplicationError(f"{path} is not a pre-registration file")
    expected = _sha256_json({k: v for k, v in data.items() if k != "sha256"})
    if data.get("sha256") != expected:
        raise ReplicationError(f"{path} was edited after it was written (hash mismatch)")
    return data


# -- the frozen study lake -----------------------------------------------------------------------------

def freeze_lake(source: LakeLayout, target: LakeLayout, instruments: Sequence[str], *, end: str = DATA_END, log=print) -> Dict[str, Any]:
    """Copy the study's inputs from the research lake into a fresh study lake with every candle series cut at ``end`` (bar close <= end).

    Candles (1H, 4H) are filtered; the external Binance series (funding for every market, open interest for BTC/ETH) are copied
    verbatim so the Sprint 2c reproduction sees exactly its inputs. The target must not be the source."""
    if Path(source.root).resolve() == Path(target.root).resolve():
        raise ReplicationError("the study lake must be a different directory from the research lake")
    end_ts = pd.Timestamp(end)
    end_ts = end_ts.tz_localize("UTC") if end_ts.tzinfo is None else end_ts.tz_convert("UTC")
    report: Dict[str, Any] = {"end": end_ts.isoformat(), "candles": {}, "external": {}}
    for inst in instruments:
        for bar in COLLECTED_BARS:
            table = read_candles(source, inst, bar)
            if table.num_rows == 0:
                report["candles"][f"{inst} {bar}"] = 0
                continue
            closes = pc.add(pc.cast(table["open_time"], "int64"), BAR_MS[bar])  # ms since the epoch
            keep = table.filter(pc.less_equal(closes, int(end_ts.value // 1_000_000)))
            target_dir = target.candles_dir(inst, bar)
            if target_dir.exists():
                shutil.rmtree(target_dir)
            if keep.num_rows:
                write_partitioned(keep, key="open_time", schema=CANDLE_SCHEMA, file_for_year=lambda y, i=inst, b=bar: target.candles_file(i, b, y))
            report["candles"][f"{inst} {bar}"] = int(keep.num_rows)
            log(f"frozen {inst} {bar}: {keep.num_rows} of {table.num_rows} candles (bar close <= {end_ts:%Y-%m-%d %H:%M} UTC)")
        symbol = _binance_symbol(inst)
        for kind in ("funding_rate", "metrics"):
            period = "8H" if kind == "funding_rate" else "1H"
            src = source.external_series_dir("binance", kind, symbol, period)
            if not src.exists():
                continue
            dst = target.external_series_dir("binance", kind, symbol, period)
            if dst.exists():
                shutil.rmtree(dst)
            dst.mkdir(parents=True, exist_ok=True)
            files = sorted(src.glob("*.parquet"))
            for f in files:
                shutil.copy2(f, dst / f.name)
            report["external"][f"{kind} {symbol}"] = len(files)
    return report


def _binance_symbol(instrument: str) -> str:
    from app.datalake.binance_public import SYMBOL_FOR_INSTRUMENT

    return SYMBOL_FOR_INSTRUMENT.get(instrument) or research_symbol_for(instrument)


# -- the Sprint 2c runner, loaded as a module ------------------------------------------------------------

_V1C_MODULE = "research._sprint2c_runner"


def load_v1c_runner(path: Path = V1C_SCRIPT):
    """``scripts/run_research_v1c.py`` as a module (cached). Its code is used as is; nothing is copied."""
    mod = sys.modules.get(_V1C_MODULE)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(_V1C_MODULE, path)
    if spec is None or spec.loader is None:
        raise ReplicationError(f"cannot load the Sprint 2c runner from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_V1C_MODULE] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(_V1C_MODULE, None)
        raise
    return mod


def v1c_args(cfg: ReplicationConfig, *, evaluate_holdout: bool) -> Dict[str, Any]:
    """Sprint 2c's own command-line defaults, narrowed to the study's strategies, modes and timeframes."""
    v1c = load_v1c_runner()
    argv: List[str] = ["--strategies", *cfg.strategies, "--regime-modes", *cfg.regime_modes, "--timeframes", *cfg.timeframes]
    if cfg.quick:
        argv.append("--quick")
    if evaluate_holdout:
        argv.append("--evaluate-holdout")
    if cfg.lake_dir:
        argv += ["--lake-dir", cfg.lake_dir]
    return dict(vars(v1c.parse_args(argv)))


def _norm(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if isinstance(value, float):
        return round(value, 12)
    return value


def protocol_check(args: Mapping[str, Any], meta: Mapping[str, Any]) -> Dict[str, Any]:
    """The runner's defaults against the stored Sprint 2c run's meta: every protocol parameter must be the same."""
    v1c = load_v1c_runner()
    ns = argparse.Namespace(**args)
    expected: Dict[str, Any] = {
        "train_days": meta["train_days"], "test_days": meta["test_days"], "purge_days": meta["purge_days"], "select_by": meta["select_by"],
        "min_trades": meta["min_trades"], "fee": meta["fee_rate"], "slippage": meta["slippage_rate"], "holdout_months": meta["holdout_months"],
        "rebalance_threshold": meta["rebalance_threshold"], "positioning_source": meta["positioning_source"], "brackets": meta["bracket_variants"],
        "ladder_recovery_days": (meta.get("ladder") or {}).get("recovery_days"),
    }
    got = {k: getattr(ns, k) for k in expected}
    mismatches: Dict[str, Any] = {k: {"got": got[k], "stored": expected[k]} for k in expected if _norm(got[k]) != _norm(expected[k])}
    policy = v1c._policy_spec(ns).to_dict()
    if _norm(policy) != _norm(meta["policy_sizing"]):
        mismatches["policy_sizing"] = {"got": policy, "stored": meta["policy_sizing"]}
    regime = v1c._regime_cfg(ns, "gate").to_dict()
    stored_regime = meta["regime"]
    for k in ("n_states", "vol_window_days", "bear_prob_max", "bear_scale", "n_iter", "tol", "min_train_bars"):
        if k in stored_regime and _norm(regime.get(k)) != _norm(stored_regime[k]):
            mismatches[f"regime.{k}"] = {"got": regime.get(k), "stored": stored_regime[k]}
    no_trade = v1c._no_trade(ns).label
    if no_trade != meta.get("no_trade_label"):
        mismatches["no_trade_label"] = {"got": no_trade, "stored": meta.get("no_trade_label")}
    for key, stored_key in (("strategies", "strategies"), ("regime_modes", None), ("timeframes", "timeframes")):
        stored_values = stored_regime.get("modes") if key == "regime_modes" else meta.get(stored_key)
        extra = [v for v in args[key] if v not in (stored_values or [])]
        if extra:
            mismatches[key] = {"got": list(args[key]), "stored": stored_values, "note": f"not run in Sprint 2c: {extra}"}
    if args.get("quick"):
        mismatches["quick"] = {"got": True, "stored": meta.get("quick", False), "note": "cut grids: a smoke run, never a result"}
    return {"ok": not mismatches, "mismatches": mismatches, "checked": sorted(list(expected) + ["policy_sizing", "regime", "no_trade_label",
                                                                                                "strategies", "regime_modes", "timeframes", "quick"])}


# -- one market x timeframe through Sprint 2c's run_series -----------------------------------------------

SERIES_KEYS = ("instrument", "timeframe", "results", "failures", "benchmark", "span", "holdout_span", "positioning", "sensitivity",
               "s0_blocked_share", "skipped")


def annotate_result(r: Dict[str, Any], *, s5_active: bool, funding_coverage: float) -> Dict[str, Any]:
    """Study bookkeeping on one Sprint 2c result: family, whether S5 applies, what the row is called, whether it is judged."""
    cand = r["candidate"]
    r["family"] = cand
    r["s5_applies"] = ("S5" not in cand) or s5_active
    r["funding_coverage"] = funding_coverage
    base = cand.split("+")[0]
    r["display_candidate"] = cand if r["s5_applies"] else f"{base} (run without S5: funding covers {funding_coverage * 100:.0f}% of the in-sample bars)"
    r["judged"] = cand != CONTROL and r["s5_applies"]
    r["configuration"] = f"{cand} {r['timeframe']} [{r['regime']['mode']}]"
    r["holdout_confirmed"] = holdout_verdict(r) if r.get("holdout") else None
    return r


def run_market(args: Mapping[str, Any], instrument: str, timeframe: str, cfg: ReplicationConfig, *, log=print) -> Dict[str, Any]:
    """Sprint 2c's ``run_series`` on one market and timeframe, plus the study's bookkeeping (nothing in the numbers changes)."""
    v1c = load_v1c_runner()
    log(f"[{instrument} {timeframe}] Sprint 2c runner: {len(args['strategies'])} strategies x modes {list(args['regime_modes'])} ...")
    out = v1c.run_series(dict(args), instrument, timeframe)
    series: Dict[str, Any] = {k: out.get(k) for k in SERIES_KEYS}
    if out.get("skipped"):
        log(f"[{instrument} {timeframe}] skipped: {out['skipped']}")
        return series
    cov = float((out.get("positioning") or {}).get("funding_coverage") or 0.0)
    series["funding_coverage"] = cov
    series["s5_active"] = bool(cov >= cfg.funding_coverage_min)
    series["results"] = [annotate_result(r, s5_active=series["s5_active"], funding_coverage=cov) for r in out["results"]]
    return series


def run_market_job(job: Mapping[str, Any]) -> Dict[str, Any]:
    """Process-pool entry point: one series per job (loads the runner inside the worker)."""
    cfg = ReplicationConfig(**job["cfg"])
    return run_market(job["args"], job["instrument"], job["timeframe"], cfg, log=lambda msg: print(msg, flush=True))


# -- the reproduction of Sprint 2c ---------------------------------------------------------------------------

REPRO_KEYS = ("total_return", "cagr", "sharpe", "max_drawdown", "calmar", "profit_factor")
STORED_DECIMALS = 6
REPRO_TOLERANCE = 0.5 * 10 ** -STORED_DECIMALS + 1e-12


def _num(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(x) else x


def _canon(params: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in (params or {}).items()}


def stored_result(stored: Sequence[Mapping[str, Any]], candidate: str, instrument: str, timeframe: str, mode: str) -> Optional[Mapping[str, Any]]:
    for r in stored:
        if r["candidate"] == candidate and r["instrument"] == instrument and r["timeframe"] == timeframe and (r.get("regime") or {}).get("mode") == mode:
            return r
    return None


def reproduction_check(series: Mapping[str, Any], stored: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Every result of a BTC/ETH series against Sprint 2c's stored one: metrics to the stored 6 decimals, trades, rule, gate verdict."""
    checks: List[Dict[str, Any]] = []
    for r in series.get("results", []):
        mode = (r.get("regime") or {}).get("mode")
        exp = stored_result(stored, r["candidate"], r["instrument"], r["timeframe"], mode)
        row: Dict[str, Any] = {"candidate": r["candidate"], "instrument": r["instrument"], "timeframe": r["timeframe"], "regime": mode}
        if exp is None:
            row.update({"ok": False, "note": "no stored Sprint 2c result for this configuration"})
            checks.append(row)
            continue
        diffs: Dict[str, float] = {}
        exact = True
        for k in REPRO_KEYS:
            a, b = _num(r["oos"].get(k)), _num(exp["oos"].get(k))
            if k == "profit_factor" and (r["oos"].get(k) is None or not math.isfinite(_num(r["oos"].get(k)))):
                a = 999.0
            diffs[k] = abs(a - b)
            exact &= round(a, STORED_DECIMALS) == b
        worst = max(diffs.values()) if diffs else 0.0
        trades_ok = int(_num(r["oos"].get("n_trades"))) == int(_num(exp["oos"].get("n_trades")))
        selected_ok = json.dumps(_canon(r.get("selected_params")), sort_keys=True) == json.dumps(_canon(exp.get("selected_params")), sort_keys=True)
        passed_ok = bool((r.get("acceptance") or {}).get("passed")) == bool((exp.get("acceptance") or {}).get("passed"))
        row.update({"max_abs_difference": worst, "rounds_to_stored": bool(exact), "n_trades": int(_num(r["oos"].get("n_trades"))),
                    "n_trades_stored": int(_num(exp["oos"].get("n_trades"))), "selected_matches": bool(selected_ok), "verdict_matches": bool(passed_ok),
                    "ok": bool(worst <= REPRO_TOLERANCE and trades_ok and selected_ok and passed_ok),
                    "reproduced": {k: r["oos"].get(k) for k in REPRO_KEYS}, "stored": {k: exp["oos"].get(k) for k in REPRO_KEYS}})
        checks.append(row)
    return checks


# -- verdicts (pre-registered) -----------------------------------------------------------------------------------

def markets_needed(n_markets: int) -> int:
    return max(1, math.ceil(n_markets / 2.0))


def judged_results(series_list: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    return [r for s in series_list for r in s.get("results", []) if r.get("judged")]


def btc_passers_2c(stored: Sequence[Mapping[str, Any]], cfg: ReplicationConfig) -> List[Dict[str, Any]]:
    """The configurations that passed every gate on BTC-USDT in Sprint 2c, within the study's families, timeframes and modes."""
    out = []
    for r in stored:
        if (r["instrument"] == "BTC-USDT" and r["candidate"] in cfg.families and r["timeframe"] in cfg.timeframes
                and (r.get("regime") or {}).get("mode") in cfg.regime_modes and (r.get("acceptance") or {}).get("passed")):
            out.append({"candidate": r["candidate"], "timeframe": r["timeframe"], "mode": r["regime"]["mode"],
                        "configuration": f"{r['candidate']} {r['timeframe']} [{r['regime']['mode']}]",
                        "btc": _metrics_of(r), "btc_holdout": r.get("holdout"), "btc_holdout_confirmed": holdout_verdict(r)})
    return out


def _metrics_of(r: Mapping[str, Any]) -> Dict[str, Any]:
    oos = r.get("oos") or {}
    acc = r.get("acceptance") or {}
    return {"cagr": oos.get("cagr"), "sharpe": oos.get("sharpe"), "max_drawdown": oos.get("max_drawdown"), "calmar": oos.get("calmar"),
            "profit_factor": oos.get("profit_factor"), "n_trades": oos.get("n_trades"), "total_return": oos.get("total_return"),
            "rolling_12m_positive_share": acc.get("rolling_positive_share"), "worst_calendar_year_return": acc.get("worst_calendar_year_return"),
            "passed": bool(acc.get("passed")), "failed": list(acc.get("failed") or [])}


def configuration_replication(series_list: Sequence[Mapping[str, Any]], passers_2c: Sequence[Mapping[str, Any]], markets: Sequence[str]) -> List[Dict[str, Any]]:
    """The primary test: each BTC passer of Sprint 2c on every new market."""
    needed = markets_needed(len(markets))
    out = []
    for p in passers_2c:
        per_market = []
        for m in markets:
            r = next((x for s in series_list if s["instrument"] == m for x in s.get("results", [])
                      if x["candidate"] == p["candidate"] and x["timeframe"] == p["timeframe"] and x["regime"]["mode"] == p["mode"]), None)
            if r is None:
                per_market.append({"instrument": m, "ran": False})
                continue
            entry = {"instrument": m, "ran": True, "judged": bool(r.get("judged")), "display_candidate": r.get("display_candidate"),
                     "passed": bool(r.get("judged") and r["acceptance"]["passed"]), "failed": list(r["acceptance"].get("failed") or []),
                     "metrics": _metrics_of(r), "holdout": r.get("holdout"), "holdout_confirmed": r.get("holdout_confirmed")}
            per_market.append(entry)
        n_pass = sum(1 for e in per_market if e.get("passed"))
        n_ran = sum(1 for e in per_market if e.get("ran") and e.get("judged"))
        out.append(dict(p, markets=per_market, n_pass=n_pass, n_judged=n_ran, needed=needed, replicated=bool(n_pass >= needed and n_ran > 0),
                        confirmed=[e["instrument"] for e in per_market if e.get("holdout_confirmed") is True],
                        contradicted=[e["instrument"] for e in per_market if e.get("holdout_confirmed") is False]))
    return out


def _median(values: Sequence[Any]) -> Optional[float]:
    xs = sorted(float(v) for v in values if v is not None and isinstance(v, (int, float)) and math.isfinite(float(v)))
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else 0.5 * (xs[m - 1] + xs[m])


def family_verdicts(series_list: Sequence[Mapping[str, Any]], stored: Sequence[Mapping[str, Any]], markets: Sequence[str], cfg: ReplicationConfig) -> List[Dict[str, Any]]:
    """Per family: on how many new markets any of its configurations passes, the pre-registered label, and medians beside BTC/ETH."""
    needed = markets_needed(len(markets))
    out = []
    for fam in cfg.families:
        rows = [r for r in judged_results(series_list) if r["candidate"] == fam and r["instrument"] in markets]
        passing_by_market: Dict[str, List[str]] = {}
        for r in rows:
            if r["acceptance"]["passed"]:
                passing_by_market.setdefault(r["instrument"], []).append(r["configuration"])
        markets_run = sorted({r["instrument"] for r in rows})
        inactive = sorted({s["instrument"] for s in series_list if s.get("results") and not s.get("s5_active", True) and "S5" in fam
                           and s["instrument"] in markets})
        stored_fam = [r for r in stored if r["candidate"] == fam and r["timeframe"] in cfg.timeframes and (r.get("regime") or {}).get("mode") in cfg.regime_modes]
        passes_on_btc = any(r["instrument"] == "BTC-USDT" and (r.get("acceptance") or {}).get("passed") for r in stored_fam)
        passes_on_eth = any(r["instrument"] == "ETH-USDT" and (r.get("acceptance") or {}).get("passed") for r in stored_fam)
        n_markets_passing = len(passing_by_market)
        if not markets_run:
            label = "not run"
        elif n_markets_passing >= needed:
            label = "robust across markets"
        elif n_markets_passing >= 1:
            label = "fragile"
        elif passes_on_btc:
            label = "BTC-specific"
        else:
            label = "fails everywhere"
        confirmed = sorted({r["instrument"] for r in rows if r["acceptance"]["passed"] and r.get("holdout_confirmed") is True})
        contradicted = sorted({r["instrument"] for r in rows if r["acceptance"]["passed"] and r.get("holdout_confirmed") is False})

        def med(key: str, subset: Sequence[Mapping[str, Any]]) -> Optional[float]:
            return _median([(r.get("oos") or {}).get(key) for r in subset])

        out.append({
            "family": fam, "label": label, "markets_run": markets_run, "markets_passing": sorted(passing_by_market), "passing_configurations": passing_by_market,
            "n_markets_passing": n_markets_passing, "needed": needed, "n_configurations": len(rows),
            "n_configurations_passing": sum(1 for r in rows if r["acceptance"]["passed"]),
            "s5_inactive_markets": inactive, "passes_on_btc_2c": passes_on_btc, "passes_on_eth_2c": passes_on_eth,
            "confirmed_markets": confirmed, "contradicted_markets": contradicted,
            "medians_new": {k: med(k, rows) for k in ("calmar", "cagr", "max_drawdown", "profit_factor", "sharpe")},
            "medians_btc": {k: med(k, [r for r in stored_fam if r["instrument"] == "BTC-USDT"]) for k in ("calmar", "cagr", "max_drawdown", "profit_factor", "sharpe")},
            "medians_eth": {k: med(k, [r for r in stored_fam if r["instrument"] == "ETH-USDT"]) for k in ("calmar", "cagr", "max_drawdown", "profit_factor", "sharpe")},
            "share_profit_factor_above_1": (sum(1 for r in rows if _num((r.get("oos") or {}).get("profit_factor")) > 1.0) / len(rows)) if rows else None,
            "share_calmar_above_0": (sum(1 for r in rows if _num((r.get("oos") or {}).get("calmar")) > 0.0) / len(rows)) if rows else None,
        })
    return out


def overall_verdict(families: Sequence[Mapping[str, Any]], series_list: Sequence[Mapping[str, Any]], markets: Sequence[str]) -> Dict[str, Any]:
    rows = [r for r in judged_results(series_list) if r["instrument"] in markets]
    passed = [r for r in rows if r["acceptance"]["passed"]]
    confirmed = [r for r in passed if r.get("holdout_confirmed") is True]
    contradicted = [r for r in passed if r.get("holdout_confirmed") is False]
    unevaluated = [r for r in passed if r.get("holdout_confirmed") is None]
    labels = {f["family"]: f["label"] for f in families}
    if any(v == "robust across markets" for v in labels.values()):
        label = "robust across markets"
    elif passed:
        label = "fragile"
    else:
        label = "BTC-specific" if any(f.get("passes_on_btc_2c") for f in families) else "fails everywhere"
    counts: Dict[str, int] = {}
    for r in rows:
        for g in r["acceptance"].get("failed", []):
            counts[g] = counts.get(g, 0) + 1
    return {"label": label, "n_markets": len(markets), "n_judged": len(rows), "n_passed": len(passed), "n_confirmed": len(confirmed),
            "n_contradicted": len(contradicted), "n_unevaluated": len(unevaluated), "family_labels": labels,
            "passed": [{"instrument": r["instrument"], "configuration": r["configuration"], "calmar": r["oos"].get("calmar"),
                        "holdout_confirmed": r.get("holdout_confirmed")} for r in passed],
            "binding_gates": sorted(counts.items(), key=lambda kv: -kv[1])}


def beats_hold(series_list: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Sprint 2c's acceptance-clause statistic per series: does the best judged rule beat hold + policy by more than 0.1 Calmar?"""
    out = []
    for s in series_list:
        results = s.get("results") or []
        hold = next((r for r in results if r["candidate"] == CONTROL), None)
        judged = [r for r in results if r.get("judged")]
        if hold is None or not judged:
            continue
        best = max(judged, key=lambda r: _num(r["oos"].get("calmar"), -9.0))
        bench = s.get("benchmark") or {}
        out.append({"instrument": s["instrument"], "timeframe": s["timeframe"], "best": best["configuration"], "best_calmar": best["oos"].get("calmar"),
                    "best_cagr": best["oos"].get("cagr"), "best_max_drawdown": best["oos"].get("max_drawdown"),
                    "hold_calmar": hold["oos"].get("calmar"), "hold_cagr": hold["oos"].get("cagr"), "hold_max_drawdown": hold["oos"].get("max_drawdown"),
                    "hold_holdout": (hold.get("holdout") or {}).get("total_return"),
                    "buy_and_hold_cagr": bench.get("cagr"), "buy_and_hold_max_drawdown": bench.get("max_drawdown"), "buy_and_hold_calmar": bench.get("calmar"),
                    "beats_hold": bool(_num(best["oos"].get("calmar"), -9.0) > _num(hold["oos"].get("calmar"), -9.0) + 0.1)})
    return out


# -- the holdout ledger -------------------------------------------------------------------------------------------

LEDGER_NOTE = ("Every opening of a new market's 12-month holdout by the replication study (plan row R12), in order; entries are appended, "
               "never edited. The report shows all of them. The hold + policy control's 12 months are a comparison line, not a configuration under test.")


def holdout_openings(series_list: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in series_list:
        for r in s.get("results", []):
            h = r.get("holdout")
            if not h:
                continue
            out.append({"configuration": f"{r['candidate']} {r['instrument']} {r['timeframe']} [{r['regime']['mode']}]",
                        "role": "control" if r["candidate"] == CONTROL else "configuration",
                        "selected_params": _canon(r.get("selected_params")), "span": s.get("holdout_span"),
                        "total_return": h.get("total_return"), "max_drawdown": h.get("max_drawdown"), "profit_factor": h.get("profit_factor"),
                        "n_trades": h.get("n_trades"), "confirmed": None if r["candidate"] == CONTROL else holdout_verdict(r)})
    return out


def load_ledger(path: str) -> List[Dict[str, Any]]:
    if path == "-" or not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ReplicationError(f"the holdout ledger {path} is malformed")
    return list(data["entries"])


def write_ledger(path: str, entries: List[Dict[str, Any]]) -> None:
    Path(path).write_text(json.dumps({"note": LEDGER_NOTE, "entries": entries}, indent=1) + "\n", encoding="utf-8")


def guard_second_look(ledger: Sequence[Mapping[str, Any]], series_list: Sequence[Mapping[str, Any]], *, evaluate_holdout: bool) -> List[str]:
    """Names the configurations whose holdout an earlier run already opened (a re-run shows them again; the ledger keeps both looks)."""
    if not evaluate_holdout:
        return []
    seen = {o["configuration"] for e in ledger for o in e.get("openings", []) if o.get("role") != "control"}
    return sorted(o["configuration"] for o in holdout_openings(series_list) if o["role"] != "control" and o["configuration"] in seen)


# -- the paper-fleet shortlist ---------------------------------------------------------------------------------------

def shortlist_additions(series_list: Sequence[Mapping[str, Any]], *, source: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Confirmed passers (walk-forward pass AND holdout confirmation) as shortlist rows, each with a ``source`` tag."""
    rows = []
    for r in judged_results(series_list):
        if r["acceptance"]["passed"] and r.get("holdout_confirmed") is True:
            row = _row(r)
            row["source"] = dict(source)
            rows.append(row)
    rows.sort(key=lambda x: (-_num(x.get("calmar")), -_num(x.get("sharpe"))))
    return rows


def _shortlist_key(row: Mapping[str, Any]) -> Tuple[str, str, str, Any, str]:
    """What makes a shortlist row unique: the rule, its market and mode, and (plan row R18b) its sizing tier (a row without a tag
    is the Reference tier, so the same rule at another tier is another row)."""
    source = row.get("source") or {}
    return (row["candidate"], row["instrument"], row["timeframe"], (row.get("regime_config") or {}).get("mode"), str(source.get("tier") or "reference"))


def append_to_shortlist(path: Path, additions: Sequence[Mapping[str, Any]], *, note: str) -> Dict[str, Any]:
    """Add rows to the fleet shortlist: existing entries and their ranks untouched, new ranks continue, an amendment is recorded.

    A row whose ``source.role`` is ``control`` (plan row R18b: the slow-trend forward control) goes under ``controls`` without a
    rank; every other row is a configuration. A row already there (same rule, market, mode and tier) is never added twice.
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not additions:
        return data
    existing = list(data.get("configurations", []))
    controls = list(data.get("controls", []))
    existing_keys = {_shortlist_key(c) for c in existing}
    control_keys = {_shortlist_key(c) for c in controls}
    next_rank = max([int(c.get("rank") or 0) for c in existing] + [0]) + 1
    added = []
    for row in additions:
        key = _shortlist_key(row)
        tier = "" if key[4] == "reference" else f" @ {key[4]}"
        if (row.get("source") or {}).get("role") == "control":
            if key in control_keys:
                continue
            controls.append({k: v for k, v in row.items() if k != "rank"})
            control_keys.add(key)
            added.append(f"{row['candidate']} {row['instrument']} {row['timeframe']} [{key[3]}] (control)")
            continue
        if key in existing_keys:
            continue
        new = dict(row, rank=next_rank)
        next_rank += 1
        existing.append(new)
        existing_keys.add(key)
        added.append(f"{row['candidate']} {row['instrument']} {row['timeframe']} [{key[3]}]{tier}")
    data["configurations"] = existing
    data["controls"] = controls
    data.setdefault("amendments", []).append({"added_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "note": note, "added": added})
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data
