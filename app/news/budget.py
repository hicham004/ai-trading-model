"""Monthly spend cap for the news shadow's model calls (master plan 5.1; plan rows R4c and G5).

Every model call is priced from the token usage the API reports, at the list
prices in ``evaluation.PRICES_PER_MTOK`` (Claude Haiku 5.5 and Opus 5.5, October
2026; every cache write at the 1-hour rate, 2x input). Before a call, its WORST
case — the whole prompt priced as a cache write, plus ``max_tokens`` of output —
is reserved, and the call is made only if the reservation fits:

- the monthly cap (UTC calendar month), and
- the day's pace: what is left of the month, divided by the days left in it
  (today included), times ``daily_pace``. Unused budget rolls forward, and a news
  flood cannot spend the month in a few days. ``daily_pace = 0`` turns pacing off.

A call that does not fit is never made: the classifier reports it unavailable,
so the story is NO_EFFECT (design 13). After the call the reservation is
replaced by the actual cost. A timed-out request is charged its full worst case
(the API may have run it to the end); other failures are not billed and cost
nothing. Retries are made here, one reservation per attempt, never by the SDK.

The spend is an ESTIMATE from list prices. The spend limit on the API key in the
Anthropic console is the hard backstop. State: one small JSON file per month,
written atomically; an unreadable state file counts as a fully spent month (the
guard fails toward not spending) until the operator checks and removes it.
"""

from __future__ import annotations

import calendar
import json
import math
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from app.news.classifier import api_failure_code
from app.news.evaluation import PRICES_PER_MTOK, base_model, estimate_cost

SPEND_STATE_VERSION = "news-shadow-spend-v1"
MONTHLY_CAP_ENV = "NEWS_SHADOW_MONTHLY_CAP_USD"
DAILY_PACE_ENV = "NEWS_SHADOW_DAILY_PACE"
DEFAULT_MONTHLY_CAP_USD = 40.0
DEFAULT_DAILY_PACE = 2.0
# Conservative prompt size: real text averages 3-4 characters per token; 2 overstates it.
CHARS_PER_TOKEN_BOUND = 2.0
_MOST_EXPENSIVE = max(PRICES_PER_MTOK.values(), key=lambda p: p["output"])


