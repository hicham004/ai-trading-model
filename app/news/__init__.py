"""Phase 6b news/event agent — LOG-ONLY (owner-authorized June 30, 2026, issue #12).

Ingestion (Sprint 1, design 7.1-7.3): poll a small allowlist of official/public
sources (``sources``, ``fetch``), sanitize the text (``sanitize``: HTML, hidden
characters, homoglyphs, prompt-injection markers), de-duplicate (``dedup``) and
append JSON lines under ``data/news`` (``store``, ``pipeline``).

Agent core (Sprint 4a, design 4-7, 9, 13):

- ``schema``      the design's event model and enums, and the LLM output models;
- ``classifier``  Haiku 5.5 triage + Opus 5.5 classification (structured
                  outputs); any failure or a missing ANTHROPIC_API_KEY is NO_EFFECT;
- ``corroborate`` independent-source rules and price/volume confirmation from
                  public candles closed before the decision;
- ``decay``       TTL, monotonic decay, source weights, thresholds, the
                  effective signal, event assembly and same-story merging;
- ``overlay``     a pure function that can only block or shrink a NEW long entry;
- ``store``       append-only JSONL event and decision logs (``logs/news_shadow``).

Eval (Sprint 4b, design 15): ``evaluation`` runs the labeled synthetic stories in
``tests/fixtures/news_eval`` through the same path and scores schema validity,
prohibited actions, single-source effects and accuracy
(``scripts/eval_news_classifier.py``; the model is called only with a key).

The action vocabulary is BLOCK_NEW_LONGS, REDUCE_SIZE and NO_EFFECT only. No
module here imports execution, risk, strategy, broker or exchange code, reads
exchange or demo-account state, or reaches an order path; nothing in the
trading runtime imports this package (tests enforce both directions). Using the
overlay to gate demo or live entries is NOT authorized and needs a separate
owner decision.
"""
