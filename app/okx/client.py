"""Public OKX REST market-data client.

Public-data safety notes
------------------------
- This client only calls PUBLIC market-data endpoints (e.g. candlesticks).
- It NEVER sends API keys, signatures, or authentication headers.
- It NEVER calls account, trade, or withdrawal endpoints.

We use the synchronous ``requests`` library because it is easy to read for
beginners. The client validates every response and retries transient network
failures with a short backoff.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import List, Optional
from urllib.parse import urlsplit

import requests

from app.config import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# Public OKX candlestick endpoint. Documented at:
# https://www.okx.com/docs-v5/en/#order-book-trading-market-data-get-candlesticks
_CANDLES_PATH = "/api/v5/market/candles"
_HISTORY_CANDLES_PATH = "/api/v5/market/history-candles"
_APPROVED_REST_HOST = "www.okx.com"

# Instruments this project is allowed to fetch. Restricting the list keeps
# us within scope and makes accidental misuse harder.
ALLOWED_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")

# Each OKX candle row is an array of strings. We rely on these first columns:
#   0: ts (open time, Unix milliseconds, UTC)
#   1: open   2: high   3: low   4: close
#   5: vol (base-currency volume)
#   ... (additional volume columns)
#   8: confirm ("1" = candle closed/final, "0" = still forming)
_MIN_CANDLE_COLUMNS = 9


class OKXClientError(RuntimeError):
    """Raised when the OKX API cannot be reached or returns invalid data."""


@dataclass(frozen=True)
class Candle:
    """A single validated, immutable candlestick (all times in UTC)."""

    instrument: str
    timeframe: str
    timestamp: datetime  # candle open time, timezone-aware UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    confirmed: bool


class OKXPublicClient:
    """Minimal client for OKX public market-data endpoints."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        # ``settings`` and ``session`` are injectable so tests can run fully
        # offline without real network access.
        self._settings = settings or get_settings()
        self._session = session or requests.Session()
        self._base_url = self._settings.okx_base_url.rstrip("/")
        if session is None:
            validate_public_rest_base_url(self._base_url)

    # -- public API ---------------------------------------------------------

    def get_candles(
        self,
        instrument: str,
        timeframe: str = "1H",
        limit: int = 100,
        confirmed_only: bool = True,
    ) -> List[Candle]:
        """Fetch recent candles for ``instrument``.

        Args:
            instrument: e.g. ``"BTC-USDT"``. Must be in ``ALLOWED_INSTRUMENTS``.
            timeframe: OKX bar size, e.g. ``"1m"``, ``"15m"``, ``"1H"``, ``"1D"``.
            limit: number of candles to request (OKX caps this at 300).
            confirmed_only: drop the still-forming (unconfirmed) candle so we
                never store a partial bar.

        Returns:
            A list of :class:`Candle`, sorted oldest-first.

        Raises:
            ValueError: if the instrument is not allowed or limit is invalid.
            OKXClientError: on network failure or an invalid API response.
        """
        return self._get_candle_data(
            _CANDLES_PATH,
            instrument,
            timeframe,
            limit,
            confirmed_only=confirmed_only,
        )

    def get_history_candles(
        self,
        instrument: str,
        timeframe: str = "1m",
        limit: int = 100,
        *,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        confirmed_only: bool = True,
    ) -> List[Candle]:
        """Fetch public historical candles with optional timestamp pagination.

        ``after`` requests records older than that timestamp; ``before``
        requests records newer than it. At most one pagination direction may be
        supplied so callers cannot accidentally create an ambiguous backfill.
        """
        if after is not None and before is not None:
            raise ValueError("use at most one of after or before")
        extra_params = {}
        if after is not None:
            extra_params["after"] = self._datetime_to_ms(after, "after")
        if before is not None:
            extra_params["before"] = self._datetime_to_ms(before, "before")
        return self._get_candle_data(
            _HISTORY_CANDLES_PATH,
            instrument,
            timeframe,
            limit,
            confirmed_only=confirmed_only,
            extra_params=extra_params,
        )

    def _get_candle_data(
        self,
        path: str,
        instrument: str,
        timeframe: str,
        limit: int,
        *,
        confirmed_only: bool,
        extra_params: Optional[dict] = None,
    ) -> List[Candle]:
        if instrument not in ALLOWED_INSTRUMENTS:
            raise ValueError(
                f"Instrument {instrument!r} is not allowed. "
                f"Allowed: {', '.join(ALLOWED_INSTRUMENTS)}"
            )
        if not timeframe or not timeframe.strip():
            raise ValueError("timeframe must not be empty")
        if not 1 <= limit <= 300:
            raise ValueError("limit must be between 1 and 300")

        params = {"instId": instrument, "bar": timeframe, "limit": str(limit)}
        params.update(extra_params or {})
        payload = self._request(path, params)
        rows = self._extract_data_rows(payload)

        candles: List[Candle] = []
        for row in rows:
            candle = self._parse_candle_row(row, instrument, timeframe)
            if confirmed_only and not candle.confirmed:
                continue
            candles.append(candle)

        # OKX returns newest-first; sort oldest-first for predictable storage.
        candles.sort(key=lambda c: c.timestamp)
        logger.info(
            "Fetched candles",
            extra={
                "instrument": instrument,
                "timeframe": timeframe,
                "requested": limit,
                "returned": len(candles),
            },
        )
        return candles

    @staticmethod
    def _datetime_to_ms(value: datetime, label: str) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{label} must be timezone-aware")
        milliseconds = int(value.astimezone(timezone.utc).timestamp() * 1000)
        if milliseconds <= 0:
            raise ValueError(f"{label} must be after the Unix epoch")
        return str(milliseconds)

    # -- internal helpers ---------------------------------------------------

    def _request(self, path: str, params: dict) -> dict:
        """Perform a GET request with retries and return the parsed JSON body."""
        url = f"{self._base_url}{path}"
        last_error: Optional[Exception] = None

        for attempt in range(1, self._settings.okx_max_retries + 1):
            try:
                response = self._session.get(
                    url, params=params, timeout=self._settings.okx_request_timeout
                )
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                # ValueError also covers JSON decoding errors from .json().
                last_error = exc
                logger.warning(
                    "OKX request failed; will retry if attempts remain",
                    extra={
                        "url": url,
                        "attempt": attempt,
                        "max_attempts": self._settings.okx_max_retries,
                        "error": str(exc),
                    },
                )
                if attempt < self._settings.okx_max_retries:
                    # Simple linear backoff. Kept small and predictable.
                    time.sleep(0.5 * attempt)

        raise OKXClientError(
            f"Failed to reach OKX after {self._settings.okx_max_retries} attempts: "
            f"{last_error}"
        )

    @staticmethod
    def _extract_data_rows(payload: dict) -> List[list]:
        """Validate the top-level OKX envelope and return the ``data`` rows."""
        if not isinstance(payload, dict):
            raise OKXClientError("OKX response was not a JSON object")

        # OKX uses code "0" for success; anything else is an API-level error.
        code = payload.get("code")
        if code != "0":
            raise OKXClientError(
                f"OKX returned error code {code!r}: {payload.get('msg')!r}"
            )

        data = payload.get("data")
        if not isinstance(data, list):
            raise OKXClientError("OKX response 'data' field was not a list")
        return data

    @staticmethod
    def _parse_candle_row(row: list, instrument: str, timeframe: str) -> Candle:
        """Validate and convert one raw OKX candle row into a :class:`Candle`."""
        if not isinstance(row, list) or len(row) < _MIN_CANDLE_COLUMNS:
            raise OKXClientError(f"Malformed candle row: {row!r}")

        try:
            ts_ms = int(row[0])
            open_ = float(row[1])
            high = float(row[2])
            low = float(row[3])
            close = float(row[4])
            volume = float(row[5])
            confirmed = row[8] == "1"
        except (TypeError, ValueError) as exc:
            raise OKXClientError(f"Could not parse candle row {row!r}: {exc}") from exc
        if ts_ms <= 0:
            raise OKXClientError("Candle timestamp must be after the Unix epoch")
        if not all(isfinite(value) for value in (open_, high, low, close, volume)):
            raise OKXClientError("Candle contains a non-finite numeric value")
        if min(open_, high, low, close) <= 0 or volume < 0:
            raise OKXClientError("Candle prices must be positive and volume non-negative")
        if high < max(open_, close, low) or low > min(open_, close, high):
            raise OKXClientError("Candle OHLC values are incoherent")

        # Store timestamps as timezone-aware UTC. OKX provides Unix milliseconds.
        timestamp = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

        return Candle(
            instrument=instrument,
            timeframe=timeframe,
            timestamp=timestamp,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            confirmed=confirmed,
        )


def validate_public_rest_base_url(url: str) -> str:
    """Allow only the approved HTTPS OKX public REST origin in production."""
    try:
        parts = urlsplit(url)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"malformed OKX public REST URL: {type(exc).__name__}") from exc
    if parts.scheme != "https":
        raise ValueError("OKX public REST URL must use https")
    if parts.username or parts.password:
        raise ValueError("credentials are not allowed in the public REST URL")
    if parts.hostname != _APPROVED_REST_HOST:
        raise ValueError(f"OKX public REST host not approved: {parts.hostname!r}")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("malformed OKX public REST port") from exc
    if port not in (None, 443):
        raise ValueError(f"OKX public REST port not approved: {port!r}")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("OKX public REST base URL must not include path/query/fragment")
    return url
