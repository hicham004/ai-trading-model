# Runbook — database migrations and backups (PostgreSQL, Alembic)

**Audience:** the human operator, on the DigitalOcean Singapore VPS that runs the
Phase 6a shadow (`shadow.service`, local PostgreSQL). **Agents cannot reach the
VPS**; every step here is an operator action. Plan row R15 (CLAUDE.md open item 7,
plan gate 7: "migrations + backups in place"). Nothing here changes the schema,
the trading scope or the safety core: demo-only, `x-simulated-trading: 1`,
long-only SPOT, `ma_crossover` untouched. The one secret involved, the database
password inside `DATABASE_URL`, stays in a root-owned service environment file and
is never typed, echoed or pasted anywhere.

## Where things stand (what the VPS runs on)

- **The runtime builds its own tables.** At every start, `init_db()` in
  `app/db/database.py` calls `Base.metadata.create_all`, which creates the tables
  of `app/db/models.py` that do not exist yet and never alters an existing one.
  That is true of the code the VPS runs (`main`) and of `plan/auto` alike; R15 does
  not change it. Switching the runtime to migrations is a separate, reviewed change.
- **Alembic exists, with one revision.** Sprint 0 (on `plan/auto`, not yet merged,
  plan row G2) added `alembic.ini`, `migrations/` and the **baseline revision
  `0001`**, which reproduces exactly what `create_all` builds. Sprint 3's revision
  `0002` (on its own branch `sprint-3/exchange-side-stops`: the exchange-side stop
  ledger and two execution-quality fields, additive) will be the first real upgrade
  the VPS ever runs, after its own pull request and the G3 drills.
- **The VPS database is NOT under Alembic yet.** `shadow.service` runs `main`
  (commit `57f89c0`, June 29, 2026), which has no Alembic at all: its database has
  no `alembic_version` table, and revision 0001 is **not stamped** there. Every
  table came from `create_all`. `app/db/models.py` is identical on `main` and
  `plan/auto`, so that schema equals the baseline, which is why step 3 below stamps
  instead of upgrading. Check it yourself (prints only a table list, no secrets):

  ```bash
  sudo -u postgres psql -d "$(grep '^DATABASE_URL=' /path/to/ai-trading-model/.env | sed 's#.*/##; s#?.*##; s#"##g')" -c '\dt'
  ```

  Expect the `candles`, `demo_*`, `paper_*` and `order_book_snapshots` tables and
  **no** `alembic_version`. (If the shadow's settings live in a systemd
  `EnvironmentFile` rather than `.env`, read the database name from that file:
  `systemctl cat shadow.service | grep -i EnvironmentFile`.)
- **Backups: none that the repository knows of.** The plan's hosting line assumed
  a nightly `pg_dump`; nothing in the repository installed one until this runbook.
  Step 1 does. (DigitalOcean's droplet backups are a separate, paid product and an
  owner decision; see "Off-host copy".)
- **Why it matters.** Demo data loss is not a phase gate (CLAUDE.md, open item 7):
  the ledger can be rebuilt from the venue's history and the shadow journals. A
  schema change applied by hand, without a backup, is the kind of operational
  accident that a live phase cannot afford, so the workflow is rehearsed now, in
  demo, where a mistake costs nothing.

## The two guards

1. **Models vs. migrations: `tests/test_migrations.py`** (CI runs it on every pull
   request). It upgrades an empty SQLite database to `head` and asserts that
   Alembic's autogenerate has nothing left to say against `app/db/models.py`:
   tables, columns, indexes, unique constraints, nullability, and since R15 column
   types and server defaults too. It also checks the history stays linear, that a
   downgrade to base removes every table, that the PostgreSQL SQL renders without
   SQLite-isms, and it rehearses the owner steps of this runbook (`stamp head` on a
   `create_all` database, then `alembic check`). **Keep it; never weaken it.** A
   model change without a revision, or a revision that drifts from the models,
   fails CI before it can reach the VPS.
