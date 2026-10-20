# Master Plan v2 — Building the Best Possible AI Trading System

Date: 2026-10-20. Author: Claude (Fable 5.1) for the owner. Status: PROPOSAL — the
owner approves each sprint; nothing here authorizes live trading, phase
advancement, or safety-core changes by itself (see `PROJECT_RULES.md`).

Companion: `docs/AUDIT_2026-10-20.md` (what exists today, what was tested live,
what is wrong). You do not need to read the audit to use this plan.

---

## 0. Read this first (2 minutes)

1. **Deadline: Oct 31, 2026.** OKX stops WebSocket on port `:8443`. Every WS
   default in this repo uses `:8443`. If nothing changes, the VPS shadow run
   goes blind on Oct 31. Fix = drop the port (Sprint 0, ~1 hour).
2. **Your goal** — "a professional trader, 24/7, with an AI reading the news" —
   is the right goal and the market is converging on exactly one architecture
   for it: **a deterministic engine makes and protects every order; the AI
   reasons, researches, classifies news and explains, but never clicks buy.**
   Robinhood's own engineering motto for its Cortex assistant is "the loop
   stays dumb so the model can be smart." Composer by SoFi (June 2026)
   explicitly markets "not agentic" rule-based automation. Every live test of
   LLMs trading by themselves lost money on average (Section 2).
3. **What we have** is the safety/ops skeleton of that architecture (good) with
   almost no trading muscle: one toy strategy, no validated edge, software stop
   checked hourly, zero AI/news code. Idle since June 29.
4. **What "best possible" means in Oct 2026** (evidence-based, not hype):
   a multi-strategy systematic engine (trend/momentum, breakout, mean-reversion,
   positioning filters) with regime awareness, volatility-targeted sizing,
   exchange-side stops, maker-first execution, a news/event risk layer run by
   Claude, a Claude research agent that proposes and *proves* strategies with
   walk-forward validation, and always-on ops with AI digests. Section 3.
5. **Seven workstreams, ~14 weeks to a validated demo ensemble**, tiny live
   money earliest ~Feb 2027 if the gates in Section 8 pass. Section 4.
6. **Spend plan**: $0–$60/month in Claude API, $0 in data to start (OKX public
   endpoints give candles, funding, open interest, liquidations, long/short
   ratios for free), optional $30–$120/month for premium data/news later.
7. **First three actions**: (a) Sprint 0 fix + VPS check (this week),
   (b) Sprint 1 data lake + bulk history (next 2 weeks), (c) Sprint 2 research
   lab + strategy ensemble v1 with an honest walk-forward report.
8. **Do not**: let an LLM pick entries; add "confidence boosts" from news;
   backtest an LLM on history (it already read the news); trade perps/leverage
   before Phase 9; skip the gates because a backtest looked good.

---

## 1. Your request, translated into requirements

| # | "Professional trader, 24/7, AI reads the news" means | Status today |
|---|---|---|
| R1 | Always on, survives restarts/reboots/feed drops, fails closed, alerts a human | ✅ exists (shadow supervisor, systemd, heartbeat, Telegram) |
| R2 | Several uncorrelated strategies, each with a *proven* edge after costs | ❌ one SMA crossover, no proof |
| R3 | Knows what kind of market it is in (trend / range / danger) and adapts size or stands aside | ❌ none |
| R4 | Sizes by volatility and risk budget, never martingale, hard loss limits | ⚠️ fixed % risk, no vol targeting |
| R5 | Every position protected by an **exchange-side** stop the instant it exists | ❌ software stop, hourly check |
| R6 | Executes like a pro: maker-first, slippage budget, no chasing | ⚠️ limit orders exist; no fallback/slippage policy |
| R7 | Reads news/events 24/7 and **reduces risk** around them | ❌ design only (`PHASE6B_DESIGN.md`) |
| R8 | Explains every decision (journal) and reports daily | ✅ journal/report pattern exists |
| R9 | Continuously validated (walk-forward, holdout, forward paper vs. backtest) | ❌ none |
| R10 | Gets better over time without a human babysitting it | ❌ none (this is where AI agents come in) |

---

## 2. What already exists out there (research, Oct 2026)

### 2.1 Exchanges now ship "agent access", not "AI traders"

