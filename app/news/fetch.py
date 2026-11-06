"""Fetch sources and parse them into ``RawItem`` records (no LLM, no exchange).

The HTTP function is injectable so tests never touch the network. Responses
are size-capped, only https URLs are fetched, and the optional NewsAPI.ai key
is passed in the request body by ``sources.newsapi_request`` and never logged.
"""

from __future__ import annotations

import io
import json
import time
from calendar import timegm
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Mapping, Optional, Tuple

import feedparser
import requests

from app.logging_config import get_logger
from app.news.items import RawItem
from app.news.sources import USER_AGENT, Source, article_tier, gdelt_request, newsapi_request

logger = get_logger(__name__)

MAX_RESPONSE_BYTES = 2_000_000
HttpCall = Callable[[str, str, Optional[dict], Optional[dict], dict], Tuple[int, str]]


def default_http(method: str, url: str, params: Optional[dict], json_body: Optional[dict], headers: dict, *, timeout: float = 15.0) -> Tuple[int, str]:
    """GET/POST with a byte cap; returns ``(status_code, text)``."""
    if not url.lower().startswith("https://"):
        raise ValueError("news sources must be fetched over https")
    with requests.request(method, url, params=params, json=json_body, headers=headers, timeout=timeout, stream=True) as resp:
        raw = resp.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError(f"response larger than {MAX_RESPONSE_BYTES} bytes")
        encoding = resp.encoding or "utf-8"
        return resp.status_code, raw.decode(encoding, errors="replace")


@dataclass
class FetchResult:
    source_id: str
    status: str  # ok | http_error | network_error | parse_error | skipped
    http_status: Optional[int]
    fetched_at: datetime
    items: List[RawItem] = field(default_factory=list)
    error: str = ""

    def log_entry(self) -> dict:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "http_status": self.http_status,
            "fetched_at": self.fetched_at.isoformat(timespec="seconds"),
            "items": len(self.items),
            "error": self.error[:300],
        }


