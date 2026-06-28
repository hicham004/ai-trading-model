"""Phase 6a shadow-period tests (fully offline; fakes and in-memory SQLite).

Covers the owner-required supervisor behaviors:
* restart gating — a reconcile-inconsistent / foreign / wrong-scope gate is a
  PERMANENT halt (alert state, never re-arms); transient gate failures retry;
* bounded restart attempts — budget exhaustion halts permanently;
* daily-loss / entries-per-day caps — kill switch engaged and owned by the
  supervisor, auto-released only on a new UTC day, never when the operator
  engaged it;
plus the persisted-config tighten-only loader, journal daily rollover, and
the daily report aggregation (including lot-precision dust flatness).
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.models import Base, DemoEvent, DemoRuntimeStatus
from app.execution.driver import GateOutcome
from app.execution.identity import demo_identity_config
from app.execution.store import DemoStore
from app.shadow.config import (
    ShadowConfig,
    ShadowConfigError,
    load_shadow_config,
    shadow_settings,
)
from app.shadow.journal import DailyJsonlWriter, DecisionJournal
from app.shadow.policy import CapBreach, GateDecision, ShadowPolicy
from app.shadow.report import generate_daily_report
from app.shadow.supervisor import ALERT_FILENAME, STATE_FILENAME, ShadowSupervisor

UTC = timezone.utc


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    yield factory
    engine.dispose()


def make_config(tmp_path: Path, **overrides) -> ShadowConfig:
    values = dict(
        instrument="BTC-USDT",
        timeframe="1H",
        max_order_notional_usdt=10.0,
        max_open_positions=1,
        max_entries_per_day=3,
        max_daily_loss_usdt=1.0,
        arm_ttl_seconds=60.0,
        rearm_interval_seconds=30.0,
        max_restarts=2,
        restart_window_seconds=3600.0,
        restart_backoff_seconds=0.01,
        heartbeat_interval_seconds=0.05,
        report_refresh_seconds=3600.0,
        shadow_dir=tmp_path / "shadow",
    )
    values.update(overrides)
    return ShadowConfig(**values)


# --------------------------------------------------------------------------
# persisted config: fail closed, tighten only
# --------------------------------------------------------------------------

def _write_cfg(tmp_path: Path, **overrides) -> Path:
    data = {
        "instrument": "BTC-USDT",
        "timeframe": "1H",
        "max_order_notional_usdt": 10.0,
        "max_open_positions": 1,
        "max_entries_per_day": 3,
        "max_daily_loss_usdt": 1.0,
        "arm_ttl_seconds": 3600,
        "rearm_interval_seconds": 600,
        "max_restarts": 3,
        "restart_window_seconds": 3600,
        "restart_backoff_seconds": 30,
        "heartbeat_interval_seconds": 20,
        "report_refresh_seconds": 600,
        "shadow_dir": str(tmp_path / "shadow"),
    }
    data.update(overrides)
    path = tmp_path / "shadow_period.json"
    path.write_text(json.dumps(data))
    return path


def test_shadow_config_loads_and_validates(tmp_path):
    cfg = load_shadow_config(Settings(), _write_cfg(tmp_path))
    assert cfg.instrument == "BTC-USDT"
    assert cfg.max_order_notional_usdt == 10.0
    assert cfg.max_entries_per_day == 3


def test_shadow_config_must_tighten_notional(tmp_path):
    settings = Settings()
    path = _write_cfg(
        tmp_path, max_order_notional_usdt=settings.demo_max_order_notional + 1
    )
    with pytest.raises(ShadowConfigError):
        load_shadow_config(settings, path)


def test_shadow_config_must_tighten_open_positions(tmp_path):
    settings = Settings()
    path = _write_cfg(
        tmp_path, max_open_positions=settings.demo_max_open_positions + 1
    )
    with pytest.raises(ShadowConfigError):
        load_shadow_config(settings, path)


def test_shadow_config_rejects_unapproved_instrument(tmp_path):
    with pytest.raises(ShadowConfigError):
        load_shadow_config(Settings(), _write_cfg(tmp_path, instrument="DOGE-USDT"))


def test_shadow_config_missing_file_fails_closed(tmp_path):
    with pytest.raises(ShadowConfigError):
        load_shadow_config(Settings(), tmp_path / "missing.json")


def test_shadow_timeframe_comes_from_config_not_code(tmp_path):
    """The strategy timeframe is persisted config; shadow_settings() carries it
    into the runtime settings every consumer reads (one timeframe everywhere)."""
    settings = Settings()
    cfg = load_shadow_config(settings, _write_cfg(tmp_path, timeframe="1H"))
    assert cfg.timeframe == "1H"
    assert shadow_settings(settings, cfg).demo_timeframe == "1H"
    # 1m remains valid config too (it is on the candle-channel allowlist).
    cfg_1m = load_shadow_config(settings, _write_cfg(tmp_path, timeframe="1m"))
    assert shadow_settings(settings, cfg_1m).demo_timeframe == "1m"


def test_shadow_timeframe_rejects_unapproved_or_malformed(tmp_path):
    settings = Settings()
    # Parses fine but candle5m is NOT on the approved public-WS allowlist.
    with pytest.raises(ShadowConfigError):
        load_shadow_config(settings, _write_cfg(tmp_path, timeframe="5m"))
    # Malformed timeframe strings fail parse_timeframe (fail closed).
    with pytest.raises(ShadowConfigError):
        load_shadow_config(settings, _write_cfg(tmp_path, timeframe="1Q"))
    # Missing key fails closed.
    path = _write_cfg(tmp_path)
    data = json.loads(path.read_text())
    del data["timeframe"]
    path.write_text(json.dumps(data))
    with pytest.raises(ShadowConfigError):
        load_shadow_config(settings, path)


# --------------------------------------------------------------------------
# policy: gate classification, restart budget, caps, kill ownership
# --------------------------------------------------------------------------

def make_policy(**overrides) -> ShadowPolicy:
    values = dict(
        max_restarts=3,
        restart_window_seconds=3600,
        max_entries_per_day=3,
        max_daily_loss_usdt=Decimal("1.0"),
    )
    values.update(overrides)
    return ShadowPolicy(**values)


def test_gate_clean_proceeds():
    decision, _ = make_policy().classify_gate(
        lock_acquired=True, account_valid=True, consistent=True, armable=True, issues=[]
    )
    assert decision == GateDecision.PROCEED


@pytest.mark.parametrize(
    "issue",
    [
        "foreign open order on BTC-USDT ordId=1 (NOT auto-cancelled)",
        "WRONG ACCOUNT SCOPE: fill tradeId=1 belongs to local account 'demo'",
        "unexplained USDT balance: have 1, expected ~2",
        "ambiguous demo account selection: 2 accounts share this key",
    ],
)
def test_gate_foreign_wrong_scope_unexplained_halt(issue):
    decision, reason = make_policy().classify_gate(
        lock_acquired=True, account_valid=True, consistent=False, armable=False,
        issues=[issue],
    )
    assert decision == GateDecision.HALT
    assert reason.startswith("gate_issue:")


def test_gate_inconsistent_without_transient_marker_halts():
    decision, reason = make_policy().classify_gate(
        lock_acquired=True, account_valid=True, consistent=False, armable=False,
        issues=[],
    )
    assert (decision, reason) == (GateDecision.HALT, "reconcile_inconsistent")


@pytest.mark.parametrize(
    "issue",
    [
        "runtime lock unavailable",
        "time sync failed",
        "account validation unavailable",
        "reconciliation unavailable",
    ],
)
def test_gate_transient_failures_retry(issue):
    decision, _ = make_policy().classify_gate(
        lock_acquired=False, account_valid=False, consistent=False, armable=False,
        issues=[issue],
    )
    assert decision == GateDecision.RETRY


def test_reconcile_row_classification():
    f = ShadowPolicy.classify_reconcile_row
    assert f(consistent=True, foreign_orders=0, wrong_scope=0, unexplained=0) is None
    assert f(consistent=False, foreign_orders=1, wrong_scope=0, unexplained=0) == (
        "reconcile_foreign_orders"
    )
    assert f(consistent=False, foreign_orders=0, wrong_scope=1, unexplained=0) == (
        "reconcile_wrong_account_scope"
    )
    assert f(consistent=False, foreign_orders=0, wrong_scope=0, unexplained=2) == (
        "reconcile_unexplained_balances"
    )
    assert f(consistent=False, foreign_orders=0, wrong_scope=0, unexplained=0) == (
        "reconcile_inconsistent"
    )


def test_restart_budget_bounded_and_sliding():
    policy = make_policy(max_restarts=3, restart_window_seconds=3600)
    t0 = datetime(2026, 6, 12, 0, 0, tzinfo=UTC)
    assert policy.record_restart(t0)
    assert policy.record_restart(t0 + timedelta(minutes=10))
    assert policy.record_restart(t0 + timedelta(minutes=20))
    # 4th within the window busts the budget.
    assert not policy.record_restart(t0 + timedelta(minutes=30))
    # Old restarts expire: an hour later only recent ones count.
    assert policy.record_restart(t0 + timedelta(hours=2))


def test_caps_entries_and_daily_loss():
    policy = make_policy()
    assert policy.check_caps(entries_today=2, day_pnl_usdt=Decimal("-0.5")) == CapBreach.NONE
    assert policy.check_caps(entries_today=3, day_pnl_usdt=Decimal("0")) == (
        CapBreach.ENTRIES_PER_DAY
    )
    assert policy.check_caps(entries_today=0, day_pnl_usdt=Decimal("-1.0")) == (
        CapBreach.DAILY_LOSS
    )
    # Unmarkable equity must NOT trip the loss cap.
    assert policy.check_caps(entries_today=0, day_pnl_usdt=None) == CapBreach.NONE


def test_kill_switch_ownership_rules():
    today = date(2026, 6, 12)
    f = ShadowPolicy.may_auto_release
    # Operator-engaged (no supervisor owner): never auto-release.
    assert not f(engaged=True, owner=None, capped_day=None, today=today)
    assert not f(engaged=True, owner="halt:reconcile_foreign_orders",
                 capped_day=None, today=today)
    # Supervisor-owned but still the same UTC day: keep blocked.
    assert not f(engaged=True, owner="daily_loss", capped_day=today, today=today)
    # Supervisor-owned and a new day: release allowed.
    assert f(engaged=True, owner="daily_loss",
             capped_day=today - timedelta(days=1), today=today)
    assert f(engaged=True, owner="entries_per_day",
             capped_day=today - timedelta(days=1), today=today)
    assert not f(engaged=False, owner="daily_loss",
                 capped_day=today - timedelta(days=1), today=today)


# --------------------------------------------------------------------------
# journal: daily rollover
# --------------------------------------------------------------------------

def test_journal_daily_rollover(tmp_path):
    current = {"now": datetime(2026, 6, 12, 23, 59, tzinfo=UTC)}
    writer = DailyJsonlWriter(tmp_path, "journal", clock=lambda: current["now"])
    journal = DecisionJournal(writer)
    journal.write("candle", instrument="BTC-USDT")
    current["now"] = datetime(2026, 6, 13, 0, 1, tzinfo=UTC)
    journal.write("candle", instrument="BTC-USDT")
    journal.close()
    day1 = tmp_path / "journal-2026-06-12.jsonl"
    day2 = tmp_path / "journal-2026-06-13.jsonl"
    assert day1.exists() and day2.exists()
    line = json.loads(day1.read_text().splitlines()[0])
    assert line["kind"] == "candle" and line["instrument"] == "BTC-USDT"


# --------------------------------------------------------------------------
# supervisor: fakes
# --------------------------------------------------------------------------

class FakeRuntime:
    def __init__(self):
        self._settings = Settings()
        self.kill_engaged = False
        self.arm_calls = 0
        self.disarm_calls = 0
        self.release_calls = 0
        self.release_result = True

    def arm(self, ttl_seconds=None):
        self.arm_calls += 1
        return datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds or 60)

    def disarm(self):
        self.disarm_calls += 1

    def engage_kill_switch(self):
        self.kill_engaged = True
        return []

    def release_kill_switch(self):
        self.release_calls += 1
        if self.release_result:
            self.kill_engaged = False
        return self.release_result


class FakeStore:
    def position_summary(self, account_id, instrument):
        return Decimal(0), None

    def get_or_create_daily_baseline(self, account_id, day, equity, *, now):
        return equity


class FakeRest:
    def get_instruments(self):
        return []


class FakeDriver:
    def __init__(self, gate: GateOutcome):
        self._gate = gate
        self.account_id = 1
        self.runtime = FakeRuntime()
        self._runtime = self.runtime  # supervisor tightens _runtime._settings
        self.store = FakeStore()
        self.rest = FakeRest()
        self.shutdown_calls = 0

    def startup_gate(self):
        return self._gate

    def _shutdown(self):
        self.shutdown_calls += 1


class FakeMarketState:
    def recent_confirmed_candles(self):
        return []

    def latest_order_books(self, depth=None):
        return []


class RecordingNotifications:
    def __init__(self):
        self.calls = []

    def fill_observed(self, fill):
        self.calls.append(("fill", fill))

    def alert_written(self, **fields):
        self.calls.append(("alert", fields))

    def heartbeat_stale(self, **fields):
        self.calls.append(("heartbeat_stale", fields))

    def private_ws_auth_drop(self, **fields):
        self.calls.append(("private_ws_auth_drop", fields))

    def permanent_halt(self, **fields):
        self.calls.append(("permanent_halt", fields))

    def disarmed(self, **fields):
        self.calls.append(("disarmed", fields))


class FailingNotifications:
    def fill_observed(self, fill):
        raise RuntimeError("notify failed")

    def alert_written(self, **fields):
        raise RuntimeError("notify failed")

    def heartbeat_stale(self, **fields):
        raise RuntimeError("notify failed")

    def private_ws_auth_drop(self, **fields):
        raise RuntimeError("notify failed")

    def permanent_halt(self, **fields):
        raise RuntimeError("notify failed")

    def disarmed(self, **fields):
        raise RuntimeError("notify failed")


def make_supervisor(
    tmp_path, session_factory, driver_factory, *, tasks_factory,
    notification_sink=None, **cfg
):
    config = make_config(tmp_path, **cfg)
    journal = DecisionJournal(DailyJsonlWriter(config.shadow_dir, "journal"))
    return ShadowSupervisor(
        # Mirror the launcher: the strategy timeframe flows from the persisted
        # shadow config into the runtime settings (supervisor refuses on
        # mismatch).
        settings=shadow_settings(Settings(), config),
        config=config,
        session_factory=session_factory,
        driver_factory=driver_factory,
        journal=journal,
        market_state_factory=FakeMarketState,
        driver_tasks_factory=tasks_factory,
        notification_sink=notification_sink,
    ), config


def crash_tasks_factory(driver, stop_event):
    return [asyncio.create_task(asyncio.sleep(0))]  # "driver task died"


# --------------------------------------------------------------------------
# supervisor: restart gating — inconsistent gate halts permanently, no re-arm
# --------------------------------------------------------------------------

def test_inconsistent_gate_halts_permanently_and_never_arms(tmp_path, session_factory):
    # A genuinely inconsistent reconciliation with no specific marker string
    # (foreign/wrong-scope/unexplained carry their own markers and are tested
    # separately): the gate returns consistent=False with the reconciler's
    # issue list, which can be empty for a bare consistency failure.
    gate = GateOutcome(
        lock_acquired=True, account_valid=True, consistent=False, armable=False,
        issues=[],
    )
    drivers = []

    def factory(market_state):
        driver = FakeDriver(gate)
        drivers.append(driver)
        return driver

    supervisor, config = make_supervisor(
        tmp_path, session_factory, factory, tasks_factory=crash_tasks_factory
    )
    code = asyncio.run(supervisor.run(asyncio.Event()))
    assert code == 1
    assert (config.shadow_dir / ALERT_FILENAME).exists()
    state = json.loads((config.shadow_dir / STATE_FILENAME).read_text())
    assert state["alert"] == "reconcile_inconsistent"
    assert len(drivers) == 1  # no restart after a permanent halt
    assert drivers[0].runtime.arm_calls == 0  # never re-armed
    assert drivers[0].shutdown_calls == 1  # lock released


def test_foreign_gate_issue_halts_permanently(tmp_path, session_factory):
    gate = GateOutcome(
        lock_acquired=True, account_valid=True, consistent=False, armable=False,
        issues=["foreign open order on BTC-USDT ordId=42 (NOT auto-cancelled)"],
    )
    supervisor, config = make_supervisor(
        tmp_path, session_factory, lambda ms: FakeDriver(gate),
        tasks_factory=crash_tasks_factory,
    )
    code = asyncio.run(supervisor.run(asyncio.Event()))
    assert code == 1
    state = json.loads((config.shadow_dir / STATE_FILENAME).read_text())
    assert state["alert"].startswith("gate_issue:foreign")


# --------------------------------------------------------------------------
# supervisor: bounded restart attempts
# --------------------------------------------------------------------------

def test_restart_budget_exhaustion_halts_with_alert(tmp_path, session_factory):
    gate = GateOutcome(
        lock_acquired=True, account_valid=True, consistent=True, armable=True, issues=[]
    )
    drivers = []

    def factory(market_state):
        driver = FakeDriver(gate)
        drivers.append(driver)
        return driver

    supervisor, config = make_supervisor(
        tmp_path, session_factory, factory,
        tasks_factory=crash_tasks_factory, max_restarts=2,
    )
    code = asyncio.run(supervisor.run(asyncio.Event()))
    assert code == 1
    # max_restarts=2 -> the 3rd crash exhausts the budget: exactly 3 attempts.
    assert len(drivers) == 3
    assert (config.shadow_dir / ALERT_FILENAME).exists()
    state = json.loads((config.shadow_dir / STATE_FILENAME).read_text())
    assert state["alert"] == "restart_budget_exhausted"
    # Every attempt was clean-gated, armed, then disarmed + shut down on crash.
    for driver in drivers:
        assert driver.runtime.arm_calls >= 1
        assert driver.runtime.disarm_calls >= 1
        assert driver.shutdown_calls == 1
    # The journal's start line records the configured timeframe and account.
    journal_files = sorted(config.shadow_dir.glob("journal-*.jsonl"))
    assert journal_files
    lines = [json.loads(l) for f in journal_files for l in f.read_text().splitlines()]
    start = next(
        l for l in lines if l.get("kind") == "supervisor" and l.get("event") == "start"
    )
    assert start["timeframe"] == "1H"
    assert start["instrument"] == "BTC-USDT"
    assert "account" in start


def test_unacknowledged_alert_blocks_startup(tmp_path, session_factory):
    supervisor, config = make_supervisor(
        tmp_path, session_factory, lambda ms: pytest.fail("driver must not be built"),
        tasks_factory=crash_tasks_factory,
    )
    supervisor._state["alert"] = "restart_budget_exhausted"
    code = asyncio.run(supervisor.run(asyncio.Event()))
    assert code == 2


def test_readiness_alert_blocks_same_process_restart_and_rearm(
    tmp_path, session_factory
):
    gate = GateOutcome(
        lock_acquired=True, account_valid=True, consistent=True, armable=True, issues=[]
    )
    drivers = []
    holder = {}

    def factory(market_state):
        driver = FakeDriver(gate)
        drivers.append(driver)
        return driver

    def alert_then_crash_tasks_factory(driver, stop_event):
        async def alert_then_crash():
            holder["supervisor"]._write_readiness_alert({
                "id": 77,
                "event_type": "market_candle_backfill_failed",
                "message": "public REST candle backfill failed",
                "payload": "{}",
            })

        return [asyncio.create_task(alert_then_crash())]

    supervisor, config = make_supervisor(
        tmp_path, session_factory, factory,
        tasks_factory=alert_then_crash_tasks_factory,
        max_restarts=2,
    )
    holder["supervisor"] = supervisor

    code = asyncio.run(supervisor.run(asyncio.Event()))

    assert code == 1
    assert len(drivers) == 1
    assert drivers[0].runtime.arm_calls >= 1
    assert drivers[0].runtime.disarm_calls >= 1
    state = json.loads((config.shadow_dir / STATE_FILENAME).read_text())
    assert state["alert"].startswith("readiness:market_candle_backfill_failed")
    journal_files = sorted(config.shadow_dir.glob("journal-*.jsonl"))
    lines = [json.loads(l) for f in journal_files for l in f.read_text().splitlines()]
    assert any(
        l.get("kind") == "supervisor"
        and l.get("event") == "restart_blocked_by_alert"
        for l in lines
    )


# --------------------------------------------------------------------------
# supervisor: daily-loss / entries caps and kill-switch ownership
# --------------------------------------------------------------------------

def test_daily_loss_cap_engages_and_owns_kill_switch(tmp_path, session_factory):
    supervisor, config = make_supervisor(
        tmp_path, session_factory, lambda ms: None, tasks_factory=crash_tasks_factory
    )
    runtime = FakeRuntime()
    today = date(2026, 6, 12)
    assert supervisor.enforce_caps(runtime, today, CapBreach.DAILY_LOSS) is True
    assert runtime.kill_engaged is True
    state = json.loads((config.shadow_dir / STATE_FILENAME).read_text())
    assert state["kill_owner"] == "daily_loss"
    assert state["capped_day"] == today.isoformat()
    # Idempotent: an existing supervisor ownership is not re-engaged.
    assert supervisor.enforce_caps(runtime, today, CapBreach.DAILY_LOSS) is False
    # NONE never engages.
    fresh = FakeRuntime()
    supervisor2, _ = make_supervisor(
        tmp_path / "b", session_factory, lambda ms: None,
        tasks_factory=crash_tasks_factory,
    )
    assert supervisor2.enforce_caps(fresh, today, CapBreach.NONE) is False
    assert fresh.kill_engaged is False


def _set_kill_switch_status(session_factory, account_id: int, engaged: bool) -> None:
    session = session_factory()
    try:
        row = DemoRuntimeStatus(
            account_id=account_id, status="running", kill_switch_engaged=engaged,
            reconciliation_consistent=True, ws_authenticated=False,
            feed_connected=False, feed_stale=True,
            updated_at=datetime.now(tz=UTC),
        )
        session.add(row)
        session.commit()
    finally:
        session.close()


def test_supervisor_owned_kill_switch_releases_on_new_day(tmp_path, session_factory):
    supervisor, config = make_supervisor(
        tmp_path, session_factory, lambda ms: None, tasks_factory=crash_tasks_factory
    )
    _set_kill_switch_status(session_factory, account_id=1, engaged=True)
    runtime = FakeRuntime()
    runtime.kill_engaged = True
    yesterday = date(2026, 6, 11)
    supervisor._state["kill_owner"] = "daily_loss"
    supervisor._state["capped_day"] = yesterday.isoformat()
    supervisor._save_state()
    # Same day: no release.
    assert supervisor.maybe_release_new_day(runtime, 1, yesterday) is False
    assert runtime.release_calls == 0
    # New day: fail-closed release path is invoked and ownership cleared.
    assert supervisor.maybe_release_new_day(runtime, 1, date(2026, 6, 12)) is True
    assert runtime.release_calls == 1
    state = json.loads((config.shadow_dir / STATE_FILENAME).read_text())
    assert state["kill_owner"] is None and state["capped_day"] is None


def test_operator_engaged_kill_switch_is_never_released(tmp_path, session_factory):
    supervisor, _ = make_supervisor(
        tmp_path, session_factory, lambda ms: None, tasks_factory=crash_tasks_factory
    )
    _set_kill_switch_status(session_factory, account_id=1, engaged=True)
    runtime = FakeRuntime()
    runtime.kill_engaged = True
    # No supervisor ownership recorded -> operator's switch: hands off.
    assert supervisor.maybe_release_new_day(runtime, 1, date(2026, 6, 12)) is False
    assert runtime.release_calls == 0
    assert runtime.kill_engaged is True


def test_cap_breach_never_claims_an_operator_engaged_switch(tmp_path, session_factory):
    """A cap breach while the operator's switch is already engaged must not be
    claimed by the supervisor — otherwise the new-day path would release it."""
    supervisor, config = make_supervisor(
        tmp_path, session_factory, lambda ms: None, tasks_factory=crash_tasks_factory
    )
    runtime = FakeRuntime()
    runtime.kill_engaged = True  # operator engaged it mid-run
    today = date(2026, 6, 12)
    engaged = supervisor.enforce_caps(
        runtime, today, CapBreach.DAILY_LOSS, already_engaged=True
    )
    assert engaged is False
    state = json.loads((config.shadow_dir / STATE_FILENAME).read_text()) if (
        config.shadow_dir / STATE_FILENAME
    ).exists() else {"kill_owner": None}
    assert state.get("kill_owner") is None
    # And the new-day path therefore refuses to release.
    _set_kill_switch_status(session_factory, account_id=1, engaged=True)
    assert supervisor.maybe_release_new_day(runtime, 1, today + timedelta(days=1)) is False
    assert runtime.release_calls == 0


def test_readiness_alert_writes_alert_without_halt_or_kill(tmp_path, session_factory):
    supervisor, config = make_supervisor(
        tmp_path, session_factory, lambda ms: None, tasks_factory=crash_tasks_factory
    )
    session = session_factory()
    try:
        session.add(
            DemoEvent(
                account_id=1,
                event_time=datetime(2026, 6, 12, 12, 0, tzinfo=UTC),
                event_type="market_candle_backfill_failed",
                severity="error",
                message="public REST candle backfill did not return the exact missing window",
                payload_json="{}",
            )
        )
        session.commit()
    finally:
        session.close()

    event = supervisor._latest_readiness_alert_event(1)
    assert event is not None
    supervisor._write_readiness_alert(event)

    alert_text = (config.shadow_dir / ALERT_FILENAME).read_text()
    assert "SHADOW READINESS ALERT" in alert_text
    state = json.loads((config.shadow_dir / STATE_FILENAME).read_text())
    assert state["alert"].startswith("readiness:market_candle_backfill_failed")
    assert supervisor._state.get("kill_owner") is None
    journal_files = sorted(config.shadow_dir.glob("journal-*.jsonl"))
    assert journal_files
    lines = [json.loads(l) for f in journal_files for l in f.read_text().splitlines()]
    assert any(
        l.get("kind") == "supervisor" and l.get("event") == "readiness_alert"
        for l in lines
    )


# --------------------------------------------------------------------------
# supervisor: Telegram notification hooks are observability only
# --------------------------------------------------------------------------

def test_alert_file_write_notifies_operator(tmp_path, session_factory):
    notifications = RecordingNotifications()
    supervisor, config = make_supervisor(
        tmp_path, session_factory, lambda ms: None,
        tasks_factory=crash_tasks_factory, notification_sink=notifications,
    )

    supervisor._write_alert("restart_budget_exhausted")

    assert (config.shadow_dir / ALERT_FILENAME).exists()
    assert notifications.calls == [
        ("alert", {"reason": "restart_budget_exhausted", "alert_type": "halt"})
    ]


def test_supervisor_notifies_new_fill_rows_once(tmp_path, session_factory):
    notifications = RecordingNotifications()
    supervisor, _ = make_supervisor(
        tmp_path, session_factory, lambda ms: None,
        tasks_factory=crash_tasks_factory, notification_sink=notifications,
    )
    store = DemoStore(session_factory, "demo-seeded")
    account_id = store.ensure_account("sha256:test", demo_identity_config(Settings()))
    now = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)

    supervisor._prime_fill_notifications(account_id)
    store.record_fill(
        account_id, fill_id="fill-1", client_order_id="d5x-1",
        exchange_order_id="1", instrument="BTC-USDT", side="buy",
        fill_size="0.001", fill_price="65000", fee=None, fee_ccy=None,
        fill_time=now, source="ws", now=now,
    )

    supervisor._new_fill_notifications(account_id)
    supervisor._new_fill_notifications(account_id)

    assert len(notifications.calls) == 1
    event, fill = notifications.calls[0]
    assert event == "fill"
    assert fill["fill_id"] == "fill-1"
    assert fill["instrument"] == "BTC-USDT"


def test_supervisor_notifies_heartbeat_and_private_ws_health(
    tmp_path, session_factory
):
    notifications = RecordingNotifications()
    supervisor, _ = make_supervisor(
        tmp_path, session_factory, lambda ms: None,
        tasks_factory=crash_tasks_factory, notification_sink=notifications,
    )
    now = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
    healthy = DemoRuntimeStatus(
        account_id=1, status="running", kill_switch_engaged=False,
        reconciliation_consistent=True, feed_connected=True, feed_stale=False,
        ws_authenticated=True, lock_heartbeat=now, updated_at=now,
    )
    stale_heartbeat = DemoRuntimeStatus(
        account_id=1, status="running", kill_switch_engaged=False,
        reconciliation_consistent=True, feed_connected=True, feed_stale=False,
        ws_authenticated=True,
        lock_heartbeat=now - timedelta(seconds=Settings().demo_lock_stale_seconds + 1),
        updated_at=now,
    )
    auth_down = DemoRuntimeStatus(
        account_id=1, status="running", kill_switch_engaged=False,
        reconciliation_consistent=True, feed_connected=True, feed_stale=False,
        ws_authenticated=False, lock_heartbeat=now, updated_at=now,
    )

    supervisor._notify_runtime_health(healthy, now)
    supervisor._notify_runtime_health(stale_heartbeat, now)
    supervisor._notify_runtime_health(auth_down, now + timedelta(seconds=1))

    assert notifications.calls[0][0] == "heartbeat_stale"
    assert notifications.calls[1][0] == "private_ws_auth_drop"


def test_notification_failures_do_not_propagate(tmp_path, session_factory):
    supervisor, config = make_supervisor(
        tmp_path, session_factory, lambda ms: None,
        tasks_factory=crash_tasks_factory, notification_sink=FailingNotifications(),
    )
    now = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
    stale = DemoRuntimeStatus(
        account_id=1, status="running", kill_switch_engaged=False,
        reconciliation_consistent=True, feed_connected=True, feed_stale=False,
        ws_authenticated=False,
        lock_heartbeat=now - timedelta(seconds=Settings().demo_lock_stale_seconds + 1),
        updated_at=now,
    )

    supervisor._notify_fill({"fill_id": "fill-1"})
    supervisor._write_alert("restart_budget_exhausted")
    supervisor._notify_permanent_halt("restart_budget_exhausted")
    supervisor._notify_disarmed("attempt_cleanup")
    supervisor._notify_runtime_health(stale, now)

    assert (config.shadow_dir / ALERT_FILENAME).exists()


def test_fill_notification_observer_failure_does_not_abort_attempt(
    tmp_path, session_factory, monkeypatch
):
    gate = GateOutcome(
        lock_acquired=True, account_valid=True, consistent=True, armable=True, issues=[]
    )
    drivers = []

    def factory(market_state):
        driver = FakeDriver(gate)
        drivers.append(driver)
        return driver

    supervisor, _ = make_supervisor(
        tmp_path, session_factory, factory, tasks_factory=crash_tasks_factory
    )

    def boom(account_id):
        raise RuntimeError("notification observer db read failed")

    monkeypatch.setattr(supervisor, "_prime_fill_notifications", boom)
    monkeypatch.setattr(supervisor, "_new_fill_notifications", boom)

    outcome = asyncio.run(supervisor._run_attempt(asyncio.Event()))

    assert outcome == "crashed"
    assert len(drivers) == 1
    assert drivers[0].runtime.arm_calls >= 1
    assert drivers[0].runtime.disarm_calls >= 1
    assert drivers[0].shutdown_calls == 1


# --------------------------------------------------------------------------
# daily report: aggregation incl. lot-precision dust flatness
# --------------------------------------------------------------------------

def test_daily_report_aggregates_signals_pnl_and_dust(tmp_path, session_factory):
    from app.execution.identity import demo_identity_config
    from app.execution.store import DemoStore

    settings = Settings()
    store = DemoStore(session_factory, "demo-seeded")
    account_id = store.ensure_account("sha256:test", demo_identity_config(settings))

    day = date(2026, 6, 12)
    noon = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
    # The Session 2b dust scenario: base-ccy buy fee finer than the lot.
    store.record_fill(
        account_id, fill_id="t1", client_order_id="d5x", exchange_order_id="1",
        instrument="BTC-USDT", side="buy", fill_size="0.00015988",
        fill_price="62422.9", fee="-0.00000015988", fee_ccy="BTC",
        fill_time=noon, source="ws", now=noon,
    )
    store.record_fill(
        account_id, fill_id="t2", client_order_id="d5y", exchange_order_id="2",
        instrument="BTC-USDT", side="sell", fill_size="0.00015972",
        fill_price="62408.8", fee="-0.00996", fee_ccy="USDT",
        fill_time=noon, source="ws", now=noon,
    )

    journal_dir = tmp_path / "shadow"
    journal_dir.mkdir(parents=True)
    lines = [
        {"kind": "meta", "instrument": "BTC-USDT", "lot_size": "0.00000001"},
        {"kind": "candle", "instrument": "BTC-USDT"},
        {"kind": "candle", "instrument": "BTC-USDT"},
        {"kind": "signal", "action": "long", "confidence": 0.71, "cleared": True},
        {"kind": "signal", "action": "long", "confidence": 0.56, "cleared": False,
         "veto_reason": "confidence_too_low"},
        {"kind": "signal", "action": "flat", "confidence": 0.0, "cleared": False},
        {"kind": "stop_eval", "low": "62000", "stop_level": "61000", "breached": False},
        {
            "kind": "health",
            "ws_auth": True,
            "feed_usable": True,
            "feed_connected": True,
            "feed_stale": False,
            "market_continuity_ok": True,
            "per_feed_health": [
                {
                    "feed_id": "okx-business",
                    "connected": True,
                    "stale": False,
                }
            ],
        },
        {
            "kind": "health",
            "ws_auth": True,
            "feed_usable": False,
            "feed_connected": True,
            "feed_stale": False,
            "market_continuity_ok": False,
            "per_feed_health": [
                {
                    "feed_id": "okx-business",
                    "connected": True,
                    "stale": False,
                }
            ],
        },
        {
            "kind": "ledger_event",
            "event_type": "market_candle_backfill_failed",
            "message": "public REST candle backfill did not return the exact missing window",
        },
        {"kind": "supervisor", "event": "restart"},
    ]
    with open(journal_dir / f"journal-{day.isoformat()}.jsonl", "w") as fh:
        for line in lines:
            fh.write(json.dumps({"ts": noon.isoformat(), **line}) + "\n")

    report = generate_daily_report(
        journal_dir=journal_dir, session_factory=session_factory,
        account_id=account_id, day=day, instrument="BTC-USDT", min_confidence=0.60,
    )
    assert "LONG signals: 2 (cleared >= 0.60: 1, vetoed: 1)" in report
    assert "clearance rate: 50.0%" in report
    assert "fills: 2 (buys: 1, sells: 1)" in report
    # Sub-lot fee dust must be reported as FLAT at lot precision, not open.
    assert "FLAT at lot precision (sub-lot dust" in report
    assert "stop evaluations journaled: 1 (breaches: 0)" in report
    assert "private WS authenticated: 100.0%" in report
    assert "feed usable: 50.0%" in report
    assert "feed connected: 100.0%; feed stale: 0.0%; market continuity ok: 50.0%" in report
    assert "okx-business connected=100.0% stale=0.0%" in report
    assert "market_candle_backfill_failed=1" in report
    assert "restart=1" in report
