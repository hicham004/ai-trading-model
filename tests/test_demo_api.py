"""Offline tests for the read-only /demo API and its read-only guarantee."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.execution as execution_api
from app.api.main import app
from app.db.models import Base
from app.execution.store import DemoStore

T0 = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def client_and_store():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)

    def _get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[execution_api.get_db] = _get_db
    store = DemoStore(factory, "demo")
    client = TestClient(app)
    try:
        yield client, store
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_demo_health_unknown_account(client_and_store):
    client, _ = client_and_store
    body = client.get("/demo/health", params={"account": "demo"}).json()
    assert body["exists"] is False
    assert body["armed"] is False
    assert "DEMO" in body["note"]


def test_demo_health_reflects_armed_and_kill_switch(client_and_store):
    client, store = client_and_store
    aid = store.ensure_account("fp", {"strategy": "ma"})
    store.arm(aid, ttl_seconds=900, now=datetime.now(tz=timezone.utc))
    store.set_kill_switch(aid, True, now=datetime.now(tz=timezone.utc))
    body = client.get("/demo/health", params={"account": "demo"}).json()
    assert body["exists"] is True
    assert body["armed"] is True
    assert body["kill_switch_engaged"] is True


def test_demo_account_view_has_no_secret_fields(client_and_store):
    client, store = client_and_store
    store.ensure_account("sha256:abcd1234", {"strategy": "ma"})
    body = client.get("/demo/account", params={"account": "demo"}).json()
    text = str(body).lower()
    assert "secret" not in text and "passphrase" not in text and "ok-access" not in text
    # only a non-reversible fingerprint hint is present
    assert body["key_fingerprint"] == "sha256:abcd1234"


def test_demo_intents_and_query_limits(client_and_store):
    client, _ = client_and_store
    assert client.get("/demo/intents", params={"limit": 0}).status_code == 422
    assert client.get("/demo/fills", params={"limit": 1000}).status_code == 422
    assert client.get("/demo/intents", params={"account": "demo"}).json() == []


def test_every_demo_route_is_read_only():
    for route in app.routes:
        if route.path.startswith("/demo/"):
            assert route.methods <= {"GET", "HEAD"}, route.path
