"""Phase 6a daily summary report (offline; journal + local ledger only).

Aggregates one UTC day of the shadow run into a morning-readable markdown
file: signals fired/vetoed and the clearance rate, trades/PnL/fees, sub-lot
dust (lot-precision flatness via ``is_flat``), WS/feed uptime, reconcile
checks, restarts and cap/halt events. Read-only; no network.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from app.db.models import DemoFill, DemoReconciliation
from app.execution.precision import is_flat


def _dec(value, default: Decimal = Decimal(0)) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default
    return out if out.is_finite() else default


def _load_journal_lines(journal_dir: Path, day: date) -> list[dict]:
    path = Path(journal_dir) / f"journal-{day.isoformat()}.jsonl"
    if not path.exists():
        return []
    lines: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            lines.append(json.loads(raw))
        except ValueError:
            lines.append({"kind": "_unparseable", "raw": raw[:200]})
    return lines


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return start, start.replace(hour=23, minute=59, second=59, microsecond=999999)


def generate_daily_report(
    *,
    journal_dir: Path,
    session_factory,
    account_id: int,
    day: date,
    instrument: str,
    min_confidence: float,
) -> str:
    """Render the markdown daily report for one UTC day."""
    lines = _load_journal_lines(journal_dir, day)
    start, end = _day_bounds(day)

    # -- signals (shadow evaluation; runtime decisions are mirrored separately)
    signals = [l for l in lines if l.get("kind") == "signal"]
    longs = [s for s in signals if s.get("action") == "long"]
    cleared = [s for s in longs if s.get("cleared")]
    flats = sum(1 for s in signals if s.get("action") == "flat")
    holds = sum(1 for s in signals if s.get("action") == "hold")
    clearance = (len(cleared) / len(longs)) if longs else None

    # -- authoritative runtime decisions mirrored from the ledger
    decisions = Counter()
    for l in lines:
        if l.get("kind") == "ledger_event" and l.get("event_type") == "risk_decision":
            decisions[str(l.get("message", ""))[:80]] += 1

    # -- candles / stop evaluations
    candles = sum(1 for l in lines if l.get("kind") == "candle")
    stop_evals = [l for l in lines if l.get("kind") == "stop_eval"]
    stop_breaches = sum(1 for s in stop_evals if s.get("breached"))

    # -- trades / PnL / fees from the authoritative fills table
    session = session_factory()
    try:
        day_fills = list(
            session.scalars(
                select(DemoFill).where(
                    DemoFill.account_id == account_id,
                    DemoFill.instrument == instrument,
                    DemoFill.fill_time >= start,
                    DemoFill.fill_time <= end,
                ).order_by(DemoFill.id.asc())
            ).all()
        )
        all_fills = list(
            session.scalars(
                select(DemoFill).where(
                    DemoFill.account_id == account_id,
                    DemoFill.instrument == instrument,
                ).order_by(DemoFill.id.asc())
            ).all()
        )
        recs = list(
            session.scalars(
                select(DemoReconciliation).where(
                    DemoReconciliation.account_id == account_id,
                    DemoReconciliation.run_at >= start,
                    DemoReconciliation.run_at <= end,
                ).order_by(DemoReconciliation.id.asc())
            ).all()
        )
    finally:
        session.close()

    buys = sells = Decimal(0)
    buy_n = sell_n = 0
    fees: dict[str, Decimal] = {}
    for f in day_fills:
        notional = _dec(f.fill_size) * _dec(f.fill_price)
        if f.side == "buy":
            buys += notional
            buy_n += 1
        else:
            sells += notional
            sell_n += 1
        if f.fee_ccy and f.fee:
            fees[f.fee_ccy] = fees.get(f.fee_ccy, Decimal(0)) + _dec(f.fee)
    quote_ccy = instrument.split("-")[1]
    cash_pnl = sells - buys + fees.get(quote_ccy, Decimal(0))

    # -- end-of-day position and dust (fills are authoritative; lot size from
    #    the journal's meta line when the supervisor recorded one)
    base_ccy = instrument.split("-")[0]
    net = Decimal(0)
    for f in all_fills:
        size = _dec(f.fill_size)
        net += size if f.side == "buy" else -size
        if f.fee_ccy == base_ccy and f.fee:
            net += _dec(f.fee)
    net = max(net, Decimal(0))
    lot_size: Optional[Decimal] = None
    for l in lines:
        if l.get("kind") == "meta" and l.get("instrument") == instrument:
            lot_size = _dec(l.get("lot_size"), Decimal(0)) or None
    if lot_size is not None:
        flat = is_flat(net, lot_size)
        position_line = (
            f"FLAT at lot precision (sub-lot dust {net})" if flat and net > 0
            else ("FLAT" if flat else f"{net} OPEN")
        )
    else:
        position_line = f"{net} (raw net; lot size not journaled)"

    # -- uptime from health lines
    health = [l for l in lines if l.get("kind") == "health"]
    def pct(key: str) -> Optional[float]:
        if not health:
            return None
        return 100.0 * sum(1 for h in health if h.get(key)) / len(health)
    ws_pct, feed_pct = pct("ws_auth"), pct("feed_usable")

    # -- reconcile checks
    rec_ok = sum(1 for r in recs if r.consistent)
    rec_bad = len(recs) - rec_ok

    # -- supervisor events (restarts, caps, halts, kill switch)
    sup = [l for l in lines if l.get("kind") == "supervisor"]
    sup_counts = Counter(str(l.get("event")) for l in sup)

    def fmt(value, digits: int = 1) -> str:
        return "n/a" if value is None else f"{value:.{digits}f}"

    out = [
        f"# Shadow daily report — {day.isoformat()} (UTC) — {instrument}",
        "",
        "DEMO ONLY (`x-simulated-trading: 1`). Generated offline from the",
        "decision journal and the local demo ledger. Analysis only.",
        "",
        "## Signals (shadow evaluation of the unmodified strategy)",
        f"- confirmed candles journaled: {candles}",
        f"- LONG signals: {len(longs)} (cleared >= {min_confidence:.2f}: "
        f"{len(cleared)}, vetoed: {len(longs) - len(cleared)})",
        f"- clearance rate: "
        + (f"{100.0 * clearance:.1f}%" if clearance is not None else "n/a (no LONG signals)"),
        f"- FLAT signals: {flats}; HOLD signals: {holds}",
        "",
        "## Runtime risk decisions (authoritative ledger events)",
    ]
    if decisions:
        out += [f"- {msg}: {count}" for msg, count in decisions.most_common()]
    else:
        out.append("- none recorded")
    out += [
        "",
        "## Trades / PnL / fees (authoritative fills)",
        f"- fills: {len(day_fills)} (buys: {buy_n}, sells: {sell_n})",
        f"- buy notional: {buys} {quote_ccy}; sell notional: {sells} {quote_ccy}",
        f"- fees: " + (", ".join(f"{v} {k}" for k, v in fees.items()) or "none"),
        f"- day cash PnL ({quote_ccy}, sells - buys + {quote_ccy} fees): {cash_pnl}",
        f"- end-of-report position: {position_line}",
        "",
        "## Stop tracking",
        f"- stop evaluations journaled: {len(stop_evals)} (breaches: {stop_breaches})",
        "",
        "## Infrastructure",
        f"- health samples: {len(health)}; private WS authenticated: {fmt(ws_pct)}%; "
        f"feed usable: {fmt(feed_pct)}%",
        f"- reconciliations: {len(recs)} (consistent: {rec_ok}, inconsistent: {rec_bad})",
        f"- supervisor events: "
        + (", ".join(f"{k}={v}" for k, v in sorted(sup_counts.items())) or "none"),
        "",
    ]
    return "\n".join(out)


def write_daily_report(
    *,
    journal_dir: Path,
    session_factory,
    account_id: int,
    day: date,
    instrument: str,
    min_confidence: float,
) -> Path:
    """Generate and atomically write ``report-YYYY-MM-DD.md``; returns path."""
    text = generate_daily_report(
        journal_dir=journal_dir,
        session_factory=session_factory,
        account_id=account_id,
        day=day,
        instrument=instrument,
        min_confidence=min_confidence,
    )
    path = Path(journal_dir) / f"report-{day.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path
