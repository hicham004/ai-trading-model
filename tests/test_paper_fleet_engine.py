"""The bar-by-bar paper engine reproduces research.engine.run_vectorized exactly (one column)."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from research.engine import Costs, run_vectorized
from research.paper_fleet.engine import Decision, EngineConfig, SleeveEngine, SleeveState
from research.sizing import LadderConfig

COSTS = Costs(fee_rate=0.001, slippage_rate=0.0005)


def _series(n: int, seed: int, vol: float = 0.02):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, vol, n)))
    open_ = np.concatenate([[close[0]], close[:-1] * np.exp(rng.normal(0, 0.004, n - 1))])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.01, n)))
    return open_, high, low, close


def _signals(n: int, seed: int, close: np.ndarray):
    rng = np.random.default_rng(seed + 100)
    # Runs of desired bars (regime-like), stops 2-6 % below, optional targets, fractions with NaN warm-up.
    state = np.zeros(n, dtype=bool)
    on = False
    for i in range(n):
        if rng.random() < (0.08 if not on else 0.05):
            on = not on
        state[i] = on
    stop = close * rng.uniform(0.02, 0.06, n)
    stop[rng.random(n) < 0.05] = np.nan
    target = stop * rng.choice([2.0, 3.0], n)
    frac = np.clip(rng.uniform(0.05, 1.2, n), 0, 1.0)
    frac[:15] = np.nan
    frac[rng.random(n) < 0.03] = 0.0
    return state, stop, target, frac


def _run_both(n, seed, *, sized, ladder=None, rebalance=None, time_stop=None, trail=None, with_target=False, with_stop=True):
    o, h, l, c = _series(n, seed)
    desired, stop, target, frac = _signals(n, seed, c)
    if not with_stop:
        stop = np.full(n, np.nan)
    act, dist = (trail if trail is not None else (None, None))
    res = run_vectorized(
        o, h, l, c, desired[:, None], stop[:, None], costs=COSTS, time_stop_bars=time_stop,
        target_distance=target[:, None] if with_target else None,
        size_fraction=frac[:, None] if sized else 1.0, trail_activate_r=act, trail_r=dist,
        ladder=ladder, ladder_mask=np.array([True]) if ladder is not None else None, rebalance_threshold=rebalance,
    )
    cfg = EngineConfig(costs=COSTS, sized=sized, ladder=ladder, rebalance_threshold=rebalance, time_stop_bars=time_stop,
                       trail_activate_r=act, trail_r=dist)
    eng = SleeveEngine(cfg)
    times = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    equity, exits, entries, allocation = [], [], [], []
    for i in range(n):
        dec = Decision(bar_time=times[i], close=float(c[i]), desired=bool(desired[i]), stop_distance=float(stop[i]),
                       target_distance=float(target[i]) if with_target else float("nan"),
                       fraction=float(frac[i]) if sized else 1.0)
        out = eng.step(times[i], float(o[i]), float(h[i]), float(l[i]), float(c[i]), dec)
        # A restart between any two bars must not change anything (JSON round trip of the state).
        eng = SleeveEngine(cfg, SleeveState.from_dict(json.loads(json.dumps(eng.state.to_dict()))))
        equity.append(out.equity)
        allocation.append(out.allocation)
        for ev in out.events:
            if ev["kind"] == "exit":
                exits.append(ev)
            elif ev["kind"] == "entry":
                entries.append(ev)
    return res, np.array(equity), exits, entries, np.array(allocation), times


@pytest.mark.parametrize(
    "kw",
    [
        dict(sized=False),
        dict(sized=False, with_target=True),
        dict(sized=False, time_stop=12),
        dict(sized=False, trail=(1.0, 1.0)),
        dict(sized=False, trail=(1.0, 2.0), with_target=True),
        dict(sized=True),
        dict(sized=True, rebalance=0.25),
        dict(sized=True, ladder=LadderConfig(recovery_bars=30)),
        dict(sized=True, ladder=LadderConfig(recovery_bars=30), rebalance=0.25),
        dict(sized=True, ladder=LadderConfig(half_dd=0.03, flat_dd=0.06, recovery_bars=10), rebalance=0.25, with_target=True),
        dict(sized=True, ladder=LadderConfig(recovery_bars=30), rebalance=0.25, with_stop=False),
        dict(sized=False, with_stop=False),
    ],
)
@pytest.mark.parametrize("seed", [1, 7])
def test_bar_by_bar_engine_matches_the_vectorized_engine(kw, seed):
    n = 700
    res, equity, exits, entries, allocation, times = _run_both(n, seed, **kw)
    # Every bar but the last (the vectorized engine liquidates at the end of data).
    np.testing.assert_allclose(equity[:-1], res.equity[:-1, 0], rtol=0, atol=1e-7)
    np.testing.assert_allclose(allocation[:-1], res.allocation[:-1, 0], rtol=0, atol=1e-12)
    closed = res.trades[res.trades["exit_reason"] != "end_of_data"].reset_index(drop=True)
    assert len(exits) == len(closed)
    for ev, row in zip(exits, closed.itertuples()):
        assert ev["reason"] == row.exit_reason
        assert ev["bar_time"] == times[row.exit_i]
        assert ev["entry_time"] == times[row.entry_i]
        assert ev["bars_held"] == row.bars_held
        assert ev["reductions"] == row.reductions
        for key in ("pnl", "fill_price", "entry_price", "return_pct", "mfe_pct", "mae_pct", "size_fraction", "fees_total"):
            ref = {"fill_price": row.exit_price, "fees_total": row.fees}.get(key, getattr(row, key, None))
            assert ev[key] == pytest.approx(ref, abs=1e-9), key
    # An open position at the end is the vectorized engine's end_of_data trade.
    eod = res.trades[res.trades["exit_reason"] == "end_of_data"]
    assert len(entries) == len(closed) + len(eod)
    if len(eod):
        assert entries[-1]["bar_time"] == times[int(eod.iloc[0]["entry_i"])]
        assert entries[-1]["fill_price"] == pytest.approx(float(eod.iloc[0]["entry_price"]), abs=1e-9)


def test_anchor_bar_executes_nothing_and_a_missing_decision_keeps_stops_but_blocks_entries():
    cfg = EngineConfig(costs=Costs(0.0, 0.0), sized=False)
    eng = SleeveEngine(cfg)
    out0 = eng.step("t0", 100, 101, 99, 100, Decision("t0", 100, True, stop_distance=5.0))
    assert out0.bar_index == 0 and not out0.events and out0.equity == 10_000
    out1 = eng.step("t1", 100, 102, 98, 101, None)  # entered at t1's open; no decision at t1's close
    assert [e["kind"] for e in out1.events] == ["entry"] and out1.in_position
    assert out1.stop_px == pytest.approx(95.0)
    out2 = eng.step("t2", 101, 101, 94, 96, Decision("t2", 96, False))
    kinds = [e["kind"] for e in out2.events]
    assert kinds == ["exit", "no_decision"] and out2.events[0]["reason"] == "stop_loss"
    assert out2.events[0]["fill_price"] == pytest.approx(95.0)
    # Flat, and the pending decision says flat: nothing happens; a missing decision never enters.
    out3 = eng.step("t3", 96, 97, 95, 96, None)
    assert not out3.in_position and [e["kind"] for e in out3.events] == []
    out4 = eng.step("t4", 96, 97, 95, 96, None)
    assert [e["kind"] for e in out4.events] == ["no_decision"] and not out4.in_position


def test_entry_skips_are_reported_and_change_nothing():
    cfg = EngineConfig(costs=Costs(0.0, 0.0), sized=True)
    eng = SleeveEngine(cfg)
    eng.step("t0", 100, 101, 99, 100, Decision("t0", 100, True, stop_distance=5.0, fraction=float("nan")))
    out = eng.step("t1", 100, 101, 99, 100, Decision("t1", 100, True, stop_distance=0.5, fraction=0.5))
    assert out.events == [{"kind": "entry_skipped", "bar_time": "t1", "reason": "no_size", "fraction": None, "ladder_multiplier": 1.0}]
    out = eng.step("t2", 99.0, 101, 98, 100, Decision("t2", 100, True, stop_distance=5.0, fraction=0.5))
    assert out.events[0]["reason"] == "stop_not_below_open" and not out.in_position
    out = eng.step("t3", 100, 101, 99, 100, None)
    assert out.events[0]["kind"] == "entry" and out.events[0]["fraction"] == 0.5
    assert out.equity == pytest.approx(10_000) and out.allocation == 0.5


def test_state_round_trips_through_json_including_nan_and_pending():
    cfg = EngineConfig(costs=COSTS, sized=True, ladder=LadderConfig(recovery_bars=5), rebalance_threshold=0.25)
    eng = SleeveEngine(cfg)
    eng.step("t0", 100, 101, 99, 100, Decision("t0", 100, True, stop_distance=4.0, target_distance=float("nan"), fraction=0.4))
    eng.step("t1", 100, 103, 99, 102, Decision("t1", 102, True, stop_distance=4.0, fraction=0.3))
    text = json.dumps(eng.state.to_dict(), allow_nan=False)
    back = SleeveState.from_dict(json.loads(text))
    assert back.to_dict() == eng.state.to_dict()
    assert math.isnan(back.target_px) and back.pending.fraction == 0.3 and back.in_pos


def test_engine_config_validation():
    with pytest.raises(ValueError):
        EngineConfig(trail_activate_r=1.0)
    with pytest.raises(ValueError):
        EngineConfig(rebalance_threshold=1.5)
    with pytest.raises(ValueError):
        EngineConfig(time_stop_bars=0)
    with pytest.raises(ValueError):
        SleeveEngine(EngineConfig()).step("t", float("nan"), 1, 1, 1)


@pytest.mark.parametrize("kw", [
    dict(sized=True, ladder=LadderConfig(recovery_bars=30), rebalance=0.25),
    dict(sized=False, with_target=True),
    dict(sized=False, time_stop=40),
    dict(sized=True, ladder=LadderConfig(recovery_bars=30), rebalance=0.25, with_stop=False),
])
def test_window_restarts_reproduce_the_walk_forward_test_windows(kw):
    """Restarting every W bars equals the research run separately on each window (each from flat, ended at its last close)."""
    n, W = 700, 150
    o, h, l, c = _series(n, 3)
    desired, stop, target, frac = _signals(n, 3, c)
    if not kw.get("with_stop", True):
        stop = np.full(n, np.nan)
    sized, ladder, rebalance = kw.get("sized"), kw.get("ladder"), kw.get("rebalance")
    cfg = EngineConfig(costs=COSTS, sized=sized, ladder=ladder, rebalance_threshold=rebalance, time_stop_bars=kw.get("time_stop"),
                       window_bars=W)
    eng = SleeveEngine(cfg)
    times = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    equity, exits = [], []
    for i in range(n):
        dec = Decision(times[i], float(c[i]), bool(desired[i]), float(stop[i]),
                       float(target[i]) if kw.get("with_target") else float("nan"), float(frac[i]) if sized else 1.0)
        out = eng.step(times[i], float(o[i]), float(h[i]), float(l[i]), float(c[i]), dec)
        equity.append(out.equity)
        exits += [e for e in out.events if e["kind"] == "exit"]
    equity = np.array(equity)
    ref_exits = []
    for k, a in enumerate(range(0, n, W)):
        b = min(a + W, n)
        res = run_vectorized(o[a:b], h[a:b], l[a:b], c[a:b], desired[a:b, None], stop[a:b, None], costs=COSTS,
                             time_stop_bars=kw.get("time_stop"), target_distance=target[a:b, None] if kw.get("with_target") else None,
                             size_fraction=frac[a:b, None] if sized else 1.0, ladder=ladder,
                             ladder_mask=np.array([True]) if ladder is not None else None, rebalance_threshold=rebalance)
        start = equity[a]  # the capital the window starts with (flat on its first bar)
        # Inside the window: the same path, scaled by the capital the window started with.
        np.testing.assert_allclose(equity[a:b - 1] / start, res.equity[: b - a - 1, 0] / 10_000.0, rtol=1e-10)
        if b < n:  # the window's end (with the exit's costs) is the next window's flat start
            assert equity[b] / start == pytest.approx(res.equity[-1, 0] / 10_000.0, rel=1e-10)
            ref_exits += [("window_end" if r.exit_reason == "end_of_data" else r.exit_reason, r.pnl * start / 10_000.0)
                          for r in res.trades.itertuples()]
        else:
            ref_exits += [(r.exit_reason, r.pnl * start / 10_000.0) for r in res.trades.itertuples() if r.exit_reason != "end_of_data"]
    assert [e["reason"] for e in exits] == [r for r, _ in ref_exits]
    np.testing.assert_allclose([e["pnl"] for e in exits], [p for _, p in ref_exits], rtol=1e-9, atol=1e-7)
    assert any(r == "window_end" for r, _ in ref_exits)


def test_a_window_restart_drops_the_old_decision_and_trades_one_bar_later():
    cfg = EngineConfig(costs=Costs(0.0, 0.0), sized=False, window_bars=3)
    eng = SleeveEngine(cfg)
    always = lambda t, px: Decision(t, px, True)  # noqa: E731
    kinds = []
    for k, px in enumerate([100, 101, 102, 103, 104, 105, 106]):
        out = eng.step(f"t{k}", px, px + 1, px - 1, px, always(f"t{k}", px))
        kinds.append([e["kind"] for e in out.events])
    # t0 anchor, t1 entry, t2 hold, t3 new window: exit at t2's close and stay flat, t4 entry again ...
    assert kinds == [[], ["entry"], [], ["exit", "window_restart"], ["entry"], [], ["exit", "window_restart"]]
    assert eng.state.window == 2 and not eng.state.in_pos


# -- plan row R18b: the entry brakes and the Trader-tier fraction, bar by bar against the research engine --------------------

import dataclasses  # noqa: E402

from research.brakes import BRAKE_NAMES, TRADER_BRAKES, BarCalendar  # noqa: E402
from research.paper_fleet.engine import BrakeState, bar_calendar  # noqa: E402
from research.sizing import SIZING_TIERS, fraction_series  # noqa: E402

R18_CASES = [
    dict(sized=False, brakes=TRADER_BRAKES, vol=0.04),  # a wild full-size path: the ladder, the hard stop, the caps and the loss limits all act
    dict(sized=True, tier="trader", brakes=TRADER_BRAKES, rebalance=0.25),
    dict(sized=True, tier="trader", brakes=TRADER_BRAKES, rebalance=0.25, vol=0.05, time_stop=12),
    dict(sized=True, tier="aggressive", brakes=dataclasses.replace(TRADER_BRAKES, heat_cap=0.01), rebalance=0.25, vol=0.03),  # the heat cap acts
    dict(sized=True, tier="trader", brakes=TRADER_BRAKES, rebalance=0.25, vol=0.03, freq="6h", bars_per_day=4),
    dict(sized=True, tier="trader", brakes=None, rebalance=0.25),  # the capped fraction alone, no brake: the engine as it was
]


def _run_both_r18(n, seed, *, sized, brakes, tier=None, rebalance=None, time_stop=None, vol=0.02, freq="4h", bars_per_day=6):
    """The research engine with the tier's capped fraction and the brakes, and the bar-by-bar engine on the same decisions."""
    o, h, l, c = _series(n, seed, vol)
    desired, stop, target, frac = _signals(n, seed, c)
    times = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    if tier is not None:  # the tier's fraction, read from the candidate's stop (the per-trade cap), as research.sizing computes it
        df = pd.DataFrame({"close": c}, index=times)
        frac = fraction_series(df, SIZING_TIERS[tier], freq.upper(), 365.25 * 24 / int(freq[:-1]), stop_distance=stop).to_numpy()
    res = run_vectorized(o, h, l, c, desired[:, None], stop[:, None], costs=COSTS, time_stop_bars=time_stop,
                         size_fraction=frac[:, None] if sized else 1.0, rebalance_threshold=rebalance, brakes=brakes, bar_times=times.values)
    cfg = EngineConfig(costs=COSTS, sized=sized, rebalance_threshold=rebalance, time_stop_bars=time_stop, brakes=brakes,
                       bars_per_day=bars_per_day if brakes is not None else None)
    eng = SleeveEngine(cfg)
    tstr = times.strftime("%Y-%m-%dT%H:%M:%SZ")
    equity, allocation, exits, entries, brake_events = [], [], [], [], []
    for i in range(n):
        dec = Decision(bar_time=tstr[i], close=float(c[i]), desired=bool(desired[i]), stop_distance=float(stop[i]), fraction=float(frac[i]) if sized else 1.0)
        out = eng.step(tstr[i], float(o[i]), float(h[i]), float(l[i]), float(c[i]), dec)
        eng = SleeveEngine(cfg, SleeveState.from_dict(json.loads(json.dumps(eng.state.to_dict(), allow_nan=False))))  # a restart every bar
        equity.append(out.equity)
        allocation.append(out.allocation)
        for ev in out.events:
            if ev["kind"] == "exit":
                exits.append(ev)
            elif ev["kind"] == "entry":
                entries.append(ev)
            elif ev["kind"] in ("brake", "brake_trip", "turtle_ladder"):
                brake_events.append(ev)
        assert (out.brakes is not None) == (brakes is not None)
    return res, np.array(equity), np.array(allocation), exits, entries, brake_events, eng, tstr


