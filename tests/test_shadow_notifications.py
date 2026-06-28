"""Offline tests for shadow-run Telegram notification facade."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.shadow.notifications import ShadowTelegramNotifications

UTC = timezone.utc


class RecordingNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, event: str, **fields):
        self.calls.append((event, fields))
        return SimpleNamespace(ok=True, skipped=None, status_code=200)


class FailingNotifier:
    def notify(self, event: str, **fields):
        raise RuntimeError("network down")


def test_shadow_notification_events_send_to_underlying_notifier():
    notifier = RecordingNotifier()
    sink = ShadowTelegramNotifications(notifier, dedupe_seconds=60, inline=True)

    assert sink.fill_observed(
        {
            "fill_id": "fill-1",
            "instrument": "BTC-USDT",
            "side": "buy",
            "fill_size": "0.001",
            "fill_price": "65000",
            "source": "ws",
        }
    )
    assert sink.alert_written(reason="restart_budget_exhausted", alert_type="halt")
    assert sink.heartbeat_stale(age_seconds=75, threshold_seconds=60)
    assert sink.private_ws_auth_drop(unhealthy_seconds=35, threshold_seconds=30)
    assert sink.permanent_halt(reason="reconcile_inconsistent")
    assert sink.disarmed(reason="operator_stop")

    assert [event for event, _ in notifier.calls] == [
        "shadow_fill",
        "shadow_alert",
        "shadow_heartbeat_stale",
        "shadow_private_ws_auth_drop",
        "shadow_permanent_halt",
        "shadow_disarmed",
    ]
    assert "buy 0.001 BTC-USDT @ 65000" in notifier.calls[0][1]["title"]


def test_shadow_notification_failure_is_swallowed():
    sink = ShadowTelegramNotifications(FailingNotifier(), dedupe_seconds=0, inline=True)

    assert not sink.fill_observed({"fill_id": "fill-1"})
    assert not sink.alert_written(reason="alert", alert_type="halt")
    assert not sink.heartbeat_stale(age_seconds=75, threshold_seconds=60)
    assert not sink.private_ws_auth_drop(unhealthy_seconds=35, threshold_seconds=30)
    assert not sink.permanent_halt(reason="halt")
    assert not sink.disarmed(reason="attempt_cleanup")


def test_shadow_notification_dedupes_by_event_key():
    now = {"value": datetime(2026, 6, 28, 12, 0, tzinfo=UTC)}
    notifier = RecordingNotifier()
    sink = ShadowTelegramNotifications(
        notifier, clock=lambda: now["value"], dedupe_seconds=60, inline=True
    )

    assert sink.heartbeat_stale(age_seconds=75, threshold_seconds=60)
    assert not sink.heartbeat_stale(age_seconds=80, threshold_seconds=60)
    assert len(notifier.calls) == 1

    now["value"] += timedelta(seconds=61)
    assert sink.heartbeat_stale(age_seconds=141, threshold_seconds=60)
    assert len(notifier.calls) == 2

    assert sink.fill_observed({"fill_id": "fill-1"})
    assert not sink.fill_observed({"fill_id": "fill-1"})
    assert sink.fill_observed({"fill_id": "fill-2"})
    assert [event for event, _ in notifier.calls[-2:]] == [
        "shadow_fill",
        "shadow_fill",
    ]


def test_shadow_notification_dedupe_store_is_bounded_and_ttl_pruned():
    now = {"value": datetime(2026, 6, 28, 12, 0, tzinfo=UTC)}
    notifier = RecordingNotifier()
    sink = ShadowTelegramNotifications(
        notifier,
        clock=lambda: now["value"],
        dedupe_seconds=60,
        max_dedupe_keys=3,
        inline=True,
    )

    for i in range(10):
        assert sink.fill_observed({"fill_id": f"fill-{i}"})

    assert len(sink._last_sent) == 3
    assert set(sink._last_sent) == {"fill:fill-7", "fill:fill-8", "fill:fill-9"}

    now["value"] += timedelta(seconds=61)
    assert sink.heartbeat_stale(age_seconds=90, threshold_seconds=60)
    assert len(sink._last_sent) == 1
    assert set(sink._last_sent) == {"heartbeat_stale"}
