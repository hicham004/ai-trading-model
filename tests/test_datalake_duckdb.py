"""DuckDB views over the lake: empty lake works, populated lake is queryable."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.datalake import derivatives as d
from app.datalake.duckdb_views import candles_frame, connect
from app.datalake.layout import SERIES_KINDS, LakeLayout
from app.datalake.liquidations import JsonlSink
from app.datalake.parquet_store import write_candles
from app.okx.client import Candle

T0 = datetime(2024, 6, 1, tzinfo=timezone.utc)


def test_empty_lake_has_all_views(tmp_path: Path):
    con = connect(LakeLayout(tmp_path))
    for view in ("candles", "liquidations", *SERIES_KINDS):
        assert con.execute(f"SELECT count(*) FROM {view}").fetchone()[0] == 0
    cols = [c[0] for c in con.execute("DESCRIBE candles").fetchall()]
    assert cols[:3] == ["open_time", "instrument", "timeframe"]
    con.close()


def test_populated_lake_is_queryable(tmp_path: Path):
    layout = LakeLayout(tmp_path)
    candles = [
        Candle(inst, "1H", T0 + timedelta(hours=i), 10.0, 11.0, 9.0, 10.5, 1.0, True)
        for inst in ("BTC-USDT", "ETH-USDT")
        for i in range(5)
    ]
    write_candles(layout, candles)
    d.write_series(layout, "funding_rate", "BTC-USDT-SWAP", "8H", d.parse_funding_rows([
        {"instId": "BTC-USDT-SWAP", "fundingTime": "1717200000000", "fundingRate": "0.0001", "realizedRate": "0.0001",
         "method": "current_period", "formulaType": "withRate"}], "BTC-USDT-SWAP"))
    d.write_series(layout, "open_interest", "BTC-USDT-SWAP", "1H",
                   d.parse_open_interest_rows([["1717200000000", "1", "2", "3"]], "BTC-USDT-SWAP", "1H"))
    JsonlSink(layout).write([{"ts_ms": 1717200000000, "time": "2024-06-01T00:00:00.000+00:00", "instrument": "BTC-USDT-SWAP",
                              "inst_type": "SWAP", "side": "sell", "pos_side": "long", "bankruptcy_px": 1.0, "size": 2.0,
                              "bankruptcy_loss": 0.0, "ccy": "", "observed_at": "2024-06-01T00:00:01+00:00"}])

    con = connect(layout)
    assert con.execute("SELECT count(*) FROM candles").fetchone()[0] == 10
    assert con.execute("SELECT count(DISTINCT instrument) FROM candles").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM funding_rate").fetchone()[0] == 1
    assert con.execute("SELECT oi_usd FROM open_interest").fetchone()[0] == 3.0
    assert con.execute("SELECT count(*) FROM long_short_ratio").fetchone()[0] == 0
    assert con.execute("SELECT instrument, side FROM liquidations").fetchone() == ("BTC-USDT-SWAP", "sell")

    df = candles_frame(con, "ETH-USDT", "1H", start=T0 + timedelta(hours=1), end=T0 + timedelta(hours=4))
    assert len(df) == 3 and list(df["close"]) == [10.5, 10.5, 10.5]
    assert df["open_time"].is_monotonic_increasing
    con.close()
