# News-ingestion skeleton (Phase 6b design §7.1–7.3) — log-only, no LLM

Status: data plumbing only. This implements source ingestion, sanitization and
de-duplication from `docs/PHASE6B_DESIGN.md` and writes JSON lines under
`data/news` (git-ignored). It makes **no LLM call**, produces **no event, no
action and no risk effect**, reads no exchange or demo-account state, and is
not imported by any trading module (`tests/test_news_ingest.py` enforces the
import boundary). Classification, corroboration, TTL/decay and the risk
overlay are **not built**; they need the owner's explicit go-ahead.

Governance note (for the owner): `CLAUDE.md` still records Phase 6b as "designed
but NOT authorized" while `docs/AUDIT_2026-10-20.md` records an owner
authorization on June 30 (issue #12). This skeleton was built as Sprint 1
deliverable 5 of the master plan; if the owner considers it premature, the
commit is self-contained and can be dropped without touching the data lake.

## What runs

```bash
python scripts/ingest_news.py --list-sources
python scripts/ingest_news.py --once --dry-run          # fetch + report, write nothing
python scripts/ingest_news.py --once                    # one cycle -> data/news
python scripts/ingest_news.py --loop --interval 900     # every 15 min (cron is fine too)
```

Pipeline per cycle (`app/news/pipeline.py`): fetch each enabled source →
parse to `RawItem` (§7.1 fields: source, publisher, owner, url, canonical url,
published/observed time, title, excerpt, category hints, language, fetch
status) → `sanitize_item` → dedup on `content_key` → append.

## Sources (`app/news/sources.py`)

| id | kind | tier | state (2026-10-20) |
|---|---|---|---|
| `sec_press` | RSS | OFFICIAL | enabled; sec.gov needs a descriptive User-Agent (sent) |
| `fed_press_monetary` | RSS | OFFICIAL | enabled |
| `coinbase_status` | RSS | OFFICIAL | enabled |
| `gdelt_doc` | GDELT DOC 2.0 JSON | MEDIUM | enabled; GDELT allows one request per 5 s (throttled) |
| `bls_latest` | RSS | OFFICIAL | disabled: bls.gov answered 403 to a scripted fetch |
| `okx_status`, `binance_status` | RSS | OFFICIAL | disabled: no public RSS URL confirmed; operator to supply |
| `newsapi_ai` | Event Registry API | MEDIUM | disabled: optional; needs `NEWSAPI_AI_KEY` and cost approval |

Sources must be `https://`; category hints must be v1 watchlist categories.
The optional NewsAPI.ai key is read from the environment, sent only in the
request body and never logged or stored.

## Sanitization (`app/news/sanitize.py`)

Strip HTML/script/style; NFKC normalize; remove zero-width, bidirectional
override and control characters; collapse whitespace; cap title (300) and
excerpt (1000) length; keep SHA-256 of the original and sanitized text.
Flags: `html_stripped`, `unicode_normalized`, `zero_width_removed`,
`bidi_controls_removed`, `control_chars_removed`, `truncated`,
`homoglyph_suspect` (Latin mixed with Cyrillic/Greek/Armenian inside one
token), `prompt_injection_suspect` (instruction-like markers such as "ignore
previous instructions", "system prompt", chat-template tokens, or text that
names the risk actions). Severe flags (`prompt_injection_suspect`,
`homoglyph_suspect`, `bidi_controls_removed`) send the item to
`data/news/quarantine/` instead of `raw/`. Flags are recorded, never acted on.

## Dedup (`app/news/dedup.py`)

`content_key` = SHA-256 of the canonical URL (tracking parameters and
fragments removed), else publisher + normalized title. `story_key` = normalized
title + UTC day, a crude same-story bucket for the log; the full story model
(entities, category, assets, source family) belongs to the unbuilt classifier
stage. The seen-set (`data/news/_state/seen.json`) is pruned at 14 days /
100k keys.

## Files

```
data/news/raw/<YYYY-MM-DD>.jsonl          sanitized items
data/news/quarantine/<YYYY-MM-DD>.jsonl   severe-flag items
data/news/_fetch_log/<YYYY-MM-DD>.jsonl   one line per source fetch (status, HTTP code, counts)
data/news/_state/seen.json                dedup state
```

Override the root with `NEWS_DATA_DIR`.

## Not in scope here

Haiku/Opus classification, structured outputs, corroboration with web
search, TTL/decay, the deterministic overlay, the eval set, and any
connection to the risk manager. See `docs/PHASE6B_DESIGN.md` §7.4–§13 and
the master plan Sprint 4.
