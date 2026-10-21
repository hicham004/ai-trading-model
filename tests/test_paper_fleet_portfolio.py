"""Forward portfolio: day bookkeeping equals research daily returns; booking equals combine_sized semantics."""

from __future__ import annotations

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
