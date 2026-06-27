"""Operator notifications (observability only).

This package sends one-way status notifications to the operator (Telegram). It
is an observability surface, NOT part of the trading/risk/execution path: it
can read nothing about and authorize nothing on the exchange. It never logs or
echoes secrets.
"""

from app.notify.telegram import (
    EVENT_LABELS,
    NotifyResult,
    TelegramNotifier,
    format_message,
    redact,
)

__all__ = [
    "EVENT_LABELS",
    "NotifyResult",
    "TelegramNotifier",
    "format_message",
    "redact",
]
