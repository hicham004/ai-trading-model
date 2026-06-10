"""Pre-arming demo account security validation (fail closed).

Before the runtime may ever be armed, the authenticated demo account is checked
against the Phase 5 boundary. Anything ambiguous or dangerous fails closed:

* the account level (mode) must be on the approved SPOT cash-only allowlist
  (margin / portfolio modes are refused);
* the configured instruments must be exactly approved BTC-USDT / ETH-USDT SPOT
  pairs with a matching quote currency and a tradable state;
* no liability / borrowing / negative cash may be present (margin/borrow
  forbidden);
* the API-key fingerprint and immutable execution identity must match the
  stored account (enforced separately by the store).

Withdrawal/transfer authority is made unrepresentable by the endpoint allowlist
(there is no code path that calls those endpoints); least-privilege keys remain
an operational requirement documented for key creation. This validator never
logs or returns any secret.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from app.exchange.instruments import InstrumentMeta, parse_instruments
from app.exchange.okx_demo_rest import OKXDemoRestClient
from app.logging_config import get_logger
from app.okx.client import ALLOWED_INSTRUMENTS

logger = get_logger(__name__)


@dataclass
class AccountValidation:
    ok: bool
    acct_level: str = ""
    issues: List[str] = field(default_factory=list)
    instruments: dict[str, InstrumentMeta] = field(default_factory=dict)


def _dec(value: object) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def validate_demo_account(
    rest: OKXDemoRestClient,
    *,
    instruments: tuple[str, ...],
    allowed_acct_levels: tuple[str, ...],
    quote_ccy: str,
) -> AccountValidation:
    """Validate the authenticated demo account before arming. Fail closed."""
    issues: List[str] = []

    # 1) Account mode must be SPOT cash-only compatible.
    config = rest.get_account_config()
    acct_lv = str(config.get("acctLv", "") or "")
    approved_levels = tuple(level for level in allowed_acct_levels if level == "1")
    if acct_lv not in approved_levels:
        issues.append(
            f"account level {acct_lv!r} is not approved for SPOT cash-only "
            "execution (Phase 5 requires Simple/Spot account level '1')"
        )

    # 2) Configured instruments must be exactly approved BTC/ETH SPOT pairs.
    for inst in instruments:
        if inst not in ALLOWED_INSTRUMENTS:
            issues.append(f"instrument {inst!r} is not an approved demo SPOT pair")
    metas = parse_instruments(rest.get_instruments())
    inst_meta: dict[str, InstrumentMeta] = {}
    for inst in instruments:
        meta = metas.get(inst)
        if meta is None or not meta.is_tradable():
            issues.append(f"{inst} is not a tradable SPOT pair on the venue")
        elif meta.quote_ccy != quote_ccy:
            issues.append(
                f"{inst} quote currency {meta.quote_ccy} does not match {quote_ccy}"
            )
        else:
            inst_meta[inst] = meta

    # 3) No borrowing / liabilities / negative cash (margin/borrow forbidden).
    balances = rest.get_balances()
    details = balances.get("details", []) if isinstance(balances, dict) else []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        ccy = str(detail.get("ccy", ""))
        liab = _dec(detail.get("liab"))
        if liab is not None and liab != 0:
            issues.append(f"liability on {ccy} ({liab}); borrowing/margin is forbidden")
        borrow = _dec(detail.get("borrowFroz"))
        if borrow is not None and borrow != 0:
            issues.append(f"frozen borrow on {ccy} ({borrow}); borrowing is forbidden")
        cash = _dec(detail.get("cashBal"))
        if cash is not None and cash < 0:
            issues.append(f"negative cash on {ccy} ({cash}); borrowing is forbidden")

    ok = not issues
    if not ok:
        logger.warning("demo account validation failed", extra={"issue_count": len(issues)})
    return AccountValidation(ok=ok, acct_level=acct_lv, issues=issues, instruments=inst_meta)
