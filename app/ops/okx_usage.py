"""What this repository uses of OKX's API, as the changelog watcher's watch list (plan row R6).

Each ``WatchItem`` names one host, port, REST endpoint, WebSocket channel or
authentication detail that code in this repository depends on, with the ways an
OKX changelog entry can refer to it:

- ``text``: a regular expression over the entry's prose (code examples in
  ``<pre>`` blocks are not prose and are not searched);
- ``code``: an exact inline ``<code>`` token, e.g. ``orders`` (the bare word
  "orders" in prose would match almost every entry);
- ``anchor``: a link into the API reference, e.g.
  ``/docs-v5/en/#order-book-trading-market-data-get-candlesticks``. OKX entries
  usually link the endpoint they change rather than spell its path. Every anchor
  below was checked against https://www.okx.com/docs-v5/en/ on 2026-10-22.

The list errs toward flagging: a false alarm costs one message that a human
reads, a missed change can blind the system (the port-8443 shutdown was
announced on the changelog). ``tests/test_okx_changelog.py`` keeps it in step
with the code: every REST path and OKX host written in ``app/``, ``research/``
and ``scripts/`` must appear here. Items marked "Sprint 3" are used by the
exchange-side stop on its own branch (not merged yet), and items marked
"research" by the data lake and the fleet of paper accounts (public data only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import FrozenSet, Pattern, Tuple

CATEGORIES = ("port", "host", "path", "channel", "auth")
KINDS = ("text", "code", "anchor")


@dataclass(frozen=True)
class WatchItem:
    """One thing this repository uses; ``patterns`` are ``(kind, pattern)`` pairs."""

    category: str
    label: str
    patterns: Tuple[Tuple[str, str], ...]
    used_by: str = ""

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown watch category {self.category!r}")
        if not self.patterns:
            raise ValueError(f"watch item {self.label!r} has no pattern")
        for kind, pattern in self.patterns:
            if kind not in KINDS:
                raise ValueError(f"unknown pattern kind {kind!r} in {self.label!r}")
            if kind != "code":
                re.compile(pattern)

    def regexes(self, kind: str) -> Tuple[Pattern[str], ...]:
        flags = re.IGNORECASE if self.category == "auth" else 0
        return tuple(re.compile(p, flags) for k, p in self.patterns if k == kind)

    def tokens(self) -> Tuple[str, ...]:
        return tuple(p for k, p in self.patterns if k == "code")


def _path(path: str) -> str:
    """A REST or WebSocket path, not followed by more path characters (``/trade/order`` is not ``/trade/order-algo``)."""
    return re.escape(path) + r"(?![\w\-])"


def _host(host: str) -> str:
    """A host name not embedded in a longer one (``aws.okx.com`` is not ``wsaws.okx.com``)."""
    return r"(?<![\w.\-])" + re.escape(host) + r"(?![\w\-])"


def _anchor(fragment: str) -> str:
    """A link into the API reference; ``get-candlesticks`` is not ``get-candlesticks-history``."""
    return r"#" + re.escape(fragment) + r"(?![\w\-])"


def _rest(method: str, path: str, anchor: str, used_by: str) -> WatchItem:
    return WatchItem("path", f"{method} {path}", (("text", _path(path)), ("code", path), ("anchor", _anchor(anchor))), used_by)


_KEY_RULE = r"\b(?:permissions?|perm|IP|bind\w*|bound|expir\w*|passphrase|whitelist\w*|allowlist\w*|read[ _-]?only|revok\w*|disabl\w*)\b"


def _channel(name: str, anchor: str, used_by: str) -> WatchItem:
    return WatchItem("channel", f"WebSocket channel {name}", (("code", name), ("anchor", _anchor(anchor))), used_by)


WATCH_ITEMS: Tuple[WatchItem, ...] = (
    # -- ports: every WebSocket URL here is port-less since Sprint 0 (port 443) --------------------------
    WatchItem("port", "port 8443", (("text", r"(?<![\w.])8443(?!\w)"),), "every WebSocket URL until Sprint 0"),
    WatchItem("port", "port 443", (("text", r"(?<![\w.]):443(?!\d)"), ("text", r"\bport 443\b")), "every WebSocket and REST URL"),
    # -- hosts -----------------------------------------------------------------------------------------------
    WatchItem("host", "host www.okx.com", (("text", _host("www.okx.com")),), "public REST, demo REST, this watcher"),
    WatchItem("host", "host aws.okx.com", (("text", _host("aws.okx.com")),), "approved demo REST host"),
    WatchItem("host", "host ws.okx.com", (("text", _host("ws.okx.com")),), "public market-data WebSocket"),
    WatchItem("host", "host wspap.okx.com", (("text", _host("wspap.okx.com")),), "demo private WebSocket"),
    WatchItem("host", "WebSocket path /ws/v5/public", (("text", _path("/ws/v5/public")),), "public market data, liquidations"),
    WatchItem("host", "WebSocket path /ws/v5/business", (("text", _path("/ws/v5/business")),), "public candles"),
    WatchItem("host", "WebSocket path /ws/v5/private", (("text", _path("/ws/v5/private")),), "demo orders channel"),
    # -- REST endpoints: public market data ----------------------------------------------------------------
    _rest("GET", "/api/v5/market/candles", "order-book-trading-market-data-get-candlesticks", "candles, news shadow, paper accounts"),
    _rest("GET", "/api/v5/market/history-candles", "order-book-trading-market-data-get-candlesticks-history", "history backfill, paper accounts"),
    _rest("GET", "/api/v5/public/time", "public-data-rest-api-get-system-time", "demo clock check, news shadow clock check"),
    _rest("GET", "/api/v5/public/instruments", "public-data-rest-api-get-instruments", "demo lot and tick sizes"),
    _rest("GET", "/api/v5/public/funding-rate", "public-data-rest-api-get-funding-rate", "research: positioning data"),
    _rest("GET", "/api/v5/public/funding-rate-history", "public-data-rest-api-get-funding-rate-history", "research: positioning data"),
    _rest("GET", "/api/v5/public/open-interest", "public-data-rest-api-get-open-interest", "research: positioning data"),
    _rest("GET", "/api/v5/rubik/stat/contracts/open-interest-history",
          "trading-statistics-rest-api-get-contract-open-interest-history", "research: positioning data"),
    _rest("GET", "/api/v5/rubik/stat/contracts/long-short-account-ratio-contract",
          "trading-statistics-rest-api-get-contract-long-short-ratio", "research: positioning data"),
    _rest("GET", "/api/v5/rubik/stat/taker-volume-contract", "trading-statistics-rest-api-get-contract-taker-volume",
          "research: positioning data"),
    # -- REST endpoints: demo account and trading (always x-simulated-trading: 1) ------------------------
    _rest("GET", "/api/v5/account/config", "trading-account-rest-api-get-account-configuration", "demo account checks"),
    _rest("GET", "/api/v5/account/balance", "trading-account-rest-api-get-balance", "demo reconciliation"),
    _rest("GET", "/api/v5/account/trade-fee", "trading-account-rest-api-get-fee-rates", "demo fee rates"),
    _rest("GET", "/api/v5/trade/order", "order-book-trading-trade-get-order-details", "demo order lookup"),
    _rest("GET", "/api/v5/trade/orders-pending", "order-book-trading-trade-get-order-list", "demo reconciliation"),
    _rest("GET", "/api/v5/trade/orders-history", "order-book-trading-trade-get-order-history-last-7-days", "demo reconciliation"),
    _rest("GET", "/api/v5/trade/fills", "order-book-trading-trade-get-transaction-details-last-3-days", "demo fills"),
    _rest("POST", "/api/v5/trade/order", "order-book-trading-trade-post-place-order", "demo order placement"),
    _rest("POST", "/api/v5/trade/cancel-order", "order-book-trading-trade-post-cancel-order", "demo order cancel"),
    _rest("POST", "/api/v5/trade/amend-order", "order-book-trading-trade-post-amend-order", "demo order amend"),
    _rest("POST", "/api/v5/trade/order-algo", "order-book-trading-algo-trading-post-place-algo-order", "Sprint 3: exchange-side stop"),
    _rest("POST", "/api/v5/trade/cancel-algos", "order-book-trading-algo-trading-post-cancel-algo-order", "Sprint 3: exchange-side stop"),
    _rest("POST", "/api/v5/trade/amend-algos", "order-book-trading-algo-trading-post-amend-algo-order", "Sprint 3: exchange-side stop"),
    _rest("GET", "/api/v5/trade/order-algo", "order-book-trading-algo-trading-get-algo-order-details", "Sprint 3: exchange-side stop"),
    _rest("GET", "/api/v5/trade/orders-algo-pending", "order-book-trading-algo-trading-get-algo-order-list", "Sprint 3: exchange-side stop"),
    _rest("GET", "/api/v5/trade/orders-algo-history", "order-book-trading-algo-trading-get-algo-order-history",
          "Sprint 3: exchange-side stop"),
    # -- WebSocket channels ------------------------------------------------------------------------------
    WatchItem("channel", "WebSocket channel candle1H", (("text", r"\bcandle1H\b"), ("anchor", _anchor("order-book-trading-market-data-ws-candlesticks-channel"))),
              "the Phase 6a 1H strategy"),
    WatchItem("channel", "WebSocket channel candle1m", (("text", r"\bcandle1m\b"),), "Phase 5 demo history, live data"),
    _channel("tickers", "order-book-trading-market-data-ws-tickers-channel", "live market data"),
    _channel("trades", "order-book-trading-market-data-ws-trades-channel", "live market data"),
    _channel("books", "order-book-trading-market-data-ws-order-book-channel", "live market data"),
    _channel("orders", "order-book-trading-trade-ws-order-channel", "demo order updates"),
    _channel("orders-algo", "order-book-trading-algo-trading-ws-algo-orders-channel", "Sprint 3: exchange-side stop"),
    _channel("liquidation-orders", "public-data-websocket-liquidation-orders-channel", "research: liquidation features"),
    # -- authentication and the demo environment ----------------------------------------------------------
    WatchItem("auth", "demo header x-simulated-trading", (("text", r"x-simulated-trading"),), "every demo request"),
    WatchItem("auth", "REST signing headers OK-ACCESS-*", (("text", r"\bOK-ACCESS-(?:KEY|SIGN|TIMESTAMP|PASSPHRASE)\b"),
                                                          ("anchor", _anchor("overview-rest-authentication")),
                                                          ("anchor", _anchor("overview-rest-authentication-making-requests")),
                                                          ("anchor", _anchor("overview-rest-authentication-signature"))), "demo REST"),
    WatchItem("auth", "WebSocket login", (("code", "login"), ("anchor", _anchor("overview-websocket-login"))), "demo private WebSocket"),
    WatchItem("auth", "demo trading environment", (("text", r"\bdemo trading\b"), ("text", r"\bsimulated trading\b"),
                                                   ("anchor", _anchor("overview-demo-trading-services"))), "the whole demo path"),
    # "API key" alone is everywhere (sub-account and broker endpoints): only a sentence that ties a key to
    # its permissions, IP binding, expiry or passphrase counts.
    WatchItem("auth", "API key rules", (("text", r"\bAPI ?keys?\b(?! (?:of|for) a sub-account)[^.;]{0,80}?" + _KEY_RULE),
                                        ("text", _KEY_RULE + r"[^.;]{0,80}?\bAPI ?keys?\b(?! (?:of|for) a sub-account)"),
                                        ("text", r"\bpassphrase\b"),
                                        ("anchor", _anchor("overview-api-key-creation")),
                                        ("anchor", _anchor("overview-api-key-creation-api-key-permissions")),
                                        ("anchor", _anchor("overview-api-key-creation-api-key-security"))), "demo keys"),
    WatchItem("auth", "IP binding of keys", (("text", r"\bIP (?:address(?:es)? )?(?:whitelist|allowlist|allow-list|binding|bind)"),
                                             ("text", r"\b(?:bound|bind|binding|linked) (?:to|with) (?:an |the |your )?IP\b"),
                                             ("text", r"(?<!\d)50110(?!\d)")),
              "demo keys are bound to the VPS address (error 50110)"),
)

# Impact wording: ranks a flagged entry, never flags one on its own.
IMPACT_RE = re.compile(
    r"\b(?:deprecat\w*|decommission\w*|discontinu\w*|no longer(?! than)|will be removed|removal|sunset\w*|retir(?:e|ed|ing)|"
    r"breaking change|stop(?:s|ped)? (?:accepting|supporting)|will fail|offline|migrat\w*)\b",
    re.IGNORECASE,
)


def used_rest_paths() -> FrozenSet[str]:
    return frozenset(item.label.split(" ", 1)[1] for item in WATCH_ITEMS if item.category == "path")


def used_hosts() -> FrozenSet[str]:
    return frozenset(item.label.split(" ", 1)[1] for item in WATCH_ITEMS if item.label.startswith("host "))


def used_channels() -> FrozenSet[str]:
    return frozenset(item.label.rsplit(" ", 1)[1] for item in WATCH_ITEMS if item.category == "channel")