@pytest.mark.parametrize("kw", R18_CASES, ids=[f"{'full' if not k['sized'] else k.get('tier')}-{'brakes' if k['brakes'] else 'nobrakes'}-{k.get('freq', '4h')}-{k.get('vol', 0.02)}"
                                               for k in R18_CASES])
@pytest.mark.parametrize("seed", [1, 7, 11])
def test_brakes_and_the_trader_tier_match_the_vectorized_engine_bar_by_bar(kw, seed):
    n = 700
    res, equity, allocation, exits, entries, brake_events, eng, times = _run_both_r18(n, seed, **kw)
    np.testing.assert_allclose(equity[:-1], res.equity[:-1, 0], rtol=0, atol=1e-7)
    np.testing.assert_allclose(allocation[:-1], res.allocation[:-1, 0], rtol=0, atol=1e-12)
    closed = res.trades[res.trades["exit_reason"] != "end_of_data"].reset_index(drop=True)
    assert len(exits) == len(closed) and [e["reason"] for e in exits] == list(closed["exit_reason"])
    for ev, row in zip(exits, closed.itertuples()):
        assert ev["bar_time"] == times[row.exit_i] and ev["pnl"] == pytest.approx(row.pnl, abs=1e-9) and ev["size_fraction"] == pytest.approx(row.size_fraction, abs=1e-12)
    # The money and the share of equity at risk at the initial stop: the research's trade columns, entry by entry.
    assert len(entries) == len(res.trades)
    for ev, row in zip(entries, res.trades.itertuples()):
        assert ev["bar_time"] == times[row.entry_i]
        for key in ("risk", "risk_pct"):
            ref = getattr(row, key)
            assert (ev[key] is None and math.isnan(ref)) or ev[key] == pytest.approx(ref, abs=1e-9), key
    if kw["brakes"] is not None:
        # Every brake's trigger count and every limit's trip count are the research's (no window restart here: one window).
        assert eng.state.brakes.counts == {k: int(v[0]) for k, v in res.brakes["counts"].items()}
        assert eng.state.brakes.trips == {k: int(v[0]) for k, v in res.brakes["trips"].items()}
        assert eng.state.brakes.opportunities == int(res.brakes["opportunities"][0]) and eng.state.brakes.bars_blocked == int(res.brakes["bars_blocked"][0])
        acted = sum(eng.state.brakes.counts.values())
        assert (acted > 0) == any(e["kind"] == "brake" for e in brake_events)
        assert all("brake_multiplier" in e for e in entries)
    else:
        assert eng.state.brakes is None and not brake_events and all("brake_multiplier" not in e for e in entries)


