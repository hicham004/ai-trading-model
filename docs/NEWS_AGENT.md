# The news agent, in plain words

Status (November 4, 2026): built and tested offline, including the 30-day test runner
("news shadow", below), your two news-rule fixes of October 21 (plan row R4d) and the
two follow-up fixes covered by your go of November 4 (plan row R4e: credits to the
Financial Times count like the wire credits, and a broken link no longer costs a
collection round); **not yet run against the real AI model** and not yet running
anywhere. Phase 6b is authorized for **log-only**
operation (owner, June 30, 2026, GitHub issue #12; reconfirmed October 20, 2026).
Using news to change what the demo or a live system trades is **not** authorized.

Technical details: [`NEWS_INGESTION.md`](NEWS_INGESTION.md) (modules) and
[`PHASE6B_DESIGN.md`](PHASE6B_DESIGN.md) (the design). This page explains what the
news agent does, how we test it, and what you need to decide.

## What it is

A separate observer that reads a small set of news sources and asks one question:
*does this story make it riskier than usual to open a new bitcoin or ether position
right now?* It writes its answer into a log. Nothing else reads that log yet.

It can give only three answers:

| Answer | Meaning |
|---|---|
| `NO_EFFECT` | Nothing to do. The answer for anything uncertain, unconfirmed, old, off-topic or good news. |
| `REDUCE_SIZE` | A new long position would be made smaller. |
| `BLOCK_NEW_LONGS` | No new long position for a while. |

There is no answer that buys, sells, enlarges a position or makes the system more
confident. The agent never touches open positions, exits, stop-losses, the kill
switch or reconciliation, and in log-only mode even a "block" is only written down.

## How it decides

1. **Collect** headlines from official feeds (SEC, Federal Reserve, Coinbase status
   page) and from GDELT, a free index of world news.
2. **Clean** the text. Hidden characters are removed. Articles with look-alike
   letters (a Cyrillic "а" posing as a Latin "a"), right-to-left tricks or text that
   tries to give the AI instructions are put aside and **never reach the AI**.
3. **Quick check** (Claude Haiku 5.5, cheap): is this about one of the eight watched
   event types — SEC/ETF decisions, the Fed, inflation and jobs data, exchange hacks,
   major regulation, liquidation waves, wars and sanctions, exchange or blockchain
   incidents?
4. **Careful look** (Claude Opus 5.5): what happened, which sources are really
   independent, any sign of satire, rumor, old news or manipulation, and a proposed
   answer.
5. **Fixed rules decide**, with no AI involved:
   - a story needs **two independent sources**, or one credible source **plus a
     matching market move** (price and volume, using only data already known at
     that moment); one source alone never has an effect;
   - copies of one wire story, articles quoting one social-media post, satire,
     contradicted claims and old news have no effect;
   - **source quality** counts (your decision of October 21, 2026): official feeds
     (SEC, Fed, Coinbase status) weigh most; articles on the websites of Reuters,
     AP, Bloomberg, the Wall Street Journal/Dow Jones and the Financial Times are
     high quality, also when GDELT found them, but not the paid press releases and
     sponsored or partner pages those sites also host; every other outlet GDELT
     finds is medium quality. The Wall Street Journal, Dow Jones Newswires,
     Barron's and MarketWatch have one owner and always count as one source. A
     site that only repeats what Reuters, the Associated Press, AFP, Bloomberg,
     the Financial Times or one of those four brands reported counts as that one
     source, whatever capitalisation it uses for the name;
   - every effect fades over a few hours and then stops completely;
   - the AI's proposal is only a ceiling: the rules can lower it, never raise it.
6. **Log** the result. Any failure — no key, AI unavailable, a malformed reply —
   means `NO_EFFECT`, never a block.

## How we test it: the eval

Before the agent runs for real, it has to pass a test set ("eval") of **135 made-up
news stories**, each with the answer a careful analyst would give. Every headline is
invented (fictional exchanges such as "Kryvex" or "Meridex") and none reports a
real current event; a few real past events (FTX 2022, Terra 2022, ...) appear on
purpose, as old news being recirculated. The stories cover 13 situations:

| Situation | Stories | Right answer |
|---|---|---|
| Real-looking risk events confirmed by two or more sources | 25 | reduce or block |
| One source plus a confirming market move (and cases where the market did *not* confirm) | 9 | reduce, or nothing |
| Confirmed but harmless news (decisions as expected, good news) | 10 | nothing |
| One wire story copied many times | 13 | nothing |
| Single-source rumors | 12 | nothing |
| Satire and parody | 8 | nothing |
| Old news recirculating (FTX 2022, Terra 2022, ...) | 9 | nothing |
| Text that tries to give the AI instructions | 13 | nothing (one case: a real event must still count) |
| Look-alike letters and invisible characters | 10 | nothing (two cases: real events must still count) |
| News outside the eight watched types | 8 | nothing |
| Forecasts and opinion | 7 | nothing |
| Claims contradicted by a denial or a correction | 5 | nothing |
| Repeats and new developments of a known story | 6 | depends |

So 35 stories need a restriction, 99 need `NO_EFFECT`, and one (a bullish headline
during a price spike) accepts either. A system that always answered `NO_EFFECT`
would get 74 % right while being useless, so the report shows missed events and
false alarms separately.

**The three safety gates** (from the master plan) must all pass:

1. at least **95 %** of the AI's replies are well-formed;
2. **zero** replies try an answer outside the three allowed ones;
3. **zero** single-source stories end with an effect.

Besides the gates, the report shows how often the final answer was right for each
situation and each event type (with a margin of error), missed events, false
alarms, refusals, cut-off replies, tokens and an estimated cost.

The eval runs the **same code** the news shadow will run, and a test checks that the
answers and notes in the test set are never shown to the AI.

## How to run it

```bash
# Free self-check (no key, no internet, a few seconds):
python scripts/eval_news_classifier.py --self-test

# A real run with the AI (needs an Anthropic API key, see below):
python scripts/eval_news_classifier.py

# Re-score a saved real run for free:
python scripts/eval_news_classifier.py --replay artifacts/news_eval/<run>/recording.jsonl
```

- **Self-check.** Runs four pretend "AIs" through the whole system: one that gives
  the correct answers (must score 100 %), one that never acts (must miss every
  event), one that blocks everything (must be caught by the single-source gate) and
  one that returns broken replies (must fail). If any of these behaves differently,
  the test set or the scoring is wrong. Run it after changing any test story.
- **Real run.** Needs `ANTHROPIC_API_KEY` set in the environment. Without it the
  script prints `not run: no API key` and does nothing. It makes about 230 quick
  checks and 110 careful looks. **Estimated cost: about $4–10 per run** at list
  prices. This is an estimate, not yet measured; each run's report shows its own
  figure. It takes roughly 10–30 minutes.
- **Results** go to `artifacts/news_eval/<date>-live/`. `report.md` is the readable
  report: the result, the gates, accuracy by situation and event type, cost and a
  list of the cases to look at. Every AI reply is saved (`recording.jsonl`) so the
  run can be re-scored later at no cost.
- **Interrupted, or errors?** Run `python scripts/eval_news_classifier.py --resume
  <folder>`. It continues that same run (same stories and settings) and redoes only
  the stories without a result — for example ones that hit `rate_limited`, which is
  common with a brand-new key. Add `--workers 1` to go slower.
- The script ends with exit code 0 when every gate passes, 1 when one fails or
  too many cases hit errors, and 2 on a setup problem.

## When to run it

- Once with the capped key **before starting the 30-day news shadow** (owner step G5).
- Again after any change to the AI prompt, the AI model, the rules or the test set.
- A **FAIL** means the configuration is not ready: fix it before trusting the
  shadow's logs.

## What a pass means — and what it does not

A pass shows the agent and its rules behave safely on these 135 made-up stories.
It does **not** show that the agent catches real events in time, that it would
have saved money, or that it is ready to influence trading. That evidence can only
come from the 30-day forward shadow (design section 11), and any use of news to
gate trades needs a separate decision from you.

## The news shadow: the 30-day test run

The news shadow is the agent running for real, next to the Phase 6a demo run on the
VPS, but writing everything down instead of acting. Every 5 minutes it reads the news
sources, cleans them, asks the AI, applies the fixed rules, and keeps a list of live
events. Whenever the Phase 6a run decides about a new long position, the shadow writes
down what the news layer **would** have done at that moment: nothing, reduce, or block.
It only uses what it knew at that moment, so hindsight cannot make it look better.

- **What it can do now that it could not before:** run on its own as a service for
  weeks, survive restarts, cap its own AI spending, and write a daily report you can
  read: what it saw, what it believed, what it would have blocked or reduced, the price
  6 hours later, a list of cases worth a human look, and eight safety checks that must
  all show 0.
- **Offline rehearsal:** `python scripts/run_news_shadow.py --dry-run` replays four
  invented hours of news (a rumor, a hack confirmed by two outlets while the market
  falls, an SEC action, a hidden-instruction headline) against an invented Phase 6a
  journal, with no internet and no key, and checks every result.
- **Money:** it stops calling the AI at a monthly cap you choose (default $40), and no
  single day may use more than twice its even share of what is left. The console limit
  on the key is the backstop.
- **Safety:** it has no trading keys and cannot place or change anything. When anything
  fails, the answer is "no effect", never "block". Stopping it changes nothing in
  trading.
- **How to start it:** `docs/runbooks/NEWS_SHADOW.md` (plan step G5). Run the eval once
  with the same key first.

What the 30 days are for (design section 11): at least 20 confirmed events, at least 10
moments where a real Phase 6a entry decision met a live news event, and zero
violations of the safety checks. Even then, using news to gate trades needs your
separate decision.

## Known gaps found while building the eval

- **A wire credit the rules missed — fixed on October 21 (plan row R4d).** The rules
  recognized copies credited to "Reuters", "Bloomberg" or "(AP)", but not "the
  Associated Press" written with capitals (nor "Agence France-Presse"), so such
  copies looked like independent sources and only the AI's judgment collapsed them
  (test story `syn-ap-attribution-capitalized`). Both names now count however they
  are capitalised, and so do credits to the Wall Street Journal, Barron's,
  MarketWatch and Dow Jones Newswires. These newer recognitions never add a source:
  an article that matches several rules (say, an AP story on MarketWatch's site) may
  stand for any of those sources, and the rules count the fewest sources that
  explain all the articles. Two outlets that each published the story stay two,
  even when a third article names both, and a wire's own report always counts as
  that wire, whatever other outlet it mentions.
- **Credits to other outlets — the Financial Times added on November 4 (plan row
  R4e).** A site that writes "the Financial Times reported", "FT reported" or
  "according to the FT" now counts as the FT, together with the FT's own article, the
  way the wire credits work (test story `syn-ft-attribution`); "FT" counts only in
  capitals, so feet, FTX, the FTSE and NFTs never match. Like every newer recognition
  it can never add a source. Still not recognised: credits to other outlets (CNBC,
  CoinDesk, The Block, ...) and some short forms ("AP reported" without brackets,
  "Wall St. Journal"); such a copy still looks like a second, independent source next
  to the original article, and only the AI's judgment collapses it. The other way
  round, a passing mention counts as a credit: an article that merely mentions
  "Barron's" or "the FT" may be counted together with a Wall Street Journal or
  Financial Times article (fewer sources, never more). See "What you need to decide".
- **One malformed link can cost a whole collection round — fixed on November 4 (plan
  row R4e).** If a news feed delivered a link the URL cleaner could not read (a broken
  address or an impossible port number), the 5-minute round of collecting failed, and
  so did every round while the feed still listed that link (up to an hour for GDELT);
  articles from feeds read earlier in a failed round were marked as seen without being
  processed, so they were lost until a restart. Now the unreadable link is skipped and
  written to the service log, the article keeps its headline and goes on without a
  link (it is recognised again by its publisher and headline, and without a site it
  can never count as a high-quality outlet), and the round completes.
- **A weak repeat could switch off a live event — closed in the news shadow.** The
  rules for a repeated story used to judge the evidence on the new articles alone, so
  one outlet repeating a confirmed story made it "single source" again. The news
  shadow (R4c) collects every article of a story and judges the evidence over all of
  them, as the design asks (one story is one event, counted by its independent
  sources), so a repeat can add evidence but never erase it. The rule module itself
  was not changed for this; the test `test_a_weak_repeat_cannot_switch_off_a_live_event` covers
  it. A repeat can still weaken an event when the AI, seeing the repeat, proposes a
  milder answer: the rules let later information only soften an effect, never sharpen
  it without new evidence. The eval's story-linking cases measure that part.
- **Where only the AI's judgment protects.** The same rumor rewritten by several
  small sites, satire rewritten as news, and old news with a fresh date all look
  like separate sources to the rules, because the rules cannot tell those sites
  apart: every outlet outside the high-quality list is medium quality to them. In 16
  of the 73 single-source stories only the AI's skepticism stands between the rumor
  and an effect (17 before the October 21 fix). The single-source gate measures
  exactly this.
- **"Volatility only".** If the AI says a story should cause volatility in either
  direction, any large market move confirms it, even a rally after a hack report.
  Test story `mkt-hack-but-rally` watches this. Such an answer is defensible, so the
  story counts as a wrong answer, not as a single-source failure.
- **Some "missed events" mean caution.** With only medium-quality outlets, an effect
  needs fairly high confidence and impact numbers from the AI. A missed event on
  such a story can mean the AI was cautious rather than that it misread the story.
- **Suppression is possible, false alarms are not.** When text that tries to
  instruct the AI slips past the cleaner and the AI flags it, the rules discard the
  whole story. An attacker could therefore make the agent miss an event, but cannot
  make it cause one.
- **Not yet measured with the real AI.** This computer has no API key, so the eval
  has only been run with the pretend AIs and a hand-written sample of replies.
- **The right answers were written by an AI.** The agent that built the eval wrote
  the stories and their answers by applying the design's rules to clear-cut
  situations, and the self-check proves every answer is reachable through the real
  code. A second AI agent then checked every answer independently; the ten stories
  it questioned were corrected, along with related ones (for example two outlets
  that turned out to share an owner, invented incidents at real companies now
  moved to made-up names, and site names that gave the answer away). No person has
  reviewed them yet; a reviewer should spot-check about twenty (each story
  explains its answer in its `why` field).
- **One run is a first look.** With 135 stories, one run pins overall accuracy down
  to about ±7 percentage points, and "zero single-source effects in 73 stories" still
  allows a true rate of a few percent. `--reps 3` repeats every story three times for
  a firmer answer at three times the cost.

## What you need to decide

- **Run the eval with the capped key before the news shadow.** It needs the
  Anthropic API key from step G5 and costs about $4–10 per run.
  Recommendation: yes. Run it once before starting the shadow and after every
  prompt or model change, and treat a FAIL as a reason not to start.
- **Recognise credits to other named outlets** (CNBC, CoinDesk, The Block,
  Cointelegraph, ...) the way the wires and the Financial Times are recognised (gap
  "Credits to other outlets" above). Recommendation: not now. Let the 30-day news
  shadow's logs show which credits actually appear in the watched feeds, then add
  only those, each as a recognition that can only lower the source count.
- **The news shadow's monthly AI budget** (default $40, with a $50 limit on the key's
  workspace in the Anthropic console). Recommendation: keep $40 for the first month
  and look at the report's spend line after a week.
- **Start the 30-day news shadow on the VPS** (step G5, `docs/runbooks/NEWS_SHADOW.md`).
  Recommendation: yes, after this change (R4d) is merged and one eval run passes.

Decided on October 21, 2026 and built in R4d: the wire-credit fix, and the
high-quality outlets (Reuters, AP, Bloomberg, Dow Jones/WSJ as one owner family,
the Financial Times). Covered by your go of November 4, 2026 and built in R4e:
credits to the Financial Times count like the wire credits, and a broken link no
longer costs a collection round.
