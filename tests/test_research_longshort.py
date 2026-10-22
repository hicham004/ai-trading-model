"""Long/short engine (plan row R9): long-only parity with run_vectorized, mirrored short exits, funding, leverage."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.engine import TRADE_COLUMNS, Costs, run_vectorized
from research.longshort import LS_TRADE_COLUMNS, run_long_short, side_metrics
from research.longshort_data import funding_per_bar
from research.sizing import LadderConfig

ZERO = Costs(fee_rate=0.0, slippage_rate=0.0)
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


PARITY_CASES = [
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
]


@pytest.mark.parametrize("kw", PARITY_CASES)
@pytest.mark.parametrize("seed", [1, 7])
def test_without_shorts_or_funding_it_is_the_long_only_engine_bit_for_bit(kw, seed):
    n = 700
    o, h, l, c = _series(n, seed)
    desired, stop, target, frac = _signals(n, seed, c)
    if not kw.get("with_stop", True):
        stop = np.full(n, np.nan)
    act, dist = kw.get("trail") or (None, None)
    common = dict(costs=COSTS, time_stop_bars=kw.get("time_stop"), target_distance=target[:, None] if kw.get("with_target") else None,
                  size_fraction=frac[:, None] if kw["sized"] else 1.0, trail_activate_r=act, trail_r=dist, ladder=kw.get("ladder"),
                  ladder_mask=np.array([True]) if kw.get("ladder") is not None else None, rebalance_threshold=kw.get("rebalance"))
    ref = run_vectorized(o, h, l, c, desired[:, None], stop[:, None], **common)
    ls_kw = dict(common)
    ls_kw["costs_long"] = ls_kw.pop("costs")
    # No short decisions at all, and an all-False short matrix with (unused) funding on the short leg: both identical.
    for desired_short, f_short in ((None, None), (np.zeros((n, 1), dtype=bool), np.full(n, 0.0003))):
        res = run_long_short(o, h, l, c, desired[:, None], desired_short, stop[:, None], funding_short=f_short, **ls_kw)
        np.testing.assert_array_equal(res.equity, ref.equity)
        np.testing.assert_array_equal(res.position, ref.position)
        np.testing.assert_array_equal(res.allocation, ref.allocation)
        assert list(res.trades.columns) == list(LS_TRADE_COLUMNS)
        pd.testing.assert_frame_equal(res.trades[list(TRADE_COLUMNS)], ref.trades[list(TRADE_COLUMNS)])
        assert (res.trades["side"] == 1).all() and (res.trades["funding"] == 0.0).all()
        assert res.funding_total[0] == 0.0 and res.liquidations[0] == 0
        assert (res.side[:, 0] >= 0).all()


def test_parity_holds_across_many_columns_at_once():
    n = 500
    o, h, l, c = _series(n, 3)
    rng = np.random.default_rng(9)
    desired = rng.random((n, 6)) > 0.45
    stop = np.repeat((c * 0.04)[:, None], 6, axis=1)
    frac = np.clip(rng.uniform(0.1, 1.0, (n, 6)), 0, 1)
    ref = run_vectorized(o, h, l, c, desired, stop, costs=COSTS, size_fraction=frac, ladder=LadderConfig(recovery_bars=20),
                         rebalance_threshold=0.25, trail_activate_r=[1.0, None, 1.0, None, 2.0, None], trail_r=[1.0, None, 2.0, None, 1.0, None])
    res = run_long_short(o, h, l, c, desired, None, stop, costs_long=COSTS, size_fraction=frac, ladder=LadderConfig(recovery_bars=20),
                         rebalance_threshold=0.25, trail_activate_r=[1.0, None, 1.0, None, 2.0, None], trail_r=[1.0, None, 2.0, None, 1.0, None])
    np.testing.assert_array_equal(res.equity, ref.equity)
    pd.testing.assert_frame_equal(res.trades[list(TRADE_COLUMNS)], ref.trades[list(TRADE_COLUMNS)])


# -- the short side mirrors the reviewed long engine ---------------------------------------

def _reflect(o, h, l, c, anchor):
    """Price path reflected around ``anchor``: a short on (o, h, l, c) is a long on the reflection (zero costs)."""
    return 2 * anchor - o, 2 * anchor - l, 2 * anchor - h, 2 * anchor - c


REFLECTION_CASES = [
    dict(),
    dict(with_target=True),
    dict(time_stop=9),
    dict(trail=(1.0, 1.0)),
    dict(trail=(0.5, 2.0), with_target=True),
    dict(sized=True, rebalance=0.25),
    dict(sized=True, ladder=LadderConfig(half_dd=0.01, flat_dd=0.02, recovery_bars=5), rebalance=0.25),
    dict(sized=True, ladder=LadderConfig(half_dd=0.02, flat_dd=0.04, recovery_bars=8)),
]


@pytest.mark.parametrize("kw", REFLECTION_CASES)
@pytest.mark.parametrize("seed", range(12))
def test_a_short_is_the_long_engine_on_the_reflected_path(kw, seed):
    n = 160
    o, h, l, c = _series(n, seed, vol=0.012)
    rng = np.random.default_rng(seed + 50)
    k = int(rng.integers(20, 40))  # entry bar (decision on k-1)
    m = int(rng.integers(k + 5, n - 5))  # last desired bar
    desired = np.zeros(n, dtype=bool)
    desired[k - 1:m + 1] = True
    stop = c * rng.uniform(0.01, 0.04, n)
    stop[k - 1] = max(stop[k - 1], abs(o[k] - c[k - 1]) + 0.01 * c[k - 1])  # the entry is never skipped (one anchor)
    target = stop * 2.0
    frac = np.clip(rng.uniform(0.2, 1.0, n), 0, 1)
    anchor = o[k]
    ro, rh, rl, rc = _reflect(o, h, l, c, anchor)
    assert rl.min() > 0
    act, dist = kw.get("trail") or (None, None)
    common = dict(time_stop_bars=kw.get("time_stop"), target_distance=target[:, None] if kw.get("with_target") else None,
                  size_fraction=frac[:, None] if kw.get("sized") else 1.0, trail_activate_r=act, trail_r=dist, ladder=kw.get("ladder"),
                  rebalance_threshold=kw.get("rebalance"))
    short = run_long_short(o, h, l, c, np.zeros((n, 1), dtype=bool), desired[:, None], stop[:, None], costs_long=ZERO, **common)
    long_ = run_vectorized(ro, rh, rl, rc, desired[:, None], stop[:, None], costs=ZERO, **common)
    st, lt = short.trades.iloc[0], long_.trades.iloc[0]
    assert st["side"] == -1 and st["entry_i"] == lt["entry_i"] == k
    assert st["exit_i"] == lt["exit_i"] and st["exit_reason"] == lt["exit_reason"]
    assert st["reductions"] == lt["reductions"]
    end = int(st["exit_i"])
    np.testing.assert_allclose(short.equity[: end + 1, 0], long_.equity[: end + 1, 0], rtol=0, atol=1e-8)
    assert st["pnl"] == pytest.approx(lt["pnl"], abs=1e-8)
    assert st["return_pct"] == pytest.approx(lt["return_pct"], abs=1e-12)
    assert st["exit_price"] == pytest.approx(2 * anchor - lt["exit_price"], abs=1e-9)
    # A short's favourable excursion is the reflected long's (up to the 1/entry scale, identical here because entry == anchor).
    assert st["mfe_pct"] == pytest.approx(lt["mfe_pct"], abs=1e-12)
    assert st["mae_pct"] == pytest.approx(lt["mae_pct"], abs=1e-12)
    np.testing.assert_array_equal(short.side[: end, 0] == -1, long_.position[: end, 0])


# -- hand-computed short mechanics ------------------------------------------------------------

def _flat(prices, spread=1.0):
    o = np.asarray(prices, dtype=float)
    return o, o + spread, o - spread, o.copy()


def test_short_fee_slippage_and_pnl_math():
    o, h, l, c = _flat([100, 100, 90, 80, 80])
    ds = np.array([True, True, False, False, False])
    costs = Costs(fee_rate=0.0005, slippage_rate=0.0005)
    res = run_long_short(o, h, l, c, np.zeros(5, dtype=bool), ds, np.full(5, 5.0), costs_long=COSTS, costs_short=costs)
    fill = 100 * (1 - 0.0005)
    q = 10_000 / (fill * 1.0005)
    cash = 10_000 + fill * q - fill * q * 0.0005
    exit_fill = 80 * (1 + 0.0005)
    final = cash - exit_fill * q * (1 + 0.0005)
    t = res.trades
    assert len(t) == 1 and t.loc[0, "side"] == -1 and t.loc[0, "exit_reason"] == "signal"
    assert t.loc[0, "entry_i"] == 1 and t.loc[0, "exit_i"] == 3
    assert res.equity[1, 0] == pytest.approx(cash - q * c[1])
    assert res.equity[-1, 0] == pytest.approx(final)
    assert t.loc[0, "pnl"] == pytest.approx(final - 10_000)
    assert t.loc[0, "return_pct"] == pytest.approx((final - 10_000) / (fill * q + fill * q * 0.0005))
    assert list(res.side[:, 0]) == [0, -1, -1, 0, 0]


def test_short_stop_fills_at_stop_or_at_the_gapped_open_above_it():
    # Decision close 100, stop distance 5 -> stop 105. Bar 2 trades up through it; bar 2' gaps above it.
    o = np.array([100.0, 100.0, 101.0, 101.0])
    c = np.array([100.0, 101.0, 104.0, 104.0])
    h = np.array([101.0, 102.0, 106.0, 105.0])
    l = np.array([99.0, 99.0, 100.0, 100.0])
    ds = np.array([True, True, True, True])
    res = run_long_short(o, h, l, c, np.zeros(4, dtype=bool), ds, np.full(4, 5.0), costs_long=ZERO)
    assert res.trades.loc[0, "exit_reason"] == "stop_loss" and res.trades.loc[0, "exit_price"] == pytest.approx(105.0)
    o2 = o.copy()
    o2[2] = 108.0
    h2 = h.copy()
    h2[2] = 109.0
    res2 = run_long_short(o2, h2, l, c, np.zeros(4, dtype=bool), ds, np.full(4, 5.0), costs_long=ZERO)
    t = res2.trades.loc[0]
    assert t["exit_reason"] == "stop_loss" and t["exit_price"] == pytest.approx(108.0) and t["exit_i"] == 2


def test_a_short_needs_a_stop_above_its_open():
    o, h, l, c = _flat([100, 100, 100, 100])
    ds = np.ones(4, dtype=bool)
    no_stop = run_long_short(o, h, l, c, np.zeros(4, dtype=bool), ds, np.full(4, np.nan), costs_long=ZERO)
    assert len(no_stop.trades) == 0
    no_matrix = run_long_short(o, h, l, c, np.zeros(4, dtype=bool), ds, None, costs_long=ZERO)
    assert len(no_matrix.trades) == 0
    # Stop not above the open (the open gapped above decision close + distance): skipped, enters later.
    o2 = np.array([100.0, 106.0, 100.0, 100.0])
    res = run_long_short(o2, o2 + 1, o2 - 1, np.array([100.0, 100.0, 100.0, 100.0]), np.zeros(4, dtype=bool), ds, np.full(4, 5.0), costs_long=ZERO)
    assert res.trades.loc[0, "entry_i"] == 2
    # A long with no stop is still allowed (the long-only rule is unchanged).
    longs = run_long_short(o, h, l, c, ds, None, np.full(4, np.nan), costs_long=ZERO)
    assert len(longs.trades) == 1 and longs.trades.loc[0, "side"] == 1


def test_the_long_side_wins_a_tie_and_a_flip_is_an_exit_and_an_entry_at_one_open():
    o, h, l, c = _flat([100, 100, 100, 100, 100, 100])
    dl = np.array([True, True, False, False, False, False])
    ds = np.array([True, True, True, True, False, False])
    res = run_long_short(o, h, l, c, dl, ds, np.full(6, 5.0), costs_long=ZERO)
    t = res.trades
    assert list(t["side"]) == [1, -1]
    assert t.loc[0, "exit_i"] == 3 and t.loc[0, "exit_reason"] == "signal"  # the long follows the long-only rule
    assert t.loc[1, "entry_i"] == 3 and t.loc[1, "exit_i"] == 5
    assert list(res.side[:, 0]) == [0, 1, 1, -1, -1, 0]


def test_short_target_trailing_and_time_stop():
    # Target 2R below the decision close: decision close 100, R 5 -> target 90; bar 3 trades down to 89.
    o = np.array([100.0, 100.0, 98.0, 95.0, 92.0])
    h = o + 1
    l = np.array([99.0, 99.0, 97.0, 89.0, 91.0])
    c = o.copy()
    ds = np.ones(5, dtype=bool)
    res = run_long_short(o, h, l, c, np.zeros(5, dtype=bool), ds, np.full(5, 5.0), costs_long=ZERO, target_distance=np.full(5, 10.0))
    assert res.trades.loc[0, "exit_reason"] == "target" and res.trades.loc[0, "exit_price"] == pytest.approx(90.0)
    # Trailing: after the low is 1R below the entry the stop follows the running low at 1R above it.
    o2 = np.array([100.0, 100.0, 96.0, 93.0, 94.0, 99.0])
    l2 = np.array([99.0, 99.0, 94.0, 92.0, 93.0, 98.0])
    h2 = np.array([101.0, 101.0, 97.0, 94.0, 98.5, 100.0])
    res2 = run_long_short(o2, h2, l2, o2.copy(), np.zeros(6, dtype=bool), np.ones(6, dtype=bool), np.full(6, 5.0), costs_long=ZERO,
                          trail_activate_r=1.0, trail_r=1.0)
    t = res2.trades.loc[0]
    # Entry 100, R = 5; low 94 at bar 2 (6 >= 5): stop -> 99; bar 3 low 92 -> stop 97; bar 4 high 98.5 >= 97 -> out at 97.
    assert t["exit_reason"] == "stop_loss" and t["exit_i"] == 4 and t["exit_price"] == pytest.approx(97.0)
    res3 = run_long_short(*_flat([100] * 8), np.zeros(8, dtype=bool), np.ones(8, dtype=bool), np.full(8, 5.0), costs_long=ZERO, time_stop_bars=3)
    assert res3.trades.loc[0, "exit_reason"] == "time_stop" and res3.trades.loc[0, "bars_held"] == 3


def test_reduce_only_buys_back_part_of_a_short():
    o, h, l, c = _flat([100, 100, 100, 100, 90, 90, 90])
    frac = np.array([0.8, 0.8, 0.2, 0.2, 0.9, 0.9, 0.9])[:, None]
    res = run_long_short(o, h, l, c, np.zeros(7, dtype=bool), np.ones(7, dtype=bool), np.full(7, 20.0), costs_long=ZERO,
                         size_fraction=frac, rebalance_threshold=0.25)
    t = res.trades.loc[0]
    assert t["reductions"] == 1 and t["side"] == -1
    assert list(res.allocation[:, 0]) == [0.0, 0.8, 0.8, 0.2, 0.2, 0.2, 0.2]  # 0.9 later never adds back
    # 80 units shorted at 100; decision bar 2's fraction 0.2 buys 60 back at bar 3's open (100); the last 20 gain 10 each.
    assert t["pnl"] == pytest.approx(20 * 10.0)
    assert res.equity[-1, 0] == pytest.approx(10_000 + 200.0)


def test_funding_is_charged_on_the_position_open_at_the_bar_close():
    o, h, l, c = _flat([100, 100, 100, 100, 100])
    ds = np.array([True, True, True, False, False])
    # Entry at bar 1's open, exit at bar 4's open (decision bar 3 turned off): the short is open at the closes of bars 1-3.
    rates = np.array([0.001, 0.001, 0.002, 0.003, 0.005])
    res = run_long_short(o, h, l, c, np.zeros(5, dtype=bool), ds, np.full(5, 5.0), costs_long=ZERO, funding_short=rates)
    q = 100.0
    t = res.trades.loc[0]
    assert t["entry_i"] == 1 and t["exit_i"] == 4
    # Positive rates: longs pay shorts. Bar 0 (before the entry) and bar 4 (exit at its open) are not charged.
    assert t["funding"] == pytest.approx(q * 100 * (0.001 + 0.002 + 0.003))
    assert res.funding_total[0] == pytest.approx(t["funding"])
    assert t["pnl"] == pytest.approx(t["funding"])
    assert res.equity[2, 0] == pytest.approx(10_000 + q * 100 * 0.003)
    assert res.equity[-1, 0] == pytest.approx(10_000 + t["funding"])
    # A perp long pays the same rates; a spot long (no funding array for its leg) pays nothing.
    res_l = run_long_short(o, h, l, c, ds, None, np.full(5, 5.0), costs_long=ZERO, funding_long=rates)
    assert res_l.trades.loc[0, "funding"] == pytest.approx(-q * 100 * 0.006)
    res_spot = run_long_short(o, h, l, c, ds, None, np.full(5, 5.0), costs_long=ZERO, funding_short=rates)
    assert res_spot.trades.loc[0, "funding"] == 0.0
    # Negative funding: the short pays.
    res_neg = run_long_short(o, h, l, c, np.zeros(5, dtype=bool), ds, np.full(5, 5.0), costs_long=ZERO, funding_short=-rates)
    assert res_neg.trades.loc[0, "funding"] == pytest.approx(-q * 100 * 0.006)


def test_liquidation_tripwire_and_the_leverage_trace():
    # No stop allowed only when explicitly switched off; the price doubles -> isolated 1x margin is gone.
    o = np.array([100.0, 100.0, 150.0, 210.0, 210.0])
    c = np.array([100.0, 140.0, 200.0, 210.0, 210.0])
    h = np.maximum(o, c) + 1
    l = np.minimum(o, c) - 1
    ds = np.ones(5, dtype=bool)
    res = run_long_short(o, h, l, c, np.zeros(5, dtype=bool), ds, np.full(5, np.nan), costs_long=ZERO, require_short_stop=False)
    t = res.trades.loc[0]
    liq = 100 * 2 / 1.004
    assert t["exit_reason"] == "liquidation" and t["exit_i"] == 2 and t["exit_price"] == pytest.approx(liq)
    assert res.liquidations[0] == 1
    assert t["return_pct"] == pytest.approx(-(liq - 100) / 100)
    # Leverage at bar 1's close: 100 units x 140 / (10_000 + 100 x (100 - 140)) = 14_000 / 6_000.
    assert res.max_leverage[0] == pytest.approx(14_000 / 6_000)
    # A long at full size never exceeds 1.
    res_l = run_long_short(o, h, l, c, ds, None, None, costs_long=ZERO)
    assert res_l.max_leverage[0] == pytest.approx(1.0)


def test_end_of_data_buys_the_short_back_at_the_last_close_and_side_metrics_split_the_pnl():
    o, h, l, c = _flat([100, 100, 100, 95, 95, 90])
    dl = np.array([True, True, False, False, False, False])
    ds = np.array([False, False, True, True, True, True])
    res = run_long_short(o, h, l, c, dl, ds, np.full(6, 50.0), costs_long=ZERO)
    t = res.trades
    assert list(t["side"]) == [1, -1] and t.loc[1, "exit_reason"] == "end_of_data" and t.loc[1, "exit_price"] == pytest.approx(90.0)
    split = side_metrics(t, init_cash=10_000)
    assert split["long"]["n_trades"] == 1 and split["short"]["n_trades"] == 1
    assert split["short"]["pnl"] == pytest.approx(t.loc[1, "pnl"]) and split["short"]["pnl"] > 0
    assert res.equity[-1, 0] == pytest.approx(10_000 + t["pnl"].sum())


def test_separate_execution_prices_for_the_short_leg():
    o, h, l, c = _flat([100, 100, 100, 100])
    perp = _flat([101, 101, 99, 99])
    ds = np.array([True, True, False, False])
    res = run_long_short(o, h, l, c, np.zeros(4, dtype=bool), ds, np.full(4, 5.0), costs_long=ZERO, short_ohlc=perp)
    t = res.trades.loc[0]
    assert t["entry_price"] == pytest.approx(101.0) and t["exit_price"] == pytest.approx(99.0)
    assert res.equity[1, 0] == pytest.approx(10_000)  # marked on the perp's own close


def test_input_validation():
    o, h, l, c = _flat([100] * 4)
    with pytest.raises(ValueError):
        run_long_short(o, h, l, c, np.ones(4, dtype=bool), np.ones((4, 2), dtype=bool), None)
    with pytest.raises(ValueError):
        run_long_short(o, h, l, c, np.ones(4, dtype=bool), None, None, size_fraction=np.full(4, 1.5))
    with pytest.raises(ValueError):
        run_long_short(o, h, l, c, np.ones(4, dtype=bool), None, None, funding_short=np.full(3, 0.0))
    with pytest.raises(ValueError):
        run_long_short(o, h, l, c, np.ones(4, dtype=bool), None, None, short_ohlc=(o, h, -l, c))
    with pytest.raises(ValueError):
        run_long_short(o, h, l, c, np.ones(4, dtype=bool), None, None, maintenance_margin_rate=0.6)


# -- funding assignment to bars -----------------------------------------------------------------

def test_funding_per_bar_assigns_each_settlement_to_the_bar_it_settles_in():
    idx4 = pd.date_range("2024-01-01 00:00", periods=6, freq="4h", tz="UTC")  # 00 04 08 12 16 20
    settle = pd.Series([0.1, 0.2, 0.3, 0.4], index=pd.DatetimeIndex(["2024-01-01 00:00", "2024-01-01 08:00", "2024-01-01 16:00",
                                                                     "2024-01-02 00:00"], tz="UTC"))
    out = funding_per_bar(idx4, settle)
    # 00:00 is the first open (no earlier bar) -> dropped; 08:00 ends bar 1 (04-08); 16:00 ends bar 3; 00:00 next day ends bar 5.
    np.testing.assert_allclose(out, [0.0, 0.2, 0.0, 0.3, 0.0, 0.4])
    idx6 = pd.date_range("2024-01-01 00:00", periods=4, freq="6h", tz="UTC")  # 00 06 12 18
    out6 = funding_per_bar(idx6, settle)
    # 08:00 inside bar 1 (06-12), 16:00 inside bar 2 (12-18), next 00:00 ends bar 3.
    np.testing.assert_allclose(out6, [0.0, 0.2, 0.3, 0.4])
    # Settlements after the last bar's end are dropped; an empty series gives zeros.
    late = pd.Series([1.0], index=pd.DatetimeIndex(["2024-01-03 00:00"], tz="UTC"))
    np.testing.assert_allclose(funding_per_bar(idx6, late), np.zeros(4))
    np.testing.assert_allclose(funding_per_bar(idx6, pd.Series(dtype=float)), np.zeros(4))


def test_funding_per_bar_is_safe_across_time_units():
    """The lake stores milliseconds, pandas defaults to nanoseconds: a raw-integer comparison would drop every settlement."""
    idx_ms = pd.date_range("2024-01-01 00:00", periods=6, freq="4h", tz="UTC").as_unit("ms")
    settle_ns = pd.Series([0.2, 0.3], index=pd.DatetimeIndex(["2024-01-01 08:00", "2024-01-01 16:00"], tz="UTC").as_unit("ns"))
    np.testing.assert_allclose(funding_per_bar(idx_ms, settle_ns), [0.0, 0.2, 0.0, 0.3, 0.0, 0.0])
    settle_us = settle_ns.copy()
    settle_us.index = settle_us.index.as_unit("us")
    np.testing.assert_allclose(funding_per_bar(idx_ms.as_unit("ns"), settle_us), [0.0, 0.2, 0.0, 0.3, 0.0, 0.0])


def test_align_perp_matches_bars_across_time_units_and_fills_gaps_from_spot():
    from research.longshort_data import align_perp

    idx = pd.date_range("2024-01-01", periods=5, freq="4h", tz="UTC")
    spot = pd.DataFrame({"open": [1.0] * 5, "high": [2.0] * 5, "low": [0.5] * 5, "close": [1.5] * 5}, index=idx.as_unit("ms"))
    perp = pd.DataFrame({"open": [1.1] * 4, "high": [2.1] * 4, "low": [0.6] * 4, "close": [1.6] * 4}, index=idx[[0, 1, 3, 4]].as_unit("ns"))
    out = align_perp(spot, perp)
    assert out["missing"] == 1 and out["coverage"] == pytest.approx(0.8)
    np.testing.assert_allclose(out["close"], [1.6, 1.6, 1.5, 1.6, 1.6])


def test_a_flip_closes_the_old_side_at_the_open_and_enters_the_new_side_there_even_if_the_old_stop_would_fire():
    """Review finding (R9): a short whose stop sits inside the flip bar must not delay the long that the decision wants."""
    o = np.array([100.0, 100.0, 100.0, 100.0, 103.0, 103.0])
    h = np.array([101.0, 101.0, 101.0, 106.0, 104.0, 104.0])  # bar 3 trades up through the short's stop (105)
    l = o - 1.0
    c = np.array([100.0, 100.0, 100.0, 103.0, 103.0, 103.0])
    dl = np.array([False, False, True, True, True, True])
    ds = np.array([True, True, False, False, False, False])
    res = run_long_short(o, h, l, c, dl, ds, np.full(6, 5.0), costs_long=ZERO)
    t = res.trades
    assert list(t["side"]) == [-1, 1]
    assert t.loc[0, "exit_reason"] == "flip" and t.loc[0, "exit_i"] == 3 and t.loc[0, "exit_price"] == pytest.approx(100.0)
    assert t.loc[1, "entry_i"] == 3 and t.loc[1, "entry_price"] == pytest.approx(100.0)
    # The long leg is the long-only rule: same entry bar and price.
    ref = run_vectorized(o, h, l, c, dl, np.full(6, 5.0), costs=ZERO)
    assert ref.trades.loc[0, "entry_i"] == 3 and ref.trades.loc[0, "entry_price"] == pytest.approx(100.0)
    # A plain exit (nothing wanted on the other side) keeps the stop-first rule of the long-only engine.
    res2 = run_long_short(o, h, l, c, np.zeros(6, dtype=bool), ds, np.full(6, 5.0), costs_long=ZERO)
    assert res2.trades.loc[0, "exit_reason"] == "stop_loss" and res2.trades.loc[0, "exit_price"] == pytest.approx(105.0)


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("kw", [dict(), dict(with_target=True), dict(time_stop=10), dict(trail=(1.0, 1.0)),
                                dict(sized=True, rebalance=0.25)])
def test_without_ladder_the_long_side_trades_exactly_like_the_long_only_engine(seed, kw):
    n = 600
    o, h, l, c = _series(n, seed)
    desired_long, stop, target, frac = _signals(n, seed, c)
    rng = np.random.default_rng(seed + 500)
    short_state = np.zeros(n, dtype=bool)
    on = False
    for i in range(n):
        if rng.random() < (0.10 if not on else 0.07):
            on = not on
        short_state[i] = on
    desired_short = short_state & ~desired_long
    act, dist = kw.get("trail") or (None, None)
    common = dict(time_stop_bars=kw.get("time_stop"), target_distance=target[:, None] if kw.get("with_target") else None,
                  size_fraction=frac[:, None] if kw.get("sized") else 1.0, trail_activate_r=act, trail_r=dist,
                  rebalance_threshold=kw.get("rebalance"))
    ref = run_vectorized(o, h, l, c, desired_long[:, None], stop[:, None], costs=COSTS, **common)
    res = run_long_short(o, h, l, c, desired_long[:, None], desired_short[:, None], stop[:, None], costs_long=COSTS,
                         costs_short=Costs(fee_rate=0.0005, slippage_rate=0.0005), funding_short=np.full(n, 0.0001), **common)
    longs = res.trades[res.trades["side"] == 1].reset_index(drop=True)
    assert (res.trades["side"] == -1).any()
    cols = ["entry_i", "exit_i", "exit_reason", "bars_held", "reductions"]
    pd.testing.assert_frame_equal(longs[cols], ref.trades[cols])
    np.testing.assert_allclose(longs["entry_price"], ref.trades["entry_price"], rtol=0, atol=1e-9)
    np.testing.assert_allclose(longs["exit_price"], ref.trades["exit_price"], rtol=0, atol=1e-9)
    np.testing.assert_allclose(longs["return_pct"], ref.trades["return_pct"], rtol=0, atol=1e-9)


def test_a_long_giving_way_to_a_short_keeps_the_long_only_stop_and_the_short_waits_a_bar():
    o = np.array([100.0, 100.0, 100.0, 100.0, 97.0, 97.0])
    l = np.array([99.0, 99.0, 99.0, 94.0, 96.0, 96.0])  # bar 3 trades down through the long's stop (95)
    h = o + 1.0
    c = np.array([100.0, 100.0, 100.0, 97.0, 97.0, 97.0])
    dl = np.array([True, True, False, False, False, False])
    ds = np.array([False, False, True, True, True, False])
    res = run_long_short(o, h, l, c, dl, ds, np.full(6, 5.0), costs_long=ZERO)
    t = res.trades
    assert list(t["side"]) == [1, -1]
    assert t.loc[0, "exit_reason"] == "stop_loss" and t.loc[0, "exit_i"] == 3 and t.loc[0, "exit_price"] == pytest.approx(95.0)
    assert t.loc[1, "entry_i"] == 4  # the short starts one bar later, never overlapping the stopped long
    ref = run_vectorized(o, h, l, c, dl, np.full(6, 5.0), costs=ZERO)
    assert ref.trades.loc[0, "exit_reason"] == "stop_loss" and ref.trades.loc[0, "exit_price"] == pytest.approx(95.0)
