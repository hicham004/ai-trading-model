"""The paper fleet's cycle: public data in, one journal per account out (SIMULATION ONLY).

Each cycle (every minute in the service):

1. refresh the public 1H candles (and, every 30 minutes, the OKX funding and
   open-interest history for the S5 filter);
2. for every series (BTC/ETH x 4H/6H), process each newly COMPLETE bar in
   order: refit the regime model when its 180-day period is over, then for
   every account on that series execute the decision made at the previous
   bar's close (:class:`research.paper_fleet.engine.SleeveEngine`) and make
   the next decision (:mod:`research.paper_fleet.signals`);
3. book every UTC day the portfolio's six sleeves have finished;
4. append the journal records, then save the state atomically.

An account starts flat with 10,000 virtual USDT at the first bar of its series
that CLOSES after the account was created — when the fleet was created, or when
an account added to the shortlist later joined it (the anchor bar: its decision
is the first one; nothing fills before the next bar's open). A bar that cannot be
built because a 1H candle is missing is waited for ``grace_minutes`` and then
skipped with a note (the S0 filter then blocks entries for three bars, as in
the research). A decision that fails is journaled as an error and leaves the
account without a decision for the next bar: its stops still work, it makes no
new entry and no signal exit (fail closed).
"""

from __future__ import annotations

import traceback
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from app.datalake.layout import LakeLayout
from app.strategy.timeframes import parse_timeframe

from research.paper_fleet.config import AccountSpec, FleetManifest, SleeveSpec, account_fingerprint
from research.paper_fleet.data import MarketData, frame_until
from research.paper_fleet.engine import BarOutcome, EngineConfig, SleeveEngine, SleeveState
from research.paper_fleet.portfolio import PortfolioBook, SleeveDays, book_day
from research.paper_fleet.regime import RegimeFit, fit_series, needs_refit
from research.paper_fleet.config import PURGE_DAYS, REFIT_DAYS, TRAIN_DAYS
from research.paper_fleet.signals import (
    DECISION_WINDOW_DAYS,
    STRATEGY_WARMUP_DAYS,
    DecisionInfo,
    decide_buy_and_hold,
    decide_sleeve,
    engine_config,
    frame_decisions,
    iso,
)
from research.paper_fleet.store import FleetLock, FleetPaths, Journal, append_fleet_log, read_state, write_state

STATE_VERSION = 1


class FleetError(RuntimeError):
    """A setup problem a restart cannot fix: the fleet cannot start or resume safely (changed rules, ...)."""


class FleetNotReady(RuntimeError):
    """Temporarily not startable (the public data is missing or stale): try again later."""


# 1H history kept: the longest decision window (a gated account at the end of a regime period) plus a margin.
HISTORY_DAYS = TRAIN_DAYS + PURGE_DAYS + REFIT_DAYS + STRATEGY_WARMUP_DAYS + 30.0


@dataclass(frozen=True)
class FleetSettings:
    window_days: float = DECISION_WINDOW_DAYS
    history_days: float = HISTORY_DAYS
    grace_minutes: float = 90.0  # how long a bar with a missing 1H candle is waited for before it is skipped
    stale_minutes: float = 150.0  # newest 1H candle older than this = stale public data
    heartbeat_log_minutes: float = 60.0  # quiet cycles are logged to fleet.jsonl at most this often


def series_key(instrument: str, timeframe: str) -> str:
    return f"{instrument} {timeframe}"


def _ts(value: Any) -> pd.Timestamp:
    out = pd.Timestamp(value)
    return out.tz_localize("UTC") if out.tzinfo is None else out.tz_convert("UTC")


