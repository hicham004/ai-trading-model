"""Research data lake (Sprint 1): Parquet + JSONL files over PUBLIC OKX data.

Scope and safety
----------------
- PUBLIC endpoints only: spot candles (``/market/candles``,
  ``/market/history-candles``), SWAP derivatives statistics (funding rate,
  open interest, long/short account ratio, taker volume) and the public
  ``liquidation-orders`` WebSocket channel. Nothing here authenticates,
  signs, or reaches an account, order, or withdrawal endpoint.
- Derivatives data are *feature inputs* for research only. This project does
  not trade swaps, margin, or derivatives (see ``PROJECT_RULES.md``).
- Storage is local files under ``data/lake`` (git-ignored). The runtime
  PostgreSQL tables are untouched; DuckDB views are read-only over the files.
- Nothing in this package is imported by the execution, risk, or exchange
  modules; it cannot influence an order.
"""
