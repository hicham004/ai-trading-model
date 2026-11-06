"""Public OKX market data for the news shadow (PHASE6B_DESIGN sections 7.5, 10, 13) — read-only, no keys.

Two PUBLIC, unauthenticated REST endpoints on one pinned host, and nothing else:

- ``GET /api/v5/market/candles``  recent candles, for the price/volume
  confirmation and the classifier's market context;
- ``GET /api/v5/public/time``     the exchange clock, for the clock-skew health
  check (design 13: a skewed news clock means NO_EFFECT).

Requests carry only a User-Agent and an Accept header: no account headers, no
signature, no credential of any kind. The host and both paths are pinned, so this
module cannot reach an account, order or private endpoint. Only CONFIRMED (closed)
candles are kept; the forming candle is dropped here, and ``corroborate``
additionally ignores any candle that closed after the decision time.

Nothing here imports exchange, execution or risk code.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from app.news.corroborate import PublicCandle
from app.news.fetch import HttpCall, default_http
from app.news.sources import USER_AGENT

OKX_PUBLIC_REST = "https://www.okx.com"
CANDLES_PATH = "/api/v5/market/candles"
TIME_PATH = "/api/v5/public/time"
ALLOWED_PATHS = frozenset({CANDLES_PATH, TIME_PATH})
INSTRUMENTS: Tuple[str, ...] = ("BTC-USDT", "ETH-USDT")
DEFAULT_BAR = "5m"
MAX_LIMIT = 300  # OKX returns at most 300 recent candles per request
BAR_MINUTES: Mapping[str, int] = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1H": 60}


class MarketDataError(ValueError):
    """A public market-data reply that could not be used (never raised past ``refresh``)."""


def _check_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "") != urlsplit(OKX_PUBLIC_REST).hostname:
        raise ValueError("public market data must come from https://www.okx.com")
    if parts.path not in ALLOWED_PATHS:
        raise ValueError(f"path {parts.path!r} is not a public market-data path")
    return url


def _okx_data(text: str) -> list:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise MarketDataError("reply is not JSON") from exc
    if not isinstance(payload, dict) or str(payload.get("code")) != "0" or not isinstance(payload.get("data"), list):
        raise MarketDataError("reply is not a successful OKX response")
    return payload["data"]


def parse_candles(text: str, bar: str = DEFAULT_BAR) -> List[PublicCandle]:
    """Confirmed candles from a ``/market/candles`` reply, oldest first.

    Rows are ``[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]`` (newest
    first); ``confirm == "1"`` marks a closed candle. Volume is the base-currency
    volume. Rows that are malformed or not finite are skipped.
    """
    if bar not in BAR_MINUTES:
        raise ValueError(f"unsupported bar {bar!r}")
    interval = timedelta(minutes=BAR_MINUTES[bar])
    out: Dict[datetime, PublicCandle] = {}
    for row in _okx_data(text):
        if not isinstance(row, (list, tuple)) or len(row) < 9 or str(row[8]) != "1":
            continue
        try:
            opened = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
            values = [float(row[i]) for i in range(1, 6)]
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if not all(math.isfinite(v) for v in values) or min(values) < 0:
            continue
        o, h, low, c, vol = values
        if h < max(o, c, low) or low > min(o, c, h):
            continue
        out[opened] = PublicCandle(open_time=opened, interval=interval, open=o, high=h, low=low, close=c, volume=vol)
    return [out[t] for t in sorted(out)]


def parse_server_time(text: str) -> datetime:
    data = _okx_data(text)
    try:
        return datetime.fromtimestamp(int(data[0]["ts"]) / 1000, tz=timezone.utc)
    except (IndexError, KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
        raise MarketDataError("reply has no server time") from exc


@dataclass(frozen=True)
class InstrumentRefresh:
    instrument: str
    ok: bool
    received: int = 0
    cached: int = 0
    last_close: Optional[datetime] = None
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "instrument": self.instrument,
            "ok": self.ok,
            "received": self.received,
            "cached": self.cached,
            "last_close": self.last_close.isoformat() if self.last_close else None,
            "error": self.error[:200],
        }


class PublicMarketData:
    """Rolling cache of recent public candles per instrument, refreshed once per cycle."""

    def __init__(
        self,
        http: Optional[HttpCall] = None,
        *,
        bar: str = DEFAULT_BAR,
        limit: int = MAX_LIMIT,
        instruments: Iterable[str] = INSTRUMENTS,
        keep: int = 600,
    ) -> None:
        if bar not in BAR_MINUTES:
            raise ValueError(f"unsupported bar {bar!r}")
        if not 1 <= int(limit) <= MAX_LIMIT or int(keep) < int(limit):
            raise ValueError("limit must be 1..300 and keep at least limit")
        self._http = http or default_http
        self._bar = bar
        self._limit = int(limit)
        self._keep = int(keep)
        self._instruments = tuple(instruments)
        self._cache: Dict[str, Dict[datetime, PublicCandle]] = {i: {} for i in self._instruments}

    @property
    def instruments(self) -> Tuple[str, ...]:
        return self._instruments

    @property
    def bar(self) -> str:
        return self._bar

    def _get(self, path: str, params: Optional[dict]) -> str:
        url = _check_url(OKX_PUBLIC_REST + path)
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        status, text = self._http("GET", url, params, None, headers)
        if status != 200:
            raise MarketDataError(f"HTTP {status}")
        return text

    def refresh(self) -> List[InstrumentRefresh]:
        """Fetch recent candles for every instrument; a failure leaves the cache as it was."""
        results = []
        for inst in self._instruments:
            try:
                text = self._get(CANDLES_PATH, {"instId": inst, "bar": self._bar, "limit": str(self._limit)})
                fresh = parse_candles(text, self._bar)
            except Exception as exc:  # network, HTTP or parse: logged by the caller, never raised
                results.append(InstrumentRefresh(inst, False, cached=len(self._cache[inst]), error=f"{type(exc).__name__}: {exc}"))
                continue
            cache = self._cache[inst]
            for candle in fresh:
                cache[candle.open_time] = candle
            if len(cache) > self._keep:
                for stale in sorted(cache)[: len(cache) - self._keep]:
                    del cache[stale]
            last = max(cache.values(), key=lambda c: c.open_time).close_time if cache else None
            results.append(InstrumentRefresh(inst, True, received=len(fresh), cached=len(cache), last_close=last))
        return results

    def candles(self, instrument: str) -> Tuple[PublicCandle, ...]:
        cache = self._cache.get(instrument, {})
        return tuple(cache[t] for t in sorted(cache))

    def server_time(self) -> datetime:
        return parse_server_time(self._get(TIME_PATH, None))

    def clock_skew_seconds(self, local_now: Callable[[], datetime]) -> Optional[float]:
        """``local - exchange`` clock difference in seconds, or None when it could not be measured.

        The local time is taken at the midpoint of the request so network latency
        does not count as skew.
        """
        try:
            before = local_now()
            server = self.server_time()
            after = local_now()
        except Exception:
            return None
        midpoint = before + (after - before) / 2
        return (midpoint - server).total_seconds()
