"""Paper-fleet runner end to end on a replayed synthetic market (offline): journals, restarts, crashes, gaps, failures."""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from research import events as events_mod
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


# -- plan row R5b: two portfolio accounts, and a fleet started by the R5a code ---------------------------------------

PF = "pf-s1s2s4-btceth-vt15"
ALLOC = "pf-s1s2s4-btceth-vt15-alloc2"
PAIR = ("ctl-hold-btc-4h", PF, ALLOC)
PAIR_END = pd.Timestamp("2026-10-18 04:10", tz="UTC")


@pytest.fixture(scope="module")
def pair():
    return _subset(PAIR)


@pytest.fixture(scope="module")
def pair_straight(tmp_path_factory, data, pair):
    root = tmp_path_factory.mktemp("pair_straight")
    fleet, feed = make(root, data, pair, T0)
    advance(fleet, feed, T0 + pd.Timedelta(minutes=40), PAIR_END)
    fleet.release()
    return root


def _strip(records):
    return [{k: v for k, v in r.items() if k not in ("seq", "account")} for r in records]


def test_both_portfolios_book_the_same_days_and_v2s_reference_is_the_v1_account(pair_straight, pair):
    js = journals(pair_straight, pair)
    v1 = [r for r in js[PF] if r["type"] == "portfolio_day"]
    v2 = [r for r in js[ALLOC] if r["type"] == "portfolio_day"]
    assert [d["day"] for d in v1] == [d["day"] for d in v2] == ["2026-10-16", "2026-10-17"]
    for a, b in zip(v1, v2):
        # Started together on the same sleeves: the v1 rules inside the v2 journal ARE the v1 account.
        assert b["allocator"] == "v2" and "allocator" not in a and b["sleeve_returns"] == a["sleeve_returns"]
        assert b["reference_v1"]["equity_index"] == pytest.approx(a["equity_index"], rel=1e-12)
        assert b["weights"] == pytest.approx(a["weights"], rel=1e-12) and b["vol_scale"] == pytest.approx(a["vol_scale"], rel=1e-12)
    assert _strip(r for r in js[PF] if r["type"] == "bar") == _strip(r for r in js[ALLOC] if r["type"] == "bar")  # one decision per sleeve and bar
    warm = next(r for r in js[ALLOC] if r["type"] == "portfolio_warmup")
    assert warm["allocator"]["version"] == "v2" and warm["allocator"]["group_cap"] == 0.5 and warm["forward_start_day"] == "2026-10-16"
    assert all(ok for _, ok, _ in check_invariants(FleetPaths(pair_straight), pair)), check_invariants(FleetPaths(pair_straight), pair)
    state = read_state(pair_straight / "_state" / "fleet_state.json")
    assert state["version"] == 2 and set(state["portfolios"]) == {PF, ALLOC} and "portfolio" not in state
    assert state["portfolios"][ALLOC]["book"]["alloc"]["days"] == 2 and state["portfolios"][PF]["book"]["alloc"] is None
    status = status_from_state(state)
    assert status["accounts"][ALLOC]["allocator"]["version"] == "v2" and status["accounts"][ALLOC]["days_booked"] == 2
    assert status["accounts"][ALLOC]["allocator"]["reference_v1_equity"] == pytest.approx(status["accounts"][PF]["equity"], rel=1e-12)


def test_a_restart_with_two_portfolios_changes_nothing(pair_straight, tmp_path, data, pair):
    mid = pd.Timestamp("2026-10-16 13:10", tz="UTC")
    fleet, feed = make(tmp_path, data, pair, T0)
    advance(fleet, feed, T0 + pd.Timedelta(minutes=40), mid, step=pd.Timedelta(hours=3))
    fleet.release()
    later = mid + pd.Timedelta(hours=7)
    fleet2, feed2 = make(tmp_path, data, pair, later)
    advance(fleet2, feed2, later, PAIR_END)
    fleet2.release()
    assert journals(pair_straight, pair) == journals(tmp_path, pair)