def test_every_brake_acts_somewhere_in_the_parity_cases():
    """The parity above means something only if each brake acted at least once across the cases (the counts are the research's)."""
    union = {name: 0 for name in BRAKE_NAMES}
    trips = {"hard_stop": 0, "daily_loss": 0, "weekly_loss": 0, "monthly_loss": 0}
    for seed in (1, 7, 11):
        for kw in R18_CASES:
            if kw["brakes"] is None:
                continue
            *_, eng, _ = _run_both_r18(700, seed, **kw)
            for k, v in eng.state.brakes.counts.items():
                union[k] += v
            for k, v in eng.state.brakes.trips.items():
                trips[k] += v
    assert all(v > 0 for v in union.values()), union
    assert all(v > 0 for v in trips.values()), trips


def test_brakes_restart_with_every_window_like_the_research_test_windows():
    """With window restarts the brakes start fresh every W bars: equal to the research run separately on each window (each with
    its own EntryBrakes), the same way the ladder and the capital restart."""
    n, W = 700, 150
    o, h, l, c = _series(n, 3, 0.04)
    desired, stop, target, frac = _signals(n, 3, c)
    times = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    tstr = times.strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg = EngineConfig(costs=COSTS, sized=False, window_bars=W, brakes=TRADER_BRAKES, bars_per_day=6)
    eng = SleeveEngine(cfg)
    equity, exits, counts_per_window = [], [], []
    for i in range(n):
        if i % W == 0 and i > 0:
            counts_per_window.append(dict(eng.state.brakes.counts))
        out = eng.step(tstr[i], float(o[i]), float(h[i]), float(l[i]), float(c[i]), Decision(tstr[i], float(c[i]), bool(desired[i]), float(stop[i])))
        equity.append(out.equity)
        exits += [e for e in out.events if e["kind"] == "exit"]
    counts_per_window.append(dict(eng.state.brakes.counts))
    equity = np.array(equity)
    ref_exits = []
    for k, a in enumerate(range(0, n, W)):
        b = min(a + W, n)
        res = run_vectorized(o[a:b], h[a:b], l[a:b], c[a:b], desired[a:b, None], stop[a:b, None], costs=COSTS, brakes=TRADER_BRAKES, bar_times=times[a:b].values)
        start = equity[a]
        np.testing.assert_allclose(equity[a:b - 1] / start, res.equity[: b - a - 1, 0] / 10_000.0, rtol=1e-10)
        assert counts_per_window[k] == {name: int(v[0]) for name, v in res.brakes["counts"].items()}  # each window counted afresh
        if b < n:
            assert equity[b] / start == pytest.approx(res.equity[-1, 0] / 10_000.0, rel=1e-10)
            ref_exits += [("window_end" if r.exit_reason == "end_of_data" else r.exit_reason) for r in res.trades.itertuples()]
        else:
            ref_exits += [r.exit_reason for r in res.trades.itertuples() if r.exit_reason != "end_of_data"]
    assert [e["reason"] for e in exits] == ref_exits
    assert sum(sum(cw.values()) for cw in counts_per_window) > 0 and any(e["reason"] == "window_end" for e in exits)


