"""The news shadow's monthly spend cap: worst-case reservations, pacing, persistence and the client wrapper."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List

import pytest

from app.news.budget import (
    BudgetedClient,
    SpendCapReached,
    SpendGuard,
    env_float,
    usage_cost,
    worst_case_cost,
)

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)  # day 21 of 31: 11 days left including today


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def test_prices_and_worst_case_bounds():
    # Opus 5.5: $4 in, $20 out, $8 1-hour cache write; Haiku 5.5: $0.10 / $0.50 / $0.20.
    assert usage_cost("claude-opus-5-5", {"input_tokens": 1_000_000}) == pytest.approx(4.0)
    assert usage_cost("claude-opus-5-5", {"output_tokens": 1_000_000}) == pytest.approx(20.0)
    assert usage_cost("claude-haiku-5-5-20261001", {"cache_creation_input_tokens": 1_000_000}) == pytest.approx(0.20)
    # An unknown model is priced like the most expensive known one.
    assert usage_cost("claude-unknown", {"output_tokens": 1_000_000}) == pytest.approx(20.0)
    # Worst case: every prompt character as half a token at the cache-write price, plus all max_tokens.
    assert worst_case_cost("claude-opus-5-5", input_chars=2_000, max_tokens=1_000) == pytest.approx((1_000 * 8 + 1_000 * 20) / 1e6)


def test_monthly_cap_and_daily_pace(tmp_path: Path):
    guard = SpendGuard(tmp_path, monthly_cap_usd=11.0, daily_pace=2.0, clock=Clock(NOW))
    snap = guard.snapshot()
    assert snap.day_limit_usd == pytest.approx(11.0 / 11 * 2)  # two even shares of what is left
    assert guard.refusal(1.9) is None
    assert guard.refusal(2.1) == "daily_pace"
    assert guard.reserve(1.5) is None
    assert guard.refusal(0.6) == "daily_pace"  # reservations count until settled
    guard.settle(1.5, 1.2, "claude-opus-5-5")
    assert guard.snapshot().spent_usd == pytest.approx(1.2) and guard.snapshot().today_usd == pytest.approx(1.2)
    assert guard.refusal(0.79) is None and guard.refusal(0.81) == "daily_pace"


def test_pace_off_leaves_only_the_monthly_cap(tmp_path: Path):
    guard = SpendGuard(tmp_path, monthly_cap_usd=1.0, daily_pace=0.0, clock=Clock(NOW))
    assert guard.snapshot().day_limit_usd is None
    assert guard.refusal(1.0) is None and guard.refusal(1.01) == "monthly_cap"
    zero = SpendGuard(None, monthly_cap_usd=0.0, clock=Clock(NOW))
    assert zero.refusal(1e-9) == "monthly_cap"  # a zero cap means no model call at all


def test_unused_budget_rolls_forward_and_a_new_month_starts_fresh(tmp_path: Path):
    clock = Clock(NOW)
    guard = SpendGuard(tmp_path, monthly_cap_usd=31.0, daily_pace=1.0, clock=clock)
    guard.reserve(0.5)
    guard.settle(0.5, 0.5, "claude-haiku-5-5")
    clock.now = NOW + timedelta(days=5)  # day 26: 6 days left, 30.5 left
    assert guard.snapshot().day_limit_usd == pytest.approx(30.5 / 6)
    clock.now = datetime(2026, 11, 1, 0, 5, tzinfo=timezone.utc)
    snap = guard.snapshot()
    assert snap.month == "2026-11" and snap.spent_usd == 0.0
    assert (tmp_path / "spend-2026-10.json").exists()


def test_spend_survives_a_restart_and_refusals_are_counted(tmp_path: Path):
    clock = Clock(NOW)
    first = SpendGuard(tmp_path, monthly_cap_usd=2.0, daily_pace=0, clock=clock)
    first.reserve(1.0)
    first.settle(1.0, 1.75, "claude-opus-5-5")
    second = SpendGuard(tmp_path, monthly_cap_usd=2.0, daily_pace=0, clock=clock)
    assert second.snapshot().spent_usd == pytest.approx(1.75)
    assert second.reserve(0.5) == "monthly_cap"
    stored = json.loads((tmp_path / "spend-2026-10.json").read_text(encoding="utf-8"))
    assert stored["refused"] == {"monthly_cap": 1} and stored["calls"] == 1
    assert stored["by_model"] == {"claude-opus-5-5": pytest.approx(1.75)}


def test_an_unreadable_record_counts_as_a_spent_month_and_is_kept(tmp_path: Path):
    path = tmp_path / "spend-2026-10.json"
    path.write_text("{broken", encoding="utf-8")
    guard = SpendGuard(tmp_path, monthly_cap_usd=40.0, clock=Clock(NOW))
    snap = guard.snapshot()
    assert snap.state_error and snap.remaining_usd == 0.0
    assert guard.reserve(0.01) == "monthly_cap"
    guard.settle(0.0, 0.5, "claude-opus-5-5")
    assert path.read_text(encoding="utf-8") == "{broken"  # the evidence is never overwritten


def test_validation_and_env_parsing():
    with pytest.raises(ValueError):
        SpendGuard(None, monthly_cap_usd=-1)
    with pytest.raises(ValueError):
        SpendGuard(None, monthly_cap_usd=float("nan"))
    with pytest.raises(ValueError):
        SpendGuard(None, daily_pace=-0.5)
    with pytest.raises(ValueError):
        SpendGuard(None, clock=lambda: datetime(2026, 10, 21)).snapshot()  # naive clock
    assert env_float({}, "X", 40.0) == 40.0
    assert env_float({"X": " 12.5 "}, "X", 40.0) == 12.5
    with pytest.raises(ValueError):
        env_float({"X": "-3"}, "X", 40.0)


@dataclass
class Usage:
    input_tokens: int = 1000
    output_tokens: int = 500
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 2000


@dataclass
class Response:
    model: str = "claude-opus-5-5"
    usage: Usage = field(default_factory=Usage)


class Inner:
    def __init__(self, outcome: Any = None) -> None:
        self.calls: List[dict] = []
        self.outcome = outcome
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome or Response()


def _request(text: str = "x" * 4000, max_tokens: int = 16000) -> dict:
    return {
        "model": "claude-opus-5-5",
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": "s" * 2000}],
        "messages": [{"role": "user", "content": text}],
        "output_config": {"effort": "high"},
    }


def test_budgeted_client_charges_actual_usage(tmp_path: Path):
    guard = SpendGuard(tmp_path, monthly_cap_usd=5.0, daily_pace=0, clock=Clock(NOW))
    client = BudgetedClient(Inner(), guard)
    client.messages.create(**_request())
    expected = (1000 * 4 + 500 * 20 + 2000 * 0.20) / 1e6
    assert guard.snapshot().spent_usd == pytest.approx(expected)
    assert guard._reserved == 0.0  # the reservation is released


def test_budgeted_client_refuses_before_calling(tmp_path: Path):
    guard = SpendGuard(tmp_path, monthly_cap_usd=0.30, daily_pace=0, clock=Clock(NOW))
    inner = Inner()
    with pytest.raises(SpendCapReached) as err:
        BudgetedClient(inner, guard).messages.create(**_request())  # worst case ~$0.37
    assert err.value.reason == "monthly_cap" and inner.calls == []


class Sequence:
    """An inner client that fails with the given exceptions, then answers."""

    def __init__(self, *failures: BaseException) -> None:
        self.failures = list(failures)
        self.calls = 0
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return Response()


def _sdk_errors():
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response_429 = httpx2.Response(429, request=request)
    response_529 = httpx2.Response(529, request=request)
    return {
        "timeout": lambda: anthropic.APITimeoutError(request=request),
        "connection": lambda: anthropic.APIConnectionError(request=request),
        "429": lambda: anthropic.RateLimitError("rate limited", response=response_429, body=None),
        "529": lambda: anthropic.InternalServerError("overloaded", response=response_529, body=None),
        "400": lambda: anthropic.BadRequestError("bad", response=httpx2.Response(400, request=request), body=None),
    }


def test_a_timeout_is_charged_its_worst_case_and_never_retried(tmp_path: Path):
    import anthropic

    errors = _sdk_errors()
    guard = SpendGuard(tmp_path, monthly_cap_usd=5.0, daily_pace=0, clock=Clock(NOW))
    inner = Sequence(errors["timeout"]())
    with pytest.raises(anthropic.APITimeoutError):
        BudgetedClient(inner, guard, sleep=lambda s: None).messages.create(**_request())
    worst = worst_case_cost("claude-opus-5-5", input_chars=4000 + 2000 + 19, max_tokens=16000)
    assert inner.calls == 1 and guard.snapshot().spent_usd == pytest.approx(worst, rel=1e-3)
    assert guard._reserved == 0.0


def test_transient_failures_are_retried_each_with_its_own_reservation(tmp_path: Path):
    errors = _sdk_errors()
    sleeps: List[float] = []
    guard = SpendGuard(tmp_path, monthly_cap_usd=5.0, daily_pace=0, clock=Clock(NOW))
    inner = Sequence(errors["connection"](), errors["429"]())
    client = BudgetedClient(inner, guard, sleep=sleeps.append)
    client.messages.create(**_request())
    assert inner.calls == 3 and client.attempts == 3 and sleeps == [2.0, 8.0]
    assert guard.snapshot().spent_usd == pytest.approx((1000 * 4 + 500 * 20 + 2000 * 0.20) / 1e6)  # only the answer is billed
    stored = json.loads((tmp_path / "spend-2026-10.json").read_text(encoding="utf-8"))
    assert stored["calls"] == 1


def test_retries_stop_at_the_limit_and_non_transient_errors_are_not_retried(tmp_path: Path):
    import anthropic

    errors = _sdk_errors()
    guard = SpendGuard(tmp_path, monthly_cap_usd=5.0, daily_pace=0, clock=Clock(NOW))
    inner = Sequence(errors["529"](), errors["529"](), errors["529"]())
    with pytest.raises(anthropic.InternalServerError):
        BudgetedClient(inner, guard, max_retries=2, sleep=lambda s: None).messages.create(**_request())
    assert inner.calls == 3 and guard.snapshot().spent_usd == 0.0
    bad = Sequence(errors["400"]())
    with pytest.raises(anthropic.BadRequestError):
        BudgetedClient(bad, guard, sleep=lambda s: None).messages.create(**_request())
    assert bad.calls == 1


def test_a_retry_that_no_longer_fits_the_cap_is_refused(tmp_path: Path):
    errors = _sdk_errors()
    guard = SpendGuard(tmp_path, monthly_cap_usd=0.40, daily_pace=0, clock=Clock(NOW))

    class SpendsMeanwhileThenFails:
        def __init__(self) -> None:
            self.calls = 0
            self.messages = self

        def create(self, **kwargs: Any) -> Any:
            self.calls += 1
            guard.settle(0.0, 0.10, "claude-opus-5-5")  # other calls spent while this one ran
            raise errors["connection"]()

    inner = SpendsMeanwhileThenFails()
    with pytest.raises(SpendCapReached):
        BudgetedClient(inner, guard, sleep=lambda s: None).messages.create(**_request())
    # The first attempt fit (worst case ~$0.34 of $0.40); after $0.10 more was spent the retry did not.
    assert inner.calls == 1 and guard.snapshot().spent_usd == pytest.approx(0.10)


def test_the_real_sdk_with_retries_off_makes_exactly_one_request_per_attempt(tmp_path: Path):
    """The live wiring: SDK retries off, so every HTTP attempt passes through the guard."""
    import anthropic
    import httpx2

    seen: List[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(1)
        if len(seen) == 1:
            return httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
        body = {
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": "{}"}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        }
        return httpx2.Response(200, json=body)

    sdk = anthropic.Anthropic(
        api_key="test-value-not-a-key", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    guard = SpendGuard(tmp_path, monthly_cap_usd=5.0, daily_pace=0, clock=Clock(NOW))
    client = BudgetedClient(sdk, guard, sleep=lambda s: None)
    client.messages.create(model="claude-opus-5-5", max_tokens=100, messages=[{"role": "user", "content": "hi"}])
    assert len(seen) == 2 and client.attempts == 2
    assert guard.snapshot().spent_usd == pytest.approx((100 * 4 + 10 * 20) / 1e6)


def test_concurrent_reservations_never_exceed_the_cap(tmp_path: Path):
    guard = SpendGuard(tmp_path, monthly_cap_usd=1.0, daily_pace=0, clock=Clock(NOW))
    granted: List[float] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(50):
            if guard.reserve(0.03) is None:
                with lock:
                    granted.append(0.03)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(granted) <= 1.0 + 1e-9 and len(granted) == 33