class PaperFleet:
    def __init__(
        self,
        manifest: FleetManifest,
        paths: FleetPaths,
        market: MarketData,
        *,
        settings: FleetSettings = FleetSettings(),
        seed_lake: Optional[LakeLayout] = None,
        report_writer: Optional[Callable[[datetime], List[str]]] = None,
    ) -> None:
        self.manifest = manifest
        self.paths = paths
        self.market = market
        self.settings = settings
        self.seed_lake = seed_lake
        self.report_writer = report_writer
        self.lock = FleetLock(paths.lock_file)
        self.state: Dict[str, Any] = {}
        self.engines: Dict[str, SleeveEngine] = {}
        self.pf_engines: Dict[str, SleeveEngine] = {}
        self.pf_days: Dict[str, SleeveDays] = {}
        self.book: Optional[PortfolioBook] = None
        self.fits: Dict[str, RegimeFit] = {}
        self._by_series: Dict[str, List[AccountSpec]] = defaultdict(list)
        self._pf_by_series: Dict[str, List[Tuple[str, SleeveSpec]]] = defaultdict(list)
        self._gated: Dict[str, List[AccountSpec]] = defaultdict(list)
        self._pf_account: Optional[AccountSpec] = None
        for acc in manifest.accounts:
            if acc.kind == "portfolio":
                self._pf_account = acc
                for name, sleeve in acc.portfolio.sleeves:
                    self._pf_by_series[series_key(*sleeve.series)].append((name, sleeve))
            else:
                key = series_key(acc.instrument, acc.timeframe)
                self._by_series[key].append(acc)
                if acc.sleeve is not None and acc.sleeve.regime.active:
                    self._gated[key].append(acc)
        for key, accs in self._gated.items():
            fit_fields = {(a.sleeve.regime.n_states, a.sleeve.regime.vol_window_days, a.sleeve.regime.n_iter, a.sleeve.regime.tol,
                           a.sleeve.regime.min_train_bars) for a in accs}
            if len(fit_fields) != 1:
                raise FleetError(f"{key}: gated accounts disagree on the regime model; one fit per series is shared")
        self._last_log_at: Optional[pd.Timestamp] = None
        self._stale: Optional[bool] = None

    # -- lifecycle --------------------------------------------------------------

    def acquire(self) -> bool:
        self.paths.ensure()
        return self.lock.acquire()

    def release(self) -> None:
        self.lock.release()

    def open(self, now: datetime) -> Dict[str, Any]:
        """Create a new fleet in an empty directory, or resume the saved one.

        Resuming needs the same shared rules (costs, filters, regime timing) and, for every account that
        already runs, the same rules: a changed account would mix two rule sets in one record. An account
        added to the shortlist since then starts at the first bar that closes after now; an account no
        longer in it is retired (it stops; its journal stays).
        """
        self.paths.ensure()
        state = read_state(self.paths.state_file)
        now_ts = _ts(now)
        if state is None:
            return self._create(now_ts)
        if state.get("version") != STATE_VERSION:
            raise FleetError(f"fleet state version {state.get('version')!r} is not {STATE_VERSION}")
        if state.get("fleet_fingerprint") != self.manifest.fleet_fingerprint():
            raise FleetError("the fleet's shared rules (costs, filters, regime timing) changed since this fleet was created; "
                             "keep this directory as the record of the old fleet and start a new one in a new directory")
        known = state["accounts"]
        changed = [a.account_id for a in self.manifest.accounts
                   if a.account_id in known and known[a.account_id].get("fingerprint") != account_fingerprint(a)]
        if changed:
            raise FleetError(f"the rules of {', '.join(changed)} changed since they started; give a changed configuration a new "
                             "account id (the old record stays) or start a new fleet directory")
        revived = [a.account_id for a in self.manifest.accounts if a.account_id in known and known[a.account_id].get("retired_at")]
        if revived:
            raise FleetError(f"{', '.join(revived)} were retired from this fleet; a returning configuration needs a new account id")
        if state.get("positioning_source") != self.market.positioning:
            raise FleetError(f"this fleet's S5 accounts run on {state.get('positioning_source')!r} positioning data, not "
                             f"{self.market.positioning!r}: resume it with --positioning-source {state.get('positioning_source')}")
        self._load(state)
        boot = self.market.bootstrap(now_ts.to_pydatetime(), seed=None)
        current = {a.account_id for a in self.manifest.accounts}
        records: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        added = [a for a in self.manifest.accounts if a.account_id not in known]
        for acc in added:
            self._add_account(acc, now_ts, records)
        retired = sorted(aid for aid, meta in known.items() if aid not in current and not meta.get("retired_at"))
        for aid in retired:
            meta = known[aid]
            meta["retired_at"] = iso(now_ts)
            meta["seq"] = int(meta["seq"]) + 1
            Journal(self.paths.journal(aid)).append([{"type": "retired", "now": iso(now_ts), "seq": meta["seq"], "account": aid,
                                                      "note": "no longer in the fleet's shortlist: it stops here; this journal is its record"}])
        self.state["manifest"] = self.manifest.to_dict()
        self.state["fingerprint"] = self.manifest.fingerprint()
        self._commit(records)
        rec = {"type": "resume", "now": iso(now_ts), "data": boot.to_dict(), "cycles": self.state.get("cycles", 0),
               "added": [a.account_id for a in added], "retired": retired}
        append_fleet_log(self.paths.fleet_log, rec)
        return rec

    def _create(self, now: pd.Timestamp) -> Dict[str, Any]:
        boot = self.market.bootstrap(now.to_pydatetime(), seed=self.seed_lake)
        # A forward record must start from complete, current data: the portfolio's warm-up is built once, here.
        problems = list(boot.errors)
        for inst in self.market.instruments:
            last = self.market.last_candle_open(inst)
            if last is None or now - (last + pd.Timedelta(hours=1)) > pd.Timedelta(minutes=self.settings.stale_minutes):
                problems.append(f"{inst}: newest confirmed 1H candle {None if last is None else iso(last)}")
        if problems:
            raise FleetNotReady("public data not ready, no fleet created: " + "; ".join(problems))
        self.state = {
            "version": STATE_VERSION, "fingerprint": self.manifest.fingerprint(), "fleet_fingerprint": self.manifest.fleet_fingerprint(),
            "created_at": iso(now), "manifest": self.manifest.to_dict(), "series": {}, "accounts": {}, "portfolio": None, "fits": {},
            "cycles": 0, "positioning_source": self.market.positioning, "settings": self.settings.__dict__.copy(), "reports": {},
        }
        records: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for acc in self.manifest.accounts:
            self._add_account(acc, now, records)
        self._commit(records)
        rec = {"type": "created", "now": iso(now), "data": boot.to_dict(), "accounts": len(self.manifest.accounts),
               "fingerprint": self.manifest.fingerprint(), "positioning_source": self.market.positioning}
        append_fleet_log(self.paths.fleet_log, rec)
        return rec

    def _add_account(self, acc: AccountSpec, now: pd.Timestamp, records: Dict[str, List[Dict[str, Any]]]) -> None:
        """Register an account that starts now: flat, at the first bar of its series that closes after ``now``."""
        self.state["accounts"][acc.account_id] = {"seq": 0, "engine": None, "fingerprint": account_fingerprint(acc),
                                                  "created_at": iso(now), "retired_at": None}
        pairs = [s.series for _, s in acc.portfolio.sleeves] if acc.kind == "portfolio" else [(acc.instrument, acc.timeframe)]
        for inst, tf in pairs:
            self.state["series"].setdefault(series_key(inst, tf), {"anchor": None, "last_bar": None, "bars": 0, "gaps": 0, "created_at": iso(now)})
        if acc.kind != "portfolio":
            self.engines[acc.account_id] = SleeveEngine(self._engine_cfg(acc))
        records[acc.account_id].append(self._start_record(acc, now))
        if acc.kind == "portfolio":
            records[acc.account_id].extend(self._portfolio_warmup(now))

    def _engine_cfg(self, acc: AccountSpec) -> EngineConfig:
        if acc.kind == "buy_and_hold":
            return EngineConfig(costs=self.manifest.costs, init_cash=self.manifest.init_cash, sized=False)
        return engine_config(acc.sleeve, costs=self.manifest.costs, init_cash=self.manifest.init_cash)

    def _start_record(self, acc: AccountSpec, now: pd.Timestamp) -> Dict[str, Any]:
        return {
            "type": "start", "created_at": iso(now), "spec": acc.to_dict(), "fingerprint": account_fingerprint(acc),
            "fleet_fingerprint": self.manifest.fleet_fingerprint(), "init_cash": self.manifest.init_cash,
            "positioning_source": self.market.positioning,
            "anchor_rule": "starts flat at the first bar of its series that closes after created_at; fills only from the next bar's open",
            "note": "SIMULATION ONLY - virtual fills on public data; nothing here is an order or approves one",
        }

    def _account_started(self, account_id: str, bar_close: pd.Timestamp) -> bool:
        """An account only trades bars that close after it was created."""
        created = self.state["accounts"][account_id].get("created_at") or self.state["created_at"]
        return bar_close > _ts(created)

    def _load(self, state: Dict[str, Any]) -> None:
        self.state = state
        for acc in self.manifest.accounts:
            meta = state["accounts"].get(acc.account_id)
            if acc.kind == "portfolio" or meta is None:
                continue
            raw = meta.get("engine")
            self.engines[acc.account_id] = SleeveEngine(self._engine_cfg(acc), SleeveState.from_dict(raw) if raw else None)
        pf = state.get("portfolio")
        if pf is not None and self._pf_account is not None and self._pf_account.account_id in state["accounts"]:
            self.book = PortfolioBook.from_dict(pf["book"])
            for name, sleeve in self._pf_account.portfolio.sleeves:
                cfg = engine_config(sleeve, costs=self.manifest.costs, init_cash=self.manifest.init_cash)
                self.pf_engines[name] = SleeveEngine(cfg, SleeveState.from_dict(pf["sleeves"][name]["engine"]))
                self.pf_days[name] = SleeveDays.from_dict(pf["sleeves"][name]["days"])
        self.fits = {k: RegimeFit.from_dict(v) for k, v in (state.get("fits") or {}).items()}

    # -- portfolio warm-up -----------------------------------------------------------

    def _portfolio_warmup(self, now: pd.Timestamp) -> List[Dict[str, Any]]:
        acc = self._pf_account
        spec = acc.portfolio
        forward_start = (now.floor("D") + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        self.book = PortfolioBook(forward_start_day=forward_start)
        warm_from = now - pd.Timedelta(days=spec.warmup_days)
        summary: Dict[str, Any] = {}
        for name, sleeve in spec.sleeves:
            cfg = engine_config(sleeve, costs=self.manifest.costs, init_cash=self.manifest.init_cash)
            engine = SleeveEngine(cfg)
            days = SleeveDays()
            tf = parse_timeframe(sleeve.timeframe)
            bars = self.market.bars(sleeve.instrument, sleeve.timeframe)
            hist = bars[(bars.index + tf) <= now]
            hist = hist[hist.index > warm_from - pd.Timedelta(days=self.settings.window_days)]
            ctx = self.market.context(sleeve.instrument, sleeve.timeframe)
            decisions = frame_decisions(sleeve, hist, ctx, start=warm_from) if len(hist) else []
            warm = hist[hist.index >= warm_from]
            for (ts, row), dec in zip(warm.iterrows(), decisions):
                out = engine.step(iso(ts), float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), dec)
                days.on_bar(ts, ts + tf, out.equity, self.manifest.init_cash)
            self.book.absorb(name, days)
            self.pf_engines[name] = engine
            self.pf_days[name] = days
            summary[name] = {"bars": int(len(warm)), "equity": engine.state.equity, "in_position": engine.state.in_pos,
                             "trades_closed": engine.state.trades_closed}
        return [{"type": "portfolio_warmup", "from": iso(warm_from), "until": iso(now), "forward_start_day": forward_start,
                 "sleeves": summary, "days_of_history": len(self.book.daily),
                 "note": "warm-up history only seeds the trailing weights and the vol estimate; it is not part of the forward record"}]

    # -- one cycle ----------------------------------------------------------------------

    def cycle(self, now: datetime) -> Dict[str, Any]:
        now_ts = _ts(now)
        summary: Dict[str, Any] = {"now": iso(now_ts), "bars": {}, "errors": [], "portfolio_days": [], "gaps": []}
        try:
            refresh = self.market.refresh(now_ts.to_pydatetime())
            summary["data"] = refresh.to_dict()
            summary["errors"].extend(refresh.errors)
        except Exception as exc:  # public data down: process what is stored, try again next cycle
            summary["errors"].append(f"refresh: {type(exc).__name__}: {exc}")
        records: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        failed = False
        summary["bars"] = {key: 0 for key in sorted(self.state["series"])}
        try:
            # Every series' new bars in ONE time order (close time, then series): a catch-up after downtime
            # processes and journals exactly what live running would have.
            plan: List[Tuple[pd.Timestamp, str, pd.Timestamp, Optional[Dict[str, Any]]]] = []
            for key in sorted(self.state["series"]):
                plan.extend(self._plan_series(key, now_ts))
            plan.sort(key=lambda item: (item[0], item[1]))
            for _close, key, ts, gap in plan:
                self._run_bar(key, ts, gap, records, summary)
                summary["bars"][key] += 1
        except Exception as exc:  # never keep a half-processed cycle: reload the saved state, retry next cycle
            summary["errors"].append(f"bars: {type(exc).__name__}: {exc}")
            summary["traceback"] = traceback.format_exc(limit=5)
            self._reload_after_error()
            records = defaultdict(list)
            failed = True
        summary["processing_failed"] = failed
        try:
            if self.book is not None and not failed:
                summary["portfolio_days"] = self._book_portfolio_days(records)
            self.state["cycles"] = int(self.state.get("cycles", 0)) + 1
            self.state["last_cycle"] = iso(now_ts)
            summary["stale"] = self._stale_check(now_ts, summary)
            self._commit(records)
        except Exception:
            # Nothing of a cycle that could not be saved stays in memory: the next cycle redoes it from the last saved
            # state, and journal records already written are recognised by their sequence numbers.
            self._reload_after_error()
            raise
        self._log_cycle(now_ts, summary)
        if self.report_writer is not None:
            try:
                summary["reports"] = self.report_writer(now_ts.to_pydatetime())
            except Exception as exc:
                summary["errors"].append(f"report: {type(exc).__name__}: {exc}")
        return summary

    def _reload_after_error(self) -> None:
        state = read_state(self.paths.state_file)
        if state is not None:
            self.engines, self.pf_engines, self.pf_days = {}, {}, {}
            self._load(state)

    def _plan_series(self, key: str, now: pd.Timestamp) -> List[Tuple[pd.Timestamp, str, pd.Timestamp, Optional[Dict[str, Any]]]]:
        """The complete bars of one series still to process, in order, with a gap note where bars are missing.

        Stops before a bar that follows a missing one while the missing bar's 1H candle may still arrive
        (``grace_minutes`` after it closed).
        """
        inst, tf = key.split(" ")
        s = self.state["series"][key]
        delta = parse_timeframe(tf)
        bars = self.market.bars(inst, tf)
        if bars.empty:
            return []
        created = _ts(s.get("created_at") or self.state["created_at"])
        last = None if s["last_bar"] is None else _ts(s["last_bar"])
        todo = bars[(bars.index + delta) > created] if last is None else bars[bars.index > last]
        grace = pd.Timedelta(minutes=self.settings.grace_minutes)
        out: List[Tuple[pd.Timestamp, str, pd.Timestamp, Optional[Dict[str, Any]]]] = []
        for ts in todo.index:
            gap = None
            if last is not None:
                expected = last + delta
                if ts > expected:
                    if now < ts + delta + grace:
                        break  # a late 1H candle of the bar at `expected` may still arrive: wait `grace` after the next bar closed
                    gap = {"type": "gap", "series": key, "missing_from": iso(expected), "missing_bars": int((ts - expected) / delta),
                           "next_bar": iso(ts)}
            out.append((ts + delta, key, ts, gap))
            last = ts
        return out

    def _run_bar(self, key: str, ts: pd.Timestamp, gap: Optional[Dict[str, Any]], records: Dict[str, List[Dict[str, Any]]],
                 summary: Dict[str, Any]) -> None:
        inst, tf = key.split(" ")
        s = self.state["series"][key]
        if gap is not None:
            summary["gaps"].append(gap)
            s["gaps"] = int(s.get("gaps", 0)) + int(gap["missing_bars"])
            delta = parse_timeframe(tf)
            for acc in self._by_series.get(key, []):
                if self._account_started(acc.account_id, ts + delta):
                    records[acc.account_id].append(dict(gap))
            if self._pf_by_series.get(key) and self._pf_account is not None and self._account_started(self._pf_account.account_id, ts + delta):
                records[self._pf_account.account_id].append(dict(gap))
        self._process_bar(inst, tf, ts, self.market.bars(inst, tf), records)
        s["last_bar"] = iso(ts)
        if s["anchor"] is None:
            s["anchor"] = iso(ts)
        s["bars"] = int(s.get("bars", 0)) + 1

    def _process_bar(self, inst: str, tf: str, ts: pd.Timestamp, bars: pd.DataFrame, records: Dict[str, List[Dict[str, Any]]]) -> None:
        key = series_key(inst, tf)
        delta = parse_timeframe(tf)
        window = frame_until(bars, ts)
        row = window.iloc[-1]
        o, h, low, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        fit: Optional[RegimeFit] = None
        if self._gated.get(key):
            fit = self.fits.get(key)
            if needs_refit(fit, ts):
                fit = fit_series(bars, inst, tf, ts, self._gated[key][0].sleeve.regime)
                self.fits[key] = fit
                self.state["fits"][key] = fit.to_dict()
                for acc in self._gated[key]:
                    if self._account_started(acc.account_id, ts + delta):
                        records[acc.account_id].append({"type": "regime_fit", "bar": iso(ts), **fit.summary()})
        ctx = self.market.context(inst, tf)
        ages = self.market.positioning_age(inst, ts) if self.market.positioning == "okx" else {}
        for acc in self._by_series.get(key, []):
            if not self._account_started(acc.account_id, ts + delta):
                continue  # added later: its anchor is the first bar that closes after it was created
            info, err = self._decide(acc.sleeve, acc.kind, window, ctx, fit)
            out = self.engines[acc.account_id].step(iso(ts), o, h, low, c, None if info is None else info.decision)
            records[acc.account_id].append(self._bar_record(ts, delta, (o, h, low, c), out, info, err, ages if acc.sleeve is not None and acc.sleeve.uses_positioning else None))
        pf_live = self._pf_account is not None and self._account_started(self._pf_account.account_id, ts + delta)
        for name, sleeve in (self._pf_by_series.get(key, []) if pf_live else []):
            info, err = self._decide(sleeve, "sleeve", window, ctx, None)
            engine = self.pf_engines[name]
            out = engine.step(iso(ts), o, h, low, c, None if info is None else info.decision)
            self.pf_days[name].on_bar(ts, ts + delta, out.equity, self.manifest.init_cash)
            rec = self._bar_record(ts, delta, (o, h, low, c), out, info, err, None)
            rec["sleeve"] = name
            records[self._pf_account.account_id].append(rec)

    def _decide(self, sleeve: Optional[SleeveSpec], kind: str, window: pd.DataFrame, ctx, fit: Optional[RegimeFit]) -> Tuple[Optional[DecisionInfo], Optional[str]]:
        try:
            if kind == "buy_and_hold":
                return decide_buy_and_hold(window), None
            return decide_sleeve(sleeve, window, ctx, regime_fit=fit, window_days=self.settings.window_days), None
        except Exception as exc:  # fail closed: no decision -> stops only, no entry, no signal exit
            return None, f"{type(exc).__name__}: {exc}"

    def _bar_record(self, ts, delta, ohlc, out: BarOutcome, info: Optional[DecisionInfo], err: Optional[str], ages) -> Dict[str, Any]:
        rec: Dict[str, Any] = {
            "type": "bar", "bar": iso(ts), "close_time": iso(ts + delta), "ohlc": [float(x) for x in ohlc], "anchor": out.bar_index == 0,
            "bar_index": out.bar_index, "events": out.events, "equity": out.equity, "cash": out.cash, "quantity": out.qty,
            "in_position": out.in_position, "allocation": out.allocation, "stop_price": out.stop_px, "target_price": out.target_px,
            "ladder_level": out.ladder_level, "ladder_multiplier": out.ladder_multiplier,
        }
        if info is not None:
            rec["decision"] = info.to_dict()
        else:
            rec["decision_error"] = err
        if ages is not None:
            rec["positioning_age_hours"] = ages
        return rec

    def _book_portfolio_days(self, records: Dict[str, List[Dict[str, Any]]]) -> List[str]:
        acc = self._pf_account
        for name, days in self.pf_days.items():
            self.book.absorb(name, days)
        booked: List[str] = []
        for day in self.book.days_ready(self.pf_days):
            in_pos = {name: eng.state.in_pos for name, eng in self.pf_engines.items()}
            rec = book_day(self.book, acc.portfolio, day, in_pos)
            rec["equity"] = self.manifest.init_cash * self.book.equity
            records[acc.account_id].append(rec)
            booked.append(day)
        return booked

    # -- persistence --------------------------------------------------------------------

    def _commit(self, records: Dict[str, List[Dict[str, Any]]]) -> None:
        for acc in self.manifest.accounts:
            new = records.get(acc.account_id) or []
            meta = self.state["accounts"].get(acc.account_id)
            if meta is None:
                continue
            for rec in new:
                meta["seq"] = int(meta["seq"]) + 1
                rec["seq"] = meta["seq"]
                rec["account"] = acc.account_id
            Journal(self.paths.journal(acc.account_id)).append(new)
            if acc.kind != "portfolio":
                meta["engine"] = self.engines[acc.account_id].state.to_dict()
        if self.book is not None:
            self.state["portfolio"] = {
                "book": self.book.to_dict(),
                "sleeves": {name: {"engine": self.pf_engines[name].state.to_dict(), "days": self.pf_days[name].to_dict()} for name in self.pf_engines},
            }
        write_state(self.paths.state_file, self.state)

    def _stale_check(self, now: pd.Timestamp, summary: Dict[str, Any]) -> bool:
        stale = False
        newest: Dict[str, Optional[str]] = {}
        for inst in self.market.instruments:
            last = self.market.last_candle_open(inst)
            newest[inst] = None if last is None else iso(last)
            if last is None or now - (last + pd.Timedelta(hours=1)) > pd.Timedelta(minutes=self.settings.stale_minutes):
                stale = True
        summary["newest_candle"] = newest
        if stale != self._stale:
            append_fleet_log(self.paths.fleet_log, {"type": "data_stale" if stale else "data_fresh", "now": iso(now), "newest_candle": newest})
            self._stale = stale
        self.state["health"] = {"stale": stale, "newest_candle": newest, "last_cycle": iso(now),
                                "last_errors": summary["errors"][-5:]}
        return stale

    def _log_cycle(self, now: pd.Timestamp, summary: Dict[str, Any]) -> None:
        busy = any(summary["bars"].values()) or summary["errors"] or summary["portfolio_days"] or summary["gaps"]
        due = self._last_log_at is None or now - self._last_log_at >= pd.Timedelta(minutes=self.settings.heartbeat_log_minutes)
        if busy or due:
            rec = {k: v for k, v in summary.items() if k != "traceback"}
            rec["type"] = "cycle"
            rec["cycles"] = self.state.get("cycles")
            append_fleet_log(self.paths.fleet_log, rec)
            self._last_log_at = now

    # -- read-only views --------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return status_from_state(self.state, self.manifest)


