"""Account-partition safety guard (fail closed on ambiguous local accounts).

Phase 5 stores each logical demo "account" as a local row keyed by name. The
SAME OKX demo API key can back several local rows (e.g. ``demo`` and
``demo-seeded``). If a runtime silently runs under the default-named row while
another row on the SAME key owns the real order ledger, reconciliation sees the
exchange's own orders/fills as "foreign" and fails closed for the wrong reason.

This module makes that situation explicit instead of silent:

* :func:`assert_unambiguous_demo_account` hard-errors when more than one local
  account shares this credential's key fingerprint AND the operator did not
  explicitly choose one (no ``--account`` flag and no ``DEMO_ACCOUNT_NAME`` in
  the environment). The error names the candidates so the operator can pick.
* :func:`clordid_owners_for_fingerprint` lets the reconciler tell "wrong account
  scope" (a sibling row on the same key owns this clOrdId) apart from a genuinely
  foreign order/fill.

No secret is read here; only the non-reversible key fingerprint hint is used.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DemoAccount, DemoOrderIntent


class AmbiguousDemoAccountError(RuntimeError):
    """Raised when the demo account selection is ambiguous (fail closed)."""


def account_selection_source(account_flag: Optional[str], env_value: Optional[str]) -> str:
    """Classify how the demo account name was chosen: flag / env / default.

    * ``flag``    - an explicit ``--account`` argument was given.
    * ``env``     - no flag, but ``DEMO_ACCOUNT_NAME`` is set in the environment.
    * ``default`` - neither; the hard-coded default name is in use (implicit).
    """
    if account_flag is not None:
        return "flag"
    if (env_value or "").strip():
        return "env"
    return "default"


def log_account_selection(
    logger: logging.Logger, account_name: str, source: str
) -> None:
    """Emit a structured audit line naming the account and its selection source."""
    logger.info(
        "demo account selected",
        extra={"account": account_name, "selection_source": source},
    )


def _normalize(fingerprint: Optional[str]) -> str:
    return (fingerprint or "").strip()


def accounts_with_fingerprint(
    session_factory: Callable[[], Session], fingerprint: str
) -> List[Tuple[int, str]]:
    """Return ``(id, name)`` for every local account on this key fingerprint."""
    fp = _normalize(fingerprint)
    if not fp:
        return []
    session = session_factory()
    try:
        rows = session.execute(
            select(DemoAccount.id, DemoAccount.name)
            .where(DemoAccount.key_fingerprint == fp)
            .order_by(DemoAccount.id.asc())
        ).all()
        return [(int(r[0]), str(r[1])) for r in rows]
    finally:
        session.close()


def clordid_owners_for_fingerprint(
    session_factory: Callable[[], Session],
    fingerprint: str,
    *,
    exclude_account_id: Optional[int] = None,
) -> Dict[str, str]:
    """Map ``clOrdId -> owning account name`` across same-key sibling accounts.

    Used to classify an order/fill the current account does not own: if a
    sibling account on the SAME key owns the clOrdId, it is "wrong account
    scope", not genuinely foreign.
    """
    fp = _normalize(fingerprint)
    if not fp:
        return {}
    session = session_factory()
    try:
        rows = session.execute(
            select(DemoOrderIntent.client_order_id, DemoAccount.name)
            .join(DemoAccount, DemoAccount.id == DemoOrderIntent.account_id)
            .where(DemoAccount.key_fingerprint == fp)
        ).all()
        owners: Dict[str, str] = {}
        for cl_ord_id, name in rows:
            if exclude_account_id is not None:
                # Skip rows owned by the excluded account so a clOrdId the
                # current account already owns is never mislabelled.
                pass
            owners.setdefault(str(cl_ord_id), str(name))
        if exclude_account_id is not None:
            excluded = {
                str(r[0])
                for r in session.execute(
                    select(DemoOrderIntent.client_order_id).where(
                        DemoOrderIntent.account_id == exclude_account_id
                    )
                ).all()
            }
            owners = {cl: name for cl, name in owners.items() if cl not in excluded}
        return owners
    finally:
        session.close()


def account_fingerprint(
    session_factory: Callable[[], Session], account_id: int
) -> str:
    """Return the stored key fingerprint for one local account ('' if unknown)."""
    session = session_factory()
    try:
        return _normalize(
            session.scalar(
                select(DemoAccount.key_fingerprint).where(DemoAccount.id == account_id)
            )
        )
    finally:
        session.close()


def assert_unambiguous_demo_account(
    session_factory: Callable[[], Session],
    *,
    account_name: str,
    fingerprint: str,
    explicit: bool,
) -> None:
    """Fail closed if several local accounts share this key and none was chosen.

    ``explicit`` must be True when the operator selected the account on purpose
    (a ``--account`` flag or a ``DEMO_ACCOUNT_NAME`` environment value). When the
    selection is implicit (the hard-coded default) and more than one local
    account shares this credential's fingerprint, raise so the operator must pick.
    """
    if explicit:
        return
    candidates = accounts_with_fingerprint(session_factory, fingerprint)
    if len(candidates) < 2:
        return
    names = ", ".join(sorted(name for _, name in candidates))
    raise AmbiguousDemoAccountError(
        "multiple local demo accounts share this API key fingerprint "
        f"({names}); refusing to run under the default {account_name!r}. "
        "Choose one explicitly with --account <name> or set DEMO_ACCOUNT_NAME."
    )