2. **Models vs. the live database: `alembic check`.** Run on the VPS after
   stamping and after every upgrade. It compares the real PostgreSQL schema with
   the models and prints `No new upgrade operations detected.` when they agree.
   Any other output (a list of differences) means **stop**: do not upgrade, do not
   stamp again; copy the output (it holds no secrets) into an agent session.
   Before the database is stamped it says `FAILED: Target database is not up to
   date.` — that is the missing stamp, not a schema problem.

(Verified on 2026-11-04 against a fresh PostgreSQL 16, the version Ubuntu 24.04
installs: `upgrade head` then `check` is clean, and a database built by
`create_all` then `stamp head` is clean as well. The VPS itself was not touched.)

## Which database does a command hit?

`migrations/env.py` resolves the URL in this order:

1. `alembic -x url=<sqlalchemy-url> <command>` (explicit; the tests and one-off runs);
2. `sqlalchemy.url` in `alembic.ini` (empty on purpose);
3. `DATABASE_URL` from the environment / `.env` via `app.config.get_settings()`.

So on the VPS, run from the checkout, the plain commands below act on the local
PostgreSQL the shadow run uses. `alembic current` before any `upgrade`, always.

## Before you start

- The `plan/auto` pull request is merged (G2) and the VPS checkout is updated
  (`docs/runbooks/VPS_8443_UPDATE.md`, "After the Sprint 0 pull request is
  merged", steps 1–2: `git pull`, then `pip install -r requirements.txt` — that
  installs Alembic). Steps 1 and 2 of this runbook need only the checkout's files
  and the PostgreSQL client tools, so they can be done before the merge from a
  copy of the branch; step 3 needs the merged code.
- The client tools are present: `pg_dump --version`, `pg_restore --version`,
  `psql --version` (Ubuntu: `sudo apt install postgresql-client`). They are the
  same major version as the server (`psql -c 'select version()'` as `postgres`).

## Step 1 — the nightly backup (once, about 15 minutes)

**1a. The backup's own environment file.** It holds one secret: the connection
line the shadow run already uses. Copy it without displaying it.

```bash
cd /path/to/ai-trading-model                       # the checkout shadow.service runs from
sudo install -d -m 750 -o root -g root /etc/ai-trading
sudo install -m 600 -o root -g root deploy/systemd/db-backup.env.example /etc/ai-trading/db-backup.env
sudo sed -i '/^DATABASE_URL=$/d' /etc/ai-trading/db-backup.env             # drop the empty placeholder
sudo sh -c "grep '^DATABASE_URL=' $(pwd)/.env >> /etc/ai-trading/db-backup.env"   # copy the one line, unseen
sudo grep -c '^DATABASE_URL=postgresql' /etc/ai-trading/db-backup.env      # expect: 1  (a count, not the value)
```