class SpendCapReached(RuntimeError):
    """Raised by ``BudgetedClient`` instead of making a call that does not fit the budget."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _prices(model: Optional[str]) -> Mapping[str, float]:
    # An unknown model is priced like the most expensive known one (never cheaper).
    return PRICES_PER_MTOK.get(base_model(model), _MOST_EXPENSIVE)


def prompt_tokens_bound(chars: int) -> int:
    return int(math.ceil(max(0, int(chars)) / CHARS_PER_TOKEN_BOUND))


def worst_case_cost(model: Optional[str], *, input_chars: int, max_tokens: int) -> float:
    """Upper bound of one call: the whole prompt as a cache write plus ``max_tokens`` of output."""
    prices = _prices(model)
    per_input = max(prices["input"], prices["cache_write"])
    return (prompt_tokens_bound(input_chars) * per_input + max(0, int(max_tokens)) * prices["output"]) / 1_000_000


def usage_cost(model: Optional[str], usage: Mapping[str, int]) -> float:
    cost = estimate_cost(model, usage)
    if cost is None:  # a model without a price row: price it like the most expensive one
        p = _MOST_EXPENSIVE
        cost = (
            usage.get("input_tokens", 0) * p["input"]
            + usage.get("output_tokens", 0) * p["output"]
            + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
            + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]
        ) / 1_000_000
    return float(cost)


def env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")
    return value


def _utc(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("the spend guard needs timezone-aware times")
    return now.astimezone(timezone.utc)


def _empty_state(month: str) -> Dict[str, Any]:
    return {
        "version": SPEND_STATE_VERSION,
        "month": month,
        "spent_usd": 0.0,
        "by_day": {},
        "by_model": {},
        "calls": 0,
        "refused": {},
    }


@dataclass(frozen=True)
class SpendSnapshot:
    month: str
    cap_usd: float
    spent_usd: float
    today_usd: float
    remaining_usd: float
    day_limit_usd: Optional[float]
    daily_pace: float
    calls: int
    refused: Mapping[str, int]
    state_error: Optional[str]

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "cap_usd": round(self.cap_usd, 6),
            "spent_usd": round(self.spent_usd, 6),
            "today_usd": round(self.today_usd, 6),
            "remaining_usd": round(self.remaining_usd, 6),
            "day_limit_usd": None if self.day_limit_usd is None else round(self.day_limit_usd, 6),
            "daily_pace": self.daily_pace,
            "calls": self.calls,
            "refused": dict(self.refused),
            "state_error": self.state_error,
        }


class SpendGuard:
    """Monthly cap with daily pacing; thread-safe; persisted per month."""

    def __init__(
        self,
        state_dir: Optional[Path],
        *,
        monthly_cap_usd: float = DEFAULT_MONTHLY_CAP_USD,
        daily_pace: float = DEFAULT_DAILY_PACE,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
    ) -> None:
        cap = float(monthly_cap_usd)
        pace = float(daily_pace)
        if not math.isfinite(cap) or cap < 0:
            raise ValueError("the monthly cap must be a non-negative number of US dollars")
        if not math.isfinite(pace) or pace < 0:
            raise ValueError("the daily pace must be a non-negative number (0 turns pacing off)")
        self._dir = Path(state_dir) if state_dir is not None else None
        self._cap = cap
        self._pace = pace
        self._clock = clock
        self._lock = threading.RLock()
        self._state: Optional[Dict[str, Any]] = None
        self._state_error: Optional[str] = None
        self._reserved = 0.0

    @property
    def monthly_cap_usd(self) -> float:
        return self._cap

    @property
    def daily_pace(self) -> float:
        return self._pace

    def state_file(self, month: str) -> Optional[Path]:
        return None if self._dir is None else self._dir / f"spend-{month}.json"

    # -- state --------------------------------------------------------------------------

    def _load(self, now: datetime) -> Dict[str, Any]:
        month = f"{now:%Y-%m}"
        if self._state is not None and self._state.get("month") == month:
            return self._state
        self._state_error = None
        path = self.state_file(month)
        state = _empty_state(month)
        if path is not None and path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict) or loaded.get("month") != month:
                    raise ValueError("state file is for another month")
                spent = float(loaded.get("spent_usd", 0.0))
                if not math.isfinite(spent) or spent < 0:
                    raise ValueError("spent_usd is not a non-negative number")
                state.update({k: loaded[k] for k in ("by_day", "by_model", "calls", "refused") if k in loaded})
                state["spent_usd"] = spent
            except (OSError, ValueError, TypeError) as exc:
                # Fail toward not spending: an unreadable record counts as a spent month.
                self._state_error = f"unreadable spend state ({type(exc).__name__}); treated as fully spent"
        self._state = state
        return state

    def _save(self) -> None:
        if self._dir is None or self._state is None or self._state_error:
            return
        path = self.state_file(self._state["month"])
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self._state, sort_keys=True, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    # -- the rule -----------------------------------------------------------------------

    def _numbers(self, now: datetime) -> Dict[str, Any]:
        state = self._load(now)
        today = now.date().isoformat()
        spent = self._cap if self._state_error else float(state["spent_usd"])
        today_spent = float(state["by_day"].get(today, 0.0))
        day_limit = None
        if self._pace > 0:
            days_in_month = calendar.monthrange(now.year, now.month)[1]
            days_left = days_in_month - now.day + 1
            before_today = max(0.0, spent - today_spent)
            day_limit = max(0.0, self._cap - before_today) / days_left * self._pace
        return {"state": state, "spent": spent, "today": today_spent, "day_limit": day_limit}

    def refusal(self, amount: float, now: Optional[datetime] = None) -> Optional[str]:
        """Why a call costing at most ``amount`` may not be made now (None = it may)."""
        now = _utc(now or self._clock())
        with self._lock:
            n = self._numbers(now)
            if n["spent"] + self._reserved + amount > self._cap + 1e-12:
                return "monthly_cap"
            if n["day_limit"] is not None and n["today"] + self._reserved + amount > n["day_limit"] + 1e-12:
                return "daily_pace"
            return None

    def reserve(self, amount: float, now: Optional[datetime] = None) -> Optional[str]:
        """Reserve ``amount`` for one call; returns the refusal reason instead when it does not fit."""
        now = _utc(now or self._clock())
        with self._lock:
            reason = self.refusal(amount, now)
            if reason is not None:
                state = self._load(now)
                state["refused"][reason] = int(state["refused"].get(reason, 0)) + 1
                self._save()
                return reason
            self._reserved += amount
            return None

    def settle(self, reserved: float, cost: float, model: Optional[str], now: Optional[datetime] = None) -> None:
        """Replace a reservation by the call's actual cost (0 when it was never billed)."""
        now = _utc(now or self._clock())
        with self._lock:
            self._reserved = max(0.0, self._reserved - reserved)
            if cost <= 0:
                return
            state = self._load(now)
            day = now.date().isoformat()
            key = base_model(model) or "unknown"
            state["spent_usd"] = float(state["spent_usd"]) + cost
            state["by_day"][day] = float(state["by_day"].get(day, 0.0)) + cost
            state["by_model"][key] = float(state["by_model"].get(key, 0.0)) + cost
            state["calls"] = int(state["calls"]) + 1
            self._save()

    def snapshot(self, now: Optional[datetime] = None) -> SpendSnapshot:
        now = _utc(now or self._clock())
        with self._lock:
            n = self._numbers(now)
            state = n["state"]
            return SpendSnapshot(
                month=state["month"],
                cap_usd=self._cap,
                spent_usd=n["spent"],
                today_usd=n["today"],
                remaining_usd=max(0.0, self._cap - n["spent"]),
                day_limit_usd=n["day_limit"],
                daily_pace=self._pace,
                calls=int(state["calls"]),
                refused={str(k): int(v) for k, v in sorted(state["refused"].items())},
                state_error=self._state_error,
            )

    @staticmethod
    def read_month(state_dir: Path, month: str) -> Optional[Dict[str, Any]]:
        """The persisted record of one month, for reports (None when absent or unreadable)."""
        path = Path(state_dir) / f"spend-{month}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None


