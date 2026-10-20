"""News-ingestion skeleton (Phase 6b design sections 7.1-7.3) — LOG-ONLY, NO LLM.

What this package does: poll a small allowlist of official/public sources
(RSS, GDELT DOC API, optional NewsAPI.ai), sanitize the text (HTML, hidden
characters, homoglyphs, prompt-injection markers), de-duplicate, and append
JSON lines under ``data/news`` (git-ignored) with original and sanitized hashes
for audit.

What it deliberately does NOT do: call any LLM, classify events, produce a
risk action, read exchange or demo-account state, or import anything from the
execution, risk, strategy, or exchange packages. It cannot influence an order.
Classification, corroboration, TTL/decay and the risk overlay remain
unimplemented and require explicit owner authorization (see
``docs/PHASE6B_DESIGN.md`` and ``docs/NEWS_INGESTION.md``).
"""
