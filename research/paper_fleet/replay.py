"""Offline dry run of the whole paper fleet: recorded public data replayed as if live (no network).

``scripts/run_paper_fleet.py --dry-run`` replays the last ``days`` of the
research lake's PUBLIC data (OKX 1H candles and the OKX funding / open-interest
series) through the real fleet code — data refresh, bar building, regime fits,
decisions through the ``Strategy`` contract, the bar-by-bar engine, journals,
state, the weekly report — with a simulated clock that never reveals a candle
before it closed. Without a research lake (a fresh VPS checkout) it uses a
deterministic synthetic market instead. It writes only into a new or empty
output directory and checks a list of invariants at the end.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from app.datalake.layout import LakeLayout
from research.data import load_candles, load_okx_series
from research.paper_fleet.config import INSTRUMENTS, FleetManifest, load_manifest
from research.paper_fleet.data import FUNDING_PERIOD, OI_PERIOD, SOURCE_BAR, SWAP_FOR, FleetLake, MarketData
from research.paper_fleet.report import ReportScheduler, write_week
from research.paper_fleet.runner import FleetSettings, PaperFleet
from research.paper_fleet.store import FleetPaths, Journal, read_state

HOUR = pd.Timedelta(hours=1)


class ReplayFeed:
    """Serves recorded public data as the OKX public endpoints would, never past ``now``."""

    def __init__(self, candles: Mapping[str, pd.DataFrame], funding: Mapping[str, pd.DataFrame], open_interest: Mapping[str, pd.DataFrame]) -> None:
        self._candles = {k: v.sort_index() for k, v in candles.items()}
        self._funding = {k: v.sort_index() for k, v in funding.items()}
        self._oi = {k: v.sort_index() for k, v in open_interest.items()}
        self.now = pd.Timestamp("1970-01-01", tz="UTC")
        self.requests = 0

    def _visible(self, instrument: str) -> pd.DataFrame:
        df = self._candles[instrument]
        return df[df.index + HOUR <= self.now]  # only candles that have closed (OKX confirm = 1)

    def newest_candles(self, instrument: str) -> pd.DataFrame:
        self.requests += 1
        return self._visible(instrument).iloc[-300:]

    def candles_before(self, instrument: str, before_ms: int) -> pd.DataFrame:
        self.requests += 1
        df = self._visible(instrument)
        return df[df.index < pd.Timestamp(int(before_ms), unit="ms", tz="UTC")].iloc[-100:]

    def funding_history(self, swap: str, *, before_ms: Optional[int] = None) -> List[dict]:
        self.requests += 1
        df = self._funding.get(swap)
        if df is None:
            return []
        df = df[df.index <= self.now]
        if before_ms is not None:
            df = df[df.index < pd.Timestamp(int(before_ms), unit="ms", tz="UTC")]
        df = df.iloc[-100:]
        return [{"ts": int(ts.value // 1_000_000), "instrument": swap, "period": FUNDING_PERIOD, "funding_rate": float(v),
                 "realized_rate": float("nan"), "method": "", "formula_type": ""} for ts, v in zip(df.index[::-1], df["funding_rate"].to_numpy()[::-1])]

    def open_interest_history(self, swap: str, *, end_ms: Optional[int] = None) -> List[dict]:
        self.requests += 1
        df = self._oi.get(swap)
        if df is None:
            return []
        df = df[df.index <= self.now]
        if end_ms is not None:
            df = df[df.index <= pd.Timestamp(int(end_ms), unit="ms", tz="UTC")]
        df = df.iloc[-100:]
        return [{"ts": int(ts.value // 1_000_000), "instrument": swap, "period": OI_PERIOD, "oi": float(v) / 1e4, "oi_ccy": float(v) / 1e5,
                 "oi_usd": float(v)} for ts, v in zip(df.index[::-1], df["oi_usd"].to_numpy()[::-1])]


def synthetic_market(days: int = 1000, *, end: Optional[pd.Timestamp] = None, seed: int = 20261021) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame], Dict[str, pd.DataFrame]]:
    """Deterministic synthetic 1H candles (crypto-like volatility, trends and calm spells) plus funding and open interest."""
    rng = np.random.default_rng(seed)
    end = pd.Timestamp(end or "2026-10-20 00:00", tz="UTC") if (end is None or pd.Timestamp(end).tzinfo is None) else pd.Timestamp(end)
    n = int(days * 24)
    idx = pd.date_range(end - pd.Timedelta(hours=n), periods=n, freq="h", tz="UTC", name="open_time")
    candles, funding, oi = {}, {}, {}
    for k, (inst, p0) in enumerate((("BTC-USDT", 60_000.0), ("ETH-USDT", 3_000.0))):
        regime = np.repeat(rng.normal(0.0, 0.0006, n // 500 + 1), 500)[:n]
        vol = np.repeat(rng.uniform(0.004, 0.012, n // 300 + 1), 300)[:n]
        r = rng.normal(regime, vol)
        close = p0 * np.exp(np.cumsum(r))
        open_ = np.concatenate([[p0], close[:-1]])
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2)))
        volume = rng.lognormal(5 + k, 0.6, n)
        candles[inst] = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
        swap = SWAP_FOR[inst]
        f_idx = idx[(idx.hour % 8) == 0]
        funding[swap] = pd.DataFrame({"funding_rate": 1e-4 + 1e-4 * np.cumsum(rng.normal(0, 0.15, len(f_idx))) / np.sqrt(np.arange(1, len(f_idx) + 1))},
                                     index=f_idx.rename("ts"))
        oi[swap] = pd.DataFrame({"oi_usd": 1e9 * (1 + k) * np.exp(np.cumsum(rng.normal(0, 0.01, n)))}, index=idx.rename("ts"))
    return candles, funding, oi


def lake_market(layout: LakeLayout) -> Optional[Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame], Dict[str, pd.DataFrame]]]:
    candles, funding, oi = {}, {}, {}
    for inst in INSTRUMENTS:
        df = load_candles(layout, inst, SOURCE_BAR)
        if df.empty:
            return None
        candles[inst] = df
        swap = SWAP_FOR[inst]
        f = load_okx_series(layout, "funding_rate", swap, FUNDING_PERIOD, ["funding_rate"])
        o = load_okx_series(layout, "open_interest", swap, OI_PERIOD, ["oi_usd"])
        if f is not None:
            funding[swap] = f
        if o is not None:
            oi[swap] = o
    return candles, funding, oi


@dataclass
class DryRunResult:
    out_dir: Path
    source: str
    start: str
    end: str
    cycles: int
    feed_requests: int
    checks: List[Tuple[str, bool, str]] = field(default_factory=list)
    reports: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)


def run_dry(
    out_dir: Optional[Path] = None,
    *,
    days: float = 7.0,
    lake: Optional[LakeLayout] = None,
    synthetic: bool = False,
    manifest: Optional[FleetManifest] = None,
    settings: FleetSettings = FleetSettings(),
    step_minutes: float = 60.0,
) -> DryRunResult:
    out = Path(out_dir) if out_dir is not None else Path(tempfile.mkdtemp(prefix="paper-fleet-dry-run-"))
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"dry-run output directory {out} must be new or empty")
    out.mkdir(parents=True, exist_ok=True)
    data = None if synthetic or lake is None else lake_market(lake)
    source = "research lake (recorded public OKX data)" if data is not None else "synthetic market (deterministic)"
    candles, funding, oi = data if data is not None else synthetic_market(int(settings.history_days + days + 60))
    end = min(df.index[-1] for df in candles.values()) + HOUR
    start = end - pd.Timedelta(days=float(days))
    feed = ReplayFeed(candles, funding, oi)
    feed.now = start
    manifest = manifest or load_manifest()
    paths = FleetPaths(out)
    market = MarketData(FleetLake(paths.lake), feed, instruments=INSTRUMENTS, history_days=settings.history_days)
    fleet = PaperFleet(manifest, paths, market, settings=settings, report_writer=ReportScheduler(paths, every_minutes=24 * 60))
    if not fleet.acquire():
        raise RuntimeError("could not lock the dry-run directory")
    cycles = 0
    try:
        fleet.open(start.to_pydatetime())
        t = start + pd.Timedelta(minutes=5)
        while t <= end + pd.Timedelta(minutes=5):
            feed.now = t
            fleet.cycle(t.to_pydatetime())
            cycles += 1
            t += pd.Timedelta(minutes=step_minutes)
        report = write_week(paths, (end + pd.Timedelta(minutes=5)).to_pydatetime())
    finally:
        fleet.release()
    result = DryRunResult(out_dir=out, source=source, start=start.isoformat(), end=end.isoformat(), cycles=cycles, feed_requests=feed.requests)
    result.reports = sorted(str(p) for p in paths.reports.glob("weekly-*.md"))
    result.checks = check_invariants(paths, manifest)
    result.summary = summarize(paths, manifest)
    return result


def check_invariants(paths: FleetPaths, manifest: FleetManifest) -> List[Tuple[str, bool, str]]:
    """Safety and bookkeeping invariants of a finished run (offline; journals and state only)."""
    checks: List[Tuple[str, bool, str]] = []
    state = read_state(paths.state_file) or {}
    checks.append(("state saved with the manifest fingerprint", state.get("fingerprint") == manifest.fingerprint(), ""))
    created = pd.Timestamp(state.get("created_at")) if state.get("created_at") else None
    problems: List[str] = []
    for acc in manifest.accounts:
        recs = list(Journal(paths.journal(acc.account_id)).read())
        if not recs or recs[0].get("type") != "start":
            problems.append(f"{acc.account_id}: no start record")
            continue
        seqs = [int(r.get("seq", 0)) for r in recs]
        if seqs != list(range(1, len(recs) + 1)):
            problems.append(f"{acc.account_id}: journal sequence not 1..n")
        bars = [r for r in recs if r.get("type") == "bar" and ("sleeve" not in r)]
        if acc.kind != "portfolio":
            if not bars:
                problems.append(f"{acc.account_id}: no bar processed")
                continue
            if not bars[0].get("anchor") or any(r.get("anchor") for r in bars[1:]):
                problems.append(f"{acc.account_id}: anchor bar is not exactly the first bar")
            if created is not None and pd.Timestamp(bars[0]["close_time"]) <= created:
                problems.append(f"{acc.account_id}: anchor bar closed before the fleet existed")
            if bars[0].get("events"):
                problems.append(f"{acc.account_id}: something filled on the anchor bar")
        for r in recs:
            if r.get("type") != "bar":
                continue
            if float(r.get("equity", 0)) <= 0 or float(r.get("cash", 0)) < -1e-6:
                problems.append(f"{acc.account_id}: non-positive equity or negative cash at {r.get('bar')}")
            for ev in r.get("events") or []:
                if ev.get("kind") == "entry" and not (ev.get("decision_bar") and ev["decision_bar"] < ev["bar_time"]):
                    problems.append(f"{acc.account_id}: entry at {ev.get('bar_time')} without an earlier decision bar")
                if ev.get("kind") in ("entry", "reduce", "exit") and created is not None and not r.get("sleeve") and pd.Timestamp(ev["bar_time"]) < created:
                    problems.append(f"{acc.account_id}: a fill before the fleet existed")
    checks.append(("every journal starts with its start record, sequence 1..n, anchor first, no fill before a decision or the start",
                   not problems, "; ".join(problems[:5])))
    pf = [a for a in manifest.accounts if a.kind == "portfolio"]
    if pf:
        recs = list(Journal(paths.journal(pf[0].account_id)).read())
        days = [r for r in recs if r.get("type") == "portfolio_day"]
        start_day = (state.get("portfolio") or {}).get("book", {}).get("forward_start_day")
        bad = [d["day"] for d in days if start_day and d["day"] < start_day]
        caps = [d["day"] for d in days if d.get("gross_exposure_end_of_day", 0) > 1.0 + 1e-9 or d.get("vol_scale", 0) > 1.0 + 1e-12]
        checks.append(("portfolio books forward days only, never above 100 % exposure", not bad and not caps, f"{bad[:3]} {caps[:3]}"))
    return checks


def summarize(paths: FleetPaths, manifest: FleetManifest) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for acc in manifest.accounts:
        recs = list(Journal(paths.journal(acc.account_id)).read())
        bars = [r for r in recs if r.get("type") == "bar" and "sleeve" not in r]
        fills = sum(1 for r in recs if r.get("type") == "bar" for e in (r.get("events") or []) if e.get("kind") in ("entry", "exit", "reduce"))
        days = [r for r in recs if r.get("type") == "portfolio_day"]
        equity = days[-1]["equity"] if days else (bars[-1]["equity"] if bars else None)
        out[acc.account_id] = {"bars": len(bars), "fills": fills, "portfolio_days": len(days), "equity": equity,
                               "in_position": bars[-1]["in_position"] if bars else None}
    return out
