"""Forward portfolio: day bookkeeping equals research daily returns; booking equals combine_sized semantics."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from research.portfolio import combine_sized, rolling_inverse_vol_weights, to_daily_returns, vol_target_scale
from research.sizing import LadderConfig, apply_ladder_to_returns
from research.paper_fleet.config import PORTFOLIO_LADDER, PortfolioSpec, SleeveSpec
from research.paper_fleet.portfolio import PortfolioBook, SleeveDays, book_day, daily_frame


def _equity_path(n: int, freq: str, seed: int, start: str = "2026-01-01") -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.Series(10_000 * np.cumprod(1 + rng.normal(0.0004, 0.01, n)), index=idx)


@pytest.mark.parametrize("freq,hours", [("4h", 4), ("6h", 6)])
def test_sleeve_days_compound_bar_returns_like_the_research(freq, hours):
    eq = _equity_path(400, freq, seed=hours)
    eq = eq.drop(eq.index[100:110])  # a gap: a missing stretch of bars, a cash day in between
    days = SleeveDays()
    for ts, value in eq.items():
        days.on_bar(ts, ts + pd.Timedelta(hours=hours), float(value), 10_000.0)
    bar_returns = pd.concat([pd.Series([eq.iloc[0] / 10_000.0 - 1.0], index=eq.index[:1]), eq.pct_change().iloc[1:]])
    ref = to_daily_returns(bar_returns)
    got = pd.Series(days.closed)
    got.index = pd.DatetimeIndex(got.index, tz="UTC")
    ref.index = pd.DatetimeIndex(ref.index).tz_convert("UTC")
    last = eq.index[-1]
    finished = last + pd.Timedelta(hours=hours) >= last.floor("D") + pd.Timedelta(days=1)
    expected_through = last.floor("D") if finished else last.floor("D") - pd.Timedelta(days=1)
    assert days.done_through == expected_through.strftime("%Y-%m-%d")  # a day is final only once its last bar closed
    ref = ref[ref.index <= expected_through]
    pd.testing.assert_series_equal(got.sort_index(), ref.sort_index(), check_names=False, check_freq=False, rtol=1e-12)
    assert pd.Timestamp("2026-01-18", tz="UTC") not in got.index or hours == 6  # a day without bars is no row (a cash day later)


def _spec() -> PortfolioSpec:
    sleeves = tuple((f"S{i}", SleeveSpec("S1", "BTC-USDT", "6H", {"bracket": "none"})) for i in range(3))
    return PortfolioSpec(sleeves=sleeves)


def _daily(seed: int = 4, n: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC", name="day")
    data = rng.normal(0.001, 0.03, (n, 3)) * (rng.random((n, 3)) > 0.3)  # flat (cash) days too
    return pd.DataFrame(data, index=idx, columns=["S0", "S1", "S2"])


def test_booking_from_the_first_day_equals_combine_sized():
    spec = _spec()
    daily = _daily()
    book = PortfolioBook(forward_start_day=daily.index[0].strftime("%Y-%m-%d"))
    book.daily = {d.strftime("%Y-%m-%d"): {c: float(daily.loc[d, c]) for c in daily.columns} for d in daily.index}
    for d in daily.index:
        book_day(book, spec, d.strftime("%Y-%m-%d"), {"S0": True, "S1": True, "S2": False})
    ref = combine_sized(daily, name="ref", target_vol=spec.target_vol, vol_lookback_days=spec.vol_lookback_days,
                        weight_lookback_days=spec.weight_lookback_days, ladder=spec.ladder, cap=spec.cap)
    assert book.equity == pytest.approx(float(ref.equity.iloc[-1]), rel=1e-12)


def test_warm_up_seeds_the_estimates_and_the_ladder_starts_at_the_forward_start():
    spec = _spec()
    daily = _daily(seed=8)
    start = daily.index[120]
    book = PortfolioBook(forward_start_day=start.strftime("%Y-%m-%d"))
    book.daily = {d.strftime("%Y-%m-%d"): {c: float(daily.loc[d, c]) for c in daily.columns} for d in daily.index}
    records = [book_day(book, spec, d.strftime("%Y-%m-%d"), {}) for d in daily.index[120:]]
    weights = rolling_inverse_vol_weights(daily, spec.weight_lookback_days)
    raw = (daily * weights).sum(axis=1)
    scale = vol_target_scale(raw, spec.target_vol, spec.vol_lookback_days, cap=spec.cap)
    forward = (raw * scale).loc[start:]
    scaled, used = apply_ladder_to_returns(forward, spec.ladder)
    np.testing.assert_allclose([r["portfolio_return"] for r in records], scaled.to_numpy(), rtol=1e-12, atol=1e-15)
    np.testing.assert_allclose([r["ladder_multiplier"] for r in records], used.to_numpy())
    assert book.equity == pytest.approx(float((1 + scaled).prod()), rel=1e-12)
    assert all(r["vol_scale"] <= 1.0 for r in records) and all(r["gross_exposure_end_of_day"] <= 1.0 + 1e-12 for r in records)


def test_days_are_booked_only_when_every_sleeve_finished_them():
    book = PortfolioBook(forward_start_day="2026-03-02")
    a, b = SleeveDays(), SleeveDays()
    t = pd.Timestamp("2026-03-02 00:00", tz="UTC")
    for k in range(6):  # sleeve a finishes 2026-03-02 (six 4H bars)
        a.on_bar(t + pd.Timedelta(hours=4 * k), t + pd.Timedelta(hours=4 * (k + 1)), 10_000 + k, 10_000)
    for k in range(3):  # sleeve b (6H) has not closed its last bar of the day yet
        b.on_bar(t + pd.Timedelta(hours=6 * k), t + pd.Timedelta(hours=6 * (k + 1)), 10_000 + k, 10_000)
    assert book.days_ready({"a": a, "b": b}) == []
    b.on_bar(t + pd.Timedelta(hours=18), t + pd.Timedelta(hours=24), 10_010, 10_000)
    assert book.days_ready({"a": a, "b": b}) == ["2026-03-02"]
    book.absorb("a", a)
    book.absorb("b", b)
    frame = daily_frame(book, ["a", "b"])
    assert list(frame.columns) == ["a", "b"] and frame.loc["2026-03-02", "b"] == pytest.approx(0.001)


def test_the_research_portfolio_ladder_is_the_fleet_ladder():
    assert PORTFOLIO_LADDER == LadderConfig(half_dd=0.075, flat_dd=0.15, recovery_bars=30)


# -- plan row R5b: allocator v2 in the forward book -----------------------------------------------------------


ASSETS6 = {"S1/BTC/6H": "BTC-USDT", "S1/ETH/6H": "ETH-USDT", "S2/BTC/4H": "BTC-USDT", "S2/ETH/4H": "ETH-USDT", "S4/BTC/6H": "BTC-USDT",
           "S4/ETH/6H": "ETH-USDT"}


def _spec_v2(cfg=None):
    from research.allocator import DEFAULT_ALLOCATOR_V2

    sleeves = tuple((n, SleeveSpec("S1", a, n.split("/")[2], {"bracket": "none"})) for n, a in ASSETS6.items())
    return PortfolioSpec(sleeves=sleeves, allocator=DEFAULT_ALLOCATOR_V2 if cfg is None else cfg)


def _market6(seed: int, n: int = 320, vol: float = 0.03):
    """Six sleeves on two correlated coins; a calm market (small ``vol``) keeps the vol target near 1, where the cap binds."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC", name="day")
    common = rng.normal(0.0008, vol, n)
    coin_r = pd.DataFrame({"BTC-USDT": common + rng.normal(0, vol / 3, n), "ETH-USDT": 1.2 * common + rng.normal(0, vol / 1.5, n)}, index=idx)
    closes = 100.0 * (1.0 + coin_r).cumprod()
    held = pd.DataFrame({name: np.repeat(rng.random(n // 9 + 1) > 0.4, 9)[:n] for name in ASSETS6}, index=idx)
    prev = held.shift(1, fill_value=False)
    daily = pd.DataFrame({name: np.where(prev[name], coin_r[ASSETS6[name]] + rng.normal(0, 0.003, n), 0.0) for name in ASSETS6}, index=idx)
    return daily, held, closes


def _book_from(daily, held, closes, start, *, holes=()):
    book = PortfolioBook(forward_start_day=start.strftime("%Y-%m-%d"))
    for d in daily.index:
        key = d.strftime("%Y-%m-%d")
        book.daily[key] = {c: float(daily.loc[d, c]) for c in daily.columns}
        book.positions[key] = {c: bool(held.loc[d, c]) for c in held.columns if (key, c) not in holes}
        book.prices[key] = {c: float(closes.loc[d, c]) for c in closes.columns}
    return book


def test_allocator_v2_booking_is_the_research_allocator_day_by_day():
    from research.allocator import allocate_v2, daily_closes_to_returns

    daily, held, closes = _market6(seed=31, vol=0.008)
    start = daily.index[150]
    # Two sleeve-days without a bar (no record of the close position): both the book and the research carry the last close forward.
    holes = {(daily.index[200].strftime("%Y-%m-%d"), "S1/BTC/6H"), (daily.index[201].strftime("%Y-%m-%d"), "S2/ETH/4H")}
    book = _book_from(daily, held, closes, start, holes=holes)
    spec = _spec_v2()
    recs = [book_day(book, spec, d.strftime("%Y-%m-%d"), {}) for d in daily.index[150:]]
    research_held = held.astype(float)
    for day, name in holes:
        research_held.loc[pd.Timestamp(day, tz="UTC"), name] = np.nan
    run = allocate_v2(daily, research_held, daily_closes_to_returns(closes), ASSETS6, cfg=spec.allocator, target_vol=spec.target_vol,
                      vol_lookback_days=spec.vol_lookback_days, weight_lookback_days=spec.weight_lookback_days, ladder=spec.ladder, start=start)
    np.testing.assert_allclose([r["portfolio_return"] for r in recs], run.returns.to_numpy(), rtol=1e-12, atol=1e-15)
    for mine, ref in zip(recs, run.records):
        assert mine["groups"] == ref["groups"] and mine["brakes"] == ref["brakes"] and mine["positions_previous_close"] == ref["positions_previous_close"]
        assert mine["final_weights"] == pytest.approx(ref["final_weights"], rel=1e-12, abs=1e-15)
    assert book.equity == pytest.approx(float(run.equity.iloc[-1]), rel=1e-12) and book.alloc["equity"] == book.equity
    assert any("correlation cap" in r["brakes"] for r in recs) and recs[0]["allocator"] == "v2"
    assert all(r["gross_exposure_end_of_day"] == 0.0 for r in recs)  # nothing held "now" in this book: the indication is zero


def test_allocator_v2_with_its_brakes_off_books_exactly_like_v1():
    import dataclasses

    from research.allocator import AllocatorV2Config

    daily, held, closes = _market6(seed=33)
    start = daily.index[130]
    v1 = dataclasses.replace(_spec_v2(), allocator=None)
    off = _spec_v2(AllocatorV2Config(group_cap=None, loss_limit=None))
    b1, b2 = _book_from(daily, held, closes, start), _book_from(daily, held, closes, start)
    r1 = [book_day(b1, v1, d.strftime("%Y-%m-%d"), {}) for d in daily.index[130:]]
    r2 = [book_day(b2, off, d.strftime("%Y-%m-%d"), {}) for d in daily.index[130:]]
    np.testing.assert_allclose([x["portfolio_return"] for x in r2], [x["portfolio_return"] for x in r1], rtol=0, atol=1e-15)
    np.testing.assert_allclose([x["reference_v1"]["equity_index"] for x in r2], [x["equity_index"] for x in r1], rtol=1e-13)
    assert b2.equity == pytest.approx(b1.equity, rel=1e-13) and b2.lad_level == b1.lad_level


def test_sleeve_days_record_the_close_position_and_price_and_an_r5a_state_still_loads():
    days = SleeveDays()
    t = pd.Timestamp("2026-03-02 00:00", tz="UTC")
    for k in range(6):
        days.on_bar(t + pd.Timedelta(hours=4 * k), t + pd.Timedelta(hours=4 * (k + 1)), 10_000 + k, 10_000, in_position=k >= 3, close=100.0 + k)
    assert days.closed_positions == {"2026-03-02": True} and days.closed_closes == {"2026-03-02": 105.0}
    restored = SleeveDays.from_dict(json.loads(json.dumps(days.to_dict())))
    assert restored == days
    book = PortfolioBook(forward_start_day="2026-03-02")
    book.absorb("S2/BTC/4H", days, "BTC-USDT")
    assert book.positions == {"2026-03-02": {"S2/BTC/4H": True}} and book.prices == {"2026-03-02": {"BTC-USDT": 105.0}}
    assert not days.closed and not days.closed_positions and not days.closed_closes
    assert PortfolioBook.from_dict(json.loads(json.dumps(book.to_dict()))) == book
    old_book = {"forward_start_day": "2026-03-02", "daily": {}, "done_days": [], "equity": 1.0, "peak": 1.0, "lad_level": 0, "lad_flat": 0, "lad_mult": 1.0}
    b = PortfolioBook.from_dict(old_book)  # written by the R5a code: no positions, prices or allocator state
    assert b.positions == {} and b.prices == {} and b.alloc is None
    sd = SleeveDays.from_dict({"open_day": None, "day_equity": None, "prev_close_equity": 10_000.0, "done_through": "2026-03-01", "closed": {}})
    assert sd.closed_positions == {} and sd.day_in_position is None and sd.day_close is None
