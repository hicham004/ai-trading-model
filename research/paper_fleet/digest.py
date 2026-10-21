"""Facts about the paper fleet for the daily ops digest (plan row R6) — read-only, simulation only.

Reads the fleet's saved state (``_state/fleet_state.json``, replaced atomically by the
running fleet after every cycle) through the same ``status_from_state`` view as
``--status``, the names of the weekly reports, and the weekly report's own verdicts
(``build_report_data`` over the journals: each configuration against its backtest, and
the drawdown alarms). It takes no lock, writes nothing and opens no network connection,
so it can run next to a fleet that keeps running.

Returns plain, JSON-ready numbers. A forward record shorter than 30 days is flagged as
too early to judge, as the weekly report does; nothing here ranks or approves anything.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from research.paper_fleet.report import MIN_DAYS_FOR_VERDICT, build_report_data
from research.paper_fleet.runner import status_from_state
from research.paper_fleet.store import FleetPaths, read_state

LAST_CYCLE_LATE_MINUTES = 15.0  # the service runs a cycle every minute


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _brief(account: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: account.get(k) for k in ("id", "role", "instrument", "timeframe", "candidate", "equity", "return", "in_position")}


def fleet_facts(fleet_dir: Path, now: datetime) -> Dict[str, Any]:
    """Everything the digest says about the fleet; ``found`` is False when there is no fleet here."""
    paths = FleetPaths(Path(fleet_dir))
    out: Dict[str, Any] = {"dir": str(paths.root), "installed": paths.root.is_dir(), "found": False}
    if not out["installed"]:
        return out
    try:
        state = read_state(paths.state_file)
    except (OSError, ValueError) as exc:
        out["error"] = f"the fleet state could not be read ({type(exc).__name__})"
        return out
    if not isinstance(state, dict):
        return out
    try:
        status = status_from_state(state)
    except Exception as exc:  # an unexpected layout must not break the whole digest
        out["error"] = f"the fleet state has an unexpected layout ({type(exc).__name__})"
        return out
    out["found"] = True
    manifest = state.get("manifest") or {}
    init = float(manifest.get("init_cash", 10_000.0))
    specs = {a.get("account_id"): a for a in manifest.get("accounts") or []}

    created = _parse(status.get("created_at"))
    last_cycle = _parse(status.get("last_cycle"))
    out["created_at"] = status.get("created_at")
    out["days_running"] = None if created is None else max(0.0, (now - created).total_seconds() / 86400.0)
    out["too_early"] = out["days_running"] is None or out["days_running"] < MIN_DAYS_FOR_VERDICT
    out["min_days_for_verdict"] = MIN_DAYS_FOR_VERDICT
    out["last_cycle"] = status.get("last_cycle")
    out["last_cycle_age_minutes"] = None if last_cycle is None else max(0.0, (now - last_cycle).total_seconds() / 60.0)
    out["cycles"] = status.get("cycles")
    health = status.get("health") or {}
    out["data_stale"] = bool(health.get("stale"))
    out["newest_candle"] = health.get("newest_candle") or {}
    out["last_errors"] = [str(e)[:200] for e in list(health.get("last_errors") or [])[-3:]]
    out["warnings"] = [str(w)[:200] for w in status.get("warnings") or []]

    accounts: List[Dict[str, Any]] = []
    for aid, item in (status.get("accounts") or {}).items():
        spec = specs.get(aid) or {}
        equity = item.get("equity")
        sleeves = item.get("sleeves_in_position") or {}
        accounts.append({
            "id": aid,
            "role": item.get("role") or spec.get("role"),
            "kind": spec.get("kind"),
            "instrument": spec.get("instrument"),
            "timeframe": spec.get("timeframe"),
            "candidate": (spec.get("sleeve") or {}).get("candidate"),
            "holdout_confirmed": bool((spec.get("expectations") or {}).get("holdout_confirmed")),
            "equity": None if equity is None else float(equity),
            "return": None if equity is None else float(equity) / init - 1.0,
            "in_position": bool(item.get("in_position")) or any(bool(v) for v in sleeves.values()),
            "retired": bool(item.get("retired_at")),
            "allocator": item.get("allocator"),
        })
    active = [a for a in accounts if not a["retired"]]
    out["accounts"] = len(active)
    out["retired"] = len(accounts) - len(active)
    out["in_position"] = sum(1 for a in active if a["in_position"])
    ranked = sorted((a for a in active if a["role"] != "control" and a["return"] is not None), key=lambda a: a["return"])
    out["best"] = _brief(ranked[-1]) if ranked else None
    out["worst"] = _brief(ranked[0]) if ranked else None
    confirmed = []
    for a in active:
        if not a["holdout_confirmed"]:
            continue
        control = next((c for c in active if c["role"] == "control" and c["candidate"] == "hold"
                        and c["instrument"] == a["instrument"] and c["timeframe"] == a["timeframe"]), None)
        confirmed.append({"account": _brief(a), "control": _brief(control) if control else None})
    out["confirmed"] = confirmed
    allocator = next((a for a in active if a.get("allocator")), None)
    if allocator is not None:
        alloc = allocator["allocator"]
        out["allocator"] = {"id": allocator["id"], "return": allocator["return"],
                            "cooldown_days_left": int(alloc.get("cooldown_days_left") or 0),
                            "loss_limit_trips": int(alloc.get("loss_limit_trips") or 0)}
    reports = sorted(paths.reports.glob("weekly-*.md")) if paths.reports.is_dir() else []
    out["latest_report"] = str(reports[-1]) if reports else None
    # The weekly report's own verdicts (same code, same bands): status per configuration and drawdown alarms.
    try:
        data = build_report_data(paths, now)
        verdicts: Dict[str, int] = {}
        alarms: List[str] = []
        for row in data["rows"]:
            account = row["account"]
            if account.get("role") == "control" or account.get("account_id") not in {a["id"] for a in active}:
                continue
            status = str((row.get("verdicts") or {}).get("status") or "n/a")
            verdicts[status] = verdicts.get(status, 0) + 1
            if (row.get("verdicts") or {}).get("drawdown") == "ALARM":
                alarms.append(str(account.get("account_id")))
        out["verdicts"] = verdicts
        out["drawdown_alarms"] = alarms
    except Exception as exc:  # the verdicts are an extra; the facts above stand on their own
        out["verdicts_error"] = f"the weekly report's verdicts could not be computed ({type(exc).__name__})"
    return out