def _struct_to_datetime(struct) -> Optional[datetime]:
    if not struct:
        return None
    try:
        return datetime.fromtimestamp(timegm(struct), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def parse_rss(text: str, source: Source, observed_at: datetime) -> List[RawItem]:
    # Always hand feedparser a stream: given a plain string that looks like a URL
    # or a file path, it would fetch that URL or open that local file, so a
    # tampered feed body could make the host read files or call internal addresses.
    parsed = feedparser.parse(
        io.BytesIO((text or "").encode("utf-8")),
        response_headers={"content-type": "application/rss+xml; charset=utf-8"},
    )
    items: List[RawItem] = []
    for entry in parsed.get("entries", []):
        title = str(entry.get("title") or "").strip()
        link = str(entry.get("link") or "").strip()
        if not title and not link:
            continue
        excerpt = str(entry.get("summary") or entry.get("description") or "")
        published = _struct_to_datetime(entry.get("published_parsed") or entry.get("updated_parsed"))
        items.append(
            RawItem(
                source_id=source.source_id,
                publisher=source.publisher,
                publisher_owner=source.publisher_owner,
                url=link,
                title=title,
                excerpt=excerpt,
                observed_at=observed_at,
                published_at=published,
                category_hints=source.category_hints,
                language=str(parsed.get("feed", {}).get("language") or source.language)[:8],
                source_tier=source.tier,
                external_id=str(entry.get("id") or ""),
            )
        )
    return items


def _parse_gdelt_date(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def parse_gdelt(text: str, source: Source, observed_at: datetime) -> List[RawItem]:
    payload = json.loads(text) if text.strip() else {}
    if not isinstance(payload, dict):
        raise ValueError("GDELT payload was not a JSON object")
    items: List[RawItem] = []
    for article in payload.get("articles") or []:
        if not isinstance(article, dict):
            continue
        url = str(article.get("url") or "")
        title = str(article.get("title") or "")
        if not url and not title:
            continue
        items.append(
            RawItem(
                source_id=source.source_id,
                publisher=str(article.get("domain") or "unknown"),
                publisher_owner="",
                url=url,
                title=title,
                excerpt="",
                observed_at=observed_at,
                published_at=_parse_gdelt_date(str(article.get("seendate") or "")),
                category_hints=source.category_hints,
                language=str(article.get("language") or source.language)[:16],
                source_tier=article_tier(source, url),
            )
        )
    return items


def parse_newsapi_ai(text: str, source: Source, observed_at: datetime) -> List[RawItem]:
    payload = json.loads(text) if text.strip() else {}
    results = ((payload.get("articles") or {}).get("results")) if isinstance(payload, dict) else None
    items: List[RawItem] = []
    for article in results or []:
        if not isinstance(article, dict):
            continue
        published = None
        raw_date = article.get("dateTimePub") or article.get("dateTime")
        if isinstance(raw_date, str) and raw_date:
            try:
                published = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                published = None
        src = article.get("source") or {}
        url = str(article.get("url") or "")
        items.append(
            RawItem(
                source_id=source.source_id,
                publisher=str(src.get("title") or src.get("uri") or "unknown"),
                publisher_owner="",
                url=url,
                title=str(article.get("title") or ""),
                excerpt=str(article.get("body") or "")[:2000],
                observed_at=observed_at,
                published_at=published,
                category_hints=source.category_hints,
                language=str(article.get("lang") or source.language)[:8],
                source_tier=article_tier(source, url),
                external_id=str(article.get("uri") or ""),
            )
        )
    return items


class NewsFetcher:
    def __init__(
        self,
        http: Optional[HttpCall] = None,
        *,
        env: Optional[Mapping[str, str]] = None,
        gdelt_query: Optional[str] = None,
        now: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
        min_gap_seconds: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http or default_http
        self._env = env
        self._gdelt_query = gdelt_query
        self._now = now
        self._min_gap = float(min_gap_seconds)
        self._sleep = sleep
        self._clock = clock
        self._last_request: Optional[float] = None

    def _throttle(self) -> None:
        if self._last_request is not None:
            elapsed = self._clock() - self._last_request
            if elapsed < self._min_gap:
                self._sleep(self._min_gap - elapsed)
        self._last_request = self._clock()

    def fetch(self, source: Source) -> FetchResult:
        observed = self._now()
        headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, application/json, text/xml;q=0.9, */*;q=0.5"}
        if not source.enabled or not source.url:
            return FetchResult(source.source_id, "skipped", None, observed, error="source disabled or has no URL")
        try:
            if source.kind == "rss":
                self._throttle()
                status, text = self._http("GET", source.url, None, None, headers)
                parser = parse_rss
            elif source.kind == "gdelt":
                url, params = gdelt_request(source, **({"query": self._gdelt_query} if self._gdelt_query else {}))
                self._throttle()
                status, text = self._http("GET", url, params, None, headers)
                parser = parse_gdelt
            else:  # newsapi_ai
                request = newsapi_request(source, self._env)
                if request is None:
                    return FetchResult(source.source_id, "skipped", None, observed, error="no API key configured")
                url, body = request
                self._throttle()
                status, text = self._http("POST", url, None, body, headers)
                parser = parse_newsapi_ai
        except Exception as exc:  # network layer
            logger.warning("news fetch failed", extra={"source_id": source.source_id, "error": str(exc)[:200]})
            return FetchResult(source.source_id, "network_error", None, observed, error=f"{type(exc).__name__}: {exc}")
        if status == 429 and source.kind != "newsapi_ai":
            # Rate limited (GDELT enforces one request per 5 s per IP): wait one
            # gap and retry exactly once; never hammer a public service.
            try:
                self._sleep(self._min_gap)
                self._last_request = self._clock()
                if source.kind == "rss":
                    status, text = self._http("GET", source.url, None, None, headers)
                else:
                    url, params = gdelt_request(source, **({"query": self._gdelt_query} if self._gdelt_query else {}))
                    status, text = self._http("GET", url, params, None, headers)
            except Exception as exc:
                return FetchResult(source.source_id, "network_error", None, observed, error=f"{type(exc).__name__}: {exc}")
        if status != 200:
            return FetchResult(source.source_id, "http_error", status, observed, error=f"HTTP {status}")
        try:
            items = parser(text, source, observed)
        except Exception as exc:
            return FetchResult(source.source_id, "parse_error", status, observed, error=f"{type(exc).__name__}: {exc}")
        return FetchResult(source.source_id, "ok", status, observed, items=items)
