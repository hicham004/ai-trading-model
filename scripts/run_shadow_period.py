"""Phase 6a shadow-period operator commands (DEMO ONLY, local CLI).

WARNING: This drives OKX's DEMO (simulated) environment only; every request
carries ``x-simulated-trading: 1``. The live shadow run is started ONLY by the
human operator and requires BOTH the ``SHADOW_PERIOD_ENABLED=1`` environment
opt-in AND the explicit ``--run`` flag. Nothing arms by default.

    python scripts/run_shadow_period.py --gate-check          # gate only, no arm
    python scripts/run_shadow_period.py --run                 # the shadow run
    python scripts/run_shadow_period.py --report [YYYY-MM-DD] # offline report
    python scripts/run_shadow_period.py --acknowledge-alert   # operator-only

State/observability files live in ``logs/shadow/`` (gitignored): the decision
journal ``journal-YYYY-MM-DD.jsonl``, ``heartbeat.json``, ``state.json``,
``report-YYYY-MM-DD.md`` and, on a permanent halt, ``ALERT``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.database import get_session_factory, init_db  # noqa: E402
from app.logging_config import configure_logging, get_logger  # noqa: E402
from app.shadow.config import DEFAULT_CONFIG_PATH, ShadowConfigError, load_shadow_config  # noqa: E402

logger = get_logger("scripts.run_shadow_period")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 6a shadow-period commands (demo only).")
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Shadow config path.")
    p.add_argument("--gate-check", action="store_true", help="Run the startup gate and exit (no arm).")
    p.add_argument("--run", action="store_true",
                   help="Run the shadow supervisor (requires SHADOW_PERIOD_ENABLED=1).")
    p.add_argument("--report", nargs="?", const="today", default=None, metavar="YYYY-MM-DD",
                   help="Generate the daily report offline (default: today, UTC).")
    p.add_argument("--acknowledge-alert", action="store_true",
                   help="Operator-only: clear the ALERT state after review.")
    return p.parse_args(argv)


def _account_id(session_factory, account_name: str):
    from sqlalchemy import select

    from app.db.models import DemoAccount

    session = session_factory()
    try:
        account = session.scalar(select(DemoAccount).where(DemoAccount.name == account_name))
        return account.id if account is not None else None
    finally:
        session.close()


def _build_driver_factory(settings, session_factory):
    """Real driver factory (mirrors the accepted Phase 5 validation composition)."""
    from app.exchange.credentials import install_secret_redaction, load_demo_credentials
    from app.exchange.okx_demo_rest import OKXDemoRestClient
    from app.execution.driver import DemoTradingDriver

    creds = load_demo_credentials()
    install_secret_redaction(creds)

    def factory(market_state):
        rest = OKXDemoRestClient(creds, settings=settings)
        return DemoTradingDriver(
            credentials=creds, rest=rest, session_factory=session_factory,
            settings=settings, market_state=market_state,
            account_selection_explicit=bool(os.environ.get("DEMO_ACCOUNT_NAME")),
        )

    return factory


def cmd_gate_check(settings, session_factory) -> int:
    factory = _build_driver_factory(settings, session_factory)
    from app.live.market_state import MarketState

    driver = factory(MarketState())
    print("[SHADOW] running the fail-closed startup gate (no arming)...")
    gate = driver.startup_gate()
    print(f"[SHADOW] gate: lock={gate.lock_acquired} account_valid={gate.account_valid} "
          f"consistent={gate.consistent} armable={gate.armable}")
    for issue in gate.issues:
        print(f"         - {issue}")
    if gate.lock_acquired:
        driver._shutdown()
    print("[SHADOW] done. SIMULATION ONLY; nothing was armed.")
    return 0 if gate.armable else 1


def cmd_report(settings, session_factory, cfg, day_arg: str) -> int:
    from app.shadow.report import write_daily_report

    day = date.fromisoformat(day_arg) if day_arg != "today" else datetime.now(timezone.utc).date()
    account_id = _account_id(session_factory, settings.demo_account_name)
    if account_id is None:
        print(f"[SHADOW] no local account named {settings.demo_account_name!r}; nothing to report.")
        return 1
    path = write_daily_report(
        journal_dir=cfg.shadow_dir, session_factory=session_factory,
        account_id=account_id, day=day, instrument=cfg.instrument,
        min_confidence=settings.demo_min_confidence,
    )
    print(f"[SHADOW] report written: {path}")
    return 0


def cmd_acknowledge_alert(cfg) -> int:
    from app.shadow.journal import write_atomic_json
    from app.shadow.supervisor import ALERT_FILENAME, STATE_FILENAME

    state_path = Path(cfg.shadow_dir) / STATE_FILENAME
    alert_path = Path(cfg.shadow_dir) / ALERT_FILENAME
    if not alert_path.exists() and not state_path.exists():
        print("[SHADOW] no alert state present.")
        return 0
    import json

    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except ValueError:
            state = {}
    state["alert"] = None
    state["restarts"] = []
    write_atomic_json(state_path, state)
    if alert_path.exists():
        alert_path.unlink()
    print("[SHADOW] alert acknowledged and restart budget reset. The kill switch,")
    print("         if engaged, is NOT released by this command; use")
    print("         scripts/run_demo_trading.py --release-kill-switch after review.")
    return 0


def cmd_run(settings, session_factory, cfg) -> int:
    if os.environ.get("SHADOW_PERIOD_ENABLED") != "1":
        print("[SHADOW] refusing: --run requires the SHADOW_PERIOD_ENABLED=1 "
              "environment opt-in (operator only).", file=sys.stderr)
        return 2
    if not os.environ.get("DEMO_ACCOUNT_NAME"):
        print("[SHADOW] refusing: DEMO_ACCOUNT_NAME must be set explicitly "
              "(account-partition guard).", file=sys.stderr)
        return 2
    from app.exchange.credentials import demo_credentials_available

    if not demo_credentials_available():
        print("[SHADOW] refusing: no demo credentials available.", file=sys.stderr)
        return 2

    from app.live.market_state import MarketState
    from app.shadow.journal import DailyJsonlWriter, DecisionJournal
    from app.shadow.supervisor import ShadowSupervisor

    journal = DecisionJournal(DailyJsonlWriter(cfg.shadow_dir, "journal"))
    supervisor = ShadowSupervisor(
        settings=settings, config=cfg, session_factory=session_factory,
        driver_factory=_build_driver_factory(settings, session_factory),
        journal=journal, market_state_factory=MarketState,
    )

    async def main() -> int:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):
                pass
        print("[SHADOW] Phase 6a shadow supervisor starting (DEMO ONLY; Ctrl-C to stop).")
        code = await supervisor.run(stop)
        print(f"[SHADOW] supervisor exited with code {code}.")
        return code

    try:
        return asyncio.run(main())
    finally:
        journal.close()


def main(argv=None) -> int:
    configure_logging()
    args = parse_args(argv)
    settings = get_settings()
    try:
        cfg = load_shadow_config(settings, Path(args.config))
    except ShadowConfigError as exc:
        print(f"[SHADOW] config error (fail closed): {exc}", file=sys.stderr)
        return 2
    if args.acknowledge_alert:
        return cmd_acknowledge_alert(cfg)
    init_db()
    session_factory = get_session_factory()
    if args.report is not None:
        return cmd_report(settings, session_factory, cfg, args.report)
    if args.gate_check:
        return cmd_gate_check(settings, session_factory)
    if args.run:
        return cmd_run(settings, session_factory, cfg)
    print("No command given. Use --gate-check / --run / --report / --acknowledge-alert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
