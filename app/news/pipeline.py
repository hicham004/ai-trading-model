"""One ingestion cycle: fetch -> sanitize -> dedup -> JSONL. Log-only; no LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from app.logging_config import get_logger
from app.news.dedup import SeenStore, content_key, story_key
from app.news.fetch import NewsFetcher
from app.news.sanitize import sanitize_item
from app.news.sources import Source
from app.news.store import NewsStore

logger = get_logger(__name__)


@dataclass
class IngestSummary:
    sources_attempted: int = 0
    sources_ok: int = 0
    sources_skipped: int = 0
    sources_failed: int = 0
    items_fetched: int = 0
    items_new: int = 0
    items_duplicate: int = 0
    items_quarantined: int = 0
    errors: List[str] = field(default_factory=list)

    def line(self) -> str:
        return (
            f"sources ok={self.sources_ok} skipped={self.sources_skipped} failed={self.sources_failed} | "
            f"items fetched={self.items_fetched} new={self.items_new} duplicate={self.items_duplicate} "
            f"quarantined={self.items_quarantined}"
        )


def run_once(
    sources: Sequence[Source],
    fetcher: NewsFetcher,
    store: NewsStore,
    seen: Optional[SeenStore] = None,
    *,
    now: Optional[datetime] = None,
    dry_run: bool = False,
) -> IngestSummary:
    """Fetch every source once and append new sanitized items to the store."""
    now = now or datetime.now(tz=timezone.utc)
    seen = seen or SeenStore(store.seen_file)
    summary = IngestSummary()
    new_records: List[dict] = []
    quarantined: List[dict] = []
    for source in sources:
        summary.sources_attempted += 1
        result = fetcher.fetch(source)
        if not dry_run:
            store.log_fetch(result.log_entry(), when=now)
        if result.status == "skipped":
            summary.sources_skipped += 1
            continue
        if result.status != "ok":
            summary.sources_failed += 1
            summary.errors.append(f"{source.source_id}: {result.status} {result.error}".strip())
            continue
        summary.sources_ok += 1
        for raw in result.items:
            summary.items_fetched += 1
            record = sanitize_item(raw)
            key = content_key(record["canonical_url"], record["publisher"], record["title"])
            record["content_key"] = key
            record["story_key"] = story_key(record["title"], raw.published_at, raw.observed_at)
            if not seen.is_new(key):
                summary.items_duplicate += 1
                continue
            seen.add(key, now)
            if record["quarantined"]:
                summary.items_quarantined += 1
                quarantined.append(record)
            else:
                summary.items_new += 1
                new_records.append(record)
    if not dry_run:
        store.append_records(new_records)
        store.append_records(quarantined, quarantine=True)
        seen.prune(now)
        seen.save()
    logger.info("news ingestion cycle finished", extra={"summary": summary.line()})
    return summary
