"""The Alembic baseline must reproduce exactly what ``create_all`` builds.

Offline: runs the migrations against throwaway SQLite files and compares the
result with ``app.db.models.Base.metadata``. Also checks offline SQL rendering
for PostgreSQL (no connection is made).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.db.models import Base

ROOT = Path(__file__).resolve().parents[1]


def _config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", (ROOT / "migrations").as_posix())
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False  # keep pytest logging intact
    return cfg


@pytest.fixture()
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"


def test_single_linear_head():
    script = ScriptDirectory.from_config(_config("sqlite://"))
    assert script.get_heads() == ["0001"], "migration history must stay linear"
    assert script.get_base() == "0001"


def test_upgrade_head_matches_models(sqlite_url):
    command.upgrade(_config(sqlite_url), "head")
    engine = create_engine(sqlite_url, future=True)
    try:
        inspector = inspect(engine)
        expected = set(Base.metadata.tables)
        assert set(inspector.get_table_names()) == expected | {"alembic_version"}
        # Column-level agreement for every model table.
        for name, table in Base.metadata.tables.items():
            got = {c["name"] for c in inspector.get_columns(name)}
            assert got == {c.name for c in table.columns}, name
        # Autogenerate must have nothing left to say (tables, columns, indexes,
        # unique constraints, nullability). Types/defaults are rendered from
        # the same metadata, so they are excluded from this SQLite comparison.
        with engine.connect() as conn:
            ctx = MigrationContext.configure(
                conn, opts={"compare_type": False, "compare_server_default": False}
            )
            diff = compare_metadata(ctx, Base.metadata)
        assert diff == [], diff
    finally:
        engine.dispose()


def test_downgrade_to_base_removes_every_table(sqlite_url):
    cfg = _config(sqlite_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = create_engine(sqlite_url, future=True)
    try:
        remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
        assert remaining == set()
    finally:
        engine.dispose()


def test_offline_postgres_sql_renders_without_sqlite_isms(capsys):
    # Offline mode emits SQL for the target dialect without connecting.
    command.upgrade(_config("postgresql+psycopg://user:pw@localhost/db"), "head", sql=True)
    sql = capsys.readouterr().out
    assert "CREATE TABLE candles" in sql
    assert "CREATE TABLE demo_order_intents" in sql
    assert "alembic_version" in sql
    assert "DEFAULT now()" in sql, "server defaults must compile per dialect"
    assert "CURRENT_TIMESTAMP" not in sql
    assert "BIGINT" in sql  # sequence_id keeps its PostgreSQL type
