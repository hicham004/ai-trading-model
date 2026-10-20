"""Candle backfill against a fake public client: files, coverage, idempotency, guards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.datalake.backfill import backfill_candles
from app.datalake.layout import LakeLayout
from app.datalake.parquet_store import candle_coverage, read_candles, to_ms
from app.okx.client import Candle

START = datetime(2024, 1, 1, tzinfo=timezone.utc)


class FakeClient:
    """Serves hourly BTC-USDT bars between ``first`` and ``last`` like OKX would."""

    def __init__(self, first: datetime, last: datetime):
        self.first, self.last = first, last
        self.history_calls = 0

    def _candle(self, ts: datetime, confirmed=True) -> Candle:
        p = 100.0 + (ts - self.first).total_seconds() / 3600
        return Candle("BTC-USDT", "1H", ts, p, p + 1, p - 1, p + 0.5, 5.0, confirmed)

    def _page(self, upper: datetime, limit: int, confirmed_only: bool):
        rows, ts = [], upper
        while ts >= self.first and len(rows) < limit:
            rows.append(self._candle(ts))
            ts -= timedelta(hours=1)
        rows.sort(key=lambda c: c.timestamp)
        return rows

    def get_candles(self, instrument, timeframe, limit=100, confirmed_only=True):
        assert instrument == "BTC-USDT" and timeframe == "1H" and limit <= 300
        page = self._page(self.last, limit, confirmed_only)
        if not confirmed_only:
            page.append(self._candle(self.last + timedelta(hours=1), confirmed=False))
        return page

    def get_history_candles(self, instrument, timeframe, limit=100, *, after=None, before=None, confirmed_only=True):
        assert limit <= 100 and before is None and after is not None and after.tzinfo is not None
        self.history_calls += 1
        return self._page(after - timedelta(hours=1), limit, confirmed_only)


def test_backfill_writes_everything_once_and_is_idempotent(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    client = FakeClient(START, START + timedelta(hours=999))
    report = backfill_candles(client, layout, "BTC-USDT", "1H", start=START, sleep_seconds=0)
    assert report.walk.complete and report.walk.reason == "reached_start"
    assert report.added == 1000 and report.stored_rows == 1000
    assert report.stored_min == START and report.stored_max == START + timedelta(hours=999)
    assert read_candles(layout, "BTC-USDT", "1H").num_rows == 1000
    assert "complete=True" in report.summary()

    again = backfill_candles(client, layout, "BTC-USDT", "1H", start=START, sleep_seconds=0)
    assert again.added == 0 and again.walk.pages == 1  # only the newest page is re-checked
    assert candle_coverage(layout, "BTC-USDT", "1H").rows == 1000


def test_backfill_bounded_then_resumed(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    client = FakeClient(START, START + timedelta(hours=999))
    slept = []
    first = backfill_candles(
        client, layout, "BTC-USDT", "1H", start=START, max_pages=2, sleep_seconds=0.01, sleep=slept.append
    )
    assert first.walk.reason == "max_pages" and first.stored_rows == 400 and slept == [0.01, 0.01]
    second = backfill_candles(client, layout, "BTC-USDT", "1H", start=START, sleep_seconds=0)
    assert second.walk.complete and second.stored_rows == 1000
    assert candle_coverage(layout, "BTC-USDT", "1H").min_ms == to_ms(START)


def test_backfill_rejects_bad_inputs(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    client = FakeClient(START, START + timedelta(hours=10))
    with pytest.raises(ValueError):
        backfill_candles(client, layout, "DOGE-USDT", "1H", start=START)
    with pytest.raises(ValueError):
        backfill_candles(client, layout, "BTC-USDT", "1Q", start=START)
    with pytest.raises(ValueError):
        backfill_candles(client, layout, "BTC-USDT", "1H", start=datetime(2024, 1, 1))
