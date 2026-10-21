"""Raw source items (PHASE6B_DESIGN section 7.1 fields) and URL canonicalization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"fbclid", "gclid", "igshid", "mkt_tok", "mc_cid", "mc_eid", "ref", "ref_src", "cmpid"}


def canonicalize_url(url: str) -> str:
    """Lower-case scheme/host, drop fragments, tracking params and trailing slashes."""
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        return url
    host = (parts.hostname or "").lower()
    port = parts.port
    if port and not ((parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query, doseq=True), ""))


_MULTI_PART_SUFFIXES = frozenset({"co", "com", "org", "net", "gov", "ac", "edu"})


def registrable_domain(url: str) -> str:
    """The site a URL belongs to: its host's last two labels (three under a
    two-letter country code such as ``co.uk``), or "" when there is no host.

    A subdomain belongs to its site (``uk.reuters.com`` -> ``reuters.com``); a
    look-alike keeps its own (``reuters.com.evil.example`` -> ``evil.example``).
    Source tiers and source families both use this, so they never disagree.
    """
    try:
        host = (urlsplit(url).hostname or "").lower() if url else ""
    except ValueError:  # a malformed URL (e.g. an unbalanced IPv6 bracket) has no site
        return ""
    if host.startswith("www."):
        host = host[4:]
    labels = [p for p in host.split(".") if p]
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _MULTI_PART_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


@dataclass
class RawItem:
    """One item as the source delivered it (before sanitization)."""

    source_id: str
    publisher: str
    publisher_owner: str
    url: str
    title: str
    excerpt: str
    observed_at: datetime
    published_at: Optional[datetime] = None
    category_hints: Tuple[str, ...] = field(default_factory=tuple)
    language: str = "en"
    source_tier: str = "MEDIUM"
    fetch_status: str = "ok"
    http_status: Optional[int] = None
    external_id: str = ""

    @property
    def canonical_url(self) -> str:
        return canonicalize_url(self.url)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["canonical_url"] = self.canonical_url
        d["observed_at"] = self.observed_at.isoformat(timespec="seconds")
        d["published_at"] = self.published_at.isoformat(timespec="seconds") if self.published_at else None
        d["category_hints"] = list(self.category_hints)
        return d