def test_brake_state_round_trips_is_absent_without_brakes_and_the_calendar_is_the_research_calendar():
    with pytest.raises(ValueError, match="bars_per_day"):
        EngineConfig(brakes=TRADER_BRAKES)
    cfg = EngineConfig(costs=COSTS, sized=True, brakes=TRADER_BRAKES, bars_per_day=6)
    fresh = SleeveState.fresh(cfg)
    assert isinstance(fresh.brakes, BrakeState) and fresh.brakes.peak == 10_000 and fresh.brakes.lad_mult == 1.0 and not fresh.brakes.halted
    assert "brakes" in fresh.to_dict() and "brakes" not in SleeveState.fresh(EngineConfig(costs=COSTS, sized=True)).to_dict()
    back = SleeveState.from_dict(json.loads(json.dumps(fresh.to_dict(), allow_nan=False)))
    assert back.to_dict() == fresh.to_dict() and back.brakes.counts == {name: 0 for name in BRAKE_NAMES}
    # A state written before the brakes existed (no key) is given fresh brakes by an engine whose rules carry them, and vice versa.
    old = SleeveState.from_dict({k: v for k, v in fresh.to_dict().items() if k != "brakes"})
    assert old.brakes is None and SleeveEngine(cfg, old).state.brakes is not None
    assert SleeveEngine(EngineConfig(costs=COSTS, sized=True), fresh).state.brakes is None
    assert BrakeState.fresh(5.0).summary()["turtle_multiplier"] == 1.0
    # The calendar: days, Monday weeks and months as research.brakes.BarCalendar numbers them, whatever the timestamp unit.
    for freq in ("4h", "6h", "1h"):
        idx = pd.date_range("2025-12-29 00:00", periods=400, freq=freq, tz="UTC")  # 2025-12-29 is a Monday; crosses a year end
        cal = BarCalendar.from_times(idx.values)
        mine = [bar_calendar(t.strftime("%Y-%m-%dT%H:%M:%SZ")) for t in idx]
        assert [m[0] for m in mine] == list(cal.day) and [m[1] for m in mine] == list(cal.week) and [m[2] for m in mine] == list(cal.month)
    ms = pd.DatetimeIndex(pd.date_range("2024-01-01", periods=10, freq="4h", tz="UTC").values.astype("datetime64[ms]"), tz="UTC")
    assert [bar_calendar(str(t)) for t in ms] == list(zip(BarCalendar.from_times(ms.values).day, BarCalendar.from_times(ms.values).week, BarCalendar.from_times(ms.values).month))
    with pytest.raises(ValueError):
        bar_calendar("not a time")