R5A_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "paper_fleet_r5a"
JOIN = pd.Timestamp("2026-10-16 18:10", tz="UTC")


def _copy_r5a_fleet(root: Path) -> None:
    shutil.copytree(R5A_FIXTURE / "_state", root / "_state")
    shutil.copytree(R5A_FIXTURE / "journals", root / "journals")
    shutil.copy2(R5A_FIXTURE / "fleet.jsonl", root / "fleet.jsonl")


def test_a_fleet_written_by_the_r5a_code_resumes_and_the_allocator_account_joins_at_its_own_time(pair_straight, tmp_path, data, pair):
    _copy_r5a_fleet(tmp_path)
    path = tmp_path / "_state" / "fleet_state.json"
    old = read_state(path)
    assert old["version"] == 1 and "portfolio" in old and "portfolios" not in old  # written by the R5a code (tests/fixtures/paper_fleet_r5a)
    assert status_from_state(old)["accounts"][PF]["days_booked"] == 0  # --status still reads it before it is resumed
    fleet2, feed2 = make(tmp_path, data, pair, JOIN)  # the current code, with the allocator account added
    advance(fleet2, feed2, JOIN, PAIR_END)
    fleet2.release()
    for aid in ("ctl-hold-btc-4h", PF):
        before = (R5A_FIXTURE / "journals" / f"{aid}.jsonl").read_bytes().splitlines()
        after = (tmp_path / "journals" / f"{aid}.jsonl").read_bytes().splitlines()
        straight = (pair_straight / "journals" / f"{aid}.jsonl").read_bytes().splitlines()
        assert after[:len(before)] == before  # what the R5a code wrote stays as it was
        # ...and the record goes on as an uninterrupted run. The fixture was written on Windows; elsewhere (Linux CI) the
        # last bits of some floats differ (libm), so the records are compared value by value, not byte for byte.
        rest, rest_straight = after[len(before):], straight[len(before):]
        assert 0 < len(rest) == len(rest_straight)
        assert all(_approx_equal(json.loads(x), json.loads(y)) for x, y in zip(rest, rest_straight))
    alloc = journals(tmp_path, pair)[ALLOC]
    assert alloc[0]["type"] == "start" and alloc[0]["created_at"] == "2026-10-16T18:10:00Z"
    assert alloc[1]["type"] == "portfolio_warmup" and alloc[1]["forward_start_day"] == "2026-10-17"
    assert [r["day"] for r in alloc if r["type"] == "portfolio_day"] == ["2026-10-17"]
    first = {r["sleeve"]: r["bar"] for r in reversed(alloc) if r["type"] == "bar"}
    assert first == {"S1/BTC/6H": "2026-10-16T18:00:00Z", "S1/ETH/6H": "2026-10-16T18:00:00Z", "S2/BTC/4H": "2026-10-16T16:00:00Z",
                     "S2/ETH/4H": "2026-10-16T16:00:00Z", "S4/BTC/6H": "2026-10-16T18:00:00Z", "S4/ETH/6H": "2026-10-16T18:00:00Z"}  # right after its warm-up
    state = read_state(path)
    assert state["version"] == 2 and set(state["portfolios"]) == {PF, ALLOC} and "portfolio" not in state
    assert state["migrations"] == [{"from": 1, "to": 2, "change": "portfolio state keyed by account id (plan row R5b)"}]
    assert all(ok for _, ok, _ in check_invariants(FleetPaths(tmp_path), pair)), check_invariants(FleetPaths(tmp_path), pair)
    log = [json.loads(line) for line in (tmp_path / "fleet.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(r["type"] == "resume" and r["added"] == [ALLOC] for r in log)


def _r5a_like_fleet_until_mid(root: Path, data):
    r5a = _subset(("ctl-hold-btc-4h", PF))
    fleet, feed = make(root, data, r5a, T0)
    advance(fleet, feed, T0 + pd.Timedelta(minutes=40), pd.Timestamp("2026-10-16 09:10", tz="UTC"), step=pd.Timedelta(hours=3))
    fleet.release()


def _join(root: Path, data, manifest, now: pd.Timestamp, *, data_until: pd.Timestamp):
    """Open ``root`` at ``now`` while the public feed has only published candles up to ``data_until``."""
    candles, funding, oi = data
    feed = ReplayFeed(candles, funding, oi)
    feed.now = data_until
    paths = FleetPaths(root)
    fleet = PaperFleet(manifest, paths, MarketData(FleetLake(paths.lake), feed, instruments=INSTRUMENTS, history_days=SETTINGS.history_days),
                       settings=SETTINGS)
    assert fleet.acquire()
    return fleet, feed


def _approx_equal(a, b, rel: float = 1e-9, abs_: float = 1e-12) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_approx_equal(a[k], b[k], rel, abs_) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_approx_equal(x, y, rel, abs_) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float):
        return a == pytest.approx(b, rel=rel, abs=abs_)
    return a == b


def test_an_account_does_not_join_while_the_public_data_lags(tmp_path, data, pair):
    _r5a_like_fleet_until_mid(tmp_path, data)
    before = read_state(tmp_path / "_state" / "fleet_state.json")
    fleet, _ = _join(tmp_path, data, pair, JOIN, data_until=JOIN - pd.Timedelta(hours=9))  # the public feed is 9 hours behind
    with pytest.raises(FleetNotReady, match="not complete"):
        fleet.open(JOIN.to_pydatetime())
    fleet.release()
    assert read_state(tmp_path / "_state" / "fleet_state.json") == before and not (tmp_path / "journals" / f"{ALLOC}.jsonl").exists()


def test_portfolio_sleeves_continue_from_their_warm_up_even_when_they_joined_on_lagging_data(tmp_path, data, pair, monkeypatch):
    """The refusal above is the first defence; with it switched off, a late join still skips no bar and processes none twice."""
    fresh, lagging = tmp_path / "fresh", tmp_path / "lagging"
    for root in (fresh, lagging):
        root.mkdir()
        _r5a_like_fleet_until_mid(root, data)
    f1, feed1 = _join(fresh, data, pair, JOIN, data_until=JOIN)
    f1.open(JOIN.to_pydatetime())
    advance(f1, feed1, JOIN, PAIR_END)
    f1.release()
    monkeypatch.setattr(PaperFleet, "_series_not_ready", lambda self, now, series: [])
    f2, feed2 = _join(lagging, data, pair, JOIN, data_until=JOIN - pd.Timedelta(hours=9))
    f2.open(JOIN.to_pydatetime())  # joins with a warm-up that ends 9 hours early ...
    advance(f2, feed2, JOIN, PAIR_END)  # ... and the late bars arrive in the first cycle
    f2.release()
    a, b = journals(fresh, pair)[ALLOC], journals(lagging, pair)[ALLOC]
    warm_a, warm_b = a[1]["sleeves"], b[1]["sleeves"]
    assert all(warm_b[n]["last_bar"] < warm_a[n]["last_bar"] for n in warm_a)  # the lagging warm-up really ended earlier
    for name, tf in (("S2/BTC/4H", 4), ("S1/ETH/6H", 6)):
        live = [r["bar"] for r in b if r["type"] == "bar" and r["sleeve"] == name]
        step = pd.Timedelta(hours=tf)
        assert pd.Timestamp(live[0]) == pd.Timestamp(warm_b[name]["last_bar"]) + step  # the first live bar follows its warm-up
        assert all(pd.Timestamp(y) - pd.Timestamp(x) == step for x, y in zip(live, live[1:]))  # and none is skipped
    # The same forward record as an account that joined on complete data (late bars decided live instead of in the warm-up:
    # the two decision paths agree to floating-point rounding, tests/test_paper_fleet_signals.py).
    days_a = [{k: v for k, v in r.items() if k not in ("seq", "account")} for r in a if r["type"] == "portfolio_day"]
    days_b = [{k: v for k, v in r.items() if k not in ("seq", "account")} for r in b if r["type"] == "portfolio_day"]
    assert days_a and _approx_equal(days_a, days_b)
    sa, sb = read_state(fresh / "_state" / "fleet_state.json"), read_state(lagging / "_state" / "fleet_state.json")
    assert _approx_equal({n: s["engine"] for n, s in sa["portfolios"][ALLOC]["sleeves"].items()},
                         {n: s["engine"] for n, s in sb["portfolios"][ALLOC]["sleeves"].items()})


def test_an_account_whose_first_start_crashed_is_set_aside_and_starts_cleanly(tmp_path, data, pair, monkeypatch):
    _r5a_like_fleet_until_mid(tmp_path, data)
    real = runner_mod.write_state

    def disk_full(path, state):
        raise OSError("disk full")

    monkeypatch.setattr(runner_mod, "write_state", disk_full)
    fleet, _ = _join(tmp_path, data, pair, JOIN, data_until=JOIN)
    with pytest.raises(OSError):
        fleet.open(JOIN.to_pydatetime())  # the new account's journal is written, the state that registers it is not
    fleet.release()
    monkeypatch.setattr(runner_mod, "write_state", real)
    assert (tmp_path / "journals" / f"{ALLOC}.jsonl").exists() and ALLOC not in read_state(tmp_path / "_state" / "fleet_state.json")["accounts"]
    older = tmp_path / "journals" / f"{ALLOC}.unfinished-20261016T201000Z.jsonl"
    older.write_text('{"seq": 1, "type": "start", "note": "an even older attempt"}\n', encoding="utf-8")  # same name as the next one
    again = JOIN + pd.Timedelta(hours=2)
    fleet2, feed2 = make(tmp_path, data, pair, again)
    advance(fleet2, feed2, again, PAIR_END)
    fleet2.release()
    alloc = journals(tmp_path, pair)[ALLOC]
    assert alloc[0]["type"] == "start" and alloc[0]["created_at"] == "2026-10-16T20:10:00Z" and [r["seq"] for r in alloc] == list(range(1, len(alloc) + 1))
    aside = tmp_path / "journals" / f"{ALLOC}.unfinished-20261016T201000Z-2.jsonl"
    assert aside.exists() and json.loads(aside.read_text(encoding="utf-8").splitlines()[0])["created_at"] == "2026-10-16T18:10:00Z"
    assert "an even older attempt" in older.read_text(encoding="utf-8")  # not overwritten
    log = [json.loads(line) for line in (tmp_path / "fleet.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(r["type"] == "journal_set_aside" and r["account"] == ALLOC for r in log)
    assert all(ok for _, ok, _ in check_invariants(FleetPaths(tmp_path), pair)), check_invariants(FleetPaths(tmp_path), pair)


def test_version_1_states_migrate_even_with_a_retired_portfolio_and_status_never_fails():
    retired = {"version": 1, "portfolio": {"book": {"forward_start_day": "2026-10-16"}, "sleeves": {}},
               "accounts": {PF: {"retired_at": "2026-10-17T00:00:00Z", "seq": 3}, "ctl-hold-btc-4h": {"seq": 5}},
               "manifest": {"accounts": [{"account_id": "ctl-hold-btc-4h", "kind": "sleeve"}]}}  # the R5a code dropped a retired account from it
    out = runner_mod.migrate_state(json.loads(json.dumps(retired)))
    assert out["version"] == 2 and set(out["portfolios"]) == {PF} and "portfolio" not in out
    odd = {"version": 1, "portfolio": {"book": {}}, "accounts": {PF: {}, ALLOC: {}},
           "manifest": {"accounts": [{"account_id": PF, "kind": "portfolio"}, {"account_id": ALLOC, "kind": "portfolio"}]}}
    with pytest.raises(FleetError, match="one portfolio"):
        runner_mod.migrate_state(json.loads(json.dumps(odd)))
    status = status_from_state(odd)
    assert "one portfolio" in status["warnings"][0] and set(status["accounts"]) == {PF, ALLOC}


def test_an_account_waits_for_a_late_candle_in_an_earlier_bar_before_it_joins(tmp_path, data, pair):
    """A candle inside the 04:00 4H / 00:00 6H bar is published late (13:00): at 12:10 the bars that closed last are complete,
    but the series still waits for that candle, so the join waits too; at 13:10 it joins with a complete warm-up."""
    candles, funding, oi = data
    hidden, arrives = pd.Timestamp("2026-10-17 05:00", tz="UTC"), pd.Timestamp("2026-10-17 13:00", tz="UTC")
    late, fresh = tmp_path / "late", tmp_path / "fresh"
    for root in (late, fresh):
        root.mkdir()
        _r5a_like_fleet_until_mid(root, data)

    def opened(root, feed, at):
        feed.now = at
        paths = FleetPaths(root)
        fleet = PaperFleet(pair, paths, MarketData(FleetLake(paths.lake), feed, instruments=INSTRUMENTS, history_days=SETTINGS.history_days),
                           settings=SETTINGS)
        assert fleet.acquire()
        return fleet

    feed = LateFeed(candles, funding, oi, instrument="BTC-USDT", hidden=hidden, arrives=arrives)
    early = opened(late, feed, pd.Timestamp("2026-10-17 12:10", tz="UTC"))
    with pytest.raises(FleetNotReady, match="may still arrive"):
        early.open(pd.Timestamp("2026-10-17 12:10", tz="UTC").to_pydatetime())
    early.release()
    join = pd.Timestamp("2026-10-17 13:10", tz="UTC")
    for root, f in ((late, LateFeed(candles, funding, oi, instrument="BTC-USDT", hidden=hidden, arrives=arrives)), (fresh, ReplayFeed(candles, funding, oi))):
        fleet = opened(root, f, join)
        fleet.open(join.to_pydatetime())
        advance(fleet, f, join, pd.Timestamp("2026-10-18 04:10", tz="UTC"))
        fleet.release()
    a, b = journals(late, pair)[ALLOC], journals(fresh, pair)[ALLOC]
    assert a[1]["sleeves"]["S2/BTC/4H"]["last_bar"] == "2026-10-17T08:00:00Z" and a == b  # nothing missing: as if the candle had been on time


def test_the_dry_run_starts_later_when_its_first_hour_is_not_ready(tmp_path):
    from research.paper_fleet.replay import run_dry

    settings = FleetSettings(window_days=90.0, history_days=400.0)
    candles, funding, oi = synthetic_market(days=520, end=pd.Timestamp("2026-10-19 00:00", tz="UTC"))
    end = min(df.index[-1] for df in candles.values()) + pd.Timedelta(hours=1)
    start = end - pd.Timedelta(days=1.5)
    hole = start.floor("4h") - pd.Timedelta(hours=1)  # the last candle of the 4H bar that closed last before the start never arrives
    candles = dict(candles, **{"BTC-USDT": candles["BTC-USDT"].drop(index=[hole])})
    result = run_dry(tmp_path / "dry", days=1.5, manifest=_subset(LIGHT), settings=settings, market_data=(candles, funding, oi))
    assert result.ok, result.checks
    assert pd.Timestamp(result.start) > start and result.source == "given market data"


# -- plan row R7: the FOMC calendar is data, so a running fleet takes new dates at its next restart ---------------------

FOMC_ACCOUNTS = ("c01-s1s5-btc-6h-none", "ctl-hold-btc-4h")  # a 6H and a 4H sleeve, both behind the S0 filter
FOMC_T0 = pd.Timestamp("2027-01-25 10:20", tz="UTC")
FOMC_RESTART = pd.Timestamp("2027-01-26 21:10", tz="UTC")  # the code is updated before the first 2027 meeting
FOMC_END = pd.Timestamp("2027-01-28 12:10", tz="UTC")
FOMC_WINDOW = (pd.Timestamp("2027-01-27 12:00", tz="UTC"), pd.Timestamp("2027-01-28 00:00", tz="UTC"))  # statement 2027-01-27


@pytest.fixture(scope="module")
def data_2027():
    return synthetic_market(days=1000, end=pd.Timestamp("2027-01-29 00:00", tz="UTC"))


def _pre_r7_calendar(monkeypatch) -> None:
    """The S0 filter as it was before plan row R7: the built-in FOMC calendar ended on 2026-12-09."""
    old = tuple(d for d in events_mod.FOMC_DECISION_DAYS if d < "2027")
    assert len(old) == 57 and old[-1] == "2026-12-09"
    real = events_mod.fomc_windows
    monkeypatch.setattr(events_mod, "FOMC_DECISION_DAYS", old)  # the module's list too, for anything that reads it while running
    monkeypatch.setattr(events_mod, "fomc_windows", lambda **kw: real(**dict(kw, days=old)))  # its default was bound at import


def _s0(root: Path, manifest):
    """Per account: bar open time -> whether the S0 filter allowed entries in the decision made at that bar's close."""
    return {aid: {r["bar"]: r["decision"]["diagnostics"]["s0_tradeable"] for r in recs if r["type"] == "bar" and "decision" in r}
            for aid, recs in journals(root, manifest).items()}


def test_a_fleet_started_on_the_old_fomc_calendar_resumes_and_blocks_the_2027_meetings_after_a_restart(tmp_path, data_2027, monkeypatch):
    accounts = _subset(FOMC_ACCOUNTS)
    straight, never, updated = tmp_path / "straight", tmp_path / "never_updated", tmp_path / "updated"
    fleet, feed = make(straight, data_2027, accounts, FOMC_T0)  # always the new calendar
    advance(fleet, feed, FOMC_T0 + pd.Timedelta(minutes=40), FOMC_END)
    fleet.release()
    with monkeypatch.context() as m:
        _pre_r7_calendar(m)
        fleet, feed = make(never, data_2027, accounts, FOMC_T0)  # never updated: the old calendar throughout
        advance(fleet, feed, FOMC_T0 + pd.Timedelta(minutes=40), FOMC_END)
        fleet.release()
        fleet, feed = make(updated, data_2027, accounts, FOMC_T0)  # started on the old calendar, running until the update ...
        advance(fleet, feed, FOMC_T0 + pd.Timedelta(minutes=40), FOMC_RESTART)
        fleet.release()
    fleet, feed = make(updated, data_2027, accounts, FOMC_RESTART)  # ... then restarted on the new one, in the same folder
    advance(fleet, feed, FOMC_RESTART, FOMC_END)
    fleet.release()
    assert journals(updated, accounts) == journals(straight, accounts)  # as if it had always had the new calendar
    log = [json.loads(line) for line in (updated / "fleet.jsonl").read_text(encoding="utf-8").splitlines()]
    # Resumed, not refused. That no fingerprint covers the dates is pinned by the R5a fingerprints in test_paper_fleet_config.py.
    assert [r["type"] for r in log if r["type"] in ("created", "resume")] == ["created", "resume"]
    new, old = _s0(straight, accounts), _s0(never, accounts)
    for aid in FOMC_ACCOUNTS:
        inside = sorted(t for t in new[aid] if FOMC_WINDOW[0] <= pd.Timestamp(t) <= FOMC_WINDOW[1])
        assert len(inside) == (4 if aid.startswith("ctl-hold") else 3), (aid, inside)  # 4H: 12, 16, 20, 00 h; 6H: 12, 18, 00 h
        assert not any(new[aid][t] for t in inside), aid  # the new calendar blocks new entries around the statement
        assert any(old[aid][t] for t in inside), aid  # the old one did not
