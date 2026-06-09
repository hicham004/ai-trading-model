"""Database engine and session management.

Provides a single shared engine plus a session factory. Other modules import
``get_session`` (a context manager) or ``session_scope`` for transactions.

The default database is the local Docker PostgreSQL service, but any
SQLAlchemy URL works (tests use an in-memory SQLite database), so the rest of
the code never needs to know which database is in use.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base
from app.logging_config import get_logger

logger = get_logger(__name__)

# Lazily-initialised module-level engine and session factory so importing this
# module never forces a database connection (handy for tests and tooling).
_engine: Optional[Engine] = None
_SessionFactory: Optional[sessionmaker] = None


def get_engine() -> Engine:
    """Return the shared SQLAlchemy engine, creating it on first use."""
    global _engine
    if _engine is None:
        database_url = get_settings().database_url
        # ``pool_pre_ping`` quietly recycles dropped connections, which is
        # common when PostgreSQL runs in a container that restarts.
        _engine = create_engine(database_url, pool_pre_ping=True, future=True)
        logger.info(
            "Created database engine",
            extra={"dialect": _engine.dialect.name},
        )
    return _engine


def get_session_factory() -> sessionmaker:
    """Return the shared session factory, creating it on first use."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _SessionFactory


def init_db() -> None:
    """Create all tables if they do not already exist."""
    Base.metadata.create_all(bind=get_engine())
    logger.info("Database tables are ready")


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session that commits on success, rolls back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