def test_entry_events_carry_the_risk_at_the_initial_stop_and_a_blocked_entry_is_reported():
    """Zero costs, all in, a stop 5 % below the entry: a stop-out costs exactly the recorded risk; the bar after the exit is blocked by the
    no-entry-after-an-exit brake (a `brake` event, then `entry_skipped` with reason `brake`); the next bar enters at full size."""
    only_after_exit = dataclasses.replace(TRADER_BRAKES, ladder=None, hard_stop_dd=None, max_entries_per_market_per_day=None, max_entries_per_day=None,
                                          daily_loss_limit=None, weekly_loss_limit=None, monthly_loss_limit=None, heat_cap=None)
    cfg = EngineConfig(costs=Costs(0.0, 0.0), sized=False, brakes=only_after_exit, bars_per_day=6)
    eng = SleeveEngine(cfg)
    times = pd.date_range("2024-01-01", periods=6, freq="4h", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    want = lambda t, px: Decision(t, px, True, stop_distance=5.0)  # noqa: E731  (the stop sits 5 below the decision close)
    out0 = eng.step(times[0], 100, 101, 99, 100, want(times[0], 100.0))
    out1 = eng.step(times[1], 100, 101, 99, 100, want(times[1], 100.0))  # enters at 100: 100 units, stop 95, risk 500 = 5 % of 10,000
    entry = out1.events[0]
    assert entry["kind"] == "entry" and entry["risk"] == pytest.approx(500.0) and entry["risk_pct"] == pytest.approx(0.05) and entry["brake_multiplier"] == 1.0
    out2 = eng.step(times[2], 100, 100, 94, 96, want(times[2], 96.0))  # stopped at 95: the loss is the recorded risk
    assert out2.events[0]["kind"] == "exit" and out2.events[0]["pnl"] == pytest.approx(-500.0) and out2.equity == pytest.approx(9_500.0)
    out3 = eng.step(times[3], 96, 97, 95.5, 96, want(times[3], 96.0))  # the bar after the exit: blocked
    assert [e["kind"] for e in out3.events] == ["brake", "entry_skipped"]
    assert out3.events[0]["blocked_by"] == ["entry_after_exit"] and out3.events[0]["multiplier"] == 0.0 and out3.events[1]["reason"] == "brake"
    assert out3.events[1]["blocked_by"] == ["entry_after_exit"] and not out3.in_position and out3.brakes["counts"]["entry_after_exit"] == 1
    out4 = eng.step(times[4], 96, 97, 95.5, 96, want(times[4], 96.0))  # enters at 96 with the stop at 91
    assert out4.events[0]["kind"] == "entry" and out4.events[0]["brake_multiplier"] == 1.0 and out4.in_position and out4.stop_px == pytest.approx(91.0)
    assert out0.brakes == {**out0.brakes, "turtle_multiplier": 1.0, "halted": False} and eng.state.brakes.opportunities == 3
