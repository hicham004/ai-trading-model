# Runbook — database schema migrations (Alembic)

Sprint 0 added Alembic with a **baseline revision `0001`** that reproduces
exactly the schema `Base.metadata.create_all` builds from `app/db/models.py`
(`tests/test_migrations.py` asserts they match). The runtime still calls
`create_all` on startup (`init_db` in `app/db/database.py`); switching the
runtime to migrations is a separate, reviewed change. Until then, migrations
are the reviewed way to evolve the schema and `create_all` stays a no-op
safety net for tables that already exist.

Files: `alembic.ini` (no URL inside), `migrations/env.py`,
`migrations/versions/*.py`. `migrations/` and `alembic.ini` are
safety-sensitive paths for the travel-mode guard.

## Which database does a command hit?

`migrations/env.py` resolves the URL in this order:

1. `alembic -x url=<sqlalchemy-url> <command>` (explicit; used by tests);
2. `sqlalchemy.url` in `alembic.ini` (empty on purpose);
3. `DATABASE_URL` from the environment / `.env` via `app.config.get_settings()`.

So on the VPS the plain commands below act on the local PostgreSQL the shadow
run uses. Double-check with `alembic current` before any `upgrade`.

## One-time: adopt an existing database (VPS, local docker)

The tables already exist (created by `create_all`), so do **not** `upgrade`;
mark the database as being at the baseline:

```bash
pg_dump "$DATABASE_URL" > "backup-$(date +%F).sql"   # VPS: back up first
alembic current        # expect: (empty) — not yet under Alembic
alembic stamp head
alembic current        # expect: 0001 (head)
```

## Fresh database

```bash
alembic upgrade head
```

(or start the app once — `create_all` builds the same tables — then
`alembic stamp head`).

## Adding a revision

1. Edit `app/db/models.py`.
2. Generate and **review** the script (autogenerate is a draft: it does not
   see renamed columns, data backfills, or dialect-specific defaults):

   ```bash
   alembic revision --autogenerate -m "short_description"
   ```

3. Apply locally (docker PostgreSQL) and run the tests.
   `tests/test_migrations.py` fails if the migrations and the models disagree.

   ```bash
   alembic upgrade head
   python -m pytest -q
   ```

4. Open a PR. Do not run `upgrade` on the VPS before the PR is merged and the
   database is backed up. Prefer additive changes; never drop a ledger table
   in the same revision that stops writing to it.

## Notes

- SQLite (tests) cannot ALTER most things in place; `env.py` enables Alembic
  batch mode on SQLite so future `alter_column` / drop-constraint operations
  work in tests as well as on PostgreSQL.
- `server_default=sa.func.now()` is used in the baseline so each dialect
  compiles its own `now()` / `CURRENT_TIMESTAMP`.
- `alembic upgrade head --sql` prints the SQL without connecting (offline
  mode), useful for reviewing what a revision will do on PostgreSQL.
