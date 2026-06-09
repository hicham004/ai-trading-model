"""Read-only dashboard for stored candles and optional Phase 3A live status.

Run locally with::

    streamlit run dashboard/streamlit_app.py

This dashboard only READS public market data from the local database and the
optional FastAPI live-data endpoints. It has no trading, order, or account
features.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the project root importable when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import requests  # noqa: E402
import streamlit as st  # noqa: E402
from sqlalchemy import distinct, select  # noqa: E402

from app.db.database import get_session_factory, init_db  # noqa: E402
from app.db.models import Candle  # noqa: E402
from app.okx.client import ALLOWED_INSTRUMENTS  # noqa: E402

# Base URL of the read-only FastAPI app exposing /live endpoints. The dashboard
# only READS these over HTTP; it never opens a WebSocket itself.
LIVE_API_BASE = os.getenv("LIVE_API_BASE", "http://localhost:8000")


@st.cache_data(ttl=30)
def load_instruments() -> list[str]:
    """Return instruments that currently have stored candles."""
    init_db()
    session = get_session_factory()()
    try:
        stored = session.scalars(select(distinct(Candle.instrument))).all()
    finally:
        session.close()
    return sorted(stored) or list(ALLOWED_INSTRUMENTS)


@st.cache_data(ttl=30)
def load_candles(instrument: str, timeframe: str, limit: int) -> pd.DataFrame:
    """Load the most recent candles into a DataFrame (oldest-first)."""
    session = get_session_factory()()
    try:
        rows = session.scalars(
            select(Candle)
            .where(Candle.instrument == instrument, Candle.timeframe == timeframe)
            .order_by(Candle.open_time.desc())
            .limit(limit)
        ).all()
    finally:
        session.close()

    records = [
        {
            "open_time": row.open_time,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
        }
        for row in reversed(rows)
    ]
    return pd.DataFrame.from_records(records)


def render_live_status() -> None:
    """Optional Phase 3A section: live PUBLIC market-data status (read-only).

    Reads the FastAPI /live endpoints over HTTP. It never opens a WebSocket and
    degrades gracefully if the live API or stream is not running.
    """
    st.subheader("Live public market data (Phase 3A, WIP)")
    st.caption(
        "Read-only status of the live PUBLIC OKX stream. Observation only — "
        "no strategies, signals, or trading."
    )
    try:
        health_response = requests.get(f"{LIVE_API_BASE}/live/health", timeout=2)
        ticker_response = requests.get(f"{LIVE_API_BASE}/live/tickers", timeout=2)
        health_response.raise_for_status()
        ticker_response.raise_for_status()
        health = health_response.json()
        tickers = ticker_response.json()
    except (requests.RequestException, ValueError):
        st.info(
            "Live status unavailable. Start the API with its in-process stream: "
            "`LIVE_WS_AUTOSTART=true uvicorn app.api.main:app`. The standalone "
            "runner uses separate in-memory state and does not populate this panel."
        )
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("Connection", str(health.get("status", "unknown")))
    col2.metric("Stale", str(health.get("stale", True)))
    col3.metric("Since last msg (s)", str(health.get("seconds_since_last_message")))
    feeds = health.get("feeds", [])
    if feeds:
        st.caption("Required feed health")
        st.dataframe(pd.DataFrame.from_records(feeds), width="stretch")
    if tickers:
        st.dataframe(pd.DataFrame.from_records(tickers), width="stretch")
    else:
        st.write("No live tickers observed yet.")


def main() -> None:
    st.set_page_config(page_title="AI Trading Model - Candles", layout="wide")
    st.title("AI Trading Model — Candle Viewer")
    st.caption(
        "Read-only research and Phase 3A observation dashboard over PUBLIC "
        "market data. No trading or account features."
    )

    render_live_status()
    st.divider()

    instruments = load_instruments()

    with st.sidebar:
        st.header("Filters")
        instrument = st.selectbox("Instrument", instruments)
        timeframe = st.text_input("Timeframe (OKX bar)", value="1H")
        limit = st.slider("Max candles", min_value=10, max_value=1000, value=200)
        if st.button("Refresh data"):
            st.cache_data.clear()

    df = load_candles(instrument, timeframe, limit)

    if df.empty:
        st.warning(
            f"No stored candles for {instrument} {timeframe}. "
            "Run `python scripts/fetch_candles.py` first."
        )
        return

    st.subheader(f"{instrument} · {timeframe} · {len(df)} candles")

    col1, col2, col3 = st.columns(3)
    col1.metric("Latest close", f"{df['close'].iloc[-1]:,.2f}")
    col2.metric("Period high", f"{df['high'].max():,.2f}")
    col3.metric("Period low", f"{df['low'].min():,.2f}")

    chart_df = df.set_index("open_time")
    st.line_chart(chart_df[["close"]])

    with st.expander("Show raw candle table"):
        st.dataframe(df, width="stretch")


# Streamlit runs this file as the main module, so __name__ == "__main__".
if __name__ == "__main__":
    main()
