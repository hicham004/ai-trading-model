"""Read-only DuckDB views over the lake files (research convenience).

``connect(layout)`` returns an in-memory DuckDB connection with these views:

- ``candles``          all spot candles (instrument, timeframe, open_time, OHLCV, confirmed)
- ``funding_rate``, ``open_interest``, ``long_short_ratio``, ``taker_volume``
- ``liquidations``     JSON-lines liquidation records

A view over a glob that matches no file is created empty with the right
schema, so queries never fail on a fresh lake.
"""

from __future__ import annotations

import glob
from datetime import datetime
from typing import Optional

import duckdb
import pandas as pd
import pyarrow as pa

from app.datalake.derivatives import SCHEMAS
from app.datalake.layout import SERIES_KINDS, LakeLayout
from app.datalake.parquet_store import CANDLE_SCHEMA, TS_TYPE

LIQUIDATION_SCHEMA = pa.schema(
    [
        ("ts_ms", pa.int64()),
        ("time", pa.string()),
        ("instrument", pa.string()),
        ("inst_type", pa.string()),
        ("side", pa.string()),
        ("pos_side", pa.string()),
        ("bankruptcy_px", pa.float64()),
        ("size", pa.float64()),
        ("bankruptcy_loss", pa.float64()),
        ("ccy", pa.string()),
        ("observed_at", pa.string()),
    ]
)


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _create_view(con: duckdb.DuckDBPyConnection, name: str, pattern: str, reader_sql: str, schema: pa.Schema) -> None:
    if glob.glob(pattern):
        con.execute(f"CREATE OR REPLACE VIEW {name} AS {reader_sql}")
    else:
        empty = schema.empty_table()
        con.register(f"_empty_{name}", empty)
        con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM _empty_{name}")


def connect(layout: LakeLayout, *, database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    """Open DuckDB with views over every lake dataset (missing datasets are empty)."""
    con = duckdb.connect(database)
    pattern = layout.candles_glob()
    _create_view(
        con,
        "candles",
        pattern,
        f"SELECT * FROM read_parquet({_sql_str(pattern)}, union_by_name=true)",
        CANDLE_SCHEMA,
    )
    for kind in SERIES_KINDS:
        pattern = layout.series_glob(kind)
        _create_view(
            con,
            kind,
            pattern,
            f"SELECT * FROM read_parquet({_sql_str(pattern)}, union_by_name=true)",
            SCHEMAS[kind],
        )
    pattern = layout.liquidations_glob()
    _create_view(
        con,
        "liquidations",
        pattern,
        f"SELECT * FROM read_json_auto({_sql_str(pattern)}, format='newline_delimited', union_by_name=true)",
        LIQUIDATION_SCHEMA,
    )
    return con


def candles_frame(
    con: duckdb.DuckDBPyConnection,
    instrument: str,
    timeframe: str,
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> pd.DataFrame:
    """Candles for one series as a pandas frame ordered by ``open_time``."""
    sql = "SELECT * FROM candles WHERE instrument = ? AND timeframe = ?"
    params: list = [instrument, timeframe]
    if start is not None:
        sql += " AND open_time >= ?"
        params.append(start)
    if end is not None:
        sql += " AND open_time < ?"
        params.append(end)
    sql += " ORDER BY open_time"
    return con.execute(sql, params).df()


__all__ = ["connect", "candles_frame", "LIQUIDATION_SCHEMA", "TS_TYPE"]
