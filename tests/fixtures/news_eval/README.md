# News-classifier eval set (Phase 6b, plan row R4b)

Labeled stories for `scripts/eval_news_classifier.py` and `app/news/evaluation.py`.
See `docs/NEWS_AGENT.md` for what the eval measures and how to run it.

**Everything here is synthetic.** Every headline, excerpt, company, figure and date
is invented for testing; none reports a real event. Exchange, protocol, token and
fund names such as Kryvex, Meridex, Varkon, ARVD, Altora or Halvorsen are
fictional. Real agencies, outlets and countries appear only so that the classifier
sees realistic sources; no claim about them is true. Two real names are the
subject of invented incidents because the cases need them: Coinbase, whose
official status feed is one of the agent's sources (`corr-incident-coinbase-halt`,
`mkt-coinbase-status-selloff`, `rum-official-notice-alone`,
`conf-status-page-vs-rumor`, `ben-coinbase-restored`, `hz-title-cyrillic-a`), and
Ethereum, for ETH-only protocol incidents (`corr-incident-eth-finality`,
`hz-cyrillic-ethereum`). The few real past events in `stale_repost` (FTX 2022,
Terra 2022, Mt. Gox 2014, the 2021 China ban, Silvergate 2023, March 2020) are
there because they are real: those cases test that old news recirculating with a
fresh date is recognized as old. The set holds headlines and short source
summaries only, never article bodies.

## Where the labels come from

The stories and labels were written by the AI agent that built the eval (Claude
Opus 5.5, plan row R4b, October 20, 2026), applying the rules of
`docs/PHASE6B_DESIGN.md` to deliberately clear-cut situations; each case's `why`
gives the reasoning. A second agent re-derived every label independently on
October 21, 2026; the cases it flagged were corrected (an ambiguous
single-source flag, repost families, same-owner outlets, real names, accepted
categories) and the stale reposts' single-source flags made consistent. The
reference self-test proves every label is reachable through the real sanitizer,
corroboration and decay code, but **no human has reviewed the labels yet**. A
reviewer should spot-check a sample, starting with the cases where only the
classifier's judgment protects (listed by the `always_block` row of
`--self-test`). Grading is on the final action, category and source facts, never
on wording, so a model is not rewarded for phrasing answers like the author.

The news-rule changes of plan row R4d (October 21, 2026: the owner's HIGH
outlets, credits to "the Associated Press" and "Agence France-Presse" in any
capitalisation, Dow Jones's four brands as one source) changed the tier of 46
stories (MEDIUM to HIGH) and the source families of one
(`syn-ap-attribution-capitalized`), but no right answer: every effect story that
is now HIGH already accepted a block, and no story's count of independent sources
rose, so no label changed.
Three explanations were brought up to date (the `corroborated` description,
`corr-hack-kryvex` and `syn-ap-attribution-capitalized`, which the rules now
collapse to one source without the classifier's help).

Effect labels backed only by MEDIUM-tier outlets sit near the thresholds: the
final action depends on the confidence, impact and horizon the model gives (for
example `corr-liq-below-67k` or `corr-incident-stakewell`), so a missed effect
there can mean cautious numbers rather than a misread story. A story with a HIGH
outlet can also end with a block when the model's reading is confident and
high-impact; its label accepts that.

## Layout

- `cases/<kind>.json` — one file per case kind (13 kinds, 134 cases): the seven
  the plan row names (`corroborated`, `syndicated_copies`, `single_source_rumor`,
  `satire`, `stale_repost`, `prompt_injection`, `homoglyph_zero_width`) and six
  that cover the other direction and the design's edge cases
  (`benign_corroborated`, `market_confirmed`, `off_watchlist`, `speculative`,
  `conflicted`, `story_linking`).
- `market.json` — public-style 15-minute candles for BTC-USDT and ETH-USDT: a calm
  baseline and named scenarios (`selloff`, `rally`, `dip_low_volume`,
  `late_selloff`, ...) placed around each case's first publication time.
- `recorded/sample_run.jsonl` — hand-written model replies for 18 cases, in the
  format a live run records, with deliberate flaws (invalid JSON, a BOOST action,
  a refusal, a truncation, an invented source id, credulous answers that let
  single-source stories through, a missing reply). The offline tests replay it
  and check every number the scorer reports. It is not a real model run.

## A case

```json
{
  "id": "corr-hack-kryvex",
  "summary": "For humans: what the case is about.",
  "now": "2026-11-03T09:30:00Z",
  "items": [
    {"key": "a", "publisher": "reuters.com", "published": "-16m", "observed": "-13m",
     "title": "Crypto exchange Kryvex halts withdrawals after $1.2 billion hot-wallet breach"},
    {"key": "b", "publisher": "coindesk.com", "published": "-12m", "observed": "-9m",
     "title": "Kryvex confirms hack, says about $1.2B in bitcoin and ether drained from hot wallets"}
  ],
  "market": "calm",
  "expect": {"action": "REDUCE_SIZE", "accept": ["BLOCK_NEW_LONGS"],
             "category": "EXCHANGE_HACK_EXPLOIT", "single_source": false},
  "why": "The label's reasoning, for reviewers."
}
```

- `items` are articles exactly as a source delivers them, before sanitization:
  `source` is a source id from `app/news/sources.py` (default `gdelt_doc`, whose
  articles carry only a domain and a headline; like the fetcher, the loader makes
  them HIGH tier on the HIGH outlets' sites — reuters.com, apnews.com,
  bloomberg.com, wsj.com, dowjones.com, ft.com — and MEDIUM everywhere else;
  official feeds such as `sec_press` supply their own publisher and OFFICIAL
  tier). Times
  are ISO-8601 or offsets from `now` (`-15m`, `-3d`). Every character outside
  ASCII is written as a JSON `\u` escape, so hidden and look-alike characters
  stay visible: `\u200b` zero-width space, `\u0435` Cyrillic e, `\u202e`
  right-to-left override, `\udb40\udc..` Unicode tag characters. A test keeps
  the case, market and recording files ASCII-only.
- `expect.action` is the final action a careful classifier plus the
  deterministic rules should end with; `accept` lists other acceptable final
  actions (for real risk events both REDUCE_SIZE and BLOCK_NEW_LONGS are usually
  fine: the split depends on source tier and the model's numbers).
  `category` / `category_accept` grade the watchlist category; `assets` grades
  the affected assets when given.
- `single_source: true` means at most one independent source makes the claim
  (copies, reposts, relays of one post and recirculated old stories count once;
  a denial does not count) and no market move confirms it under any reasonable
  reading: any effect on such a story counts against the single-source gate
  (target zero). A story the market might confirm under a defensible reading
  (`mkt-hack-but-rally`) is left out of the gate and graded on accuracy only.
- `independent`, `signs`, `corroboration`, `direction`, `reaction`,
  `same_story_as` and `new_development` describe the reference answer — what a
  careful classifier would say. `same_story_as` / `new_development` are also
  graded for stories with `existing_events`.
- `why` explains the label. Labels, notes and summaries never reach a model; only
  the article fields do (a test checks this).

## Checking the labels

`python scripts/eval_news_classifier.py --self-test` runs four scripted offline
models through the full pipeline: the reference answers (built from the labels)
must score 100 % and pass every gate, which proves each label is reachable
through the real sanitizer, corroboration and decay rules; a model that never
acts must miss every due effect; a model that blocks everything must be caught by
the single-source gate; a model with broken output must fail schema validity.
Run it after editing any case.