| Product | What the AI layer actually is | Lesson |
|---|---|---|
| **OKX Agent Trade Kit** (official, MIT, [docs](https://www.okx.com/docs-v5/agent_en/)) | MCP server + CLI + Skills, 79 tools: market data (no key), spot/swap/futures/options trading, algo orders (conditional, OCO TP/SL, trailing), account, grid/DCA bots. **Demo mode and read-only mode** built in. "[CAUTION]" tags on money-moving tools rely on the model obeying, not a hard block. | OKX itself gives Claude a trading interface — but their own docs say use sub-accounts, minimal permissions, demo first. We should use it for *research/ops tooling*, never as the order path. |
| Binance AI Skills Hub (Mar 2026) | 7 modular agent skills (spot orders, wallet analytics, smart-money, contract risk) | Same pattern: tools for agents, no decision engine. |
| Bybit MCP (Apr 2026) | Market data, execution, portfolio for Claude/ChatGPT/Cursor; keys stay client-side | Same. |
| Gemini Agentic Trading (Apr 27, 2026) | "First agentic trading through a regulated US exchange", MCP; "Trading Skills" like spread check, candles | No published guardrails beyond "predefined strategies". |
| Kraken CLI/MCP (Nov 2025) | 134 commands, paper mode | Same. |
| Coinbase agents / AgentKit | Autonomous agents trading within user-set limits; AgentKit for on-chain | Autonomy exists; edge is not published anywhere. |

### 2.2 Brokerages: autonomous agents with limits, assistants with approval

Per Yahoo Finance/Jefferies (Jul 2026): Coinbase, eToro ("Tori") and Robinhood launched autonomous agents that trade within user-set limits (Robinhood: separate "agentic account", equities only, 50K+ accounts in weeks); Interactive Brokers keeps a "human in the middle" approving every trade; Schwab ships a chat assistant (no execution) in H2 2026. **Composer by SoFi** (Jun 2026): natural language → rule-based strategy → backtest → automated execution, 2,000+ community strategies, and it *explicitly* distinguishes itself from "agentic trading tools" that keep using AI to decide. **Robinhood Cortex** (Aug 2026 engineering post): one model, minimal tool loop, deterministic code runs the loop/tools/caching, input+output guardrails, strong eval set, "every layer of scaffolding we didn't build is a layer that can't dilute the model."

### 2.3 Retail crypto bots

3Commas, Cryptohopper ("Algorithm Intelligence" = strategy switching), Pionex (PionexGPT setup helper), Bitsgap (AI parameter suggestions), Coinrule (no-code if/then + "adaptive AI"), HaasOnline (scripting). Their "AI" is setup help and strategy switching over grid/DCA/if-then logic; **no independent performance data exists for any of them**, and review sites quote unverifiable "win rates".

### 2.4 Open-source LLM trading agents

TradingAgents (~112K stars; analyst/researcher/trader/risk agents that debate; **backtest only**; only in v0.5 did it add point-in-time data integrity), ai-hedge-fund (45–59K stars; investor-persona agents; **simulation only**), FinRL (reinforcement learning; Alpaca live layer), AgenticTrading, FinRobot. Popular, educational, **none has published live edge**.

### 2.5 What happens when LLMs actually trade (the evidence that shapes this plan)

- **Alpha Arena S1** (nof1, Oct 18–Nov 3 2025, $10K real each on Hyperliquid perps, numbers-only inputs): Qwen3-Max +22%, DeepSeek +5%, **Claude Sonnet 4.5 ≈ −31% to −42%, Gemini −45%, Grok 4 −58%, GPT-5 −59%**. S1.5 (US stocks): only Grok 4.2 profitable; across 32 sessions only 6 finished positive and pooled capital fell ~⅓. No verified Season 2 results as of Aug 2026.
- **Six-month production record, two fleets** (arXiv 2609.05663, Sep 2026): 3,505 user-funded on-chain vaults + ~500 user-built agents on Hyperliquid perps, 7.5M LLM calls. **No directional edge** (41% round-trip win rate vs 50% for matched retail traders); leverage did not adapt to volatility (median 5x in every vol bucket); 43% of positions reached +3% unrealized and **half of those still closed at a loss**; a *mechanical exit bracket* would have recovered ~39 bps per position; swapping frontier models changed consistency, not decision quality. Their conclusion: **operating-layer design and risk controls shape outcomes more than strategy text.**
- **Agent Market Arena** (arXiv 2510.11695): framework design, not the backbone model, drove most behavioural variation.
- **Survey of agentic quant trading** (arXiv 2608.31041, Aug 2026): "strong model or forecasting capability does not reliably translate into trading performance", especially live and under reliability controls.
- **PolyBench** (Apr 2026): 5 of 7 frontier models lost money on prediction markets while reporting high confidence.
- **LLM news sentiment**: improves in-sample fit, not out-of-sample forecasts (J. Big Data 2026); in a multi-agent crypto portfolio, the news agent lowered volatility rather than raising returns (arXiv 2501.00826).

### 2.6 What the quant literature says works (and what doesn't)

- Simple technical rules: ~15,000 rules tested on BTC/ETH/LTC/XRP look profitable in-sample; one version of the paper reports **no out-of-sample forecasting power for Bitcoin** (Hudson & Urquhart, Annals of OR 2021). → Never trust one backtest; walk-forward or nothing.
- **Time-series momentum and attention** predict crypto returns (Liu & Tsyvinski, NBER 2018 / RFS 2021): 1-day to 4-week momentum, Google/Twitter attention surges precede gains. Time-series momentum on 8 majors 2020–Oct 2025 ≈ 32%/yr with deep drawdowns (BATP 2025). → Trend/momentum is the one robust family; drawdown control is the problem to solve.
- **Risk-managed TSMOM** (Howden & Andreev, SSRN 2026): halving exposure when the market is >15% below its peak controls drawdown; vol targeting on top added little; 30-day lookback is a fragile optimum. → Use crash-state de-risking; sweep lookbacks; expect modest, not magic.
- **Timeframe**: a 2026 trend-following study found 6-hour bars the best trade-off (1H churns fees, daily misses moves). → Our 1H choice is plausible; test 4H/6H.
- **Regimes**: 3–4 state hidden (semi-)Markov models fit BTC volatility regimes (Malta HSMM paper; Kokia et al. 2020). → Regime filter v2 = HMM on returns+vol; v1 = simple vol/trend rules.
- **Costs**: OKX spot regular users pay roughly 0.08–0.10% per side (VIP1 0.0675/0.08; EEA spot-only 0.10/0.20). Hourly strategies bleed; maker-first and lower turnover matter.

### 2.7 Conclusions that drive the design

1. No one sells an AI that trades profitably. What exists: agent *access* (MCP/skills), NL *strategy builders*, autonomous agents with *user limits* and no published edge.
2. The industry architecture is settled: **deterministic loop + LLM reasoning**. Our repo already enforces it (`PROJECT_RULES.md`). Keep it.
3. Edge comes from systematic strategies with risk management and execution quality. The LLM's proven value is (a) a *risk brake* on news, (b) *research velocity*, (c) ops/explanation.
4. The fleets paper is a free lesson list: vol-adaptive sizing, mechanical exit brackets, exchange-side stops, operating-layer design > prompt text.
5. Therefore "best possible" = build the engine properly (Sections 3–4) and put AI everywhere except the order decision (Section 5).

---

## 3. Target architecture v2

```text
L0 DATA LAKE        OKX candles 1m/5m/1H/4H/1D (BTC, ETH, +SOL later) · trades · books
                    OKX SWAP public: funding, OI, liquidations (WS), long/short, taker vol
                    CoinGecko context · official RSS (SEC/Fed/BLS/exchange status)
                    news APIs (GDELT free, NewsAPI.ai/CryptoPanic optional) · X tiny watchlist
                    Polymarket public odds (macro/crypto events) · macro calendar
                    storage: Parquet + DuckDB (research) | PostgreSQL (runtime)
        ↓
L1 FEATURE STORE    returns, realized/Parkinson vol, ATR, trend strength, breakout distance,
                    VWAP distance, RSI/z-score, funding z, OI change, long/short, taker
                    imbalance, book imbalance, spread, BTC/ETH relative, attention proxy,
                    news-risk score (from L6a)
        ↓
L2 REGIME MODEL     v1 rules (vol tercile × trend state) → v2 HMM/HSMM 3–4 states
                    → v3 gradient-boosting meta-labeler (should this signal be taken?)
        ↓
L3 STRATEGY         S0 no-trade filter · S1 TSMOM/trend (multi-lookback, vol-scaled)
   ENSEMBLE         S2 breakout + volume/ATR filters · S3 range mean-reversion (RSI/VWAP/z)
                    S4 vol-compression breakout · S5 positioning filter (funding/OI crowding)
                    S6 event-momentum (opportunity mode, much later)
                    → standard Signal {dir, confidence, stop, target, horizon, reason}
        ↓
L4 ALLOCATOR +      vol-targeted sizing · ≤0.5% risk/trade · exposure & correlation caps
   RISK ENGINE      daily/weekly loss limits · drawdown ladder (−5% halve, −10% halt)
   (deterministic)  cooldowns · news overlay (BLOCK/REDUCE only) · kill switch · FINAL VETO
        ↓
L5 EXECUTION        exchange-side conditional stop placed WITH every entry (OCO/TP-SL)
                    post-only limit entry, timeout → market within slippage budget
                    idempotent clOrdId · reconciliation · precision/lot rules · TWAP later
        ↓
L6 AI LAYER         a) News/Event Agent (defensive, log-only first, then gating)
   (Claude)         b) Research Agent (hypothesis → backtest → walk-forward → report)
                    c) Ops Agent (daily digest, anomaly explanation, weekly research memo)
                    d) Operator Copilot (chat over journal/DB with READ-ONLY tools)
        ↓
L7 OBSERVABILITY    journal (JSONL) · heartbeat · metrics · Telegram · daily/weekly reports
   + GOVERNANCE     safety contract unchanged · PR-only · human phase gates
```

**Framework decision.** Keep our core (it is reviewed and tested). Add **vectorbt** (open-source; PRO optional) + **DuckDB/Parquet** for research sweeps and walk-forward; keep our event-driven simulator as the execution-faithful final check. Re-evaluate **nautilus_trader** (v2 RC Sep 2026, Rust core, OKX adapter: spot/swap/futures data+trading, margin not yet) for Phase 9 (perps/shorts/multi-venue). Do not rewrite now.

**Universe.** BTC-USDT, ETH-USDT spot long-only through Phase 8. Add SOL-USDT for diversification once the ensemble exists. Perps (short side, funding carry) only in Phase 9 with a new review.

**Timeframes.** Research 1H, 4H, 6H, 1D. Execution on 1H/4H candle closes plus *event-driven* stop handling via exchange-side orders (no more waiting for the hour to close).

---

## 4. Roadmap — sprints, deliverables, acceptance criteria

Owner = you approve. Builder = Claude Code (Fable/Opus). Reviewer = Codex and/or a second Claude session with `/code-review`. Effort is in focused agent sessions (≈ half-day blocks).

### Sprint 0 — Stop the bleeding (Oct 20–27, ~3 sessions)

Deliverables:
1. Drop `:8443` from every WS default and doc: `app/config.py` (public, business, demo private), `app/exchange/okx_public_ws.py`, `app/exchange/okx_demo_endpoints.py`, `.env.example`, `docs/PHASE3A_LIVE_DATA.md`, `docs/PHASE5_DEMO_TRADING.md`. Validators already accept a port-less URL.
2. VPS: set `OKX_PUBLIC_WS_URL`, `OKX_BUSINESS_WS_URL`, `OKX_DEMO_PRIVATE_WS_URL` without the port in `.env`, restart `shadow.service`, confirm a fresh heartbeat and `candle1H` delivery.
3. Pull `logs/shadow/` daily reports July→Oct from the VPS into `docs/evidence/` (redacted); write a 1-page summary (entries, fills, PnL, restarts, alerts).
4. Hygiene: delete `resume_claude_at_1.sh`; CI Python 3.13; add `uv.lock` (or pip-tools); add `pip-audit`/Dependabot; Alembic baseline migration; fix dashboard y-axis.
5. Close PR #7 (smoke test); keep issue #12 (Phase 6b) open and link this plan.

Acceptance: PR merged, VPS heartbeat `state=running` after Oct 31, evidence summary in repo.

### Sprint 1 — Data lake v2 (Oct 27–Nov 10, ~6 sessions)

Deliverables:
1. `scripts/backfill_history.py`: paginate OKX `/market/history-candles` for BTC/ETH (SOL optional) at 1m, 5m, 1H, 4H, 1D back to 2020; resumable; dedupe; gap report.
2. Derivatives features from OKX public endpoints (free): funding rate + history, open interest (+ history via rubik), long/short account ratio, taker volume, liquidation orders (WS channel) for BTC/ETH-USDT-SWAP. Stored alongside spot candles (features only; we do not trade swaps).
3. Storage: Parquet files + DuckDB views for research; Postgres keeps runtime tables; Alembic migrations in place.
4. Data-quality suite: continuity, duplicates, timestamp alignment, outliers; nightly job.
5. News ingestion skeleton (Phase 6b 7.1): official RSS (SEC, Fed, BLS, OKX/Binance/Coinbase status), GDELT DOC API, optional NewsAPI.ai (free 2K searches) — raw items → sanitized → JSONL. No LLM yet.

Acceptance: ≥5 years of 1H BTC/ETH candles with zero unexplained gaps; feature tables rebuildable from scratch in <30 min; tests.

### Sprint 2 — Research lab + strategy ensemble v1 (Nov 10–Dec 1, ~10 sessions)

Deliverables:
1. `research/` package: vectorbt-based sweep harness; **walk-forward** (rolling train/validate with purge gap), untouched holdout (last 12 months), parameter-robustness heatmaps, Monte Carlo on trade order and slippage, deflated-Sharpe style multiple-testing correction; metrics: Sharpe, Sortino, profit factor, max DD, exposure, turnover, fees/slippage share.
2. Strategies S1–S5 implemented in the existing `Strategy` contract (so they drop into paper/demo unchanged), with ATR-based stops and targets, time stops, and a **vol-scaled signal strength** instead of the current made-up confidence.
3. Regime v1 (rules) and the S0 no-trade filter (spread, staleness, vol spike, event windows).
4. Honest report `docs/research/ENSEMBLE_V1_REPORT.md`: every strategy's walk-forward numbers after realistic costs (0.08–0.10%/side + slippage), by regime, with the holdout untouched until the end. Expect several strategies to fail; that is the point.
5. Calibrated confidence: map each strategy's signal strength to historical hit-rate buckets; the risk floor becomes meaningful.

Acceptance: ≥2 strategies with walk-forward profit factor >1.2 after costs, positive in ≥3 of 4 yearly windows, max DD <20%, and not dependent on one parameter. If none pass, Sprint 2 extends; nothing goes to demo.

### Sprint 3 — Execution v2 in demo (Dec 1–Dec 15, ~5 sessions, safety-core review required)

Deliverables:
1. Exchange-side protective stop on every entry: OKX conditional/OCO algo order (`/api/v5/trade/order-algo`, `tdMode: cash`) or `attachAlgoOrds` on the spot order — verify both in demo, pick the one that fills reliably; reconcile algo orders like regular orders; cancel/replace on exit; alarms if a position exists without a live stop for >N seconds.
2. Entry policy: post-only limit at/inside the spread, timeout T, then market only if expected slippage ≤ budget; record expected vs realized slippage.
3. Mechanical exit bracket: stop + target + time stop + trailing after 1R (from the fleets paper's +39 bps lesson).
4. Demo validation drills: stop triggers while the process is dead; kill switch; reconciliation after restart; partial fills.

Acceptance: 2-week demo run with zero positions unprotected, documented drill results, independent review, owner sign-off. **This closes the hard blocker that has been open since June.**

### Sprint 4 — Phase 6b News/Event Agent, log-only (Dec 1–Dec 22 build, then 30+ days forward; ~8 sessions)

Build exactly `docs/PHASE6B_DESIGN.md` with 2026 tooling (Section 5.2). Log-only; no gating until criteria in PHASE6B §11 pass. Start the forward clock before the holidays so January has data.

Acceptance: PHASE6B §11 pass criteria (≥30 days, ≥20 corroborated events, zero single-source effects, etc.) + an eval set of ≥100 labeled headlines incl. adversarial ones with ≥95% schema validity.

### Sprint 5 — Regime v2, allocator, risk engine v2, paper fleet (Dec 15–Jan 12, ~8 sessions)

Deliverables:
1. HMM/HSMM regime model (hmmlearn) trained walk-forward; regime-conditioned strategy enablement.
2. Allocator: vol targeting per strategy and per portfolio; correlation cap; drawdown ladder; weekly loss limit; cooldowns.
3. **Paper fleet**: run 10–30 strategy/parameter variants in parallel on live public data (free, local) to generate forward evidence 20x faster than one demo bot; dashboard ranks them by forward Sharpe vs. backtest expectation.
4. Ensemble shadow on demo (`demo-ensemble-1h` account) with 2–3 winners.

Acceptance: forward paper stats within tolerance of walk-forward expectations for the chosen strategies; demo ensemble reconciles cleanly for 30 days.

### Sprint 6 — Phase 7 validation and the live checklist (Jan 12–Feb 15, 2027)

Gates in Section 8. Output: `docs/PHASE7_VALIDATION.md` + go/no-go memo. If go: Phase 8 tiny live ($100–300, long-only spot, exchange-side stops, read+trade key, no withdrawal, IP whitelist, daily kill switch) with a pre-agreed scale ladder (double capital only after N weeks within expectations; halve on breach).

### Later (Phase 9+)

Perps/short side and funding carry (nautilus adapter evaluation), SOL/other majors, multi-venue, Opportunity Mode (event momentum) only after 6b v1 passes and a separate forward study, TWAP for size, on-chain data.

---

## 5. The AI plan

### 5.1 Which model does what (prices per 1M tokens, Oct 2026)

| Job | Model | Why |
|---|---|---|
| Headline triage (thousands/day) | Claude Haiku 5.5 — $0.10 in / $0.50 out | Cheap enough to classify every item; strict JSON |
| Event classification + corroboration reasoning | Claude Opus 5.5 — $4 / $20 | Contradiction detection, source-quality judgment, adversarial skepticism |
| Daily digest, weekly research memo, PR review | Claude Sonnet 5.5 — $2 / $10 or Opus 5.5 | Long-context summarization over journals |
| Building the system (Claude Code) | Fable 5.1 / Opus 5.5 | Long-horizon agentic coding |

Budget at watchlist scale: a few hundred items/day through Haiku + tens through Opus ≈ **$10–40/month**, less with prompt caching and the Batch API (50% off) for nightly re-scoring.

### 5.2 News/Event Agent — implement PHASE6B_DESIGN with today's tools

Keep the design (defensive vocabulary, single-source veto, TTL/decay, forward-only validation). Upgrade the mechanics:

- **Structured outputs** instead of "return JSON please": `client.messages.parse(..., output_format=NewsEvent)` with a Pydantic model mirroring PHASE6B §4; invalid → `NO_EFFECT`.
- **Corroboration with server-side tools**: `web_search_20260209` / `web_fetch_20260209` with `allowed_domains` pinned to official and tier-HIGH publishers; the model must cite the second independent source or return `SINGLE_SOURCE`.
- **Prompt caching** on the frozen system prompt + enum tables; **Batch API** for the nightly report and re-scoring.
- **Eval set first**: 100+ labeled headlines (true events, copies, rumors, satire, prompt-injection, homoglyphs) with expected `action`; run on every prompt/model change; target ≥95% schema validity, zero prohibited actions, zero single-source effects.
- Two-stage pipeline: Haiku 5.5 filters to watchlist categories; Opus 5.5 classifies candidates with market context (price/volume from our own feed).

Sketch (Python SDK):

```python
from pydantic import BaseModel
from typing import Literal, List
import anthropic

class NewsEvent(BaseModel):
    category: Literal["ETF_SEC_DECISION","FED_FOMC_RATES","MACRO_CPI_PPI_JOBS",
                      "EXCHANGE_HACK_EXPLOIT","MAJOR_REGULATORY_ACTION","LIQUIDATION_CASCADE",
                      "GEOPOLITICAL_ESCALATION","MAJOR_EXCHANGE_PROTOCOL_INCIDENT","NONE"]
    confidence: float
    corroboration_status: Literal["SINGLE_SOURCE","INDEPENDENT_SOURCE_CONFIRMED",
                                  "PRICE_VOLUME_CONFIRMED","CONFLICTED","REJECTED"]
    action: Literal["BLOCK_NEW_LONGS","REDUCE_SIZE","NO_EFFECT"]
    assets: List[str]
    expires_in_minutes: int
    raw_summary: str

client = anthropic.Anthropic()
resp = client.messages.parse(
    model="claude-opus-5-5",
    max_tokens=2000,
    system=[{"type": "text", "text": SYSTEM_PROMPT_V1, "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": sanitized_batch_json}],
    output_format=NewsEvent,
)
event = resp.parsed_output  # validated; deterministic code applies TTL/decay/veto next
```

The deterministic consumer (`app/news/decay.py`, `overlay.py`) stays exactly as designed: it can only make an allowed entry smaller or blocked.

### 5.3 Research Agent — AI as the quant, not the trader (biggest ROI)

Loop: *hypothesis → implement in the Strategy contract → vectorbt sweep → walk-forward → report → human reads*. Run it with Claude Code (or the Claude Agent SDK on the VPS) in a `research/` sandbox that CI forbids from touching `app/execution`, `app/risk`, `app/exchange`. Ground truth is the validation harness, not the model's opinion. Weekly: the agent proposes ≤3 new hypotheses from the literature list in Section 2.6 and the paper's own failure analysis; anything that passes goes to the paper fleet.

### 5.4 Ops Agent and Operator Copilot

- Daily 07:00 Beirut: digest of journal + heartbeat + reconciliation + news-shadow decisions → Telegram. Implement as a cron script calling the API, or a Claude **Managed Agents scheduled deployment** (beta; cron + budget cap; no exchange access, read-only artifacts).
- Copilot: chat over the DB/journal with **read-only** tools (the "loop stays dumb" pattern); no tool can reach the exchange. Replaces the old OpenClaw idea.

### 5.5 Agent workflow (how we build)

Claude Code builds in bounded PRs; Codex (or a second Claude with `/code-review`) reviews; you approve. Safety-core paths keep the travel-mode guard. Each sprint has a kickoff prompt (Section 10) and a definition of done. Drop ceremony that does not protect money: smoke-test PRs, duplicate governance prose, nightly "resume" scripts.

---

## 6. Data and tooling shopping list

| Need | Source | Cost (Oct 2026) |
|---|---|---|
| Candles, trades, books (spot) | OKX public REST/WS | free |
| Funding, OI, liquidations, long/short, taker volume | OKX public `/public/funding-rate*`, `/public/open-interest`, `/rubik/stat/*`, liquidation WS channel | free |
| Market context | CoinGecko Demo | free (10K calls/mo) |
| Official events | SEC, Fed, BLS, exchange status RSS | free |
| Broad news | GDELT DOC API | free |
| Crypto news | NewsAPI.ai (free 2K searches; $90/mo 5K tokens) · CryptoPanic (check vendor page) | $0–90/mo |
| X watchlist | X API pay-per-use: $0.005 per post read, 3M reads/mo cap | ~$30/mo for a tiny list |
| Derivatives/on-chain premium (later) | Coinglass $29–79 personal ($299 commercial) · CryptoQuant ~$39–109 (credits) | optional |
| Prediction markets (later, signal research only) | Polymarket public API | free |
| Research tooling | vectorbt (OSS; PRO optional), DuckDB, Parquet, Optuna, hmmlearn, LightGBM, MLflow or JSON runs | free |
| Dev tooling | uv, ruff, pytest, Alembic, pip-audit | free |
| Hosting | existing DO Singapore VPS (+ nightly `pg_dump`) | ~$25–85/mo |
| AI | Claude API (Section 5.1) | ~$10–60/mo |

---

## 7. Governance: keep the contract, lose the ceremony

Keep (non-negotiable): demo-only until gates; LLM never places/sizes/approves orders; risk manager final veto; fail-closed; no martingale; PR-only; human approves each phase; secrets never in repo/logs.

Change: one `CHANGELOG.md`; the per-phase docs become short records; a `research/` sandbox with lighter rules; sprint-level definition of done instead of per-file ceremony; remove travel-mode bits that block routine research PRs while keeping the safety-path guard.

---

## 8. Gates before any real money (Phase 7 → 8)

All must be true, each with evidence in the repo:

1. ≥2 strategies with walk-forward PF >1.2 after costs, positive in ≥3 of 4 years, max DD <20%, robust to ±30% parameter changes.
2. ≥60 days forward paper/demo where realized Sharpe and slippage are within tolerance of expectations.
3. Exchange-side stop on 100% of demo positions; drills passed (process killed with open position → stop still fires).
4. Zero unresolved reconciliation inconsistencies in the last 30 days; kill switch and disarm drills logged.
5. News agent: §11 criteria passed; zero prohibited effects.
6. Position persistence across restarts reviewed (today a restart flattens the position).
7. Migrations + backups in place; incident runbook written; Telegram token rotated.
8. Independent review of the full chain; owner signs the capital and scale ladder.

---

## 9. Honest expectations and risks

- The evidence says most bots and all LLM-only traders lose; a validated systematic engine with strict risk control can be modestly positive with controlled drawdowns. "Best possible" means surviving every regime and compounding small edges, not predicting the market.
- Risks: overfitting (mitigated by walk-forward/holdout/deflated Sharpe), regime shifts (regime model + no-trade filter + drawdown ladder), exchange/API changes (changelog monitor in the ops digest — the 8443 cutoff is the example), operational drift (drills), fee drag (maker-first, lower turnover, 4H/6H candidates), news false positives (log-only first).
- Timeline risk: this plan assumes ~2–3 focused sessions per week. With fewer, the sprints stretch; the order does not change.

---

## 10. Kickoff prompts (copy-paste into Claude Code)

**Sprint 0**
```text
Read docs/MASTER_PLAN_2026-10-20.md Sprint 0. On a new branch: remove ":8443" from every WebSocket default and doc (config.py, okx_public_ws.py, okx_demo_endpoints.py, .env.example, docs). Keep validators accepting None/443/8443. Add a test that defaults contain no port. Delete resume_claude_at_1.sh. Bump CI to Python 3.13. Add uv lockfile and pip-audit job. Run pytest and the travel-mode guard. Open a PR; do not merge. Then write a VPS runbook snippet for updating .env and restarting shadow.service.
```

**Sprint 1**
```text
Read docs/MASTER_PLAN_2026-10-20.md Sprint 1. Build scripts/backfill_history.py using app/okx/client.get_history_candles with resumable pagination for BTC-USDT and ETH-USDT at 1m,5m,1H,4H,1D back to 2020; store to Parquet under data/ and expose DuckDB views; add a data-quality report. Add OKX public derivatives collectors (funding, OI, long/short ratio, taker volume, liquidation WS) for *-USDT-SWAP as feature inputs only. Tests for pagination, dedupe, gap detection. Public endpoints only; no credentials.
```

**Sprint 2**
```text
Read docs/MASTER_PLAN_2026-10-20.md Sprint 2 and Section 2.6. Create research/ with a vectorbt sweep harness, walk-forward with purge gap, 12-month untouched holdout, parameter heatmaps, Monte Carlo, deflated Sharpe. Implement S1 TSMOM (multi-lookback, vol-scaled), S2 breakout+volume/ATR, S3 range mean-reversion, S4 vol-compression, S5 funding/OI crowding filter, S0 no-trade filter, all in the existing Strategy contract with ATR stops/targets/time stops. Produce docs/research/ENSEMBLE_V1_REPORT.md with costs 0.10%/side + slippage. Do not touch app/execution, app/risk, app/exchange.
```

**Reviewer (Codex or /code-review)**
```text
Review this PR against PROJECT_RULES.md and docs/MASTER_PLAN_2026-10-20.md. Try to break it: look-ahead bias, timestamp misalignment, cost omissions, unprotected positions, LLM output reaching order logic, secrets. Report findings only; do not approve phases.
```

---

## Sources

Exchanges/brokers: [OKX Agent docs](https://www.okx.com/docs-v5/agent_en/) · [OKX changelog (8443 cutoff)](https://www.okx.com/docs-v5/log_en/) · [Bybit MCP](https://www.aap.com.au/aapreleases/cision20260422ae40834/) · [Gemini Agentic Trading](https://theblock.co/post/399001/gemini-rolls-out-agentic-trading-allowing-ai-bots-to-directly-manage-crypto-exchange-trading-accounts) · [Exchange agent-skills race](https://blockeden.xyz/blog/2026/03/10/exchange-ai-agent-skills-war-binance-okx-bitget-mcp-trading/) · [Brokerage AI agents (Yahoo/Jefferies)](https://finance.yahoo.com/technology/ai/articles/brokerages-accelerate-rollout-ai-trading-140623312.html) · [Composer by SoFi](https://investors.sofi.com/news/news-details/2026/Introducing-Composer-by-SoFi-AI-Powered-Investing-From-Idea-to-Execution/default.aspx) · [Robinhood Cortex engineering](https://robinhood.com/us/en/careers/blog/loop-stays-dumb-so-the-model-can-be-smart/) · [Alpaca MCP server](https://alpaca.markets/mcp-server) · [AI brokers comparison](https://www.finder.com/stock-trading/ai-trading-bot)

Retail bots: [Coin Bureau](https://coinbureau.com/analysis/best-crypto-ai-trading-bots) · [Coinfomania](https://coinfomania.com/top-7-ai-crypto-trading-bots-reviewed-and-tested-in-2026/) · [Intellectia](https://intellectia.ai/blog/ai-crypto-trading-bots-review-2026)

Open source: [TradingAgents](https://github.com/TauricResearch/TradingAgents) · [AgenticTrading](https://github.com/Open-Finance-Lab/AgenticTrading) · [Agentic quant trading survey](https://arxiv.org/pdf/2608.31041) · [nautilus OKX adapter](https://nautilustrader.io/docs/nightly/integrations/okx) · [vectorbt PRO](https://vectorbt.pro/) · [CCXT vs NautilusTrader](https://docs.ccxt.com/docs/comparisons/ccxt-vs-nautilustrader)

Evidence: [Alpha Arena S1](https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/) · [Alpha Arena S1.5](https://forklog.com/en/ai-model-grok-4-2-triumphs-in-trading-tournament/) · [SCMP on Qwen](https://www.scmp.com/tech/tech-trends/article/3331425/alibabas-ai-model-outperforms-us-rivals-crypto-trading-showdown) · [Two fleets, six months (arXiv 2609.05663)](https://arxiv.org/abs/2609.05663) · [Agent Market Arena (arXiv 2510.11695)](https://arxiv.org/abs/2510.11695) · [PolyBench](https://arxiv.org/html/2604.14199v1) · [LiveMACE](https://arxiv.org/html/2610.09872v1) · [StockBench](https://arxiv.org/html/2510.02209v2) · [ChatGPT news sentiment, J. Big Data 2026](https://link.springer.com/article/10.1186/s40537-026-01392-x) · [LLM multi-agent crypto portfolio](https://arxiv.org/html/2501.00826v3) · [AI in markets review (arXiv 2609.04917)](https://arxiv.org/html/2609.04917v1)

Quant literature: [Hudson & Urquhart 2021](https://link.springer.com/article/10.1007/s10479-019-03357-1) · [Liu & Tsyvinski (NBER w24877)](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf) · [Momentum in cryptocurrencies (BATP)](https://www.journals.vu.lt/BATP/en/article/download/44540/42590/138419) · [Risk-managed TSMOM in crypto (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7115459) · [Crypto momentum moments (Springer)](https://link.springer.com/article/10.1007/s11408-025-00474-9) · [Trend following timeframe study (arXiv 2602.11708)](https://arxiv.org/html/2602.11708v1) · [HSMM regimes BTC (Malta)](https://www.um.edu.mt/library/oar/bitstream/123456789/102459/1/BSCT5%20%281%29.pdf) · [Non-homogeneous HMM crypto (arXiv 2011.03741)](https://arxiv.org/pdf/2011.03741.pdf)

Data/pricing: [OKX fees notice](https://www.okx.com/en-us/help/advance-notice-spot-and-futures-trading-fee-adjustment-090926) · [OKX EEA spot fees](https://www.okx.com/en-us/help/what-are-the-new-trading-fees-for-eea-users) · [Coinglass pricing](https://www.coinglass.com/ko/pricing) · [CryptoQuant API update](https://cryptobriefing.com/cryptoquant-api-upgrade-rate-limits/) · [NewsAPI.ai plans](https://newsapi.ai/plans) · [X API pricing](https://docs.x.com/x-api/getting-started/pricing) · [CoinGecko/CMC tiers](https://coinmarketcap.com/academy/es/article/understanding-crypto-api-subscription-models-for-traders-in-2026) · [Polymarket/Kalshi API guide](https://oddspapi.io/blog/?p=97)
