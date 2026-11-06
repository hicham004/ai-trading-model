"""On-disk layout of the research data lake (public data only).

```
<root>/
  candles/<instrument>/<timeframe>/<year>.parquet       spot OHLCV (one row per bar)
  derivatives/<kind>/<instrument>/<period>/<year>.parquet   OKX SWAP statistics (features)
  external/<venue>/<kind>/<symbol>/<period>/<year>.parquet   other venues' PUBLIC statistics (features only)
  liquidations/<instrument>/<YYYY-MM-DD>.jsonl          public liquidation-orders feed
  _state/<job>.json                                     resumable backfill cursors
  _reports/                                             data-quality reports
```

The root defaults to ``data/lake`` (git-ignored) and can be moved with the
``DATA_LAKE_DIR`` environment variable. Every path segment that comes from
user input is validated so a malformed instrument or timeframe can never
escape the lake directory.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Optional

DEFAULT_LAKE_DIR = "data/lake"
LAKE_DIR_ENV = "DATA_LAKE_DIR"

# Derivatives series kinds stored under ``derivatives/<kind>/``.
SERIES_KINDS = ("funding_rate", "open_interest", "long_short_ratio", "taker_volume")

# External (non-OKX) PUBLIC statistics stored under ``external/<venue>/<kind>/``.
# Research features only: this project never trades on these venues.
EXTERNAL_VENUES = ("binance",)
EXTERNAL_KINDS = ("funding_rate", "metrics")

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{0,63}$")


def safe_segment(value: str, label: str) -> str:
    """Return ``value`` if it is a safe single path segment, else raise."""
    if not isinstance(value, str) or not _SEGMENT_RE.match(value) or ".." in value:
        raise ValueError(f"unsafe {label} for a lake path: {value!r}")
    return value


@dataclass(frozen=True)
class LakeLayout:
    """Resolve every file the lake writes or reads."""

    root: Path

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "LakeLayout":
        env = os.environ if env is None else env
        return cls(Path(env.get(LAKE_DIR_ENV, DEFAULT_LAKE_DIR)))

    # -- spot candles -------------------------------------------------------
    def candles_dir(self, instrument: str, timeframe: str) -> Path:
        return (
            self.root
            / "candles"
            / safe_segment(instrument, "instrument")
            / safe_segment(timeframe, "timeframe")
        )

    def candles_file(self, instrument: str, timeframe: str, year: int) -> Path:
        return self.candles_dir(instrument, timeframe) / f"{int(year):04d}.parquet"

    def candles_glob(self) -> str:
        return (self.root / "candles" / "*" / "*" / "*.parquet").as_posix()

    # -- derivatives statistics (features only) -----------------------------
    def series_dir(self, kind: str, instrument: str, period: str) -> Path:
        if kind not in SERIES_KINDS:
            raise ValueError(f"unknown series kind {kind!r}; expected one of {SERIES_KINDS}")
        return (
            self.root
            / "derivatives"
            / kind
            / safe_segment(instrument, "instrument")
            / safe_segment(period, "period")
        )

    def series_file(self, kind: str, instrument: str, period: str, year: int) -> Path:
        return self.series_dir(kind, instrument, period) / f"{int(year):04d}.parquet"

    def series_glob(self, kind: str) -> str:
        if kind not in SERIES_KINDS:
            raise ValueError(f"unknown series kind {kind!r}; expected one of {SERIES_KINDS}")
        return (self.root / "derivatives" / kind / "*" / "*" / "*.parquet").as_posix()

    # -- external venues' public statistics (features only) -----------------
    def external_series_dir(self, venue: str, kind: str, symbol: str, period: str) -> Path:
        if venue not in EXTERNAL_VENUES:
            raise ValueError(f"unknown external venue {venue!r}; expected one of {EXTERNAL_VENUES}")
        if kind not in EXTERNAL_KINDS:
            raise ValueError(f"unknown external series kind {kind!r}; expected one of {EXTERNAL_KINDS}")
        return (
            self.root
            / "external"
            / venue
            / kind
            / safe_segment(symbol, "symbol")
            / safe_segment(period, "period")
        )

    def external_series_file(self, venue: str, kind: str, symbol: str, period: str, year: int) -> Path:
        return self.external_series_dir(venue, kind, symbol, period) / f"{int(year):04d}.parquet"

    def external_series_glob(self, venue: str, kind: str) -> str:
        if venue not in EXTERNAL_VENUES or kind not in EXTERNAL_KINDS:
            raise ValueError(f"unknown external series {venue!r}/{kind!r}")
        return (self.root / "external" / venue / kind / "*" / "*" / "*.parquet").as_posix()

    # -- liquidations (public WebSocket, JSON lines per UTC day) ------------
    def liquidations_dir(self, instrument: str) -> Path:
        return self.root / "liquidations" / safe_segment(instrument, "instrument")

    def liquidations_file(self, instrument: str, day: date) -> Path:
        return self.liquidations_dir(instrument) / f"{day.isoformat()}.jsonl"

    def liquidations_glob(self) -> str:
        return (self.root / "liquidations" / "*" / "*.jsonl").as_posix()

    # -- bookkeeping --------------------------------------------------------
    def state_file(self, *parts: str) -> Path:
        name = "__".join(safe_segment(p, "state key") for p in parts)
        return self.root / "_state" / f"{name}.json"

    @property
    def reports_dir(self) -> Path:
        return self.root / "_reports"
