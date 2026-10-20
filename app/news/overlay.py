"""Shadow news-risk overlay (PHASE6B_DESIGN sections 7.7, 12 and 13) — pure, log-only.

``evaluate_new_long_entry`` takes a snapshot of ONE candidate *new long entry*
(the baseline Phase 6a decision, read from journal files by the caller) plus
the current news events, and returns what the news layer WOULD have done:

- NO_EFFECT: the baseline decision unchanged (size multiplier 1);
- REDUCE_SIZE: the baseline decision with its size multiplied by a value in (0, 1);
- BLOCK_NEW_LONGS: not allowed (size multiplier 0).

It can only keep, shrink or block. It never allows an entry the baseline
blocked, never raises a size, and has no notion of exits, protective stops,
cancels, the kill switch, disarming or reconciliation: there is no input that
represents them, so it cannot block or delay any of them. Unhealthy news state
(stale store, clock skew, outage) means NO_EFFECT, never a global block.

Nothing here reads credentials, opens a connection or touches an order path.
In Phase 6b the result is journaled only; execution ignores it. Using it to
gate demo or live entries is NOT authorized (separate owner decision).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional, Tuple

from app.news.decay import DEFAULT_POLICY, DecayPolicy, signal_for_instrument
from app.news.schema import Action, NewsEvent, require_utc

OVERLAY_VERSION = "phase6b-overlay-v1"


@dataclass(frozen=True)
class NewLongEntryCandidate:
    """A snapshot of one candidate NEW LONG entry and the baseline verdict on it.

    ``baseline_allowed`` is the existing runtime's decision (mechanical gates and
    the deterministic risk manager); ``baseline_size_fraction`` its approved
    position fraction, when known.
    """

    instrument: str
    decision_time: datetime
    baseline_allowed: bool
    baseline_reason: Optional[str] = None
    baseline_size_fraction: Optional[Decimal] = None
    signal_ref: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, str) or not self.instrument.strip():
            raise ValueError("instrument is required")
        object.__setattr__(self, "decision_time", require_utc(self.decision_time))
        if not isinstance(self.baseline_allowed, bool):
            raise ValueError("baseline_allowed must be a bool")
        fraction = self.baseline_size_fraction
        if fraction is not None:
            fraction = Decimal(str(fraction))
            if not fraction.is_finite() or not Decimal(0) <= fraction <= Decimal(1):
                raise ValueError("baseline_size_fraction must be in [0, 1]")
            object.__setattr__(self, "baseline_size_fraction", fraction)


@dataclass(frozen=True)
class NewsOverlayDecision:
    """The hypothetical news effect on one new long entry (design 12 shape + audit fields)."""

    instrument: str
    decision_time: datetime
    allowed: bool
    reason: str
    action: Action
    event_id: Optional[str]
    size_multiplier: Decimal
    effective_severity: float
    baseline_allowed: bool
    baseline_reason: Optional[str]
    baseline_size_fraction: Optional[Decimal]
    adjusted_size_fraction: Optional[Decimal]
    would_have_blocked_here: bool
    would_have_reduced_here: bool
    active_event_ids: Tuple[str, ...] = field(default_factory=tuple)
    signal_ref: str = ""
    policy_version: str = ""
    overlay_version: str = OVERLAY_VERSION

    def to_log_record(self) -> dict:
        return {
            "kind": "shadow_entry_overlay",
            "instrument": self.instrument,
            "decision_time": self.decision_time.isoformat(),
            "signal_ref": self.signal_ref,
            "allowed": self.allowed,
            "reason": self.reason,
            "action": self.action.value,
            "event_id": self.event_id,
            "active_event_ids": list(self.active_event_ids),
            "size_multiplier": str(self.size_multiplier),
            "effective_severity": round(self.effective_severity, 6),
            "baseline_allowed": self.baseline_allowed,
            "baseline_reason": self.baseline_reason,
            "baseline_size_fraction": None if self.baseline_size_fraction is None else str(self.baseline_size_fraction),
            "adjusted_size_fraction": None if self.adjusted_size_fraction is None else str(self.adjusted_size_fraction),
            "would_have_blocked_here": self.would_have_blocked_here,
            "would_have_reduced_here": self.would_have_reduced_here,
            "policy_version": self.policy_version,
            "overlay_version": self.overlay_version,
        }


def evaluate_new_long_entry(
    candidate: NewLongEntryCandidate,
    events: Iterable[NewsEvent],
    *,
    news_healthy: bool = True,
    policy: DecayPolicy = DEFAULT_POLICY,
) -> NewsOverlayDecision:
    """Pure: same inputs, same decision; inputs are never mutated."""
    if not isinstance(candidate, NewLongEntryCandidate):
        raise TypeError("the news overlay only evaluates NewLongEntryCandidate snapshots")
    base_fraction = candidate.baseline_size_fraction

    def decision(action: Action, multiplier: Decimal, reason: str, *, event_id=None, severity=0.0, active=()) -> NewsOverlayDecision:
        allowed = candidate.baseline_allowed and action is not Action.BLOCK_NEW_LONGS
        adjusted = None if base_fraction is None else (base_fraction * multiplier if allowed else Decimal(0))
        return NewsOverlayDecision(
            instrument=candidate.instrument,
            decision_time=candidate.decision_time,
            allowed=allowed,
            reason=reason,
            action=action,
            event_id=event_id,
            size_multiplier=multiplier,
            effective_severity=severity,
            baseline_allowed=candidate.baseline_allowed,
            baseline_reason=candidate.baseline_reason,
            baseline_size_fraction=base_fraction,
            adjusted_size_fraction=adjusted,
            # A baseline that already said no is never counted as a prevented trade.
            would_have_blocked_here=candidate.baseline_allowed and action is Action.BLOCK_NEW_LONGS,
            would_have_reduced_here=candidate.baseline_allowed and action is Action.REDUCE_SIZE,
            active_event_ids=tuple(active),
            signal_ref=candidate.signal_ref,
            policy_version=policy.version,
        )

    if not news_healthy:
        return decision(Action.NO_EFFECT, Decimal(1), "news_unhealthy")
    try:
        combined, _ = signal_for_instrument(tuple(events), candidate.instrument, candidate.decision_time, policy)
    except Exception as exc:  # malformed input is a news failure: NO_EFFECT, never a block
        return decision(Action.NO_EFFECT, Decimal(1), f"news_error:{type(exc).__name__}")
    multiplier = combined.size_multiplier
    if not Decimal(0) <= multiplier <= Decimal(1):  # defensive: a multiplier can never raise size
        return decision(Action.NO_EFFECT, Decimal(1), "news_error:multiplier_out_of_range")
    reason = {
        Action.NO_EFFECT: "news_no_effect",
        Action.REDUCE_SIZE: "news_reduce_size",
        Action.BLOCK_NEW_LONGS: "news_block_new_longs",
    }[combined.action]
    if not candidate.baseline_allowed:
        reason = "baseline_blocked"
    return decision(
        combined.action,
        multiplier,
        reason,
        event_id=combined.deciding_event_id,
        severity=combined.effective_severity,
        active=combined.active_event_ids,
    )
