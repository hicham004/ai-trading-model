# News agent (Phase 6b) — ingestion skeleton and agent core, log-only

Status: Phase 6b is authorized for **log-only** operation (owner, June 30,
2026, GitHub issue #12; reconfirmed October 20, 2026). Using news to gate demo
or live entries is **not** authorized and needs a separate owner decision.

- **Ingestion** (Sprint 1, design §7.1–7.3, this page's first half): source
  ingestion, sanitization and de-duplication writing JSON lines under
  `data/news` (git-ignored). No LLM.
- **Agent core** (Sprint 4a, design §4–7, §9, §13, section
  [Agent core](#agent-core-sprint-4a) below): event schema, Haiku/Opus
  classifier, corroboration, TTL/decay, the shadow overlay and the
  append-only shadow logs. It is a library; the log-only shadow runner, its
  daily report and the VPS unit come in Sprint 4c.
- **Eval** (Sprint 4b, section [Eval](#eval-sprint-4b) below): 134 labeled
  synthetic stories and a harness that scores the classifier on them. The
  owner-facing explanation is [`NEWS_AGENT.md`](NEWS_AGENT.md).

Nothing in `app/news` reads exchange or demo-account state, and no trading
module imports it (`tests/test_news_boundaries.py` enforces both directions).

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
title + UTC day, a crude same-story bucket; the classifier refines it by
linking an item to an existing event (`same_story_as`), and source families
are judged in `corroborate.py`. `event_id` (Sprint 4a) names one story: a hash
of category, story key, first-source 6-hour time bucket and assets, e.g.
`evt_20261020_hack_btc_eth_<12 hex>`. The seen-set
(`data/news/_state/seen.json`) is pruned at 14 days / 100k keys.

## Files

```
data/news/raw/<YYYY-MM-DD>.jsonl          sanitized items
data/news/quarantine/<YYYY-MM-DD>.jsonl   severe-flag items
data/news/_fetch_log/<YYYY-MM-DD>.jsonl   one line per source fetch (status, HTTP code, counts)
data/news/_state/seen.json                dedup state
```

Override the root with `NEWS_DATA_DIR`.

## Agent core (Sprint 4a)

All modules are pure Python with no network access except the classifier's
calls to the Anthropic API, which happen only when `ANTHROPIC_API_KEY` is set.

| Module | What it does |
|---|---|
| `app/news/schema.py` | The design's `NewsEvent` (§4) with exactly its enums, strict validation (no unknown fields, finite 0–1 numbers, UTC timestamps, `expires_at > first_seen_at`, NO_EFFECT forced for SINGLE_SOURCE / CONFLICTED / REJECTED / EXPIRED, short clean summary); the two LLM output models `TriageVerdict` and `ClassifierVerdict`; `SourceItemRef` built from ingestion records. |
| `app/news/classifier.py` | Stage 1: Claude Haiku 5.5 triage per item (effort `low`). Stage 2: Claude Opus 5.5 classification per story (effort `high`) with the item set, existing event candidates and public market context. Structured outputs (`output_config.format`, schema from the Pydantic models), frozen system prompt (the §9 draft verbatim + a reference appendix, `phase6b-classifier-v1`) with a 1-hour prompt-cache marker; strict Pydantic validation of the reply. No key, SDK error, refusal, truncation, invalid JSON, schema violation, an action outside the vocabulary, or an invented source/event id all give `ok=False` = NO_EFFECT. Items with severe sanitization flags (or spoofed publisher names) are never sent. The API host is pinned to `https://api.anthropic.com`. |
| `app/news/corroborate.py` | Independence: articles map to source *families* (wire copies, social-post relays, same owner, identical headlines collapse; LOW/UNKNOWN tiers and quarantined items never count; the model may narrow the set, never widen it; its CONFLICTED/REJECTED/EXPIRED are respected). Price/volume confirmation: move ≥ 0.5 × ATR and reaction volume ≥ 1.5 × the rolling average in the expected direction, from public candles **closed before the decision time** only. |
| `app/news/decay.py` | §6 TTL table, linear (default) or exponential decay that never rises and is zero from `expires_at`, source weights (OFFICIAL 1.0, HIGH 0.9, MEDIUM 0.65, LOW/UNKNOWN 0), thresholds (< 0.35 none; 0.35–0.55 ×0.75; 0.55–0.70 ×0.50; ≥ 0.70 block, or ×0.25 where a category may not block), the effective signal and the most-conservative combination (no compounding). `build_event` turns a verdict into an event: id, timestamps, TTL and status are deterministic and the model's proposed action is only a ceiling. `merge_event`: a repeat of the same story keeps its id and TTL; only new independent evidence can strengthen an event. Policy version `phase6b-decay-v1`. |
| `app/news/overlay.py` | `evaluate_new_long_entry`: a pure function over a snapshot of one candidate NEW long entry and the current events. It can keep, shrink or block that entry; it never allows what the baseline blocked, never raises a size, and has no input that represents exits, stops, cancels, the kill switch or reconciliation. Unhealthy news state is NO_EFFECT. |
| `app/news/store.py` | `NewsShadowLog`: append-only `logs/news_shadow/events-YYYY-MM-DD.jsonl` and `decisions-YYYY-MM-DD.jsonl` (design §11 record kinds), secret-looking keys and values redacted. Override the directory with `NEWS_SHADOW_LOG_DIR`. |

The `anthropic` SDK is the only new dependency (pinned and hashed in
`requirements.txt`); only `classifier.py` imports it.

## Eval (Sprint 4b)

`app/news/evaluation.py` and `scripts/eval_news_classifier.py` (design §15,
master plan §5.2). The labeled set lives in `tests/fixtures/news_eval/` (see its
README): 134 synthetic stories in 13 kinds, each article raw as a source would
deliver it, with the final action, category and source facts a careful
classifier should end with. Each case runs through the production path: the
real sanitizer builds the ingestion records, `NewsClassifier` triages each article
and classifies the story, public-style candles from `market.json` feed the
price/volume check (only candles closed before the decision), then `assess`,
`build_event` and `effective_signal` decide. Story-linking cases carry existing
events; a reply that links a repeat merges into that event (`merge_event`), a
new development builds a fresh one.

Scoring: schema validity per stage (gate ≥ 95 %), prohibited actions (gate 0),
single-source effects (gate 0), and final-action and category accuracy per kind
and per category with 95 % Wilson intervals, missed and false effects, triage
recall, story links, refusals, truncations, tokens, latency and a list-price
cost estimate. Infrastructure failures (API errors, a missing recording, a
reply from another model than the one asked for — a dated snapshot of the
requested model counts as that model) are never scored; above 10 % they make
the run INCONCLUSIVE, and only a case's last attempt counts. Clients: the real
SDK client only when `ANTHROPIC_API_KEY` is set (otherwise `not run: no API key`,
exit 0; five SDK retries against rate limits), a recording wrapper
(`recording.jsonl`, whose header keeps the run's models and settings; replayable
with `--replay`, payload hashes checked), and four scripted offline models for
`--self-test` (reference answers, never-acting, block-everything, broken output).
`--resume DIR` continues an interrupted live or replay run with its own cases,
repetitions, models and efforts, redoing only unscored cases; the cost counts
every attempt. Outputs go to `artifacts/news_eval/` (git-ignored).

## Not in scope here

The shadow runner, daily report, spend cap and VPS unit (Sprint 4c);
corroboration through the API's web-search/web-fetch tools (master plan §5.2,
not built); Batch-API re-scoring; and any connection to the risk manager or the
demo runtime, which needs a separate owner decision. See
`docs/PHASE6B_DESIGN.md` and the master plan Sprint 4.
