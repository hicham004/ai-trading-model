# News shadow dry-run fixture

Used by `python scripts/run_news_shadow.py --dry-run` (and its tests) to run the
whole Phase 6b news shadow offline: no network, no API key, no OKX access. Every
name is invented (Kryvex, Meridex, the `.example` sites); nothing here reports a
real event.

| File | What it is |
|---|---|
| `scenario.json` | The clock (2026-10-19 09:00–13:20 UTC, a cycle every 5 minutes), the sources, the public-candle scenario (BTC and ETH fall about 2.4 % and 3.2 % on triple volume from 10:10), the expected results |
| `feeds/*.json` | What each source publishes and when. The dry run renders them in the real wire formats (RSS 2.0 XML; GDELT DOC JSON showing the last hour, like the live `timespan=1h` query) so the production parsers run unchanged |
| `model.json` | The scripted offline "model": triage and classification answers by headline, with typical token counts so the spend cap is exercised |
| `phase6a/journal-2026-10-19.jsonl` | A Phase 6a journal in the supervisor's real line format; the dry run appends each line when the clock passes its `ts` |

The story, cycle by cycle:

- **09:00** — the official feeds' backlog (published days earlier) is skipped as
  stale without an AI call; two GDELT headlines are triaged and are off the
  watchlist.
- **09:20** — an unverified post about Kryvex: one source, an event with no
  effect, expiring at 11:20.
- **09:35** — a prompt-injection headline and a homoglyph headline are
  quarantined and never reach the model.
- **10:05** — a Reuters report of a Meridex hot-wallet breach (HIGH tier: it is on
  reuters.com), copied word for word by two sites: one triage call, one source
  family (`wire:reuters`), no effect.
- **10:25** — an independent outlet confirms it while BTC and ETH fall on volume:
  linked to the same event, judged over all four articles, two independent
  families plus market confirmation. With a HIGH source the event is classified
  BLOCK_NEW_LONGS, but twenty minutes of fading have already taken it just under
  the block line: its strongest effect is REDUCE_SIZE x0.50 (severity 0.689).
  Its expiry stays 16:05: a repeat never re-fires it.
- **10:40** — one more copy of the Reuters headline is attached to the event
  without any model call.
- **11:00** — Phase 6a allows a new long: the news layer **would have reduced** it
  (to 50 %).
- **11:10** — the SEC press release about the Meridex operator: one official
  source, no effect yet. **11:15** — an independent outlet corroborates it:
  BLOCK_NEW_LONGS, fading over the next 24 hours (block, then reduce, then nothing).
- **12:00** — Phase 6a itself blocks a new long (confidence floor): the news layer
  would block too, but it is **not counted** as a prevented trade.
- **13:00** — Phase 6a allows a new long: the news layer **would have blocked** it.
- The 07:00 candle's decision happened before the shadow started and is not
  evaluated; FLAT and HOLD signals are never evaluated.

Change a story or an expectation here and the tests in
`tests/test_news_shadow_runner.py` and `tests/test_news_shadow_cli.py` tell you
what moved.
