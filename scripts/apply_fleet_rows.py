"""Apply owner-decided paper-fleet rows from a spec file (plan row R23) — SIMULATION ONLY, no study run, no holdout opened.

Builds each row of the spec from its study's stored record (``research.fleet_rows``), appends the rows to the paper fleet's
shortlist with ``research.replication.append_to_shortlist`` (an amendment names the plan row and the decision) and proves the
fleet can load the amended file; if it cannot, the file is restored untouched (the R12 rule). Rows already in the shortlist are
never added twice. Nothing here trades, sizes or approves anything; the running fleet takes new accounts only at its next
restart from an updated checkout (``docs/runbooks/PAPER_FLEET.md``, "Updating the fleet's code").

Modes::

    python scripts/apply_fleet_rows.py --spec docs/research/paper_fleet_additions_r23.json --check   # build + validate on a copy
    python scripts/apply_fleet_rows.py --spec docs/research/paper_fleet_additions_r23.json           # apply (the R12 rule)

Exit codes: 0 = applied, checked, or nothing to add; 1 = the fleet cannot load the amended shortlist (restored); 2 = a bad spec,
a missing file or a record the row cannot be built from.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

if __name__ == "__main__":
    sys.modules.setdefault("dotenv", None)  # app/config.py then skips load_dotenv(): no .env secrets in this process (as the fleet does)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.fleet_rows import DEFAULT_SPEC, FleetRowError, apply_rows, build_rows, load_spec, rows_present  # noqa: E402
from research.paper_fleet.config import DEFAULT_SHORTLIST  # noqa: E402


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Apply owner-decided paper-fleet rows from a spec (simulation only; the R12 restore rule).")
    p.add_argument("--spec", type=Path, default=DEFAULT_SPEC, help=f"The decision spec (default {DEFAULT_SPEC.relative_to(DEFAULT_SPEC.parents[2]).as_posix()}).")
    p.add_argument("--shortlist", type=Path, default=DEFAULT_SHORTLIST, help="The paper fleet's shortlist JSON to amend.")
    p.add_argument("--check", action="store_true", help="Build the rows and validate the amended shortlist on a copy; write nothing.")
    p.add_argument("--json", action="store_true", help="Print the built rows as JSON.")
    return p.parse_args(argv)


def _summary(row) -> str:
    src = row.get("source") or {}
    hold = row.get("holdout") or {}
    words = (f"{row['candidate']} {row['instrument']} {row['timeframe']} [{(row.get('regime_config') or {}).get('mode')}] @ {src.get('cell')}"
             f" ({src.get('role')}) from {src.get('study')}: walk-forward Calmar {row.get('calmar')}, CAGR {row.get('cagr')}, max DD {row.get('max_drawdown')}, "
             f"{row.get('n_trades')} trades; gates {'passed' if row.get('passed') else 'not passed (' + ', '.join(row.get('failed_gates') or []) + ')'}")
    if hold:
        words += f"; holdout {hold.get('total_return')} ({hold.get('n_trades')} trades, {'confirmed' if row.get('holdout_confirmed') else 'not confirmed'})"
    else:
        words += "; no holdout (a control is never judged)" if src.get("role") == "control" else "; no holdout"
    return words


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        spec = load_spec(args.spec)
        rows = build_rows(spec)
    except (FleetRowError, ValueError, OSError, KeyError) as exc:
        print(f"fleet rows refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"{spec['plan_row']}: {len(rows)} row(s) built from the studies' records; decided: {spec['decided']}")
    for row in rows:
        print("  " + _summary(row))
    if args.json:
        print(json.dumps(rows, indent=1, default=str))
    try:
        shortlist = json.loads(Path(args.shortlist).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"fleet rows refused: cannot read {args.shortlist}: {exc}", file=sys.stderr)
        return 2
    present = rows_present(shortlist, rows)
    if len(present) == len(rows):
        print(f"already in the shortlist: {'; '.join(present)}; nothing to add")
        return 0
    if present:
        print(f"already in the shortlist (skipped): {'; '.join(present)}")
    try:
        ok, message, added = apply_rows(args.shortlist, rows, note=spec["amendment_note"], check_only=args.check)
    except (OSError, ValueError) as exc:
        print(f"fleet rows refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"shortlist: {message}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
