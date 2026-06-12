"""Phase 6a decision journal: append-only JSONL with daily UTC rollover.

Two complementary sources are journaled so runs can be replayed and compared
against backtests (and, later, the Phase 6b news log):

* ``DecisionJournal`` — lines written directly by the supervisor: every
  confirmed candle, every shadow-evaluated signal (with confidence and veto
  reason), every stop evaluation, supervisor lifecycle/health, heartbeats.
* ``LedgerPoller`` — id-watermarked mirrors of the authoritative demo ledger
  tables (events, intents, submissions, order updates, fills,
  reconciliations). The runtime remains authoritative; the journal is a
  read-only projection and never mutates the ledger.

No secrets are ever written: the mirrored tables are secret-free by design
and the journal adds only market data and decision metadata.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

from sqlalchemy import select

from app.db.models import (
    DemoEvent,
    DemoFill,
    DemoOrderIntent,
    DemoOrderUpdate,
    DemoReconciliation,
    DemoSubmission,
)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class DailyJsonlWriter:
    """Append JSON lines to ``<dir>/<prefix>-YYYY-MM-DD.jsonl`` (UTC days)."""

    def __init__(
        self,
        directory: Path,
        prefix: str,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._dir = Path(directory)
        self._prefix = prefix
        self._clock = clock
        self._dir.mkdir(parents=True, exist_ok=True)
        self._current_day: Optional[str] = None
        self._handle = None

    def path_for_day(self, day: str) -> Path:
        return self._dir / f"{self._prefix}-{day}.jsonl"

    def write(self, record: dict) -> None:
        now = self._clock()
        day = now.date().isoformat()
        if day != self._current_day:
            self.close()
            self._handle = open(self.path_for_day(day), "a", encoding="utf-8")
            self._current_day = day
        record = {"ts": now.isoformat(), **record}
        self._handle.write(json.dumps(record, default=str) + "\n")
        self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            try:
                self._handle.close()
            finally:
                self._handle = None
                self._current_day = None


class DecisionJournal:
    """Typed convenience facade over the daily JSONL writer."""

    def __init__(self, writer: DailyJsonlWriter) -> None:
        self._writer = writer

    def write(self, kind: str, **fields) -> None:
        self._writer.write({"kind": kind, **fields})

    def close(self) -> None:
        self._writer.close()


def write_atomic_json(path: Path, payload: dict) -> None:
    """Write a small JSON file atomically (tmp + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    os.replace(tmp, path)


class LedgerPoller:
    """Journal new demo-ledger rows past per-table id watermarks (read-only)."""

    def __init__(self, session_factory, account_id: int, journal: DecisionJournal) -> None:
        self._session_factory = session_factory
        self._account_id = account_id
        self._journal = journal
        self._watermarks: Dict[str, int] = {}

    def prime(self) -> None:
        """Set watermarks to the current table heads WITHOUT journaling them.

        Used at supervisor startup so the journal records only what happens
        during the shadow run (historical rows are already in the database).
        """
        for name, model in self._tables():
            session = self._session_factory()
            try:
                head = session.scalar(
                    select(model.id)
                    .where(model.account_id == self._account_id)
                    .order_by(model.id.desc())
                    .limit(1)
                )
            finally:
                session.close()
            self._watermarks[name] = int(head or 0)

    def poll(self) -> int:
        """Journal every new row; returns the number of lines written."""
        written = 0
        for name, model in self._tables():
            wm = self._watermarks.get(name, 0)
            session = self._session_factory()
            try:
                rows = list(
                    session.scalars(
                        select(model)
                        .where(model.account_id == self._account_id, model.id > wm)
                        .order_by(model.id.asc())
                    ).all()
                )
            finally:
                session.close()
            for row in rows:
                self._journal.write(f"ledger_{name}", **self._row_fields(name, row))
                self._watermarks[name] = int(row.id)
                written += 1
        return written

    @staticmethod
    def _tables():
        return (
            ("event", DemoEvent),
            ("intent", DemoOrderIntent),
            ("submission", DemoSubmission),
            ("order_update", DemoOrderUpdate),
            ("fill", DemoFill),
            ("reconciliation", DemoReconciliation),
        )

    @staticmethod
    def _row_fields(name: str, row) -> dict:
        if name == "event":
            return {
                "row_id": row.id,
                "event_time": row.event_time,
                "event_type": row.event_type,
                "severity": row.severity,
                "message": row.message,
                "payload": row.payload_json,
            }
        if name == "intent":
            return {
                "row_id": row.id,
                "client_order_id": row.client_order_id,
                "signal_id": row.signal_id,
                "instrument": row.instrument,
                "side": row.side,
                "intent": row.intent,
                "ord_type": row.ord_type,
                "price": row.price,
                "size": row.size,
                "stop_loss": row.stop_loss,
                "status": row.status,
                "requested_at": row.requested_at,
            }
        if name == "submission":
            return {
                "row_id": row.id,
                "client_order_id": row.client_order_id,
                "request_kind": row.request_kind,
                "attempt": row.attempt,
                "outcome": row.outcome,
                "code": row.code,
                "message": row.message,
                "sent_at": row.sent_at,
            }
        if name == "order_update":
            return {
                "row_id": row.id,
                "client_order_id": row.client_order_id,
                "state": row.state,
                "filled_size": row.filled_size,
                "avg_price": row.avg_price,
                "fee": row.fee,
                "fee_ccy": row.fee_ccy,
                "source": row.source,
                "update_time": row.update_time,
            }
        if name == "fill":
            return {
                "row_id": row.id,
                "fill_id": row.fill_id,
                "client_order_id": row.client_order_id,
                "instrument": row.instrument,
                "side": row.side,
                "fill_size": row.fill_size,
                "fill_price": row.fill_price,
                "fee": row.fee,
                "fee_ccy": row.fee_ccy,
                "fill_time": row.fill_time,
                "source": row.source,
            }
        if name == "reconciliation":
            return {
                "row_id": row.id,
                "run_at": row.run_at,
                "consistent": row.consistent,
                "foreign_orders": row.foreign_orders,
                "unexplained_balances": row.unexplained_balances,
                "issues": row.issues_json,
            }
        return {"row_id": row.id}
