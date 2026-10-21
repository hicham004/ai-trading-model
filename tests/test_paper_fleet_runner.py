"""Paper-fleet runner end to end on a replayed synthetic market (offline): journals, restarts, crashes, gaps, failures."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pandas as pd
import pytest

from research.engine import Costs
from research.paper_fleet import runner as runner_mod
from research.paper_fleet.config import INSTRUMENTS, FleetManifest, load_manifest
from research.paper_fleet.data import FleetLake, MarketData
from research.paper_fleet.replay import ReplayFeed, check_invariants, synthetic_market
from research.paper_fleet.runner import FleetError, FleetNotReady, FleetSettings, PaperFleet, status_from_state
from research.paper_fleet.store import FleetPaths, Journal, read_state

KEEP = ("c01-s1s5-btc-6h-none", "c03-s2-btc-4h-gate", "ctl-hold-btc-4h", "ctl-bh-eth-6h", "pf-s1s2s4-btceth-vt15")
LIGHT = ("c01-s1s5-btc-6h-none", "ctl-hold-btc-4h", "ctl-bh-eth-6h")  # no regime fit, no portfolio: quick runs
SETTINGS = FleetSettings(window_days=120.0)  # the live history (907 days): gated windows are exactly the live ones
T0 = pd.Timestamp("2026-10-15 10:20", tz="UTC")
END = pd.Timestamp("2026-10-17 04:10", tz="UTC")
STEP = pd.Timedelta(hours=2)


@pytest.fixture(scope="module")
def data():
    return synthetic_market(days=1000, end=pd.Timestamp("2026-10-19 00:00", tz="UTC"))


def _subset(ids):
    full = load_manifest()
    return FleetManifest(accounts=tuple(a for a in full.accounts if a.account_id in ids), sources=full.sources)


@pytest.fixture(scope="module")
def manifest():
    return _subset(KEEP)


@pytest.fixture(scope="module")
def light():
    return _subset(LIGHT)


def make(root: Path, data, manifest, now: pd.Timestamp):
    candles, funding, oi = data
    feed = ReplayFeed(candles, funding, oi)
    feed.now = now
    paths = FleetPaths(root)
    market = MarketData(FleetLake(paths.lake), feed, instruments=INSTRUMENTS, history_days=SETTINGS.history_days)
    fleet = PaperFleet(manifest, paths, market, settings=SETTINGS)
    assert fleet.acquire()
    fleet.open(now.to_pydatetime())
    return fleet, feed


def advance(fleet, feed, start: pd.Timestamp, end: pd.Timestamp, step=STEP):
    """Cycles from ``start`` every ``step``, and always one last cycle exactly at ``end``."""
    t = start
    out = []
    while t < end:
        feed.now = t
        out.append(fleet.cycle(t.to_pydatetime()))
        t += step
    feed.now = end
    out.append(fleet.cycle(end.to_pydatetime()))
    return out


def journals(root: Path, manifest):
    return {a.account_id: [json.loads(l) for l in (root / "journals" / f"{a.account_id}.jsonl").read_text(encoding="utf-8").splitlines()]
            for a in manifest.accounts}


@pytest.fixture(scope="module")
def straight(tmp_path_factory, data, manifest):
    root = tmp_path_factory.mktemp("straight")
    fleet, feed = make(root, data, manifest, T0)
    summaries = advance(fleet, feed, T0 + pd.Timedelta(minutes=40), END)
    fleet.release()
    return root, summaries


def test_a_fresh_fleet_starts_flat_at_the_first_bar_closing_after_its_creation(straight, manifest):
    root, summaries = straight
    js = journals(root, manifest)
    state = read_state(root / "_state" / "fleet_state.json")
    assert state["series"]["BTC-USDT 4H"]["anchor"] == "2026-10-15T08:00:00Z"  # 08:00-12:00 closes after 10:20
    assert state["series"]["ETH-USDT 6H"]["anchor"] == "2026-10-15T06:00:00Z"
    for aid, recs in js.items():
        assert recs[0]["type"] == "start" and recs[0]["account"] == aid and recs[0]["seq"] == 1
        assert [r["seq"] for r in recs] == list(range(1, len(recs) + 1))
    bars = [r for r in js["c03-s2-btc-4h-gate"] if r["type"] == "bar"]
    assert bars[0]["anchor"] and not bars[0]["events"] and bars[0]["equity"] == 10_000.0
    assert len(bars) == 11  # 2026-10-15 08:00 .. 2026-10-17 00:00 (that bar closes at 04:00; END is 04:10)
    assert any(r["type"] == "regime_fit" for r in js["c03-s2-btc-4h-gate"])
    assert not any(r["type"] == "regime_fit" for r in js["c01-s1s5-btc-6h-none"])
    c01 = [r for r in js["c01-s1s5-btc-6h-none"] if r["type"] == "bar"]
    assert "positioning" in c01[-1]["decision"]["diagnostics"] and "positioning_age_hours" in c01[-1]
    pf = js["pf-s1s2s4-btceth-vt15"]
    assert pf[1]["type"] == "portfolio_warmup" and pf[1]["forward_start_day"] == "2026-10-16"
    days = [r for r in pf if r["type"] == "portfolio_day"]
    assert [d["day"] for d in days] == ["2026-10-16"]
    assert all(0.0 <= d["vol_scale"] <= 1.0 for d in days) and days[-1]["equity"] == pytest.approx(10_000 * days[-1]["equity_index"])
    assert {r["sleeve"] for r in pf if r["type"] == "bar"} == {"S1/BTC/6H", "S1/ETH/6H", "S2/BTC/4H", "S2/ETH/4H", "S4/BTC/6H", "S4/ETH/6H"}
    assert all(ok for _, ok, _ in check_invariants(FleetPaths(root), manifest)), check_invariants(FleetPaths(root), manifest)
    fills = sum(1 for recs in js.values() for r in recs if r["type"] == "bar" for e in r["events"] if e["kind"] in ("entry", "exit"))
    assert fills > 0
    status = status_from_state(state)
    assert set(status["accounts"]) == set(KEEP) and status["accounts"]["pf-s1s2s4-btceth-vt15"]["days_booked"] == 1


def test_a_restart_in_the_middle_changes_nothing(straight, tmp_path, data, manifest):
    root, _ = straight
    mid = pd.Timestamp("2026-10-16 09:10", tz="UTC")
    fleet, feed = make(tmp_path, data, manifest, T0)
    advance(fleet, feed, T0 + pd.Timedelta(minutes=40), mid, step=pd.Timedelta(hours=3))
    fleet.release()
    # Down for 9 hours: the resumed fleet catches up with every bar it missed, in order.
    later = mid + pd.Timedelta(hours=9)
    fleet2, feed2 = make(tmp_path, data, manifest, later)
    advance(fleet2, feed2, later, END)
    fleet2.release()
    a, b = journals(root, manifest), journals(tmp_path, manifest)
    assert a == b


def test_a_crash_between_journal_and_state_writes_never_duplicates_records(straight, tmp_path, data, manifest, monkeypatch):
    root, _ = straight
    mid = pd.Timestamp("2026-10-16 11:10", tz="UTC")
    fleet, feed = make(tmp_path, data, manifest, T0)
    advance(fleet, feed, T0 + pd.Timedelta(minutes=40), mid, step=pd.Timedelta(hours=4))

    def boom(path, state):
        raise OSError("disk full")

    monkeypatch.setattr(runner_mod, "write_state", boom)
    feed.now = mid + pd.Timedelta(hours=1)
    with pytest.raises(OSError):
        fleet.cycle(feed.now.to_pydatetime())  # journals got the 12:00 bar; the state did not
    fleet.release()
    monkeypatch.undo()
    fleet2, feed2 = make(tmp_path, data, manifest, mid + pd.Timedelta(hours=1))
    advance(fleet2, feed2, mid + pd.Timedelta(hours=1), END)
    fleet2.release()
    assert journals(root, manifest) == journals(tmp_path, manifest)


def _reopen(root, data, manifest, now):
    candles, funding, oi = data
    feed = ReplayFeed(candles, funding, oi)
    feed.now = now
    paths = FleetPaths(root)
    market = MarketData(FleetLake(paths.lake), feed, instruments=INSTRUMENTS, history_days=SETTINGS.history_days)
    return PaperFleet(manifest, paths, market, settings=SETTINGS), feed


def test_a_second_instance_is_locked_out_and_changed_rules_refuse_to_resume(tmp_path, data, light):
    fleet, feed = make(tmp_path, data, light, T0)
    other, _ = _reopen(tmp_path, data, light, T0)
    assert not other.acquire()
    fleet.release()
    # A changed account (same id, other rules) would mix two rule sets in one record: refused.
    changed_acc = dataclasses.replace(light.accounts[0], sleeve=dataclasses.replace(light.accounts[0].sleeve, rebalance_threshold=0.5))
    changed = FleetManifest(accounts=(changed_acc,) + light.accounts[1:], sources=light.sources)
    f2, _ = _reopen(tmp_path, data, changed, T0)
    assert f2.acquire()
    with pytest.raises(FleetError, match="rules of c01-s1s5-btc-6h-none changed"):
        f2.open(T0.to_pydatetime())
    f2.release()
    # Changed shared rules (costs) refuse the whole fleet.
    costly = FleetManifest(accounts=light.accounts, sources=light.sources, costs=Costs(fee_rate=0.002, slippage_rate=0.0005))
    f3, _ = _reopen(tmp_path, data, costly, T0)
    assert f3.acquire()
    with pytest.raises(FleetError, match="shared rules"):
        f3.open(T0.to_pydatetime())
    f3.release()


def test_an_added_account_starts_at_its_own_time_and_a_removed_one_is_retired(tmp_path, data, light):
    first = FleetManifest(accounts=light.accounts[:2], sources=light.sources)  # c01 and ctl-hold-btc-4h
    fleet, feed = make(tmp_path, data, first, T0)
    advance(fleet, feed, T0 + pd.Timedelta(minutes=40), pd.Timestamp("2026-10-16 01:10", tz="UTC"), step=pd.Timedelta(hours=4))
    fleet.release()
    later = pd.Timestamp("2026-10-16 07:30", tz="UTC")  # after 6 h of downtime
    second = FleetManifest(accounts=(light.accounts[0], light.accounts[2]), sources=light.sources)  # hold retired, bh-eth-6h added
    fleet2, feed2 = make(tmp_path, data, second, later)
    advance(fleet2, feed2, later, pd.Timestamp("2026-10-16 20:10", tz="UTC"), step=pd.Timedelta(hours=4))
    fleet2.release()
    js = {aid: list(Journal(tmp_path / "journals" / f"{aid}.jsonl").read()) for aid in ("c01-s1s5-btc-6h-none", "ctl-hold-btc-4h", "ctl-bh-eth-6h")}
    added = [r for r in js["ctl-bh-eth-6h"] if r["type"] == "bar"]
    assert js["ctl-bh-eth-6h"][0]["created_at"] == "2026-10-16T07:30:00Z"
    assert added[0]["anchor"] and added[0]["bar"] == "2026-10-16T06:00:00Z"  # the first 6H bar that closes after 07:30
    assert js["ctl-hold-btc-4h"][-1]["type"] == "retired"
    hold_bars = [r["bar"] for r in js["ctl-hold-btc-4h"] if r["type"] == "bar"]
    assert hold_bars[-1] == "2026-10-15T20:00:00Z"  # nothing after it was retired
    c01 = [r["bar"] for r in js["c01-s1s5-btc-6h-none"] if r["type"] == "bar"]
    assert c01 == sorted(c01) and "2026-10-16T00:00:00Z" in c01 and "2026-10-16T12:00:00Z" in c01  # caught up without a hole
    state = read_state(tmp_path / "_state" / "fleet_state.json")
    assert state["accounts"]["ctl-hold-btc-4h"]["retired_at"] == "2026-10-16T07:30:00Z"
    assert state["series"]["ETH-USDT 6H"]["anchor"] == "2026-10-16T06:00:00Z"
    status = status_from_state(state)
    assert status["accounts"]["ctl-hold-btc-4h"]["retired_at"] and not status["accounts"]["ctl-bh-eth-6h"]["retired_at"]
    # A retired id cannot come back with the same name.
    f3, _ = _reopen(tmp_path, data, light, later + pd.Timedelta(hours=20))
    assert f3.acquire()
    with pytest.raises(FleetError, match="retired"):
        f3.open((later + pd.Timedelta(hours=20)).to_pydatetime())
    f3.release()


def test_a_missing_candle_skips_its_bar_after_the_grace_period(tmp_path, data, light):
    manifest = light
    candles, funding, oi = data
    hole = pd.Timestamp("2026-10-16 09:00", tz="UTC")  # inside the 08:00-12:00 4H bar and the 06:00-12:00 6H bar
    holed = {k: (v.drop(index=[hole]) if k == "BTC-USDT" else v) for k, v in candles.items()}
    fleet, feed = make(tmp_path, (holed, funding, oi), manifest, T0)
    advance(fleet, feed, T0 + pd.Timedelta(minutes=40), pd.Timestamp("2026-10-16 20:10", tz="UTC"))
    fleet.release()
    js = journals(tmp_path, manifest)
    hold = js["ctl-hold-btc-4h"]
    gaps = [r for r in hold if r["type"] == "gap"]
    assert gaps and gaps[0]["missing_from"] == "2026-10-16T08:00:00Z" and gaps[0]["missing_bars"] == 1
    bars = [r["bar"] for r in hold if r["type"] == "bar"]
    assert "2026-10-16T08:00:00Z" not in bars and "2026-10-16T12:00:00Z" in bars and bars == sorted(bars)
    state = read_state(tmp_path / "_state" / "fleet_state.json")
    assert state["series"]["BTC-USDT 4H"]["gaps"] == 1 and state["series"]["BTC-USDT 6H"]["gaps"] == 1
    assert state["series"]["ETH-USDT 6H"]["gaps"] == 0


def test_a_failed_decision_fails_closed_for_that_account_only(tmp_path, data, light, monkeypatch):
    manifest = light
    real = runner_mod.decide_sleeve
    bad = "2026-10-15T20:00:00Z"

    def flaky(spec, window, ctx, **kw):
        if spec.candidate == "hold" and spec.timeframe == "4H" and window.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ") == bad:
            raise RuntimeError("synthetic failure")
        return real(spec, window, ctx, **kw)

    monkeypatch.setattr(runner_mod, "decide_sleeve", flaky)
    fleet, feed = make(tmp_path, data, manifest, T0)
    advance(fleet, feed, T0 + pd.Timedelta(minutes=40), pd.Timestamp("2026-10-16 04:10", tz="UTC"))
    fleet.release()
    hold = [r for r in journals(tmp_path, manifest)["ctl-hold-btc-4h"] if r["type"] == "bar"]
    failed = next(r for r in hold if r["bar"] == bad)
    assert "synthetic failure" in failed["decision_error"] and "decision" not in failed
    nxt = hold[hold.index(failed) + 1]
    assert [e["kind"] for e in nxt["events"]][-1] == "no_decision"
    others = [r for r in journals(tmp_path, manifest)["c01-s1s5-btc-6h-none"] if r["type"] == "bar"]
    assert others and all("decision" in r for r in others)  # the other accounts are unaffected


def test_stale_public_data_is_reported(tmp_path, data, light):
    fleet, feed = make(tmp_path, data, light, T0)
    frozen = T0 + pd.Timedelta(hours=2)
    feed.now = frozen
    fleet.cycle(frozen.to_pydatetime())
    later = frozen + pd.Timedelta(hours=4)
    s = fleet.cycle(later.to_pydatetime())  # the feed still serves nothing newer than `frozen`
    fleet.release()
    assert s["stale"] is True
    log = [json.loads(l) for l in (tmp_path / "fleet.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(r["type"] == "data_stale" for r in log)
    assert read_state(tmp_path / "_state" / "fleet_state.json")["health"]["stale"] is True


@pytest.fixture(scope="module")
def light_straight(tmp_path_factory, data, light):
    root = tmp_path_factory.mktemp("light_straight")
    fleet, feed = make(root, data, light, T0)
    advance(fleet, feed, T0 + pd.Timedelta(minutes=40), END)
    fleet.release()
    return root


def test_a_failed_save_in_a_running_loop_loses_nothing(light_straight, tmp_path, data, light, monkeypatch):
    """The service keeps running after a failed save: the cycle is redone from the saved state, nothing is lost or doubled."""
    fleet, feed = make(tmp_path, data, light, T0)
    mid = pd.Timestamp("2026-10-16 11:10", tz="UTC")
    advance(fleet, feed, T0 + pd.Timedelta(minutes=40), mid, step=pd.Timedelta(hours=4))
    real = runner_mod.write_state
    calls = {"n": 0}

    def fail_once(path, state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real(path, state)

    monkeypatch.setattr(runner_mod, "write_state", fail_once)
    feed.now = mid + pd.Timedelta(hours=1)
    with pytest.raises(OSError):
        fleet.cycle(feed.now.to_pydatetime())
    advance(fleet, feed, mid + pd.Timedelta(hours=2), END)  # the same object keeps going, like the service loop
    fleet.release()
    assert journals(light_straight, light) == journals(tmp_path, light)


def test_no_fleet_is_created_from_stale_public_data(tmp_path, data, light):
    late = pd.Timestamp("2026-10-19 12:00", tz="UTC")  # the replayed market ends at 2026-10-19 00:00
    candles, funding, oi = data
    feed = ReplayFeed(candles, funding, oi)
    feed.now = late
    paths = FleetPaths(tmp_path)
    fleet = PaperFleet(light, paths, MarketData(FleetLake(paths.lake), feed, instruments=INSTRUMENTS, history_days=SETTINGS.history_days),
                       settings=SETTINGS)
    assert fleet.acquire()
    with pytest.raises(FleetNotReady, match="not ready"):
        fleet.open(late.to_pydatetime())
    fleet.release()
    assert not paths.state_file.exists() and not list(paths.journals.glob("*.jsonl"))


def test_resuming_with_another_positioning_source_is_refused(tmp_path, data, light):
    fleet, feed = make(tmp_path, data, light, T0)
    fleet.release()
    candles, funding, oi = data
    paths = FleetPaths(tmp_path)
    other = PaperFleet(light, paths, MarketData(FleetLake(paths.lake), feed, instruments=INSTRUMENTS, history_days=SETTINGS.history_days,
                                                positioning="none"), settings=SETTINGS)
    assert other.acquire()
    with pytest.raises(FleetError, match="positioning"):
        other.open(T0.to_pydatetime())
    other.release()


class LateFeed(ReplayFeed):
    """One 1H candle is published late (at ``arrives``), as OKX sometimes does after an outage."""

    def __init__(self, candles, funding, oi, *, instrument, hidden, arrives):
        super().__init__(candles, funding, oi)
        self.instrument, self.hidden, self.arrives = instrument, hidden, arrives

    def _visible(self, instrument):
        df = super()._visible(instrument)
        if instrument == self.instrument and self.now < self.arrives:
            df = df.drop(index=[self.hidden], errors="ignore")
        return df


def test_a_late_candle_within_the_grace_period_is_not_a_gap(tmp_path, data, light):
    candles, funding, oi = data
    hidden = pd.Timestamp("2026-10-16 09:00", tz="UTC")  # in the 08:00-12:00 4H bar
    feed = LateFeed(candles, funding, oi, instrument="BTC-USDT", hidden=hidden, arrives=pd.Timestamp("2026-10-16 16:40", tz="UTC"))
    feed.now = T0
    paths = FleetPaths(tmp_path)
    fleet = PaperFleet(light, paths, MarketData(FleetLake(paths.lake), feed, instruments=INSTRUMENTS, history_days=SETTINGS.history_days),
                       settings=SETTINGS)
    assert fleet.acquire()
    fleet.open(T0.to_pydatetime())
    t = T0 + pd.Timedelta(minutes=40)
    waited = False
    while t <= pd.Timestamp("2026-10-16 21:10", tz="UTC"):
        feed.now = t
        s = fleet.cycle(t.to_pydatetime())
        if pd.Timestamp("2026-10-16 16:10", tz="UTC") <= t < pd.Timestamp("2026-10-16 16:40", tz="UTC"):
            waited = waited or s["bars"]["BTC-USDT 4H"] == 0  # the 12:00 bar is complete, but the fleet waits for 08:00's candle
        t += pd.Timedelta(minutes=30)
    fleet.release()
    hold = [r for r in Journal(tmp_path / "journals" / "ctl-hold-btc-4h.jsonl").read()]
    assert waited and not any(r["type"] == "gap" for r in hold)
    bars = [r["bar"] for r in hold if r["type"] == "bar"]
    assert "2026-10-16T08:00:00Z" in bars and bars == sorted(bars)