def status_from_state(state: Dict[str, Any], manifest: Optional[FleetManifest] = None) -> Dict[str, Any]:
    """A compact status from the saved state alone (used by ``--status``; reads no network)."""
    out: Dict[str, Any] = {"created_at": state.get("created_at"), "last_cycle": state.get("last_cycle"), "cycles": state.get("cycles"),
                           "fingerprint": state.get("fingerprint"), "positioning_source": state.get("positioning_source"),
                           "health": state.get("health"), "series": state.get("series"), "accounts": {}}
    labels = {a["account_id"]: a for a in (state.get("manifest") or {}).get("accounts", [])}
    for aid, meta in (state.get("accounts") or {}).items():
        eng = meta.get("engine")
        item: Dict[str, Any] = {"label": labels.get(aid, {}).get("label"), "role": labels.get(aid, {}).get("role"), "journal_records": meta.get("seq"),
                                "created_at": meta.get("created_at"), "retired_at": meta.get("retired_at")}
        if eng:
            item.update({"equity": eng.get("equity"), "in_position": eng.get("in_pos"), "allocation": eng.get("alloc") if eng.get("in_pos") else 0.0,
                         "last_bar": eng.get("last_bar_time"), "trades_closed": eng.get("trades_closed"), "fees_paid": eng.get("fees_paid"),
                         "ladder_level": eng.get("lad_level")})
        out["accounts"][aid] = item
    pf = state.get("portfolio")
    if pf:
        book = pf["book"]
        init = (state.get("manifest") or {}).get("init_cash", 10_000.0)
        for aid, item in out["accounts"].items():
            if labels.get(aid, {}).get("kind") == "portfolio":
                item.update({"equity": init * float(book.get("equity", 1.0)), "forward_start_day": book.get("forward_start_day"),
                             "days_booked": len(book.get("done_days") or []), "ladder_level": book.get("lad_level"),
                             "sleeves_in_position": {n: s["engine"].get("in_pos") for n, s in pf["sleeves"].items()}})
    return out
