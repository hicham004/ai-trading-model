"""Source allowlist for the news-ingestion skeleton (PHASE6B_DESIGN sections 3, 8).

Only the v1 watchlist categories. Sources are official or high-quality public
feeds; nothing here scrapes social media. Disabled entries record a URL that
still needs operator confirmation (checked 2026-10-20) and are skipped.

A source's tier is the tier of the articles it publishes. An aggregator (GDELT,
NewsAPI.ai) only finds articles, so its hits take the tier of the outlet whose
site they are on: HIGH for the owner's HIGH outlets, otherwise the aggregator's
MEDIUM (``article_tier``).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import unquote, urlsplit

from app.news.items import registrable_domain

CATEGORIES: Tuple[str, ...] = (
    "ETF_SEC_DECISION",
    "FED_FOMC_RATES",
    "MACRO_CPI_PPI_JOBS",
    "EXCHANGE_HACK_EXPLOIT",
    "MAJOR_REGULATORY_ACTION",
    "LIQUIDATION_CASCADE",
    "GEOPOLITICAL_ESCALATION",
    "MAJOR_EXCHANGE_PROTOCOL_INCIDENT",
)

NEWSAPI_AI_KEY_ENV = "NEWSAPI_AI_KEY"
GDELT_DEFAULT_QUERY = (
    '(bitcoin OR ethereum OR "crypto exchange" OR stablecoin OR "SEC ETF" OR FOMC) sourcelang:english'
)
USER_AGENT = "ai-trading-model-news-ingest/0.1 (research; log-only; +https://github.com/hicham004/ai-trading-model)"

# The owner's HIGH outlets (decision of 2026-10-21): Reuters, AP, Bloomberg, Dow
# Jones/WSJ (one owner family) and the Financial Times, by the sites they publish
# on. Subdomains count (``uk.reuters.com``); look-alikes do not. Dow Jones's
# Barron's and MarketWatch stay MEDIUM. Which outlets are one source family is
# decided in ``corroborate`` (Dow Jones's four brands always are).
HIGH_TIER_DOMAINS: Mapping[str, str] = MappingProxyType(
    {
        "reuters.com": "Reuters",
        "apnews.com": "Associated Press",
        "bloomberg.com": "Bloomberg",
        "wsj.com": "The Wall Street Journal (Dow Jones)",
        "dowjones.com": "Dow Jones Newswires",
        "ft.com": "Financial Times",
    }
)
# Pages on those sites that are not the outlet's own reporting (paid press releases,
# the company's own press room, sponsored, partner and branded content, company
# announcements) are not HIGH. Matched on the decoded path, one segment at a time.
_NOT_REPORTING_PATH = re.compile(
    r"/(?:press|press-?(?:releases?|room)|sponsored(?:-?content)?|partner-?content|brand-?features?|plus"
    r"|advertorials?|paid-?posts?|announce(?:ments?)?)(?:/|$)",
    re.I,
)
_NOT_REPORTING_HOSTS = ("partners.", "sponsored.")
_PLAIN_HOST = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")
AGGREGATOR_KINDS = frozenset({"gdelt", "newsapi_ai"})


@dataclass(frozen=True)
class Source:
    source_id: str
    publisher: str
    publisher_owner: str
    kind: str  # "rss" | "gdelt" | "newsapi_ai"
    url: str
    category_hints: Tuple[str, ...]
    tier: str  # OFFICIAL | HIGH | MEDIUM
    language: str = "en"
    enabled: bool = True
    note: str = ""
    min_interval_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.kind not in ("rss", "gdelt", "newsapi_ai"):
            raise ValueError(f"unknown source kind {self.kind!r}")
        for hint in self.category_hints:
            if hint not in CATEGORIES:
                raise ValueError(f"unknown category hint {hint!r}")
        if self.url and not self.url.lower().startswith("https://"):
            raise ValueError("sources must be fetched over https")


DEFAULT_SOURCES: Tuple[Source, ...] = (
    Source(
        "sec_press",
        "U.S. Securities and Exchange Commission",
        "U.S. Government",
        "rss",
        "https://www.sec.gov/news/pressreleases.rss",
        ("ETF_SEC_DECISION", "MAJOR_REGULATORY_ACTION"),
        "OFFICIAL",
        note="sec.gov requires a descriptive User-Agent (sent by default).",
    ),
    Source(
        "fed_press_monetary",
        "Board of Governors of the Federal Reserve System",
        "U.S. Government",
        "rss",
        "https://www.federalreserve.gov/feeds/press_monetary.xml",
        ("FED_FOMC_RATES",),
        "OFFICIAL",
    ),
    Source(
        "bls_latest",
        "U.S. Bureau of Labor Statistics",
        "U.S. Government",
        "rss",
        "https://www.bls.gov/feed/bls_latest.rss",
        ("MACRO_CPI_PPI_JOBS",),
        "OFFICIAL",
        enabled=False,
        note="bls.gov answered HTTP 403 to a scripted fetch on 2026-10-20; enable once an accepted access method is confirmed.",
    ),
    Source(
        "coinbase_status",
        "Coinbase Status",
        "Coinbase",
        "rss",
        "https://status.coinbase.com/history.rss",
        ("MAJOR_EXCHANGE_PROTOCOL_INCIDENT",),
        "OFFICIAL",
    ),
    Source(
        "okx_status",
        "OKX Status",
        "OKX",
        "rss",
        "",
        ("MAJOR_EXCHANGE_PROTOCOL_INCIDENT",),
        "OFFICIAL",
        enabled=False,
        note="No public RSS endpoint confirmed on 2026-10-20; operator to supply the status feed URL.",
    ),
    Source(
        "binance_status",
        "Binance Announcements",
        "Binance",
        "rss",
        "",
        ("MAJOR_EXCHANGE_PROTOCOL_INCIDENT",),
        "OFFICIAL",
        enabled=False,
        note="No public RSS endpoint confirmed on 2026-10-20; operator to supply.",
    ),
    Source(
        "gdelt_doc",
        "GDELT Project (DOC 2.0 API)",
        "GDELT",
        "gdelt",
        "https://api.gdeltproject.org/api/v2/doc/doc",
        CATEGORIES,
        "MEDIUM",
        note="Free; GDELT asks for at most one request every 5 seconds.",
        min_interval_seconds=300.0,
    ),
    Source(
        "newsapi_ai",
        "NewsAPI.ai (Event Registry)",
        "Event Registry",
        "newsapi_ai",
        "https://eventregistry.org/api/v1/article/getArticles",
        CATEGORIES,
        "MEDIUM",
        enabled=False,
        note=f"Optional paid/free-tier API; needs {NEWSAPI_AI_KEY_ENV} in the environment and operator cost approval.",
        min_interval_seconds=900.0,
    ),
)


def get_sources(
    ids: Optional[Iterable[str]] = None,
    *,
    include_disabled: bool = False,
    sources: Sequence[Source] = DEFAULT_SOURCES,
) -> List[Source]:
    wanted = set(ids) if ids is not None else None
    out = []
    for source in sources:
        if wanted is not None and source.source_id not in wanted:
            continue
        if not source.enabled and not include_disabled:
            continue
        out.append(source)
    if wanted is not None:
        unknown = wanted - {s.source_id for s in sources}
        if unknown:
            raise ValueError(f"unknown source id(s): {sorted(unknown)}")
    return out


def high_outlet(url: str) -> Optional[str]:
    """The HIGH outlet whose own reporting ``url`` is, else None.

    Only a plain http(s) URL with an ASCII host counts: no backslash, user-info or
    bad port, which URL parsers read differently, and no third-party section of
    the site (press releases and press rooms, sponsored, partner or branded pages).
    """
    url = url or ""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".")
        parts.port  # raises ValueError for a port that is not a number in range
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or "\\" in url or "@" in parts.netloc:
        return None
    if not _PLAIN_HOST.fullmatch(host) or host.startswith(_NOT_REPORTING_HOSTS) or _NOT_REPORTING_PATH.search(unquote(parts.path)):
        return None
    return HIGH_TIER_DOMAINS.get(registrable_domain(url))


def article_tier(source: Source, url: str) -> str:
    """The tier of one article ``source`` delivered, from the article's own URL.

    An aggregator hit on a HIGH outlet's own reporting (``high_outlet``) is HIGH;
    every other aggregator hit keeps the aggregator's MEDIUM, and a feed's own
    articles keep the feed's tier. An aggregator the operator rated LOW or UNKNOWN
    stays switched off: only a MEDIUM aggregator's hits are raised.
    """
    if source.kind in AGGREGATOR_KINDS and source.tier == "MEDIUM" and high_outlet(url):
        return "HIGH"
    return source.tier


def gdelt_request(source: Source, *, query: str = GDELT_DEFAULT_QUERY, timespan: str = "1h", max_records: int = 75) -> Tuple[str, dict]:
    """URL + query parameters for a GDELT DOC 2.0 article list (JSON)."""
    return source.url, {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "timespan": timespan,
        "maxrecords": str(int(max_records)),
        "sort": "DateDesc",
    }


def newsapi_request(
    source: Source, env: Optional[Mapping[str, str]] = None, *, keywords: Sequence[str] = ("bitcoin", "ethereum", "crypto exchange"), max_items: int = 50
) -> Optional[Tuple[str, dict]]:
    """URL + JSON body for Event Registry's getArticles, or None when no key is configured.

    The key travels only in the request body and must never be logged.
    """
    env = os.environ if env is None else env
    key = (env.get(NEWSAPI_AI_KEY_ENV) or "").strip()
    if not key:
        return None
    return source.url, {
        "action": "getArticles",
        "keyword": list(keywords),
        "keywordOper": "or",
        "lang": "eng",
        "articlesPage": 1,
        "articlesCount": int(max_items),
        "articlesSortBy": "date",
        "resultType": "articles",
        "apiKey": key,
    }
