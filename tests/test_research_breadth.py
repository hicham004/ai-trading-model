"""Plan row R20: the multi-market book (parity with the engine on one sleeve, the book-level brakes, the correlation cap, the cash constraint, the daily
records), the daily weekly-rebalanced basket of the rotation test, the pre-registration, the jobs through the Sprint 2c runner, the stored reproduction
targets, the verdict rules, the report and the command line. Everything runs offline on synthetic candles."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.datalake.layout import LakeLayout
from research import breadth as bd
from research import breadth_study as st
from research.brakes import TRADER_BRAKES, BrakeSpec
from research.data import bars_per_year
from research.engine import Costs, run_vectorized
from research.report_breadth import executive_summary, owner_decisions, render_report
from research.sizing import SIZING_TIERS, rule_fraction_matrix
from research.strategies import get_candidate
from research.strategies.base import FeatureContext
from research.sweep import build_frames
from tests.test_research_round2 import _frame, _write

ROOT = Path(__file__).resolve().parents[1]
PPY = bars_per_year("6H")
ZERO = Costs(fee_rate=0.0, slippage_rate=0.0)


# -- synthetic data -----------------------------------------------------------------------------------------------------

def _market(seed: int, n: int = 6000) -> pd.DataFrame:
    regime = np.sign(np.sin(np.arange(n) / 60.0))
    return _frame(seed, 0.004 * regime, n=n, freq="6h")


def _flat(n: int, price: float = 100.0, start: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="6h", tz="UTC", name="open_time")
    return pd.DataFrame({"open": price, "high": price * 1.001, "low": price * 0.999, "close": price, "volume": 1.0}, index=idx)


def _sleeve(name: str, inst: str, n: int, *, enter_at, fraction: float, stop_pct: float, hold_bars: int = 10, strength: float = 1.0) -> bd.SleeveInput:
    """A sleeve that wants to be long from decision bar ``enter_at`` for ``hold_bars`` bars, with a stop ``stop_pct`` below the price."""
    desired = np.zeros(n, dtype=bool)
    for e in ([enter_at] if isinstance(enter_at, int) else enter_at):
        desired[e:e + hold_bars] = True
    return bd.SleeveInput(name, inst, "S1", desired, np.full(n, 100.0 * stop_pct), np.full(n, fraction), np.full(n, strength))


def _book(markets, sleeves, *, brakes=TRADER_BRAKES, corr_cap=0.5, costs=None):
    clock = next(iter(markets.values())).index
    cfg = bd.BookConfig(brakes=brakes, corr_cap=corr_cap)
    return bd.run_book(clock, markets, sleeves, costs=costs or {m: ZERO for m in markets}, cfg=cfg, market_order=list(markets))


# -- parity with the engine ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bracket", ["none", "tp2", "trail1", "time30"])
@pytest.mark.parametrize("brakes", [None, TRADER_BRAKES])
def test_book_on_one_sleeve_is_the_engine_bit_for_bit(bracket, brakes):
    df = _market(1)
    ctx = FeatureContext(timeframe="6H", periods_per_year=PPY)
    cand = get_candidate("S1")
    fr = build_frames(cand, df, [dict(cand.default_params, bracket=bracket)], ctx)
    fracs = rule_fraction_matrix(df, SIZING_TIERS["trader"], fr.stop, "6H", PPY)
    costs = Costs(0.001, 0.0005)
    eng = run_vectorized(df["open"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(), fr.desired, fr.stop, costs=costs,
                         time_stop_bars=fr.time_stops, target_distance=fr.target, size_fraction=fracs, trail_activate_r=fr.trail_activate, trail_r=fr.trail_dist,
                         rebalance_threshold=0.25, brakes=brakes, bar_times=np.asarray(df.index.values))
    n = len(df)
    sleeve = bd.SleeveInput("S1/X", "X-USDT", "S1", fr.desired[:, 0], fr.stop[:, 0], fracs[:, 0], fr.strength[:, 0], None if fr.target is None else fr.target[:, 0],
                            None if fr.time_stops[0] is None else np.full(n, float(fr.time_stops[0])),
                            None if fr.trail_activate is None else np.full(n, float(fr.trail_activate[0])), None if fr.trail_dist is None else np.full(n, float(fr.trail_dist[0])))
    book = bd.run_book(df.index, {"X-USDT": df}, [sleeve], costs={"X-USDT": costs}, cfg=bd.BookConfig(brakes=brakes, corr_cap=None))
    np.testing.assert_allclose(book.equity.to_numpy(), eng.equity[:, 0], rtol=1e-10, atol=1e-6)
    assert len(book.trades) == len(eng.trades) > 20
    cols = ["entry_i", "exit_i", "entry_price", "exit_price", "quantity", "fees", "pnl", "return_pct", "bars_held", "mfe_pct", "mae_pct", "size_fraction", "reductions",
            "stop_price", "risk", "risk_pct"]
    a, b = book.trades.reset_index(drop=True), eng.trades.reset_index(drop=True)
    np.testing.assert_allclose(a[cols].to_numpy(dtype=float), b[cols].to_numpy(dtype=float), rtol=1e-9, atol=1e-9, equal_nan=True)
    assert (a["exit_reason"] == b["exit_reason"]).all()
    if brakes is not None:
        for name in ("entry_cap_market_day", "entry_after_exit", "daily_loss", "weekly_loss", "monthly_loss", "hard_stop", "ladder"):
            assert book.brakes["counts"][name] == int(eng.brakes["counts"][name][0]), name
        assert book.brakes["trips"] == {k: int(v[0]) for k, v in eng.brakes["trips"].items()}
    assert book.position.sum().sum() == int(eng.position.sum())
    assert set(bd.BOOK_TRADE_COLUMNS) <= set(book.trades.columns)


# -- the book-level rules ------------------------------------------------------------------------------------------------------

def test_entry_caps_act_across_sleeves_on_one_market_and_across_the_book_by_strength():
    n = 40
    mkts = {f"M{k}-USDT": _flat(n) for k in range(4)}
    # Two rules on M0 want the same bars of one UTC day (bars 8-11 are one day at 6H): the stronger one gets the market's one entry of the
    # day; the other is blocked at both bars it wants and, its signal gone, never enters.
    s_weak = _sleeve("S1/M0", "M0-USDT", n, enter_at=8, fraction=0.2, stop_pct=0.05, hold_bars=2, strength=0.5)
    s_strong = _sleeve("S1+VC/M0", "M0-USDT", n, enter_at=8, fraction=0.2, stop_pct=0.05, hold_bars=2, strength=2.0)
    res = _book(mkts, [s_weak, s_strong], corr_cap=None)
    assert res.brakes["counts"]["entry_cap_market_day"] == 2 and res.brakes["counts"]["entries"] == 1
    assert list(res.trades["sleeve"]) == ["S1+VC/M0"] and int(res.trades["entry_i"].iloc[0]) == 9
    # A blocked sleeve whose signal holds into the next day enters then (blocked, not cancelled): bars 9-11 are the cap, bar 12 is the bar after
    # the strong sleeve's exit at bar 11 (no entry in the market there), bar 13 fills.
    s_weak_long = _sleeve("S1/M0", "M0-USDT", n, enter_at=8, fraction=0.2, stop_pct=0.05, hold_bars=10, strength=0.5)
    res = _book(mkts, [s_weak_long, s_strong], corr_cap=None)
    t = res.trades.set_index("sleeve")
    assert int(t.loc["S1+VC/M0", "entry_i"]) == 9 and int(t.loc["S1+VC/M0", "exit_i"]) == 11 and int(t.loc["S1/M0", "entry_i"]) == 13
    assert res.brakes["counts"]["entry_cap_market_day"] == 3 and res.brakes["counts"]["entry_after_exit"] == 1
    # Four markets, one sleeve each, all wanting the same bars: three enter (the book's daily cap), the weakest is blocked.
    sleeves = [_sleeve(f"S1/M{k}", f"M{k}-USDT", n, enter_at=8, fraction=0.1, stop_pct=0.05, hold_bars=2, strength=float(4 - k)) for k in range(4)]
    res = _book(mkts, sleeves, corr_cap=None)
    assert res.brakes["counts"]["entry_cap_book_day"] == 2 and res.brakes["counts"]["entries"] == 3
    assert set(res.trades["sleeve"]) == {"S1/M0", "S1/M1", "S1/M2"}
    # No entry in a market on the bar after an exit there, whichever sleeve exited.
    s_a = _sleeve("S1/M0", "M0-USDT", n, enter_at=5, fraction=0.1, stop_pct=0.05, hold_bars=5)  # long from bar 6, exits at bar 11's open
    s_b = _sleeve("S1+VC/M0", "M0-USDT", n, enter_at=11, fraction=0.1, stop_pct=0.05, hold_bars=1)  # wants bar 12 = the bar after the exit
    res = _book(mkts, [s_a, s_b], corr_cap=None)
    assert res.brakes["counts"]["entry_after_exit"] == 1 and list(res.trades["sleeve"]) == ["S1/M0"] and int(res.trades["exit_i"].iloc[0]) == 11
    with pytest.raises(ValueError):
        bd.run_book(_flat(n).index, mkts, [], costs={m: ZERO for m in mkts})


def _wave(n: int, phase: float, start: str = "2024-01-01") -> pd.DataFrame:
    """A deterministic 1 % oscillation (no stop 5 % away is ever hit); two markets with the same phase move together, a quarter period apart they do not."""
    idx = pd.date_range(start, periods=n, freq="6h", tz="UTC", name="open_time")
    close = 100.0 * (1.0 + 0.01 * np.sin(np.arange(n) / 5.0 + phase))
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.0005, "low": np.minimum(open_, close) * 0.9995, "close": close, "volume": 1.0}, index=idx)


def test_heat_cap_scales_open_and_new_positions_of_one_bet_equally_and_leaves_other_bets_alone():
    n = 400
    # Two markets that move together (one bet by correlation) and a third a quarter period apart (its own bet).
    mkts = {"A-USDT": _wave(n, 0.0), "B-USDT": _wave(n, 0.0), "C-USDT": _wave(n, np.pi / 2)}
    # Each entry risks 2 % of equity (fraction x stop share = 0.2 x 10 %); the bet's cap is 3 %.
    s_a = _sleeve("S1/A", "A-USDT", n, enter_at=300, fraction=0.2, stop_pct=0.10, hold_bars=30)
    s_b = _sleeve("S1/B", "B-USDT", n, enter_at=305, fraction=0.2, stop_pct=0.10, hold_bars=30)
    s_c = _sleeve("S1/C", "C-USDT", n, enter_at=310, fraction=0.2, stop_pct=0.10, hold_bars=30)
    for s in (s_a, s_b, s_c):
        s.stop = 0.10 * mkts[s.instrument]["close"].to_numpy()
    res = _book(mkts, [s_a, s_b, s_c], corr_cap=None)
    c = res.brakes["counts"]
    # C's entry is in another bet: it must not trim A and B, whose risk drifted a little above their share (entries only).
    assert c["entries"] == 3 and c["heat_cap_entries"] == 1 and c["heat_cap_reductions"] == 1 and c["cash_bound_entries"] == 0, c
    t = res.trades.set_index("sleeve")
    # A was cut to 0.75 of its size when B entered (both end at 1.5 % of risk); C is another bet and keeps its full 2 %.
    assert t.loc["S1/A", "reductions"] == 1 and abs(t.loc["S1/B", "risk_pct"] - 0.015) < 1e-3 and abs(t.loc["S1/C", "risk_pct"] - 0.02) < 1e-3
    assert 0.70 < t.loc["S1/B", "funded_multiplier"] < 0.80 and t.loc["S1/C", "funded_multiplier"] == 1.0  # 3 % / (A's drifted risk + 2 %)
    groups = next(d["groups"] for d in reversed(res.daily) if d["positions_close"].get("S1/A"))
    assert ["S1/A", "S1/B"] in groups and ["S1/C"] in groups, groups
    # The 8 % variant (group share 4 %) lets the second entry in whole.
    res8 = _book(mkts, [s_a, s_b, s_c], brakes=BrakeSpec(heat_cap=0.08), corr_cap=None)
    assert res8.brakes["counts"]["heat_cap_entries"] == 0 and res8.brakes["counts"]["heat_cap_reductions"] == 0 and res8.brakes["counts"]["entries"] == 3


def test_correlation_cap_scales_a_bet_above_half_of_equity_at_the_next_day():
    n = 400
    mkts = {"A-USDT": _wave(n, 0.0), "B-USDT": _wave(n, 0.0)}
    # Two 40 % positions in one bet (80 % of equity) with wide stops (risk 2 % each: within the heat cap).
    sleeves = [_sleeve(f"S1/{k}", f"{k}-USDT", n, enter_at=300, fraction=0.4, stop_pct=0.05, hold_bars=40) for k in ("A", "B")]
    for s in sleeves:
        s.stop = 0.05 * mkts[s.instrument]["close"].to_numpy()
    res = _book(mkts, sleeves, brakes=None, corr_cap=0.5)
    c = res.brakes["counts"]
    # The first day after the two entries cuts both positions to 25 % each; the cap is re-checked every day, so a drift above 50 % is trimmed again.
    assert c["corr_cap_reductions"] >= 2 and res.brakes["corr_cap_days"] >= 1 and (res.trades["reductions"] >= 1).all()
    first_cap_day = next(d for d in res.daily if "correlation cap" in d["brakes"])
    key = "+".join(first_cap_day["groups"][0])
    assert first_cap_day["invested_before_cap"][key] > 0.79 and abs(first_cap_day["group_multipliers"][key] - 0.5 / first_cap_day["invested_before_cap"][key]) < 1e-12
    assert res.value_share.sum(axis=1).max() < 0.81 and res.value_share.sum(axis=1).iloc[-60:].max() <= 0.5 + 0.02
    res_off = _book(mkts, sleeves, brakes=None, corr_cap=None)
    assert res_off.brakes["counts"]["corr_cap_reductions"] == 0 and (res_off.trades["reductions"] == 0).all()


def test_cash_constraint_never_sells_an_open_position_and_counts_bound_and_blocked_entries():
    n = 60
    mkts = {f"M{k}-USDT": _flat(n) for k in range(3)}
    sleeves = [_sleeve(f"S1/M{k}", f"M{k}-USDT", n, enter_at=10 + 4 * k, fraction=0.7, stop_pct=0.02, hold_bars=30) for k in range(3)]
    res = _book(mkts, sleeves, brakes=None, corr_cap=None)
    c = res.brakes["counts"]
    t = res.trades.set_index("sleeve")
    # M0 takes 70 %, M1 gets the 30 % left (bound), M2 finds no cash until M0's exit frees it, then enters: nothing is ever sold to make room.
    assert c["entries"] == 3 and c["cash_bound_entries"] == 1 and c["cash_blocked_entries"] >= 1
    assert abs(t.loc["S1/M0", "size_fraction"] - 0.7) < 1e-12 and 0.29 < t.loc["S1/M1", "size_fraction"] < 0.31 and bool(t.loc["S1/M1", "cash_bound"])
    assert int(t.loc["S1/M2", "entry_i"]) >= int(t.loc["S1/M0", "exit_i"]) and not bool(t.loc["S1/M0", "cash_bound"])
    assert (res.trades["reductions"] == 0).all() and res.value_share.sum(axis=1).max() <= 1.0 + 1e-9


def test_loss_limits_and_the_ladder_read_the_books_equity_and_block_or_cut_other_sleeves_entries():
    n = 80
    a = _flat(n)
    crash = 30
    a.loc[a.index[crash:], ["open", "high", "low", "close"]] = 85.0  # a 15 % fall at one bar, then flat
    a.loc[a.index[crash], "open"] = 100.0
    a.loc[a.index[crash], "high"] = 100.1
    a.loc[a.index[crash], "low"] = 84.9
    mkts = {"A-USDT": a, "B-USDT": _flat(n)}
    s_a = bd.SleeveInput("hold/A", "A-USDT", "hold", np.ones(n, dtype=bool), np.full(n, np.nan), np.full(n, 0.8), None)  # 80 % in A, no stop: the fall costs 12 %
    s_b = _sleeve("S1/B", "B-USDT", n, enter_at=[crash + 1, crash + 10], fraction=0.1, stop_pct=0.05, hold_bars=3)
    daily_only = BrakeSpec(weekly_loss_limit=None, monthly_loss_limit=None)
    res = _book(mkts, [s_a, s_b], brakes=daily_only, corr_cap=None)
    c = res.brakes["counts"]
    assert res.brakes["trips"]["daily_loss"] >= 1 and c["daily_loss"] >= 1, c
    funded = res.trades[res.trades["sleeve"] == "S1/B"]
    assert len(funded) == 1 and abs(float(funded["funded_multiplier"].iloc[0]) - 0.8) < 1e-9, "the entry after the 24-hour block is cut by the Turtle ladder (-15 % drawdown)"
    assert c["ladder"] == 1 and int(funded["entry_i"].iloc[0]) == crash + 11 and c["cash_blocked_entries"] == 0
    # With every limit on, a 15 % fall also trips the weekly (6 %) and the monthly (10 %) limit: no entry for the rest of the week and the month.
    res_all = _book(mkts, [s_a, s_b], brakes=TRADER_BRAKES, corr_cap=None)
    c_all = res_all.brakes["counts"]
    assert res_all.brakes["trips"]["weekly_loss"] == 1 and res_all.brakes["trips"]["monthly_loss"] == 1 and c_all["weekly_loss"] + c_all["monthly_loss"] >= 1
    assert res_all.trades[res_all.trades["sleeve"] == "S1/B"].empty


def test_daily_records_sleeve_contributions_and_metrics():
    n = 120
    mkts = {"A-USDT": _market(3, n), "B-USDT": _market(4, n)}
    for df in mkts.values():
        df.index = mkts["A-USDT"].index
    sleeves = [_sleeve("S1/A", "A-USDT", n, enter_at=[20, 60], fraction=0.2, stop_pct=0.05, hold_bars=10), _sleeve("S1/B", "B-USDT", n, enter_at=40, fraction=0.2, stop_pct=0.05, hold_bars=10)]
    for s in sleeves:
        s.stop = 0.05 * mkts[s.instrument]["close"].to_numpy()
    res = _book(mkts, sleeves)
    assert len(res.daily) == len({d.strftime("%Y-%m-%d") for d in res.clock}) and res.daily[-1]["day"] == res.clock[-1].strftime("%Y-%m-%d")
    assert {"positions_close", "groups", "correlations", "invested_before_cap", "group_multipliers", "brakes", "equity_index", "ladder_multiplier"} <= set(res.daily[0])
    contrib = bd.sleeve_contributions(res)
    assert set(contrib.columns) == {"S1/A", "S1/B"} and abs(contrib.sum().sum() - sum(float(t["pnl"]) / float(res.equity.loc[res.equity.index.floor("D") == pd.Timestamp(t["exit_time"]).floor("D")].iloc[-1]) for _, t in res.trades.iterrows())) < 1e-9
    m = res.metrics(PPY)
    assert m["n_trades"] == len(res.trades) == 3 and 0.0 <= m["exposure"] <= 1.0 and m["positions_max"] in (1, 2)
    j = st.judge_book(res, PPY)
    assert set(j) >= {"oos", "yearly_gate", "acceptance_r18", "trades", "per_sleeve", "brakes"} and j["acceptance_r18"]["tier"] == "trader"
    assert j["per_sleeve"]["S1/A"]["n_trades"] == 2


# -- the daily basket -------------------------------------------------------------------------------------------------------------

def _daily(seed: int, n: int = 600, cols=("A-USDT", "B-USDT", "C-USDT")):
    rng = np.random.default_rng(seed)
    days = pd.date_range("2022-01-03", periods=n, freq="D", tz="UTC", name="day")  # a Monday
    closes = pd.DataFrame({c: 100 * np.exp(np.cumsum(rng.normal(0.0005 * (k + 1), 0.02, n))) for k, c in enumerate(cols)}, index=days)
    opens = closes.shift(1).fillna(closes.iloc[0])
    return closes, opens


def test_weekly_basket_fills_on_mondays_charges_costs_and_respects_the_vol_target_and_the_filter():
    closes, opens = _daily(1)
    cfg = bd.BasketConfig(vol_target=None, costs_per_side={"A-USDT": 0.0015}, default_cost_per_side=0.0025)
    res = bd.run_weekly_basket(closes, opens, bd.fixed_selector({"A-USDT": 1.0}), cfg=cfg, start=closes.index[40], end=closes.index[-1])
    recs = res.records
    fills = [r for r in recs if r["turnover"] > 0]
    assert fills and all(pd.Timestamp(r["day"]).weekday() == 0 for r in fills[1:]) and fills[0]["day"] == recs[1]["day"]  # decided at the start's close, filled next day, then Mondays
    assert recs[0]["invested_share"] == 0.0
    first = fills[0]
    assert abs(first["cost"] - first["turnover"] * 10_000.0 * 0.0015) < 1e-6 and abs(first["turnover"] - (1.0 - 0.0015)) < 1e-9  # the cost comes out of the money invested
    assert all(0.99 < r["invested_share"] <= 1.0 + 1e-9 for r in recs[1:])
    m = res.metrics()
    assert m["days"] == len(recs) and m["rebalances"] >= len(fills) and m["fees_pct_of_start"] > 0
    # The vol target scales the weights below 1 when the basket is more volatile than the target.
    vt = bd.run_weekly_basket(closes, opens, bd.fixed_selector({"A-USDT": 1.0}), cfg=bd.BasketConfig(vol_target=0.05), start=closes.index[40], end=closes.index[-1])
    scales = [r["scale"] for r in vt.records if r["scale"] is not None]
    assert scales and all(0.0 <= s <= 1.0 for s in scales) and np.mean(scales) < 0.6
    # The filter sends the basket to cash at the next open and keeps it there until a Monday on which it is True.
    allowed = pd.Series(True, index=closes.index)
    allowed.iloc[100:130] = False
    f = bd.run_weekly_basket(closes, opens, bd.fixed_selector({"A-USDT": 1.0}), cfg=cfg, start=closes.index[40], end=closes.index[-1], allowed=allowed)
    exits = [i for i, r in enumerate(f.records) if r["filter_exit"]]
    assert len(exits) == 1
    i_exit = exits[0]
    assert f.records[i_exit - 1]["day"] == closes.index[100].strftime("%Y-%m-%d") and f.records[i_exit]["invested_share"] == 0.0
    back = next(i for i in range(i_exit, len(f.records)) if f.records[i]["invested_share"] > 0)
    assert pd.Timestamp(f.records[back]["day"]).weekday() == 0 and f.records[back - 1]["day"] >= closes.index[130].strftime("%Y-%m-%d")
    assert all(r["invested_share"] == 0.0 for r in f.records[i_exit:back])
    assert bd.basket_metrics(f)["filter_exits"] == 1 and 0 < bd.basket_metrics(f)["days_filtered_out_share"] < 1


def test_top_n_selector_ranks_trailing_returns_and_the_basket_never_reads_the_future():
    closes, opens = _daily(2)
    sel = bd.top_n_selector(21, 2, list(closes.columns))
    day = closes.index[100]
    hist = closes.loc[:day]
    ret = (hist.iloc[-1] / hist.iloc[-22] - 1.0).sort_values(ascending=False)
    picked = sel(day, hist)
    assert set(picked) == set(ret.index[:2]) and all(abs(w - 0.5) < 1e-12 for w in picked.values())
    assert sel(day, hist.iloc[-10:]) == {}
    cfg = bd.BasketConfig(vol_target=0.2)
    full = bd.run_weekly_basket(closes, opens, sel, cfg=cfg, start=closes.index[40], end=closes.index[-1])
    changed = closes.copy()
    changed.iloc[300:, :] *= 1.5
    part = bd.run_weekly_basket(changed, opens, sel, cfg=cfg, start=closes.index[40], end=closes.index[-1])
    cut = closes.index[299]
    np.testing.assert_allclose(full.equity.loc[:cut].to_numpy(), part.equity.loc[:cut].to_numpy())
    flt = bd.sma_filter(closes["A-USDT"], 200)
    assert not flt.iloc[:199].any() and flt.dtype == bool and len(flt) == len(closes)
    with pytest.raises(ValueError):
        bd.BasketConfig(vol_target=-1.0)
    with pytest.raises(ValueError):
        bd.run_weekly_basket(closes, opens.iloc[:, :2], sel, cfg=cfg, start=closes.index[0], end=closes.index[-1])


# -- the study: pre-registration, jobs, stored targets, verdicts ----------------------------------------------------------------------

def test_preregistration_is_written_once_checked_and_the_committed_file_matches_the_module(tmp_path):
    path = tmp_path / "prereg.json"
    payload = st.preregister(path, now=datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert payload["markets"] == list(st.MARKETS) and payload["rules"] == ["S1", "S1+VC", "S1+S5"] and payload["judged_cell"]["key"] == "trader|brakes|none"
    loaded = st.load_preregistration(path)
    assert loaded["sha256"] == payload["sha256"] and loaded["book_config"]["corr_cap"] == 0.5 and loaded["rotation"]["top_n"] == 3
    with pytest.raises(st.BreadthError):
        st.preregister(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["preregistration"]["gates"] = "looser"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(st.BreadthError):
        st.load_preregistration(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["preregistration"] = dict(st.PREREGISTRATION)
    data["rotation"]["top_n"] = 4
    data["sha256"] = st._sha256_json({k: v for k, v in data.items() if k != "sha256"})
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(st.BreadthError):
        st.load_preregistration(path)
    committed = st.load_preregistration(st.PREREGISTRATION_PATH)  # the committed file must match the module text (the study refuses to run otherwise)
    assert committed["preregistration"] == st.PREREGISTRATION and committed["configuration"] == st.StudyConfig().to_dict()
    assert st.check_replication_markets() and sorted(st.check_replication_markets()) == sorted(m for m in st.MARKETS if m not in st.MAJORS)
    assert st.full_study_requested(st.StudyConfig()) and not st.full_study_requested(st.StudyConfig(quick=True)) and not st.full_study_requested(st.StudyConfig(markets=("BTC-USDT",)))


def test_jobs_argv_and_the_protocol_check_explain_the_tier_only():
    cfg = st.StudyConfig(markets=("BTC-USDT", "SOL-USDT"))
    jobs = st.plan_jobs(cfg, evaluate_holdout=True)
    assert len(jobs) == 4 and all(j["strategies"] == ["hold", "S1", "S1+VC", "S1+S5"] for j in jobs)
    assert [j["evaluate_holdout"] for j in jobs] == [False, True, False, True]
    argv = st.job_argv(st.JUDGED_CELL, ["hold", "S1"], evaluate_holdout=True, lake_dir="x", quick=False)
    assert "--policy-risk-cap" in argv and "--turtle-ladder" in argv and "--brakes" in argv and "--policy-no-ladder" in argv and "--evaluate-holdout" in argv
    assert argv[argv.index("--timeframes") + 1] == "6H" and argv[argv.index("--regime-modes") + 1] == "none"
    ref = st.job_argv(st.REFERENCE_CELL, ["hold"], evaluate_holdout=False, lake_dir=None, quick=True)
    assert "--brakes" not in ref and "--policy-no-ladder" not in ref and "--quick" in ref
    v1c = st.runner()
    meta = json.loads(st.V1C_RESULTS.read_text(encoding="utf-8"))["meta"]
    args = dict(vars(v1c.parse_args(st.job_argv(st.JUDGED_CELL, ["hold", "S1", "S1+VC", "S1+S5"], evaluate_holdout=False, lake_dir=None, quick=False))))
    check = st.protocol_check_job(args, meta, st.JUDGED_CELL)
    assert check["ok_for_cell"] and list(check["expected_mismatches"]) == ["policy_sizing"] and check["unexplained_mismatches"] == {} and check["r18"]["brakes"] == TRADER_BRAKES.to_dict()
    args_ref = dict(vars(v1c.parse_args(st.job_argv(st.REFERENCE_CELL, ["hold", "S1"], evaluate_holdout=False, lake_dir=None, quick=False))))
    check_ref = st.protocol_check_job(args_ref, meta, st.REFERENCE_CELL)
    assert check_ref["ok"] and check_ref["ok_for_cell"] and check_ref["expected_mismatches"] == {}
    args_bad = dict(args_ref, fee=0.002)
    assert not st.protocol_check_job(args_bad, meta, st.REFERENCE_CELL)["ok_for_cell"]
    assert st.costs_for("BTC-USDT") == st.MAJOR_COSTS and st.costs_for("DOGE-USDT") == st.ALTCOIN_COSTS
    cfg_h8, uniform = st.ablation_config("heat_8pct")
    assert cfg_h8.brakes.heat_cap == 0.08 and not uniform and st.ablation_config("uniform_cost")[1] and st.ablation_config("raw")[0].brakes is None and st.ablation_config("raw")[0].corr_cap is None


@pytest.fixture(scope="module")
def stored_docs():
    return {"Sprint 2c": json.loads(st.V1C_RESULTS.read_text(encoding="utf-8")), "R12 replication": json.loads(st.R12_RESULTS.read_text(encoding="utf-8")),
            "R13 research round 1": json.loads(st.R13_RESULTS.read_text(encoding="utf-8")), "R16 research round 2": json.loads(st.R16_RESULTS.read_text(encoding="utf-8")),
            "R18 Trader Policy v1": json.loads(st.R18_RESULTS.read_text(encoding="utf-8")), "R19 research round 3": json.loads(st.R19_RESULTS.read_text(encoding="utf-8"))}


def test_every_sleeve_and_control_has_a_stored_reproduction_target(stored_docs):
    stored = st.stored_results(stored_docs)
    ref = {(r["candidate"], r["instrument"]): r["study_source"] for r in st._dedupe(stored["reference"])}
    for inst in st.MARKETS:
        for cand in ("hold", "S1", "S1+S5", "S1+VC"):
            assert (cand, inst) in ref, (cand, inst)
        assert ref[("S1", inst)] == ("Sprint 2c" if inst in st.MAJORS else "R12 replication")
        assert ref[("S1+VC", inst)] == ("R13 research round 1" if inst in st.MAJORS else "R16 research round 2")
    trader = {(r["candidate"], r["instrument"]): r["study_source"] for r in st._dedupe(stored["trader"])}
    assert all(("hold", inst) in trader for inst in st.MARKETS)
    assert trader[("S1+S5", "BTC-USDT")] == "R18 Trader Policy v1" and trader[("S1", "SOL-USDT")] == "R18 Trader Policy v1"
    assert all(r["timeframe"] == "6H" and (r.get("regime") or {}).get("mode") == "none" for r in stored["reference"] + stored["trader"])


def test_verdict_rules_diversification_fleet_rows_and_summary():
    judged_pass = {"oos": {"calmar": 0.9, "cagr": 0.1, "max_drawdown": 0.11, "ann_vol": 0.1, "sharpe": 1.0, "n_trades": 100, "profit_factor": 1.5}, "acceptance_r18": {"passed": True, "failed": []}}
    judged_fail = {"oos": {"calmar": 0.3}, "acceptance_r18": {"passed": False, "failed": ["calmar_gt_0_5"]}}
    sleeves = [{"configuration": "S1 BTC-USDT 6H [none]", "in_book": True, "passed_own": True, "trader": {"calmar": 0.7, "ann_vol": 0.1}},
               {"configuration": "S1 ETH-USDT 6H [none]", "in_book": True, "passed_own": False, "trader": {"calmar": 0.4, "ann_vol": 0.12}},
               {"configuration": "S1+S5 DOGE-USDT 6H [none]", "in_book": False, "passed_own": False, "trader": {"calmar": 0.1, "ann_vol": 0.2}}]
    v = st.candidate_verdict(judged_pass, sleeves, None)
    assert v["passed"] and not v["candidate"] and v["sleeves_in_book"] == 2 and v["sleeves_passing_own"] == 1 and "holdout not opened" in v["reason"]
    assert st.candidate_verdict(judged_pass, sleeves, True)["candidate"] and not st.candidate_verdict(judged_pass, sleeves, False)["candidate"]
    assert st.candidate_verdict(judged_pass, sleeves[:1], None)["candidate"], "every sleeve passing on its own makes the book a candidate without a holdout"
    assert not st.candidate_verdict(judged_fail, sleeves[:1], True)["candidate"]
    d = st.diversification(judged_pass, sleeves, {"calmar": 0.39, "cagr": 0.06, "max_drawdown": 0.15}, {"calmar": 0.5}, {"calmar": 0.2})
    assert d["n_sleeves"] == 2 and abs(d["sleeves_median_calmar"] - 0.55) < 1e-12 and abs(d["gain_vs_best_sleeve"] - 0.2) < 1e-12 and abs(d["gain_vs_hold_btc"] - 0.51) < 1e-12
    assert d["best_sleeve"]["configuration"] == "S1 BTC-USDT 6H [none]" and abs(d["gain_vs_equal_weight_nine"] - 0.7) < 1e-12
    line = st.brake_cost_line({"calmar": 0.6, "cagr": 0.1, "max_drawdown": 0.1, "n_trades": 10}, {"calmar": 0.75, "cagr": 0.12, "max_drawdown": 0.12, "n_trades": 12})
    assert line["flagged"] and abs(line["cost_calmar"] - 0.15) < 1e-12 and not st.brake_cost_line({"calmar": 0.6}, {"calmar": 0.65})["flagged"]
    book = {"judged": judged_pass, "verdict": st.candidate_verdict(judged_pass, sleeves, True), "markets": ["BTC-USDT", "ETH-USDT"], "n_sleeves": 2, "config": {}, "holdout": {"evaluated": True, "confirmed": True, "oos": {}},
            "sleeves": [{"sleeve": "S1/BTC", "instrument": "BTC-USDT", "candidate": "S1", "in_book": True, "selected_params": {}}]}
    rows = st.fleet_rows(book, {"passed": False}, source={"study": st.STUDY_NAME})
    assert len(rows) == 1 and rows[0]["kind"] == "breadth_book" and rows[0]["source"]["tier"] == "trader" and rows[0]["source"]["account_kind"] == "breadth_book"
    assert st.fleet_rows({"judged": judged_fail, "verdict": {"candidate": False}}, {"passed": True, "holdout": {"confirmed": True, "evaluated": True}, "config": {}, "lines": {}}, source={})[0]["kind"] == "rotation"
    assert st.fleet_rows(None, None, source={}) == []
    summary = st.overall_summary([{"ok": True}, {"ok": True}], sleeves, book, {"passed": False, "checks": {}, "holdout": {}})
    assert summary["reproductions_ok"] == 2 and summary["book_candidate"] and summary["n_sleeves_in_book"] == 2 and summary["rotation_passed"] is False


# -- end to end on a synthetic lake -------------------------------------------------------------------------------------------------------

def _hourly(seed: int, n: int = 26_000, start: str = "2021-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="h", tz="UTC", name="open_time")
    regime = np.sign(np.sin(np.arange(n) / 500.0)) * 0.0004 + 0.00005
    close = 100 * np.exp(np.cumsum(regime + rng.normal(0, 0.006, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
    volume = rng.lognormal(3, 0.5, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


@pytest.fixture(scope="module")
def study_lake(tmp_path_factory):
    layout = LakeLayout(tmp_path_factory.mktemp("r20_lake") / "lake")
    _write(layout, "BTC-USDT", _hourly(1), bar="1H")
    _write(layout, "SOL-USDT", _hourly(2), bar="1H")
    return layout


@pytest.fixture(scope="module")
def synthetic_run(study_lake):
    cfg = st.StudyConfig(markets=("BTC-USDT", "SOL-USDT"), rules=("S1",), quick=True, reproduction=False, lake_dir=str(study_lake.root))
    outputs = [st.run_job(j) for j in st.plan_jobs(cfg, evaluate_holdout=False)]
    meta = json.loads(st.V1C_RESULTS.read_text(encoding="utf-8"))["meta"]
    merged, series_info = st.merge_results(outputs, meta)
    return cfg, merged, series_info


def test_run_job_merge_book_and_rotation_on_the_synthetic_lake(study_lake, synthetic_run):
    cfg, merged, series_info = synthetic_run
    assert set(merged) == {st.result_key(c, i, k) for c in ("hold", "S1") for i in ("BTC-USDT", "SOL-USDT") for k in ("reference|nobrakes|none", "trader|brakes|none")}
    for r in merged.values():
        assert r["protocol_check"]["unexplained_mismatches"] == {"quick": r["protocol_check"]["unexplained_mismatches"]["quick"]}  # a smoke run shows only the quick flag
        assert r["role"] == ("control" if r["candidate"] == "hold" else "sleeve") and r["in_book"] == (r["candidate"] == "S1" and r["cell"]["key"] == "trader|brakes|none")
    table = st.sleeve_table(merged)
    assert [s["configuration"] for s in table] == ["S1 BTC-USDT 6H [none]", "S1 SOL-USDT 6H [none]"] and all(s["in_book"] for s in table)
    data = {m: st.load_market(study_lake, m) for m in cfg.markets}
    clock, markets, sleeves, notes, start = st.build_book_inputs(study_lake, data, merged, rules=cfg.rules)
    assert len(sleeves) == 2 and len(clock) == len(data["BTC-USDT"].df_in) and all(n["in_book"] for n in notes)
    # The sleeve's arrays carry the per-window selected rule: nothing is desired before the first test window, something after; the book starts there.
    s = sleeves[0]
    first_test = data[s.instrument].windows[0].test.start
    assert not s.desired[:first_test].any() and s.desired[first_test:].any() and np.isfinite(s.fraction[first_test:]).any()
    assert start == min(data[m].windows[0].test.start for m in cfg.markets) and all(n["joins"] for n in notes)
    book = st.run_book_study(study_lake, data, merged, rules=cfg.rules, log=lambda m: None)
    assert book["n_sleeves"] == 2 and set(book["ablations"]) == set(st.ABLATIONS) and book["judged"]["oos"]["n_trades"] > 0
    assert set(book["post_hoc"]) == set(st.POST_HOC) and book["post_hoc"]["no_hard_stop"]["pre_registered"] is False
    assert book["clock"]["warmup_bars"] == start and book["judged"]["oos"]["bars"] == len(clock) - start + 1
    assert book["hold_btc_trader"] is not None and book["hold_btc_book_sim"] is not None and book["holdout"]["evaluated"] is False
    assert book["verdict"]["sleeves_in_book"] == 2 and isinstance(book["daily"], list) and book["daily"]
    hold_args = st.hold_arrays(data["BTC-USDT"])
    assert hold_args["desired"][first_test:].all() and not hold_args["desired"][:first_test].any() and np.isnan(hold_args["stop"]).all()
    rot = st.run_rotation_study(data, log=lambda m: None)
    assert set(rot["lines"]) >= {"rotation", "btc_vt20", "equal_weight_nine_vt20", "btc_buy_and_hold"} and rot["checks"]["passed"] == rot["passed"] and rot["holdout"]["evaluated"] is False
    assert pd.Timestamp(rot["span"]["start"]).weekday() == 0
    corr = st.market_correlations(data)
    assert set(corr) == {"in_sample", "recent"} and corr["in_sample"]["days"] > 0
    div = st.diversification(book["judged"], table, st._metrics_of(st.result_of(merged, "hold", "BTC-USDT", st.JUDGED_CELL)), book["hold_btc_book_sim"], rot["lines"]["equal_weight_nine_vt20"])
    assert div["n_sleeves"] == 2 and div["gain_vs_hold_btc"] is not None
    # The holdout construction builds arrays that are live only on the holdout bars.
    hclock, hmarkets, hsleeves, _, hstart = st.build_book_inputs(study_lake, data, merged, rules=cfg.rules, holdout=True)
    assert len(hclock) == len(data["BTC-USDT"].df_all) and len(hclock) - hstart == len(data["BTC-USDT"].df_hold) and all(len(hs.desired) == len(hclock) for hs in hsleeves)
    assert not any(hs.desired[:hstart].any() for hs in hsleeves)
    openings = st.holdout_openings(merged, series_info, book, rot)
    assert openings == []
    run = {"meta": {"study": st.STUDY_NAME, "preregistration": st.PREREGISTRATION, "generated_at": "now", "elapsed_minutes": 1.0, "workers": 1, "data_end": st.DATA_END, "v1c_meta": {}},
           "results": [{k: v for k, v in r.items() if k not in ("trades", "args")} for r in merged.values()], "reproduction": [], "sleeves": table, "book": book, "rotation": rot,
           "correlations": corr, "diversification": div, "overall": st.overall_summary([], table, book, rot), "holdout_openings": openings, "earlier_looks": [],
           "shortlist_recorded_only": [], "shortlist_note": "nothing recorded for the fleet"}
    text = render_report(json.loads(json.dumps(run, default=str)))
    assert "## The breadth book" in text and "## The rotation test" in text and "Candidate under the R5b rule" in text and "What the book-level rules did" in text
    summary = executive_summary(json.loads(json.dumps(run, default=str)))
    assert any("breadth book" in s for s in summary) and any("rotation test" in s for s in summary)
    assert owner_decisions(json.loads(json.dumps(run, default=str)))


def test_report_renders_the_stub_and_the_cli_refuses_the_holdout_outside_the_full_study(tmp_path, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_breadth_v1", ROOT / "scripts" / "run_breadth_v1.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stub = {"meta": {"study": st.STUDY_NAME, "preregistration": st.PREREGISTRATION, "preregistration_file": "x", "preregistration_written_at": "t", "preregistration_sha256": "abc",
                     "data_end": st.DATA_END}, "results": [], "sleeves": [], "book": None, "rotation": None, "overall": {}}
    text = render_report(stub)
    assert "Pre-registration only" in text and "The rotation test, as fixed" in text and "Nothing yet" in text
    prereg = tmp_path / "prereg.json"
    report = tmp_path / "report.md"
    assert mod.main(["--preregister", "--preregistration", str(prereg), "--report", str(report)]) == 0 and prereg.exists() and "Pre-registration only" in report.read_text(encoding="utf-8")
    assert mod.main(["--preregister", "--preregistration", str(prereg), "--report", "-"]) == 2
    rc = mod.main(["--evaluate-holdout", "--markets", "BTC-USDT", "--preregistration", str(prereg), "--report", "-", "--json", "-", "--holdout-ledger", str(tmp_path / "l.json")])
    assert rc == 2 and "full pre-registered study" in capsys.readouterr().err
    rc = mod.main(["--evaluate-holdout", "--preregistration", str(prereg), "--report", "-", "--json", "-", "--holdout-ledger", "-"])
    assert rc == 2 and "needs a holdout ledger" in capsys.readouterr().err
    rc = mod.main(["--cells", "reference|nobrakes|none", "--preregistration", str(prereg), "--report", "-", "--json", "-", "--holdout-ledger", "-", "--quick"])
    assert rc == 2 and "needs the Trader cell" in capsys.readouterr().err
    saved = tmp_path / "saved.json"
    saved.write_text(json.dumps(stub), encoding="utf-8")
    out = tmp_path / "re.md"
    assert mod.main(["--render-from-json", str(saved), "--report", str(out)]) == 0 and out.exists()
    assert mod.main(["--preregistration", str(tmp_path / "missing.json"), "--report", "-", "--json", "-", "--holdout-ledger", "-"]) == 2
    ledger_path = tmp_path / "ledger.json"
    st.write_breadth_ledger(str(ledger_path), [{"openings": [{"configuration": "S1 BTC-USDT 6H [none]", "cell": "trader|brakes|none", "role": "sleeve"}]}])
    from research.replication import load_ledger

    entries = load_ledger(str(ledger_path))
    second = st.guard_second_look(entries, [{"configuration": "S1 BTC-USDT 6H [none]", "cell": "trader|brakes|none", "role": "sleeve"}], evaluate_holdout=True)
    assert second == ["S1 BTC-USDT 6H [none] @ trader|brakes|none"] and st.guard_second_look(entries, [], evaluate_holdout=False) == []
