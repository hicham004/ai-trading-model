"""Exchange-authoritative reconciliation (fail closed on the unexplained).

The exchange - not the local ledger - is authoritative for orders, fills, and
balances. Before new entries are allowed, the runtime reconciles:

* every OWNED open intent is resolved by querying the exchange by client order
  id (handled by the lifecycle);
* exchange open orders whose client order id we do not recognise are FOREIGN.
  Foreign orders make reconciliation inconsistent and require operator review;
  they are NEVER cancelled automatically;
* exchange fills are recorded idempotently;
* base/quote balances are compared against an immutable first-run baseline
  adjusted by our own recorded fills. OKX's preloaded demo assets are reserved
  inventory, not bot positions; a later unexplained difference fails closed.

A ``consistent=False`` result blocks new entries; protective handling and
operator commands remain available.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DemoBalanceSnapshot, DemoFill, DemoOrderIntent
from app.execution.ids import CLIENT_ORDER_PREFIX
from app.execution.store import (
    STATUS_LIVE,
    STATUS_PARTIAL,
    STATUS_PENDING,
    STATUS_UNKNOWN,
    DemoStore,
)
from app.exchange.okx_demo_rest import OKXDemoRestClient
from app.logging_config import get_logger

logger = get_logger(__name__)

# Tolerance (base-currency units) for the balance cross-check.
_BALANCE_TOLERANCE = Decimal("0.00000001")
_OPEN_STATUSES = {STATUS_PENDING, STATUS_UNKNOWN, STATUS_LIVE, STATUS_PARTIAL}


@dataclass
class ReconcileResult:
    consistent: bool
    foreign_orders: int = 0
    unexplained_balances: int = 0
    wrong_scope: int = 0
    issues: List[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _dec(value: object) -> Optional[Decimal]:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


class DemoReconciler:
    """Compares exchange truth to the local ledger and fails closed."""

    def __init__(
        self,
        store: DemoStore,
        rest: OKXDemoRestClient,
        session_factory: Callable[[], Session],
        account_id: int,
        *,
        instruments: tuple[str, ...],
        key_fingerprint: Optional[str] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
        stops=None,
    ) -> None:
        self._store = store
        self._rest = rest
        self._session_factory = session_factory
        self._account_id = account_id
        self._instruments = instruments
        self._key_fingerprint = key_fingerprint
        self._clock = clock
        self._stops = stops  # ProtectiveStopManager (Sprint 3) or None
        self._metas: dict = {}

    def set_instrument_meta(self, metas) -> None:
        """Instrument rules (lot/min sizes) for the position-vs-stop report (set by the driver after validation)."""
        self._metas = dict(metas or {})

    def reconcile(self) -> ReconcileResult:
        now = self._clock()
        issues: List[str] = []
        intents = self._load_intents()
        known = set(intents)
        # Sibling accounts on the SAME API key: a clOrdId they own is "wrong
        # account scope" (running under the wrong --account), not foreign.
        sibling_owner = self._sibling_clordid_owners()
        wrong_scope = 0
        stops = self._stops if (self._stops is not None and self._stops.enabled) else None
        owned_children = 0

        # 1) Foreign or locally incompatible open orders (never cancelled here).
        foreign = 0
        pending = self._rest.get_pending_orders()
        for order in pending:
            inst = str(order.get("instId", ""))
            if inst not in self._instruments:
                continue
            cl = str(order.get("clOrdId", "") or "")
            if not cl or not cl.startswith(CLIENT_ORDER_PREFIX) or cl not in known:
                child = stops.owned_child(order) if stops is not None else None
                if child is not None:
                    # The venue-created SELL of an owned exchange-side stop (still resting / partially filled).
                    owned_children += 1
                    cid = stops.child_client_id(
                        child, child_ord_id=str(order.get("ordId") or "") or None,
                        size=str(order.get("sz") or child.actual_size or child.size), now=now,
                    )
                    self._store.apply_order_update(
                        self._account_id, client_order_id=cid, exchange_order_id=str(order.get("ordId") or "") or None,
                        state=str(order.get("state", "") or ""),
                        filled_size=str(order.get("accFillSz")) if order.get("accFillSz") not in (None, "") else None,
                        avg_price=str(order.get("avgPx")) if order.get("avgPx") else None,
                        fee=str(order.get("fee")) if order.get("fee") else None,
                        fee_ccy=str(order.get("feeCcy")) if order.get("feeCcy") else None,
                        update_time=now, source="reconcile", now=now,
                    )
                    continue
                owner = sibling_owner.get(cl)
                if owner is not None:
                    wrong_scope += 1
                    issues.append(
                        f"WRONG ACCOUNT SCOPE: open order on {inst} "
                        f"ordId={order.get('ordId')} clOrdId={cl} belongs to local "
                        f"account {owner!r} on this same API key; run under "
                        f"--account {owner} (NOT foreign; NOT auto-cancelled)"
                    )
                    continue
                foreign += 1
                issues.append(
                    f"foreign open order on {inst} ordId={order.get('ordId')} "
                    f"clOrdId={cl or '<none>'} (NOT auto-cancelled; operator review)"
                )
                continue
            intent = intents[cl]
            if intent.status not in _OPEN_STATUSES or intent.instrument != inst:
                foreign += 1
                issues.append(
                    f"exchange-open order {cl} conflicts with local "
                    f"status={intent.status} instrument={intent.instrument}; "
                    "operator review"
                )
                continue
            mismatches = []
            for field, expected in (
                ("side", intent.side),
                ("ordType", intent.ord_type),
            ):
                actual = str(order.get(field, "") or "")
                if actual and actual != expected:
                    mismatches.append(f"{field}={actual!r} expected {expected!r}")
            for field, expected in (("sz", intent.size), ("px", intent.price)):
                actual = _dec(order.get(field))
                wanted = _dec(expected)
                if actual is not None and wanted is not None and actual != wanted:
                    mismatches.append(f"{field}={actual} expected {wanted}")
            if mismatches:
                foreign += 1
                issues.append(
                    f"exchange-open order {cl} parameter mismatch: "
                    + ", ".join(mismatches)
                )

        # 1b) Exchange-side protective stops: venue pending algo orders vs the local stop ledger.
        algo_pending = 0
        if stops is not None:
            venue_algos: List[dict] = []
            for ord_type in ("conditional", "oco"):
                venue_algos.extend(self._rest.get_pending_algo_orders(ord_type))
            local_open = {r.algo_cl_ord_id: r for r in self._store.list_open_algo_orders(self._account_id)}
            seen: set = set()
            for row in venue_algos:
                inst = str(row.get("instId", ""))
                if inst not in self._instruments:
                    continue
                algo_pending += 1
                algo_cl = str(row.get("algoClOrdId", "") or "")
                local = self._store.get_algo_order(self._account_id, algo_cl) if algo_cl else None
                if local is None and row.get("algoId"):
                    local = self._store.find_algo_order(self._account_id, algo_id=str(row.get("algoId")))
                if local is None:
                    foreign += 1
                    issues.append(
                        f"foreign algo order on {inst} algoId={row.get('algoId')} algoClOrdId={algo_cl or '<none>'} "
                        "(NOT auto-cancelled; operator review)"
                    )
                    continue
                seen.add(local.algo_cl_ord_id)
                if str(row.get("side", "") or "") not in ("", "sell") or str(row.get("tdMode", "") or "") not in ("", "cash"):
                    foreign += 1
                    issues.append(f"owned algo order {local.algo_cl_ord_id} has unexpected side/tdMode; operator review")
                    continue
                stops.project(local.algo_cl_ord_id, row, source="reconcile", now=now)
            for algo_cl in local_open:
                if algo_cl not in seen:
                    stops.resolve(algo_cl, now=now)

        # 2) Record only fills belonging to known, matching local intents.
        recorded_fills = 0
        for inst in self._instruments:
            for fill in self._rest.get_fills(inst):
                trade_id = str(fill.get("tradeId", "") or "")
                if not trade_id:
                    continue
                cl = str(fill.get("clOrdId", "") or "")
                intent = intents.get(cl)
                side = str(fill.get("side", "") or "")
                size = _dec(fill.get("fillSz"))
                price = _dec(fill.get("fillPx"))
                child_intent = None
                if intent is None and stops is not None and not self._store.has_fill(self._account_id, trade_id):
                    # A fill of the venue-created SELL of an owned stop carries no local clOrdId:
                    # match by algoClOrdId / algoId / child ordId, else ask the venue which order it was.
                    child = stops.owned_child(fill)
                    if child is None and fill.get("ordId") and not cl:
                        try:
                            parent_order = self._rest.get_order(inst, ord_id=str(fill.get("ordId")))
                        except Exception as exc:  # unknown stays unknown; classified as foreign below
                            parent_order = None
                            logger.warning("child order lookup failed", extra={"error_type": type(exc).__name__})
                        if parent_order:
                            child = stops.owned_child(parent_order)
                    if child is not None:
                        cid = stops.child_client_id(
                            child, child_ord_id=str(fill.get("ordId") or "") or None,
                            size=str(child.actual_size or child.size), now=now,
                        )
                        cl = cid
                        child_intent = self._store.get_intent(self._account_id, cid)
                        intent = child_intent
                if (
                    not cl
                    or not cl.startswith(CLIENT_ORDER_PREFIX)
                    or intent is None
                    or intent.instrument != inst
                    or side != intent.side
                    or size is None
                    or size <= 0
                    or price is None
                    or price <= 0
                ):
                    if intent is None and self._store.has_fill(self._account_id, trade_id):
                        continue  # already recorded under a local id (e.g. an earlier child classification)
                    owner = sibling_owner.get(cl)
                    if owner is not None and intent is None:
                        wrong_scope += 1
                        issues.append(
                            f"WRONG ACCOUNT SCOPE: fill tradeId={trade_id} on {inst} "
                            f"clOrdId={cl} belongs to local account {owner!r} on this "
                            f"same API key; run under --account {owner} (NOT foreign)"
                        )
                        continue
                    foreign += 1
                    issues.append(
                        f"foreign or mismatched fill tradeId={trade_id} "
                        f"on {inst} clOrdId={cl or '<none>'}; operator review"
                    )
                    continue
                created = self._store.record_fill(
                    self._account_id,
                    fill_id=trade_id,
                    client_order_id=cl,
                    exchange_order_id=str(fill.get("ordId", "") or "") or None,
                    instrument=inst,
                    side=side,
                    fill_size=str(fill.get("fillSz", "0")),
                    fill_price=str(fill.get("fillPx", "0")),
                    fee=str(fill.get("fee")) if fill.get("fee") is not None else None,
                    fee_ccy=str(fill.get("feeCcy")) if fill.get("feeCcy") else None,
                    fill_time=now,
                    source="reconcile",
                    now=now,
                )
                if created:
                    recorded_fills += 1
                if child_intent is not None:
                    owned_children += 1
                    total = self._store.filled_size_for(self._account_id, cl)
                    wanted = _dec(child_intent.size) or Decimal(0)
                    self._store.apply_order_update(
                        self._account_id, client_order_id=cl, exchange_order_id=str(fill.get("ordId") or "") or None,
                        state="filled" if total >= wanted and wanted > 0 else "partially_filled",
                        filled_size=str(total), avg_price=None, fee=None, fee_ccy=None,
                        update_time=now, source="reconcile", now=now,
                    )

        # 3) Balance cross-check against a stored baseline adjusted by our fills.
        balances = self._rest.get_balances()
        details = balances.get("details", []) if isinstance(balances, dict) else []
        balance_list = [
            {
                "ccy": str(d.get("ccy", "")),
                # cashBal is total cash and is not distorted by funds frozen in
                # our own open orders. availBal is only a fallback.
                "avail": str(
                    d.get("cashBal", d.get("eq", d.get("availBal", d.get("availEq", "0"))))
                ),
                "eq": str(d.get("eq", "0")),
            }
            for d in details
            if isinstance(d, dict)
        ]
        self._store.record_balances(self._account_id, balance_list, source="rest", now=now)
        baseline = self._load_or_create_baseline(balance_list, now)
        unexplained = self._check_balances(balance_list, baseline, issues)

        # 4) Positions without a live exchange-side stop (reported; the driver's guard alarms).
        unprotected = 0
        if stops is not None:
            from app.execution.precision import floor_size
            from app.execution.store import ALGO_LIVE

            for inst in self._instruments:
                meta = self._metas.get(inst)
                if meta is None:
                    continue
                position, _ = self._store.position_summary(self._account_id, inst)
                try:
                    sellable = floor_size(position, meta.lot_size) if position > 0 else Decimal(0)
                except Exception:  # pragma: no cover - defensive
                    sellable = Decimal(0)
                if sellable >= meta.min_size and not any(
                    r.status == ALGO_LIVE for r in self._store.list_open_algo_orders(self._account_id, instrument=inst)
                ):
                    unprotected += 1
                    issues.append(f"position on {inst} ({sellable}) has no live exchange-side stop")

        consistent = foreign == 0 and wrong_scope == 0 and unexplained == 0
        summary = {
            "instruments": list(self._instruments),
            "pending_orders": len(pending),
            "recorded_fills": recorded_fills,
            "wrong_scope": wrong_scope,
            "balances": balance_list,
            "algo_pending": algo_pending,
            "owned_children": owned_children,
            "unprotected_positions": unprotected,
        }
        self._store.record_reconciliation(
            self._account_id,
            consistent=consistent,
            foreign_orders=foreign,
            unexplained_balances=unexplained,
            issues=issues,
            summary=summary,
            now=now,
        )
        if not consistent:
            logger.warning(
                "demo reconciliation INCONSISTENT; new entries blocked",
                extra={
                    "foreign_orders": foreign,
                    "wrong_scope": wrong_scope,
                    "unexplained": unexplained,
                },
            )
        return ReconcileResult(
            consistent, foreign, unexplained, wrong_scope, issues, summary
        )

    def _sibling_clordid_owners(self) -> dict[str, str]:
        """Map clOrdId -> sibling account name for same-key accounts (not self).

        Lets reconciliation report a clOrdId owned by another local account on
        the SAME API key as 'wrong account scope' rather than 'foreign'.
        """
        from app.execution.account_guard import (
            account_fingerprint,
            clordid_owners_for_fingerprint,
        )

        fp = self._key_fingerprint or account_fingerprint(
            self._session_factory, self._account_id
        )
        if not fp:
            return {}
        return clordid_owners_for_fingerprint(
            self._session_factory, fp, exclude_account_id=self._account_id
        )

    def _load_intents(self) -> dict[str, DemoOrderIntent]:
        session = self._session_factory()
        try:
            rows = session.scalars(
                select(DemoOrderIntent).where(
                    DemoOrderIntent.account_id == self._account_id
                )
            ).all()
            return {row.client_order_id: row for row in rows}
        finally:
            session.close()

    def _load_or_create_baseline(self, current: list, now: datetime) -> dict:
        """Return the baseline per-ccy availability, creating it on first run."""
        session = self._session_factory()
        try:
            row = session.scalar(
                select(DemoBalanceSnapshot)
                .where(
                    DemoBalanceSnapshot.account_id == self._account_id,
                    DemoBalanceSnapshot.source == "baseline",
                )
                .order_by(DemoBalanceSnapshot.id.asc())
                .limit(1)
            )
            stored = row.balances_json if row is not None else None
        finally:
            session.close()
        if stored is None:
            # OKX demo accounts are normally seeded with several virtual assets.
            # Preserve the first authenticated snapshot as immutable reserved
            # inventory. Bot position/exposure accounting is fill-derived, so
            # these preloaded base assets can never be sold by this runtime.
            self._store.record_balances(
                self._account_id, current, source="baseline", now=now
            )
            return {b["ccy"]: b["avail"] for b in current}
        try:
            parsed = json.loads(stored)
            return {b["ccy"]: b["avail"] for b in parsed if isinstance(b, dict)}
        except (ValueError, TypeError):
            return {}

    def _check_balances(self, current: list, baseline: dict, issues: List[str]) -> int:
        """Flag configured base/quote cash balances unexplained by owned fills."""
        net = self._net_currency_from_fills()
        current_by_ccy = {b["ccy"]: b["avail"] for b in current}
        unexplained = 0
        base_ccys = {inst.split("-")[0] for inst in self._instruments}
        quote_ccys = {inst.split("-")[1] for inst in self._instruments}
        for ccy in base_ccys | quote_ccys:
            cur = _dec(current_by_ccy.get(ccy, "0")) or Decimal(0)
            base = _dec(baseline.get(ccy, "0")) or Decimal(0)
            expected = base + net.get(ccy, Decimal(0))
            if (cur - expected).copy_abs() > _BALANCE_TOLERANCE:
                unexplained += 1
                issues.append(
                    f"unexplained {ccy} balance: have {cur}, expected ~{expected} "
                    "(baseline + recorded fills); operator review"
                )
        return unexplained

    def _net_currency_from_fills(self) -> dict[str, Decimal]:
        """Net base/quote cash changes implied by our own recorded fills."""
        session = self._session_factory()
        try:
            fills = session.scalars(
                select(DemoFill).where(DemoFill.account_id == self._account_id)
            ).all()
        finally:
            session.close()
        net: dict[str, Decimal] = {}
        for fill in fills:
            base, quote = fill.instrument.split("-")[:2]
            size = _dec(fill.fill_size) or Decimal(0)
            price = _dec(fill.fill_price) or Decimal(0)
            notional = size * price
            if fill.side == "buy":
                net[base] = net.get(base, Decimal(0)) + size
                net[quote] = net.get(quote, Decimal(0)) - notional
            elif fill.side == "sell":
                net[base] = net.get(base, Decimal(0)) - size
                net[quote] = net.get(quote, Decimal(0)) + notional
            if fill.fee_ccy:
                net[fill.fee_ccy] = net.get(fill.fee_ccy, Decimal(0)) + (
                    _dec(fill.fee) or Decimal(0)
                )
        return net
