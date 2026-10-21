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


def _series(n: int, seed: int):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.02, n)))
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
