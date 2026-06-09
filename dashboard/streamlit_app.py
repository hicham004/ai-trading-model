"""Streamlit dashboard for viewing stored candles (read-only research view).

Run locally with::

    streamlit run dashboard/streamlit_app.py

This dashboard only READS public candle data from the local database. It has
no trading, ordering, or account features (Phase 1).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from sqlalchemy import distinct, select  # noqa: E402

from app.db.database import get_session_factory, init_db  # noqa: E402
from app.db.models import Candle  # noqa: E402
from app.okx.client import ALLOWED_INSTRUMENTS  # noqa: E402


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


def main() -> None:
    st.set_page_config(page_title="AI Trading Model - Candles", layout="wide")
    st.title("AI Trading Model — Candle Viewer")
    st.caption(
        "Phase 1 research dashboard. Read-only view of PUBLIC market data. "
        "No trading or account features."
    )

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
