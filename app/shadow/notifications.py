"""Telegram notifications for the Phase 6a shadow supervisor.

This module is observability only. It reads already-persisted supervisor/runtime
state and sends one-way operator messages. Notification failures are swallowed
so a bad token, network outage, or Telegram error can never affect trading,
arming, exits, reconciliation, or supervisor control flow.
"""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Callable, Mapping, Optional, Protocol

from app.logging_config import get_logger
from app.notify.telegram import TelegramNotifier

logger = get_logger(__name__)

DEFAULT_DEDUPE_SECONDS = 300.0
DEFAULT_DEDUPE_MAX_KEYS = 256


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class EventNotifier(Protocol):
    def notify(self, event: str, **fields):
        ...


class ShadowTelegramNotifications:
    """Secret-safe, best-effort shadow-run notification facade."""

    def __init__(
        self,
        notifier: Optional[EventNotifier] = None,
        *,
        clock: Callable[[], datetime] = _utcnow,
        dedupe_seconds: float = DEFAULT_DEDUPE_SECONDS,
        max_dedupe_keys: int = DEFAULT_DEDUPE_MAX_KEYS,
        inline: bool = False,
    ) -> None:
        self._notifier = notifier if notifier is not None else TelegramNotifier.from_env()
        self._clock = clock
        self._dedupe_seconds = max(0.0, float(dedupe_seconds))
        self._max_dedupe_keys = max(1, int(max_dedupe_keys))
        self._inline = inline
        self._last_sent: dict[str, datetime] = {}

    @classmethod
    def from_env(
        cls,
        *,
        clock: Callable[[], datetime] = _utcnow,
        dedupe_seconds: float = DEFAULT_DEDUPE_SECONDS,
        max_dedupe_keys: int = DEFAULT_DEDUPE_MAX_KEYS,
    ) -> "ShadowTelegramNotifications":
        return cls(
            clock=clock,
            dedupe_seconds=dedupe_seconds,
            max_dedupe_keys=max_dedupe_keys,
        )

    def fill_observed(self, fill: Mapping[str, object]) -> bool:
        fill_id = str(fill.get("fill_id") or fill.get("row_id") or "unknown")
        side = str(fill.get("side") or "?")
        size = str(fill.get("fill_size") or "?")
        price = str(fill.get("fill_price") or "?")
        instrument = str(fill.get("instrument") or "?")
        source = str(fill.get("source") or "?")
        return self._send(
            "shadow_fill",
            key=f"fill:{fill_id}",
            title=f"Shadow fill observed: {side} {size} {instrument} @ {price}",
            details=f"source={source} fill_id={fill_id}",
        )

    def alert_written(self, *, reason: str, alert_type: str = "halt") -> bool:
        return self._send(
            "shadow_alert",
            key=f"alert:{alert_type}:{reason}",
            title=f"Shadow ALERT written: {reason}",
            details=f"type={alert_type}; operator review required",
        )

    def heartbeat_stale(self, *, age_seconds: float, threshold_seconds: float) -> bool:
        return self._send(
            "shadow_heartbeat_stale",
            key="heartbeat_stale",
            title="Shadow runtime heartbeat stale",
            details=(
                f"age_seconds={age_seconds:.1f}; "
                f"threshold_seconds={threshold_seconds:.1f}"
            ),
        )

    def private_ws_auth_drop(
        self, *, unhealthy_seconds: float, threshold_seconds: float
    ) -> bool:
        return self._send(
            "shadow_private_ws_auth_drop",
            key="private_ws_auth_drop",
            title="Shadow private WS auth unhealthy",
            details=(
                f"unhealthy_seconds={unhealthy_seconds:.1f}; "
                f"threshold_seconds={threshold_seconds:.1f}"
            ),
        )

    def permanent_halt(self, *, reason: str) -> bool:
        return self._send(
            "shadow_permanent_halt",
            key=f"permanent_halt:{reason}",
            title=f"Shadow supervisor permanent halt: {reason}",
            details="shadow run stopped fail-closed; operator action required",
        )

    def disarmed(self, *, reason: str) -> bool:
        return self._send(
            "shadow_disarmed",
            key="shadow_disarmed",
            title="Shadow runtime disarmed",
            details=f"reason={reason}",
        )

    def _send(
        self,
        event: str,
        *,
        key: str,
        title: str,
        details: Optional[str] = None,
    ) -> bool:
        now = self._clock()
        self._prune_dedupe(now)
        last = self._last_sent.get(key)
        if last is not None and (now - last).total_seconds() < self._dedupe_seconds:
            return False

        # Mark before sending: a failing token/network must not generate a tight
        # retry loop in the supervisor.
        self._last_sent[key] = now
        self._prune_dedupe(now)
        if self._inline:
            return self._deliver(event, title=title, details=details)
        try:
            thread = threading.Thread(
                target=self._deliver,
                kwargs={"event": event, "title": title, "details": details},
                name="shadow-telegram-notify",
                daemon=True,
            )
            thread.start()
        except Exception as exc:
            logger.warning(
                "shadow notification dispatch failed",
                extra={"event": event, "error_type": type(exc).__name__},
            )
            return False
        return True

    def _prune_dedupe(self, now: datetime) -> None:
        if self._dedupe_seconds > 0:
            expired = [
                key for key, sent_at in self._last_sent.items()
                if (now - sent_at).total_seconds() >= self._dedupe_seconds
            ]
            for key in expired:
                self._last_sent.pop(key, None)
        while len(self._last_sent) > self._max_dedupe_keys:
            self._last_sent.pop(next(iter(self._last_sent)), None)

    def _deliver(
        self, event: str, *, title: str, details: Optional[str] = None
    ) -> bool:
        try:
            result = self._notifier.notify(event, title=title, details=details)
        except Exception as exc:
            logger.warning(
                "shadow notification failed",
                extra={"event": event, "error_type": type(exc).__name__},
            )
            return False
        if not getattr(result, "ok", False) and not getattr(result, "skipped", None):
            logger.warning(
                "shadow notification was not delivered",
                extra={
                    "event": event,
                    "status_code": getattr(result, "status_code", None),
                },
            )
            return False
        return True
