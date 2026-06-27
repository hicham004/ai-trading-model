"""A small, boring Telegram notifier for AgentOps travel mode.

Design goals (deliberately minimal):

- One-way, fire-and-forget operator notifications (CI status, PR activity,
  safety-check failures, daily-report-ready).
- **Never logs or echoes secrets.** The bot token and chat id are redacted from
  any returned error text, and the token is never printed.
- **Offline-testable.** The HTTP call is an injectable ``transport`` callable,
  so tests run with a mock and never touch the network. Missing credentials
  produce a clean "skipped" result, not an exception.
- **No trading authority.** This module cannot read or change any exchange,
  order, position, or balance. It only sends text to the operator.

Credentials come from the environment only:

- ``TELEGRAM_BOT_TOKEN``
- ``TELEGRAM_CHAT_ID``
- ``TELEGRAM_DRY_RUN`` (optional; truthy -> format and dedup but never send)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

REDACTION = "***"
_TELEGRAM_API = "https://api.telegram.org"
_TRUTHY = {"1", "true", "yes", "on"}

# Stable, human-readable labels for the events CI/automation reports. Keeping
# these as data (not f-strings scattered around) makes formatting testable.
EVENT_LABELS: dict[str, str] = {
    "ci_pass": "✅ CI passed",
    "ci_fail": "❌ CI failed",
    "pr_opened": "\U0001f4ec PR opened",
    "pr_updated": "\U0001f501 PR updated",
    "safety_fail": "\U0001f6d1 Travel-mode safety check FAILED",
    "report_ready": "\U0001f4ca Daily report ready",
}

# Transport contract: ``transport(url, payload) -> (status_code, body_text)``.
Transport = Callable[[str, dict], "tuple[int, str]"]


def redact(text: str, *secrets: Optional[str]) -> str:
    """Replace every occurrence of each secret with the redaction marker."""
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, REDACTION)
    return out


def format_message(
    event: str,
    *,
    title: Optional[str] = None,
    url: Optional[str] = None,
    details: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    """Build a plain-text notification body. Pure; no secrets involved.

    Unknown events fall back to the raw event name so callers never crash on a
    new event type.
    """
    label = EVENT_LABELS.get(event, event)
    lines = [label if not repo else f"{label} — {repo}"]
    if title:
        lines.append(title)
    if details:
        lines.append(details)
    if url:
        lines.append(url)
    return "\n".join(lines)


@dataclass(frozen=True)
class NotifyResult:
    """Outcome of a send attempt. ``skipped`` explains a non-network no-op."""

    ok: bool
    skipped: Optional[str] = None  # "missing-credentials" | "dry-run" | "deduplicated"
    status_code: Optional[int] = None
    error: Optional[str] = None  # already redacted


def _requests_transport(url: str, payload: dict, *, timeout: float = 10.0) -> "tuple[int, str]":
    """Default transport using ``requests`` (only imported when actually sending)."""
    import requests  # local import: tests inject a mock and never need the network

    resp = requests.post(url, data=payload, timeout=timeout)
    return resp.status_code, resp.text


class TelegramNotifier:
    """Sends short operator messages to a Telegram chat. Secret-safe."""

    def __init__(
        self,
        token: Optional[str],
        chat_id: Optional[str],
        *,
        dry_run: bool = False,
        transport: Optional[Transport] = None,
        min_interval_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._token = token or None
        self._chat_id = chat_id or None
        self._dry_run = bool(dry_run)
        self._transport = transport or _requests_transport
        self._min_interval = max(0.0, float(min_interval_seconds))
        self._clock = clock
        self._last_text: Optional[str] = None
        self._last_time: float = 0.0

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        *,
        transport: Optional[Transport] = None,
        min_interval_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> "TelegramNotifier":
        import os

        env = os.environ if env is None else env
        dry_run = env.get("TELEGRAM_DRY_RUN", "").strip().lower() in _TRUTHY
        return cls(
            token=env.get("TELEGRAM_BOT_TOKEN"),
            chat_id=env.get("TELEGRAM_CHAT_ID"),
            dry_run=dry_run,
            transport=transport,
            min_interval_seconds=min_interval_seconds,
            clock=clock,
        )

    @property
    def configured(self) -> bool:
        return bool(self._token and self._chat_id)

    def _safe(self, text: str) -> str:
        return redact(text, self._token, self._chat_id)

    def send(self, text: str) -> NotifyResult:
        """Send ``text``. Returns a result; never raises for ordinary failures."""
        if not self.configured:
            # No credentials: a clean no-op so CI never fails for lack of a bot.
            return NotifyResult(ok=False, skipped="missing-credentials")

        now = self._clock()
        if (
            self._min_interval > 0.0
            and self._last_text == text
            and (now - self._last_time) < self._min_interval
        ):
            return NotifyResult(ok=True, skipped="deduplicated")

        if self._dry_run:
            self._last_text, self._last_time = text, now
            return NotifyResult(ok=True, skipped="dry-run")

        url = f"{_TELEGRAM_API}/bot{self._token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": text}
        try:
            status, body = self._transport(url, payload)
        except Exception as exc:  # network/transport errors must not crash CI
            return NotifyResult(ok=False, error=self._safe(str(exc)))

        self._last_text, self._last_time = text, now
        ok = 200 <= int(status) < 300
        return NotifyResult(
            ok=ok,
            status_code=int(status),
            error=None if ok else self._safe(body),
        )

    def notify(self, event: str, **fields) -> NotifyResult:
        """Format ``event`` (+fields) and send it."""
        return self.send(format_message(event, **fields))
