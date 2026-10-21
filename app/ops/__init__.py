"""Operations tooling (plan row R6; master plan sections 5.4 and 9) — observability only.

- ``digest``: a plain-English daily digest of the Phase 6a shadow, the news
  shadow, the fleet of paper accounts and the OKX changelog watcher, built from
  the files those services already write, and sent through the existing
  Telegram notifier.
- ``digest_ai``: an optional short Claude summary on top of that digest, only
  when ``ANTHROPIC_API_KEY`` is set; the deterministic digest is always sent.
- ``okx_changelog`` and ``okx_usage``: a daily watcher of OKX's public API
  changelog that flags new or edited entries mentioning a host, port, REST
  path, WebSocket channel or authentication detail this repository uses (the
  port-8443 kind of change).

Nothing here can place, size, approve, modify or cancel an order. It reads files
and one public web page, holds no exchange keys, never opens the demo database,
and nothing in the trading runtime imports it, so it cannot block or delay an
exit, a protective stop, the kill switch or reconciliation.
"""
