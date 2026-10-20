# Schema migrations (Alembic)

`0001_baseline` reproduces exactly what `Base.metadata.create_all` creates
today (see `tests/test_migrations.py`, which asserts the two agree). The
runtime still calls `create_all`; see `docs/runbooks/DB_MIGRATIONS.md` for how
to stamp an existing database and how to add a revision.
