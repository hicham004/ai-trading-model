"""Alembic environment: wires migrations to the app's SQLAlchemy metadata.

Database URL resolution order (never a hard-coded production URL):

1. ``alembic -x url=<sqlalchemy-url> ...`` (tests and one-off runs);
2. ``sqlalchemy.url`` in ``alembic.ini`` (left empty by default);
3. ``app.config.get_settings().database_url`` (``DATABASE_URL`` / ``.env``).

The runtime still creates tables with ``Base.metadata.create_all`` (see
``app/db/database.py``); switching the runtime to migrations is a separate,
reviewed change. Until then an existing database is brought under Alembic
control with ``alembic stamp head`` (see ``docs/runbooks/DB_MIGRATIONS.md``).
"""

from __future__ import annotations

import logging.config

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db.models import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    logging.config.fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _resolve_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    url = (x_args.get("url") or "").strip()
    if url:
        return url
    url = (config.get_main_option("sqlalchemy.url") or "").strip()
    if url:
        return url
    from app.config import get_settings  # local import: loads .env lazily

    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection (``alembic upgrade --sql``)."""
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    section = dict(config.get_section(config.config_ini_section) or {})
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things in place; batch mode rebuilds.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
