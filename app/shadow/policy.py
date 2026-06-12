"""Pure Phase 6a supervision policy (no I/O, no network, fully unit-testable).

Encodes the owner's shadow-period rules:

* The supervisor may re-arm after a CLEAN gated restart (gate consistent and
  armable).
* ANY reconcile inconsistency, wrong-account-scope, or foreign detection means
  PERMANENT disarm until the operator intervenes (no auto-recovery).
* Restart attempts are bounded (``max_restarts`` within
  ``restart_window_seconds``); exhausting the budget is also a permanent halt.
* Shadow caps: at most ``max_entries_per_day`` entry intents per UTC day, and
  a ``max_daily_loss_usdt`` equity drawdown from the day's baseline, after
  which trading is disarmed for the rest of the day (kill switch blocks new
  entries; protective exits stay possible).
* The supervisor may auto-release the kill switch on a new UTC day ONLY if it
  engaged it itself (cap enforcement). An operator-engaged kill switch is
  never auto-released.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Tuple


class GateDecision(str, Enum):
    PROCEED = "proceed"
    RETRY = "retry"
    HALT = "halt"


class CapBreach(str, Enum):
    NONE = "none"
    ENTRIES_PER_DAY = "entries_per_day"
    DAILY_LOSS = "daily_loss"


# Kill-switch ownership labels the supervisor records when IT engages the
# switch. Anything else (including None) is treated as operator-owned.
SUPERVISOR_KILL_OWNERS = ("entries_per_day", "daily_loss")

# Gate issue substrings that mean a human must look before anything re-arms.
_HALT_MARKERS = (
    "foreign",
    "wrong account scope",
    "unexplained",
    "ambiguous",  # ambiguous demo account selection (partition guard)
)
# Gate issue substrings that are transient infrastructure failures: a bounded
# retry is allowed (the restart budget still applies).
_TRANSIENT_MARKERS = (
    "runtime lock unavailable",
    "time sync failed",
    "account validation unavailable",
    "reconciliation unavailable",
)


@dataclass
class ShadowPolicy:
    """Decision logic parameterized by the persisted shadow config values."""

    max_restarts: int
    restart_window_seconds: float
    max_entries_per_day: int
    max_daily_loss_usdt: Decimal
    restarts: List[datetime] = field(default_factory=list)

    # -- gate classification --------------------------------------------------

    def classify_gate(
        self,
        *,
        lock_acquired: bool,
        account_valid: bool,
        consistent: bool,
        armable: bool,
        issues: List[str],
    ) -> Tuple[GateDecision, str]:
        """Classify one startup-gate outcome.

        Permanent-halt markers win over transient markers: if reconciliation
        names anything foreign / wrong-scope / unexplained / ambiguous, no
        retry is allowed regardless of other issues.
        """
        joined = " | ".join(issues).lower()
        for marker in _HALT_MARKERS:
            if marker in joined:
                return GateDecision.HALT, f"gate_issue:{marker.replace(' ', '_')}"
        if lock_acquired and account_valid and consistent and armable:
            return GateDecision.PROCEED, "gate_clean"
        for marker in _TRANSIENT_MARKERS:
            if marker in joined:
                return GateDecision.RETRY, f"transient:{marker.replace(' ', '_')}"
        if not consistent:
            # Reconciliation ran and the ledger genuinely disagrees with the
            # exchange (no transient marker explains it): operator required.
            return GateDecision.HALT, "reconcile_inconsistent"
        if not account_valid:
            # Account validation FAILED (wrong mode/level): config problem a
            # restart cannot fix.
            return GateDecision.HALT, "account_validation_failed"
        # Armable False with consistent True means unresolved/ambiguous orders
        # remain; gate re-queries on every restart, so bounded retry.
        return GateDecision.RETRY, "not_armable_yet"

    @staticmethod
    def classify_reconcile_row(
        *, consistent: bool, foreign_orders: int, wrong_scope: int, unexplained: int
    ) -> Optional[str]:
        """Return a permanent-halt reason for a reconciliation row, or None."""
        if foreign_orders > 0:
            return "reconcile_foreign_orders"
        if wrong_scope > 0:
            return "reconcile_wrong_account_scope"
        if unexplained > 0:
            return "reconcile_unexplained_balances"
        if not consistent:
            return "reconcile_inconsistent"
        return None

    # -- restart budget --------------------------------------------------------

    def record_restart(self, now: datetime) -> bool:
        """Record one restart; return True while the budget allows another."""
        cutoff = now - timedelta(seconds=self.restart_window_seconds)
        self.restarts = [t for t in self.restarts if t > cutoff]
        self.restarts.append(now)
        return len(self.restarts) <= self.max_restarts

    def restarts_in_window(self, now: datetime) -> int:
        cutoff = now - timedelta(seconds=self.restart_window_seconds)
        return len([t for t in self.restarts if t > cutoff])

    # -- shadow caps -----------------------------------------------------------

    def check_caps(
        self, *, entries_today: int, day_pnl_usdt: Optional[Decimal]
    ) -> CapBreach:
        """Evaluate the persisted shadow caps.

        ``day_pnl_usdt`` is None when equity cannot currently be marked (no
        usable quote / no balance snapshot); the loss cap is then NOT
        evaluated — the driver itself already blocks entries on stale feeds,
        and guessing a PnL would be worse than waiting one tick.
        """
        if entries_today >= self.max_entries_per_day:
            return CapBreach.ENTRIES_PER_DAY
        if day_pnl_usdt is not None and day_pnl_usdt <= -self.max_daily_loss_usdt:
            return CapBreach.DAILY_LOSS
        return CapBreach.NONE

    # -- kill-switch ownership ---------------------------------------------------

    @staticmethod
    def may_auto_release(
        *, engaged: bool, owner: Optional[str], capped_day: Optional[date], today: date
    ) -> bool:
        """True only for a supervisor-owned engagement on a NEW UTC day."""
        if not engaged or owner not in SUPERVISOR_KILL_OWNERS:
            return False
        return capped_day is None or capped_day < today