If the shadow's `DATABASE_URL` lives in a systemd `EnvironmentFile` instead of
`.env`, `grep` from that file. Do not `cat` the result. Never put OKX keys here and
never point the service at the repository `.env`. The optional settings are
documented in the file: `DB_BACKUP_RETENTION_DAYS` (default 14 nights),
`DB_BACKUP_KEEP_MIN` (the newest 7 dumps are never removed, whatever their age),
`DB_BACKUP_MIN_FREE_MB` (no dump starts with less than 500 MB free) and
`DB_BACKUP_DIR` (change it together with the unit's `ReadWritePaths`).

**1b. Units and timer.** The service writes only its own folder,
`/var/lib/ai-trading/db-backups`, which systemd creates for the checkout's user
(`StateDirectory`), mode 700; the rest of the system is read-only to it and the
checkout's `.env` is unreachable.

```bash
cd /path/to/ai-trading-model
REPO=$(pwd)
RUN_AS=$(stat -c %U "$REPO")          # the user that owns the checkout
for f in db-backup.service db-backup.timer; do
  sed -e "s#/path/to/ai-trading-model#$REPO#g" -e "s#CHANGE_ME_USER#$RUN_AS#g" \
      deploy/systemd/$f | sudo tee /etc/systemd/system/$f > /dev/null
done
sudo systemd-analyze verify /etc/systemd/system/db-backup.service /etc/systemd/system/db-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now db-backup.timer
systemctl list-timers 'db-backup*' --no-pager      # next run: tonight 02:30 UTC
```

`systemd-analyze verify` must print nothing (or only warnings about other units).

**1c. The first backup, now.**

```bash
sudo systemctl start db-backup.service
journalctl -u db-backup.service -n 20 --no-pager
# expect, in order: "backup of database '...' ... starting", "backup ok: ai-trading-<db>-<time>.pgdump (... bytes, ... archive entries, ...s)",
# "prune: 1 dump(s) on disk, all kept (never fewer than 7)", "done: 1 dump(s) kept in /var/lib/ai-trading/db-backups; latest.json updated"
sudo ls -la /var/lib/ai-trading/db-backups          # the dump (mode 600), its .sha256, latest.json, history.jsonl
sudo cat /var/lib/ai-trading/db-backups/latest.json # "status":"ok" (no secrets in it: database name and host only)
```

What the service did: `pg_dump --format=custom` into a temporary file, then
`pg_restore --list` on it (a dump nobody can read back is not a backup), then an
atomic rename, a SHA-256 checksum next to it, and only then retention. A failed
night leaves the older dumps exactly as they were and writes
`"status":"failed"` with the reason into `latest.json`.

**1d. Commands by hand.** The script needs the same environment as the service.
Define this once per shell session (it reads the root-owned file as root and runs
from the checkout):

```bash
cd /path/to/ai-trading-model
dbtool() { sudo bash -c 'set -a; . /etc/ai-trading/db-backup.env; set +a; export DB_BACKUP_DIR=${DB_BACKUP_DIR:-/var/lib/ai-trading/db-backups}; exec bash scripts/db_backup.sh "$@"' _ "$@"; }
dbtool list              # the dumps on disk and the last result
dbtool verify            # checksum + archive listing of the newest dump
dbtool --help
```

The script's own commands, for reference (`dbtool X` runs `bash scripts/db_backup.sh X`
with the service's environment):

```text
bash scripts/db_backup.sh backup                      # what db-backup.service runs every night
bash scripts/db_backup.sh verify [FILE]               # checksum + archive listing (default: the newest dump)
bash scripts/db_backup.sh restore-drill [FILE] [--keep]   # restore into a scratch database, compare, drop
bash scripts/db_backup.sh list                        # the dumps on disk and latest.json
```

Take backups only through `sudo systemctl start db-backup.service` (as the service
user, in the service's sandbox), never with `dbtool backup`: a dump written by
root in that folder is one the service user cannot verify later. `verify`,
`restore-drill` and `list` write nothing into the folder.

## Step 2 — the restore drill: prove a backup restores (5 minutes)

A listing proves the file is readable; only a restore proves it restores. The
drill restores the newest dump into a **new scratch database** next to the live
one (`<db>_drill_<time>`), compares the row counts of every table with the live
database, prints the Alembic revision found inside the backup, and drops the
scratch database again. It touches the live database with `SELECT count(*)` only,
inside a read-only transaction (`default_transaction_read_only=on`): it cannot
write to it even by mistake. `shadow.service` may keep running.

```bash
dbtool verify
dbtool restore-drill
```

Expect, in this order: `verify ok`, `restore drill: creating the scratch database`,
`restored ... in Ns; comparing row counts`, a table with the columns `in backup` and
`live now` (live counts at or above the backup are normal: the shadow keeps
writing), `the restored database is at Alembic revision 0001` (or `has no
alembic_version table` before step 3), `restore drill ok: N tables restored`, and
`scratch database ... dropped`. Exit code 0. `dbtool restore-drill --keep` leaves
the scratch database for a look (drop it afterwards with the printed `DROP
DATABASE` statement, as the `postgres` user).

Run the drill after step 1, **before every upgrade (step 4)** and about once a
quarter. If it fails: `RESTORE FAILED` means the dump does not restore cleanly —
keep the output for an agent session, and do not rely on that night's file;
`could not create the scratch database` means the role lacks `CREATEDB`
(troubleshooting table).

For a fully independent proof, copy a dump to another machine with the same
PostgreSQL major version and restore it there (`createdb t && pg_restore
--no-owner --no-privileges --single-transaction --dbname=t <file>`).

## Step 3 — bring the database under Alembic (once, after the merge; 5 minutes)

The tables exist already, so the database is **stamped** at the baseline, never
upgraded. Stamping writes one row into a new `alembic_version` table and changes
nothing else; the shadow run may keep running. Back up first, as before every
schema-related action.

```bash
cd /path/to/ai-trading-model
sudo systemctl start db-backup.service && journalctl -u db-backup.service -n 4 --no-pager   # "backup ok"
.venv/bin/alembic current        # expect: no revision shown (the database is not under Alembic yet)
.venv/bin/alembic check          # expect: FAILED: Target database is not up to date.  (the missing stamp, see "The two guards")
.venv/bin/alembic stamp head     # expect: Running stamp_revision  -> 0001
.venv/bin/alembic current        # expect: 0001 (head)
.venv/bin/alembic check          # expect: No new upgrade operations detected.
```

If the last line lists differences instead: stop; do not run `upgrade`; copy the
output into an agent session. The database stays as it was (stamped, unchanged).

A **fresh** database (a new VPS, a local Docker PostgreSQL) is the other way
round: `alembic upgrade head` builds it, and `create_all` at the first start then
finds every table present.

## Step 4 — a schema change on the VPS (every future revision)

The first will be Sprint 3's `0002`. Preconditions, all of them:

- the pull request with the revision is **merged into `main`** and CI (which runs
  `tests/test_migrations.py`) was green; never a feature branch on the VPS;
- the revision is **additive** (new tables, new nullable columns); a revision that
  drops or rewrites a ledger table needs its own reviewed plan;
- you have read what it will run: `alembic upgrade head --sql` prints the SQL
  without connecting;
- a fresh backup and a passing restore drill (below);
- the shadow run is **flat if at all possible** (`"flat_at_lot": true` in
  `logs/shadow/heartbeat.json`). The restart that goes with a deploy rebuilds the
  strategy window and exits an open position through the reviewed exit path
  (accepted demo behaviour; `docs/design/POSITION_PERSISTENCE.md`). Prefer to wait
  for flatness rather than force an exit.

```bash
cd /path/to/ai-trading-model
cat logs/shadow/heartbeat.json                     # state, flat_at_lot
sudo systemctl stop shadow.service                 # the deploy needs a restart anyway; nothing trades meanwhile
sudo systemctl start db-backup.service && journalctl -u db-backup.service -n 4 --no-pager   # "backup ok"
dbtool restore-drill                               # "restore drill ok"
git fetch && git status && git pull                # clean, on main
.venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .
.venv/bin/alembic current                          # the revision before (0001 the first time)
.venv/bin/alembic upgrade head --sql | less        # read the SQL (optional, no connection)
.venv/bin/alembic upgrade head                     # the change itself; one transaction on PostgreSQL
.venv/bin/alembic current                          # the new head
.venv/bin/alembic check                            # No new upgrade operations detected.
.venv/bin/python scripts/run_shadow_period.py --gate-check     # armable=True
sudo systemctl start shadow.service
sleep 60 && cat logs/shadow/heartbeat.json         # state=running, fresh timestamp
```

PostgreSQL runs the whole revision in one transaction: a failing `upgrade` leaves
the schema as it was (`alembic current` shows the old revision). Then do not retry
blindly: start the service again on the old code (`git checkout <previous commit
of main>` or revert the pull request), and bring the output to an agent session.

## When something goes wrong

**The upgrade applied, the new code misbehaves.** Stop the service, go back to
the previous `main` commit, start again. Additive revisions need **no** schema
rollback for that: the old code ignores tables and columns it does not know.
Downgrade (`alembic downgrade -1`) only when the revision's own notes ask for it,
and only after a backup; it removes exactly what the revision added, data included.

**The database is lost or damaged: restore from a dump.** This is disaster
recovery, done with the service stopped, into a **new** database, never over the
live one while anything runs:

```bash
sudo systemctl stop shadow.service
dbtool verify <file>                                            # the dump you will use
NEW=trading_restored_$(date +%Y%m%d)
sudo install -m 600 -o postgres -g postgres /var/lib/ai-trading/db-backups/<file> /tmp/restore.pgdump   # the postgres user cannot read the 700 folder
sudo -u postgres createdb -O <role> "$NEW"                      # <role>: the user in DATABASE_URL
sudo -u postgres pg_restore --no-owner --no-privileges --single-transaction --dbname="$NEW" /tmp/restore.pgdump
sudo -u postgres psql -d "$NEW" -At -c 'SELECT version_num FROM alembic_version;'   # the revision inside the dump (empty if dumped before the stamp)
sudo rm -f /tmp/restore.pgdump
```

Then point `DATABASE_URL` at the new name (the same file you copied from in step
1a, and the backup's env file), run `--gate-check`, and start. **Read this before
you do:** the restored ledger ends at the dump's time. Every fill the venue
executed after that moment is unknown to it, so the reconciliation's balance
cross-check (venue balances must equal the account's first-day baseline plus its
own fills) fails closed, the runtime disarms and stays disarmed, and the account
cannot continue (`docs/design/POSITION_PERSISTENCE.md`, scenario 16: a venue stop
order the ledger does not know is "foreign" and halts). That is the design, not a
fault. A restore gives the **history** back; continuing to trade means a new
account name, flat first, as in `docs/runbooks/VPS_8443_UPDATE.md`. If no fill
happened after the dump (`logs/shadow/journal-*.jsonl` shows the fills), the
restored account can continue once `--gate-check` passes.

## Day to day

```bash
systemctl list-timers 'db-backup*' --no-pager      # last and next run
journalctl -u db-backup.service -n 20 --no-pager   # last night's lines
dbtool list                                        # the dumps and latest.json
```

A failed night shows `db-backup.service` as `failed` in `systemctl --failed`,
`"status":"failed"` with a `reason` in `latest.json`, and the older dumps are
untouched. The timer tries again the next night. The daily ops digest
(`docs/runbooks/OPS_DIGEST.md`) does not yet report the backup; that is a
proposed follow-up in `docs/PLAN_STATUS.md`, section 2. Until then, glance at
`list-timers` when you look at the server.

Disk: a dump of the demo database is small (tens of kilobytes to a few megabytes;
the candles table grows by one row an hour). Fourteen nights fit in a few tens of
megabytes. The script refuses to start a dump with less than 500 MB free
(`DB_BACKUP_MIN_FREE_MB`).

## Off-host copy (optional, the owner's choice)

The dumps live on the same disk as the database: a lost droplet takes both.
Options, none of them built here: DigitalOcean's droplet backups (paid, in the
droplet's settings), or a weekly copy to your laptop:

```bash
# from your laptop; the files are mode 600 on the server, so copy as the checkout's user or with sudo
rsync -av --rsync-path='sudo rsync' 'vps:/var/lib/ai-trading/db-backups/' ~/ai-trading-db-backups/
```

A copied dump contains the demo ledger and public candles, no keys and no tokens.

## Adding a revision (developers, locally)

1. Edit `app/db/models.py`.
2. Generate and **review** the script (autogenerate is a draft: it does not see
   renamed columns, data backfills or dialect-specific defaults):

   ```bash
   alembic revision --autogenerate -m "short_description"
   ```

3. Apply it to the local Docker PostgreSQL (`docker-compose.yml`), check, test:

   ```bash
   alembic upgrade head
   alembic check                      # No new upgrade operations detected.
   python -m pytest -q tests/test_migrations.py && python -m pytest -q
   ```

   `tests/test_migrations.py` fails if the migrations and the models disagree.

4. Open a pull request (`migrations/` and `alembic.ini` are safety-sensitive
   paths, `AGENTS.md`). The VPS gets it through step 4 above only. Prefer additive
   changes; never drop a ledger table in the same revision that stops writing to
   it; keep one linear history (one head).

## Files

| File | What it is |
|---|---|
| `scripts/db_backup.sh` | The tool: `backup`, `verify`, `restore-drill`, `list` |
| `deploy/systemd/db-backup.service`, `db-backup.timer` | The nightly unit (02:30 UTC, catches up a missed night) |
| `deploy/systemd/db-backup.env.example` | Template of `/etc/ai-trading/db-backup.env` (the one secret, the optional settings) |
| `/var/lib/ai-trading/db-backups/ai-trading-<db>-<UTC time>.pgdump` | One `pg_dump --format=custom` archive per night (compressed; restore with `pg_restore`) |
| `.../<same>.pgdump.sha256` | Its checksum (`sha256sum -c`) |
| `.../latest.json`, `.../history.jsonl` | The last result; one line per run (status, file, bytes, entries, pruned, kept, reason) |
| `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_baseline.py` | Alembic; the baseline equals `create_all` |
| `tests/test_migrations.py` | The models-vs-migrations guard (CI) |

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| `ERROR: no database connection: set DATABASE_URL ...` (exit 2) | The env file has no connection line | Step 1a again; `sudo grep -c '^DATABASE_URL=' /etc/ai-trading/db-backup.env` must print 1 |
| `ERROR: missing tool(s): pg_dump ...` (exit 2) | No PostgreSQL client tools | `sudo apt install postgresql-client` |
| `pg_dump: ... FATAL: password authentication failed` (exit 1) | The copied line is not the one the shadow uses, or the password changed since | Remove the line (`sudo sed -i '/^DATABASE_URL=/d' /etc/ai-trading/db-backup.env`) and copy it again as in step 1a, from the file `shadow.service` really reads |
| `ERROR: only ... MB free in ...; need at least 500 MB` (exit 2) | The disk is nearly full | `df -h`; free space; the shadow's own logs may need rotation too |
| `the new dump is not a readable archive` (exit 1) | pg_dump finished but pg_restore cannot list the file (disk, version mismatch) | `pg_dump --version` vs the server's version; `dmesg`/`df`; the older dumps are intact |
| `ERROR: the backup folder ... is not writable` (exit 2) | `DB_BACKUP_DIR` was changed in the env file without `ReadWritePaths` in the unit | Add `ReadWritePaths=<folder>` to the unit, `daemon-reload`, or use the default folder |
| `could not create the scratch database` in the drill | The role in `DATABASE_URL` lacks `CREATEDB` | Once: `sudo -u postgres psql -c 'ALTER ROLE <role> CREATEDB;'` (the role name is the user in the URL) |
| `CHECKSUM MISMATCH` on verify | The file changed after it was written (disk fault, a copy in text mode) | Do not restore from it; use another night's dump; check the disk |
| `alembic check` → `FAILED: Target database is not up to date.` | The database is not stamped yet (step 3) or an upgrade is pending (step 4) | `alembic current`; then stamp (step 3) or upgrade (step 4) |
| `alembic check` lists differences after a stamp or an upgrade | The live schema and the models disagree | Stop; copy the output to an agent session; do not upgrade or stamp again |
| `alembic stamp head` → `Can't locate revision` or two heads | The checkout is not on `main`, or a branch brought its own revision | `git status`; only `main` runs on the VPS |
| `systemd-analyze verify` complains about `StateDirectory` | A very old systemd | Ubuntu 24.04 has systemd 255; otherwise replace it with a `ReadWritePaths=` line and create the folder by hand |

## Related

- `docs/runbooks/VPS_8443_UPDATE.md` — the checkout update after the merge; its
  "After the Sprint 0 pull request is merged" section points here for the stamp.
- `docs/design/POSITION_PERSISTENCE.md` — why a restart or a restore interacts
  with an open position and with reconciliation.
- `docs/runbooks/DEMO_STOP_DRILLS.md` (branch `sprint-3/exchange-side-stops`) —
  revision `0002`, the first upgrade, and its drills on a new demo account.
