# Phase 3B Review Notes

**Status: Independent adversarial review completed; explicitly accepted by the
human owner on June 9, 2026.**

Claude Code reviewed Phase 3B after the Codex implementation pass. The review
covered order-book integrity, candle backfill, persistence/restart behavior,
read-only API enforcement, shutdown behavior, and secret leakage.

## Review verdict

No blocking implementation defects were found.

Verified strengths:

- order-book snapshots, increments, keepalives, sequence gaps, maintenance
  resets, malformed frames, and reconnect behavior fail closed;
- candle gap math, bounded 300-bar public REST repair, window filtering, and
  duplicate prevention are correct;
- persistence remains outside the WebSocket receive path, retries failed
  writes, is restart-idempotent, and bounds stored book samples;
- all live API routes are read-only;
- shutdown tasks are supervised and reaped;
- persistence errors expose exception types only, not connection details; and
- no private endpoint, authentication, account, order, or withdrawal path was
  added.

## Checksum finding disposition

The reviewer suggested adding CRC32 checksum validation. This is intentionally
not implemented and is not a remaining defect.

OKX announced on May 21, 2026 that the JSON order-book `checksum` field is
being deprecated:

- demo environment: June 2, 2026;
- production environment: June 23, 2026.

After deprecation, the field remains present but always returns `0` and must
not be used for integrity verification. OKX directs clients to migrate to
strict `seqId`/`prevSeqId` validation and TLS, which the Phase 3B adapter
already enforces. Adding checksum as a required gate would create a known
failure on June 23, 2026.

Official references:

- <https://www.okx.com/en-us/help/okx-order-book-channels-checksum-field-deprecation>
- <https://www.okx.com/docs-v5/log_en/>

## Accepted design choices

- **No initial-history backfill on an empty database:** intentional. The live
  persistence worker repairs continuity after a known stored/live boundary;
  historical seeding remains the explicit `fetch_candles.py` workflow.
- **No candle retention cap:** intentional. Candles are the long-term research
  dataset. Only high-frequency sampled order books receive retention pruning.

## Gate status

Phase 3B has implementation, normal/adverse tests, documentation, builder
verification, and independent adversarial review with no blocker and no
required follow-up. The human owner explicitly accepted Phase 3B and authorized
the checkpoint commit on June 9, 2026. Acceptance is limited to public-data
observation, integrity, and optional public-data storage; it does not authorize
Phase 4.
