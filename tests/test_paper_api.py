"""Offline tests for the read-only Phase 4 paper-ledger API."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.main import app
from app.api.paper import get_db as get_paper_db
from app.db.models import (
    Base,
    PaperAccount,
    PaperEquitySnapshot,
    PaperFill,
    PaperOrder,
    PaperRuntimeStatus,
)

NOW = datetime.now(tz=timezone.utc)


@pytest.fixture()
def paper_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as session:
        account = PaperAccount(name="default", starting_cash=10_000, config_json="{}")
        session.add(account)
        session.flush()
        session.add(
            PaperRuntimeStatus(
                account_id=account.id,
                status="running",
                lock_token="runner",
                lock_heartbeat=NOW,
                feed_connected=True,
                feed_stale=False,
                books_synchronized=True,
                reconciliation_consistent=True,
            )
        )
        session.add(
            PaperEquitySnapshot(
                account_id=account.id,
                snapshot_time=NOW,
                market_time=NOW,
                cash=7_500,
                position_value=2_500,
                equity=10_000,
                realized_pnl=0,
                unrealized_pnl=0,
                day_start_equity=10_000,
                day_realized_pnl=0,
                open_position_count=1,
                positions_json=json.dumps(
                    [
                        {
                            "instrument": "BTC-USDT",
                            "quantity": 0.025,
                            "entry_price": 100_000,
                            "stop_loss": 95_000,
                            "entry_time": NOW.isoformat(),
                            "signal_id": "signal-1",
                        }
                    ]
                ),
                kill_switch_engaged=False,
            )
        )
        session.add(
            PaperOrder(
                account_id=account.id,
                client_order_id="order-1",
                signal_id="signal-1",
                instrument="BTC-USDT",
                side="buy",
                intent="entry",
                quantity=0.025,
                reference_price=100_000,
                order_time=NOW,
                status="filled",
            )
        )
        session.add(
            PaperFill(
                account_id=account.id,
                fill_id="fill-1",
                client_order_id="order-1",
                instrument="BTC-USDT",
                side="buy",
                quantity=0.025,
                price=100_000,
                fee=2.5,
                slippage_cost=1,
                fill_time=NOW,
                is_simulated=True,
            )
        )
        session.commit()

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_paper_db] = override
    client = TestClient(app)
    try:
        yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_paper_endpoints_report_virtual_state(paper_client):
    client, _ = paper_client

    health = client.get("/paper/health").json()
    account = client.get("/paper/account").json()
    positions = client.get("/paper/positions").json()
    orders = client.get("/paper/orders").json()
    fills = client.get("/paper/fills").json()

    assert health["running"] is True
    assert account["equity"] == 10_000
    assert positions["positions"][0]["instrument"] == "BTC-USDT"
    assert orders[0]["status"] == "filled"
    assert fills[0]["is_simulated"] is True
    assert "simulation only" in account["note"].lower()


def test_stale_heartbeat_is_not_reported_running(paper_client):
    client, factory = paper_client
    with factory() as session:
        status = session.query(PaperRuntimeStatus).one()
        status.lock_heartbeat = NOW - timedelta(hours=1)
        session.commit()

    health = client.get("/paper/health").json()
    assert health["running"] is False
    assert health["status"] == "stale"


def test_account_uses_authoritative_current_kill_switch(paper_client):
    client, factory = paper_client
    with factory() as session:
        status = session.query(PaperRuntimeStatus).one()
        status.kill_switch_engaged = True
        session.commit()

    assert client.get("/paper/health").json()["kill_switch_engaged"] is True
    assert client.get("/paper/account").json()["kill_switch_engaged"] is True


def test_paper_routes_are_read_only(paper_client):
    client, _ = paper_client
    assert client.post("/paper/orders").status_code == 405
    assert client.post("/paper/account").status_code == 405
    assert client.delete("/paper/orders").status_code == 405


def test_daily_report_uses_starting_equity_before_first_snapshot(paper_client):
    client, factory = paper_client
    with factory() as session:
        account = PaperAccount(name="fresh", starting_cash=5_000, config_json="{}")
        session.add(account)
        session.commit()

    report = client.get("/paper/report/daily", params={"account": "fresh"}).json()
    assert report["equity"] == 5_000
    assert report["realized_pnl"] == 0