class _Messages:
    def __init__(self, create: Callable[..., Any]) -> None:
        self.create = create


def _request_chars(kwargs: Mapping[str, Any]) -> int:
    chars = 0
    system = kwargs.get("system")
    if isinstance(system, str):
        chars += len(system)
    elif isinstance(system, (list, tuple)):
        chars += sum(len(str(block.get("text", ""))) for block in system if isinstance(block, Mapping))
    for message in kwargs.get("messages") or ():
        content = message.get("content") if isinstance(message, Mapping) else None
        chars += len(content) if isinstance(content, str) else len(json.dumps(content, default=str))
    chars += len(json.dumps(kwargs.get("output_config") or {}, default=str))
    return chars


def _usage(response: Any) -> Dict[str, int]:
    usage = getattr(response, "usage", None)
    out: Dict[str, int] = {}
    for name in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        value = getattr(usage, name, None)
        if isinstance(value, int):
            out[name] = value
    return out


def _retryable(code: str) -> bool:
    """Fast transient failures that are never billed: connection errors, rate limits, server errors."""
    return code in ("connection_error", "rate_limited") or code.startswith("api_status_5")


class BudgetedClient:
    """Wraps an SDK-like client: every request must fit the guard first and is charged after.

    The wrapped client must not retry by itself (build it with ``max_retries=0``):
    retries happen here, each with its own reservation, so no attempt escapes the
    cap. A call that does not fit raises ``SpendCapReached`` without touching the
    inner client. A timed-out request may have run to the end on the server, so it
    is charged its full worst case and is not retried; connection errors, rate
    limits and server errors (never billed) are retried up to ``max_retries`` times.
    """

    def __init__(
        self,
        inner: Any,
        guard: SpendGuard,
        *,
        max_retries: int = 2,
        backoff_seconds: Tuple[float, ...] = (2.0, 8.0),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_retries < 0 or not backoff_seconds:
            raise ValueError("max_retries must be >= 0 and backoff_seconds non-empty")
        self._inner = inner
        self._guard = guard
        self._max_retries = int(max_retries)
        self._backoff = tuple(float(b) for b in backoff_seconds)
        self._sleep = sleep
        self.attempts = 0
        self.messages = _Messages(self._create)

    def _create(self, **kwargs: Any) -> Any:
        model = kwargs.get("model")
        chars = _request_chars(kwargs)
        worst = worst_case_cost(model, input_chars=chars, max_tokens=int(kwargs.get("max_tokens") or 0))
        retries = 0
        while True:
            reason = self._guard.reserve(worst)
            if reason is not None:
                raise SpendCapReached(reason)
            self.attempts += 1
            try:
                response = self._inner.messages.create(**kwargs)
            except Exception as exc:
                code = api_failure_code(exc)
                self._guard.settle(worst, worst if code == "timeout" else 0.0, model)
                if _retryable(code) and retries < self._max_retries:
                    self._sleep(self._backoff[min(retries, len(self._backoff) - 1)])
                    retries += 1
                    continue
                raise
            served = getattr(response, "model", None) or model
            self._guard.settle(worst, usage_cost(served, _usage(response)), served)
            return response
