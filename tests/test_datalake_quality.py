"""Data-quality assessment: gaps, duplicates, alignment, OHLC coherence, outliers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.datalake.quality import assess_candles, render_markdown

T0 = datetime(2024, 3, 1, tzinfo=timezone.utc)


def frame(rows):
    return pd.DataFrame(
        rows, columns=["open_time", "open", "high", "low", "close", "volume", "confirmed"]
    )


def bar(ts, price=100.0, *, high=None, low=None, close=None, volume=10.0, confirmed=True):
    return [ts, price, high if high is not None else price + 1, low if low is not None else price - 1,
            close if close is not None else price, volume, confirmed]


def test_clean_series_is_ok():
    rows = [bar(T0 + timedelta(hours=i)) for i in range(24)]
    r = assess_candles(frame(rows), instrument="BTC-USDT", timeframe="1H")
    assert r.ok and r.rows == 24 and r.expected_rows == 24 and r.missing_rows == 0
    assert r.gap_count == 0 and r.duplicate_rows == 0 and r.misaligned_rows == 0 and r.phase_ms == 0


def test_gaps_duplicates_and_misalignment_are_counted():
    rows = [bar(T0 + timedelta(hours=i)) for i in range(10)]
    del rows[3:5]  # 2 missing bars (one gap)
    del rows[6]  # 1 more missing bar (second gap)
    rows.append(bar(T0))  # duplicate
    rows.append(bar(T0 + timedelta(hours=9, minutes=30)))  # off-grid bar
    r = assess_candles(frame(rows), instrument="BTC-USDT", timeframe="1H")
    assert not r.ok
    assert r.duplicate_rows == 1
    assert r.misaligned_rows == 1
    assert r.gap_count == 2 and r.missing_rows >= 3
    assert r.gaps[0].missing_bars == 2 and r.gaps[0].after_ms == int((T0 + timedelta(hours=2)).timestamp() * 1000)
    assert any("missing bar" in n for n in r.notes)


def test_outliers_and_incoherent_ohlc():
    rows = [bar(T0 + timedelta(hours=i)) for i in range(6)]
    rows[2] = bar(T0 + timedelta(hours=2), high=50.0)  # high below open
    rows[3] = bar(T0 + timedelta(hours=3), price=200.0, close=200.0)  # +69% log move
    rows[4] = bar(T0 + timedelta(hours=4), volume=0.0)
    rows[5] = bar(T0 + timedelta(hours=5), confirmed=False)
    r = assess_candles(frame(rows), instrument="BTC-USDT", timeframe="1H")
    assert r.incoherent_ohlc_rows == 1
    assert r.extreme_move_rows >= 1 and r.max_abs_log_return > 0.6
    assert r.zero_volume_rows == 1
    assert r.unconfirmed_rows == 1
    assert not r.ok


def test_daily_bars_with_utc8_phase_are_aligned_and_noted():
    start = datetime(2024, 3, 1, 16, tzinfo=timezone.utc)  # OKX 1D opens 16:00 UTC
    rows = [bar(start + timedelta(days=i)) for i in range(5)]
    r = assess_candles(frame(rows), instrument="BTC-USDT", timeframe="1D")
    assert r.ok and r.misaligned_rows == 0 and r.phase_ms == 16 * 3_600_000
    assert any("UTC+8" in n for n in r.notes)


def test_empty_series_and_markdown_rendering():
    empty = assess_candles(frame([]), instrument="ETH-USDT", timeframe="4H")
    assert empty.rows == 0 and "no rows stored" in empty.notes
    rows = [bar(T0 + timedelta(hours=i)) for i in range(4)]
    del rows[1]
    gappy = assess_candles(frame(rows), instrument="BTC-USDT", timeframe="1H")
    md = render_markdown([empty, gappy], generated_at=T0)
    assert "| ETH-USDT 4H | 0 |" in md
    assert "| BTC-USDT 1H | 3 |" in md and "| NO |" in md
    assert "Gap after (UTC)" in md and "2024-03-01T00:00" in md
    d = gappy.to_dict()
    assert d["ok"] is False and d["first"].startswith("2024-03-01")
