"""The nightly database backup tooling (plan row R15): the script, its systemd units, the runbook.

``scripts/db_backup.sh`` is exercised under bash with stub ``pg_dump`` / ``pg_restore`` / ``psql``
programs placed first on PATH, so these tests need no PostgreSQL and never touch a database. The
stubs record every call (arguments and the relevant environment) in a log the tests read. Where
bash is missing the script tests are skipped; the file checks always run.

What the script must hold to (docs/runbooks/DB_MIGRATIONS.md):

1. the one secret (the password inside ``DATABASE_URL``) never reaches a command line or a printed
   line: it travels in ``PGPASSWORD`` and every tool message is redacted;
2. a dump is a backup only once ``pg_restore --list`` reads it back; a failed or unreadable dump
   is discarded and the older dumps are left alone (nothing is pruned after a failure);
3. retention never removes the newest ``DB_BACKUP_KEEP_MIN`` dumps, and never a file it did not write;
4. the restore drill restores into a NEW scratch database and only reads the live one, in a
   read-only transaction; the scratch database is dropped afterwards (unless ``--keep``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "db_backup.sh"
UNITS = ROOT / "deploy" / "systemd"
RUNBOOK = ROOT / "docs" / "runbooks" / "DB_MIGRATIONS.md"

PASSWORD_IN_URL = "s3cr3t%40pw"      # percent-encoded, as SQLAlchemy writes it
PASSWORD_DECODED = "s3cr3t@pw"
URL = f"postgresql+psycopg://trading:{PASSWORD_IN_URL}@db:5432/trading"
LIVE_CONN = "postgresql://trading@db:5432/trading"   # what the tools receive: no password

PG_DUMP_STUB = r"""#!/usr/bin/env bash
printf 'pg_dump %s | PGPASSWORD=%s | PGCONNECT_TIMEOUT=%s\n' "$*" "${PGPASSWORD:-unset}" "${PGCONNECT_TIMEOUT:-unset}" >> "$STUB_LOG"
out=; for a in "$@"; do case "$a" in --file=*) out=${a#--file=};; esac; done
if [ "${STUB_PG_DUMP_FAIL:-0}" = 1 ]; then
  echo "pg_dump: error: connection failed (uri: postgresql://trading:s3cr3t%40pw@db:5432/trading) PGPASSWORD=s3cr3t@pw password=s3cr3t@pw" >&2
  exit 1
fi
if [ "${STUB_PG_DUMP_GARBAGE:-0}" = 1 ]; then printf 'not an archive\n' > "$out"; exit 0; fi
printf 'PGDMP-STUB\npayload-%s\n' "$RANDOM$RANDOM" > "$out"
"""

PG_RESTORE_STUB = r"""#!/usr/bin/env bash
printf 'pg_restore %s\n' "$*" >> "$STUB_LOG"
file="${@: -1}"
head -c 10 "$file" | grep -q PGDMP-STUB || { echo "pg_restore: error: input file does not appear to be a valid archive" >&2; exit 1; }
case " $* " in
  *" --list "*)
    printf ';\n; Archive created at 2026-11-04\n;\n2; 1259 16384 TABLE public candles trading\n'
    printf '3; 1259 16385 TABLE public alembic_version trading\n4; 0 0 TABLE DATA public alembic_version trading\n' ;;
  *)
    if [ "${STUB_PG_RESTORE_FAIL:-0}" = 1 ]; then echo "pg_restore: error: could not execute query: ERROR: relation exists" >&2; exit 1; fi ;;
esac
exit 0
"""

PSQL_STUB = r"""#!/usr/bin/env bash
printf 'psql %s | PGOPTIONS=%s\n' "$*" "${PGOPTIONS:-unset}" >> "$STUB_LOG"
sql=; prev=; for a in "$@"; do [ "$prev" = -c ] && sql=$a; prev=$a; done
case "$sql" in
  "CREATE DATABASE"*) [ "${STUB_PSQL_CREATE_FAIL:-0}" = 1 ] && { echo "ERROR: permission denied to create database" >&2; exit 1; }; exit 0 ;;
  "DROP DATABASE"*) exit 0 ;;
  "SELECT tablename"*) printf 'alembic_version\ncandles\ndemo_fills\n' ;;
  "SELECT count(*)"*) case "$*" in *_drill_*) echo 10 ;; *) echo 12 ;; esac ;;
  "SELECT version_num"*) echo 0001 ;;
esac
exit 0
"""


def _bash() -> str | None:
    """Git's bash on Windows (never the WSL launcher in System32); plain bash elsewhere."""
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            git_dir = Path(git).resolve()
            for root in (git_dir.parents[1], git_dir.parents[2] if len(git_dir.parents) > 2 else git_dir.parents[1]):
                for candidate in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
                    if candidate.exists():
                        return str(candidate)
        found = shutil.which("bash")
        return found if found and "system32" not in found.lower() else None
    return shutil.which("bash")


BASH = _bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="bash is not available on this machine")


def _posix(path: Path) -> str:
    return str(path).replace("\\", "/")


class Harness:
    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.bin = tmp_path / "bin"
        self.backups = tmp_path / "backups"
        self.log = tmp_path / "calls.log"
        self.bin.mkdir()
        self.backups.mkdir()
        for name, body in (("pg_dump", PG_DUMP_STUB), ("pg_restore", PG_RESTORE_STUB), ("psql", PSQL_STUB)):
            stub = self.bin / name
            stub.write_text(body, encoding="utf-8", newline="\n")
            stub.chmod(0o755)

    def run(self, *args: str, env: dict | None = None, url: str | None = URL) -> subprocess.CompletedProcess:
        full = dict(os.environ)
        full.pop("DATABASE_URL", None)
        full.pop("PGDATABASE", None)
        full.pop("PGPASSWORD", None)
        full["PATH"] = os.pathsep.join([str(self.bin), os.environ.get("PATH", "")])
        full["STUB_LOG"] = _posix(self.log)
        full["DB_BACKUP_DIR"] = _posix(self.backups)
        if url is not None:
            full["DATABASE_URL"] = url
        full.update(env or {})
        return subprocess.run([BASH, _posix(SCRIPT), *args], capture_output=True, text=True, timeout=180,
                              cwd=str(ROOT), env=full)

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def dumps(self) -> list[Path]:
        return sorted(p for p in self.backups.iterdir() if p.suffix == ".pgdump")

    def latest(self) -> dict:
        return json.loads((self.backups / "latest.json").read_text(encoding="utf-8"))

    def fake_dump(self, name: str, age_days: float, prefix: str = "ai-trading-trading") -> Path:
        path = self.backups / f"{prefix}-{name}.pgdump"
        path.write_bytes(b"PGDMP-STUB\nold\n")
        (self.backups / f"{path.name}.sha256").write_text("00  x\n", encoding="utf-8")
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
        return path


@pytest.fixture()
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


DUMP_NAME = re.compile(r"^ai-trading-trading-\d{8}T\d{6}Z\.pgdump$")


# --- backup -----------------------------------------------------------------------------------

@needs_bash
def test_backup_writes_a_verified_dump_with_checksum_and_status(harness: Harness):
    result = harness.run("backup")
    assert result.returncode == 0, result.stdout + result.stderr
    dumps = harness.dumps()
    assert len(dumps) == 1 and DUMP_NAME.match(dumps[0].name), [p.name for p in harness.backups.iterdir()]
    dump = dumps[0]
    assert not list(harness.backups.glob(".partial-*")), "the temporary file must be renamed, never left behind"
    checksum_line = (harness.backups / f"{dump.name}.sha256").read_text(encoding="utf-8").split()
    checksum_line[1] = checksum_line[1].lstrip("*")     # sha256sum marks binary mode with '*' on Windows
    assert checksum_line == [hashlib.sha256(dump.read_bytes()).hexdigest(), dump.name]
    latest = harness.latest()
    assert latest["status"] == "ok" and latest["file"] == dump.name and latest["bytes"] == dump.stat().st_size
    assert latest["sha256"] == checksum_line[0] and latest["archive_entries"] == 3
    assert latest["database"] == "trading" and latest["host"] == "db" and latest["kept"] == 1 and latest["pruned"] == 0
    assert latest["retention_days"] == 14 and latest["keep_min"] == 7
    history = (harness.backups / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(history) == 1 and json.loads(history[0]) == latest
    assert "backup ok:" in result.stdout and "latest.json updated" in result.stdout
    calls = harness.calls()
    assert calls[0].startswith("pg_dump ") and "pg_restore --list " in calls[1] and len(calls) == 2
    dump_call = calls[0]
    for flag in ("--format=custom", "--no-password", "--lock-wait-timeout=120000"):
        assert flag in dump_call
    assert ".partial-" in dump_call.split("--file=", 1)[1], "pg_dump writes a temporary file first"
    assert ".partial-" in calls[1], "the archive is listed before it is renamed into place"
    assert dump_call.split(" | ")[0].endswith(f" {LIVE_CONN}"), dump_call
    assert f"PGPASSWORD={PASSWORD_DECODED}" in dump_call, "the password travels in PGPASSWORD, decoded"
    assert "PGCONNECT_TIMEOUT=15" in dump_call


@needs_bash
def test_the_password_is_on_no_command_line_and_in_no_printed_line(harness: Harness):
    harness.fake_dump("20260101T000000Z", age_days=400)       # an old dump that a failure must not touch
    result = harness.run("backup", env={"STUB_PG_DUMP_FAIL": "1"})
    assert result.returncode == 1
    printed = result.stdout + result.stderr
    assert "s3cr3t" not in printed, printed
    assert "postgresql://trading:***@db:5432/trading" in printed and "PGPASSWORD=***" in printed and "password=***" in printed
    assert "pg_dump failed; no new backup written" in printed
    for call in harness.calls():
        command_line = call.split(" | ")[0]
        assert "s3cr3t" not in command_line, call
    assert [p.name for p in harness.dumps()] == ["ai-trading-trading-20260101T000000Z.pgdump"], "nothing pruned after a failure"
    assert not list(harness.backups.glob(".partial-*"))
    latest = harness.latest()
    assert latest["status"] == "failed" and latest["reason"] == "pg_dump failed" and latest["kept"] == 1


@needs_bash
def test_a_dump_that_does_not_read_back_is_discarded(harness: Harness):
    result = harness.run("backup", env={"STUB_PG_DUMP_GARBAGE": "1"})
    assert result.returncode == 1
    assert "not a readable archive" in result.stdout + result.stderr
    assert harness.dumps() == [] and not list(harness.backups.glob(".partial-*"))
    assert harness.latest()["reason"] == "the new dump is not a readable archive"


@needs_bash
def test_prune_removes_only_old_dumps_beyond_the_minimum_kept_and_only_its_own_files(harness: Harness):
    old = [harness.fake_dump(f"2026010{i}T000000Z", age_days=20) for i in range(1, 7)]       # 6 old enough
    young = [harness.fake_dump(f"2026020{i}T000000Z", age_days=1) for i in range(1, 5)]       # 4 recent
    foreign = harness.fake_dump("20260101T000000Z", age_days=400, prefix="other-database")   # not ours
    notes = harness.backups / "notes.txt"
    notes.write_text("keep me", encoding="utf-8")
    os.utime(notes, (time.time() - 400 * 86400,) * 2)

    result = harness.run("backup", env={"DB_BACKUP_RETENTION_DAYS": "14", "DB_BACKUP_KEEP_MIN": "3"})
    assert result.returncode == 0, result.stdout + result.stderr
    remaining = {p.name for p in harness.backups.iterdir()}
    for path in old:
        assert path.name not in remaining and f"{path.name}.sha256" not in remaining
    for path in young:
        assert path.name in remaining and f"{path.name}.sha256" in remaining, "young dumps stay even beyond the minimum"
    assert foreign.name in remaining and f"{foreign.name}.sha256" in remaining and notes.name in remaining
    latest = harness.latest()
    assert latest["pruned"] == 6 and latest["kept"] == 5          # 4 young + the new one
    assert result.stdout.count("prune: removed ") == 6


@needs_bash
def test_prune_never_goes_below_the_minimum_kept_whatever_the_age(harness: Harness):
    for i in range(1, 5):
        harness.fake_dump(f"2026010{i}T000000Z", age_days=400)
    result = harness.run("backup", env={"DB_BACKUP_RETENTION_DAYS": "1", "DB_BACKUP_KEEP_MIN": "7"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(harness.dumps()) == 5 and harness.latest()["pruned"] == 0
    assert "all kept (never fewer than 7)" in result.stdout


@needs_bash
def test_retention_zero_never_removes(harness: Harness):
    for i in range(1, 10):
        harness.fake_dump(f"2026010{i}T000000Z", age_days=400)
    result = harness.run("backup", env={"DB_BACKUP_RETENTION_DAYS": "0", "DB_BACKUP_KEEP_MIN": "1"})
    assert result.returncode == 0 and len(harness.dumps()) == 10 and "retention disabled" in result.stdout


@needs_bash
def test_setup_problems_exit_2_before_any_dump(harness: Harness):
    no_connection = harness.run("backup", url=None)
    assert no_connection.returncode == 2 and "no database connection" in no_connection.stderr
    sqlite = harness.run("backup", url="sqlite:///data/research.db")
    assert sqlite.returncode == 2 and "only PostgreSQL" in sqlite.stderr
    no_space = harness.run("backup", env={"DB_BACKUP_MIN_FREE_MB": "999999999"})
    assert no_space.returncode == 2 and "free in" in no_space.stderr and "nothing pruned" in no_space.stderr
    assert harness.latest()["status"] == "failed" and harness.latest()["reason"].startswith("too little free space")
    bad_setting = harness.run("backup", env={"DB_BACKUP_RETENTION_DAYS": "two weeks"})
    assert bad_setting.returncode == 2 and "DB_BACKUP_RETENTION_DAYS" in bad_setting.stderr
    unknown = harness.run("bogus")
    assert unknown.returncode == 2 and "unknown command" in unknown.stderr
    assert harness.calls() == [] and harness.dumps() == []
    for bad in (no_connection, sqlite, no_space, bad_setting, unknown):
        assert "s3cr3t" not in bad.stdout + bad.stderr


@needs_bash
def test_libpq_variables_work_without_a_url(harness: Harness):
    result = harness.run("backup", url=None, env={"PGDATABASE": "trading", "PGHOST": "localhost"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert harness.calls()[0].split(" | ")[0].endswith(" trading"), "the database name is the only connection argument"
    assert DUMP_NAME.match(harness.dumps()[0].name) and harness.latest()["host"] == "localhost"


@needs_bash
def test_help_lists_the_commands(harness: Harness):
    result = harness.run("--help")
    assert result.returncode == 0
    for word in ("backup", "verify", "restore-drill", "list", "DATABASE_URL", "DB_BACKUP_RETENTION_DAYS"):
        assert word in result.stdout


# --- verify and list -----------------------------------------------------------------------------

@needs_bash
def test_verify_accepts_an_intact_dump_and_rejects_a_changed_one(harness: Harness):
    assert harness.run("backup").returncode == 0
    dump = harness.dumps()[0]
    ok = harness.run("verify")
    assert ok.returncode == 0 and "verify ok:" in ok.stdout and "checksum matches" in ok.stdout
    assert "contains the alembic_version table" in ok.stdout
    by_name = harness.run("verify", dump.name)
    assert by_name.returncode == 0
    with dump.open("ab") as handle:
        handle.write(b"x")
    changed = harness.run("verify", dump.name)
    assert changed.returncode == 1 and "CHECKSUM MISMATCH" in changed.stderr
    (harness.backups / f"{dump.name}.sha256").unlink()
    no_checksum = harness.run("verify")
    assert no_checksum.returncode == 1 and "no checksum file" in no_checksum.stderr
    missing = harness.run("verify", "nope.pgdump")
    assert missing.returncode == 2 and "no such dump" in missing.stderr


@needs_bash
def test_list_shows_the_dumps_and_the_last_result(harness: Harness):
    assert harness.run("backup").returncode == 0
    result = harness.run("list")
    assert result.returncode == 0
    assert "1 dump(s) in" in result.stdout and harness.dumps()[0].name in result.stdout
    assert '"status":"ok"' in result.stdout


# --- restore drill -------------------------------------------------------------------------------

@needs_bash
def test_restore_drill_restores_into_a_scratch_database_and_only_reads_the_live_one(harness: Harness):
    assert harness.run("backup").returncode == 0
    harness.log.unlink()
    result = harness.run("restore-drill")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = harness.calls()
    psql_calls = [c for c in calls if c.startswith("psql ")]
    scratch = re.search(r'CREATE DATABASE "(trading_drill_\d{8}t\d{6}z)" TEMPLATE template0;', psql_calls[0])
    assert scratch, psql_calls[0]
    scratch_name = scratch.group(1)
    assert " postgresql://trading@db:5432/postgres -c CREATE DATABASE" in psql_calls[0], "created through the maintenance database"
    restore = [c for c in calls if c.startswith("pg_restore ") and "--list" not in c]
    assert len(restore) == 1
    for flag in ("--no-owner", "--no-privileges", "--single-transaction", "--no-password",
                 f"--dbname=postgresql://trading@db:5432/{scratch_name}"):
        assert flag in restore[0], restore[0]
    live_calls = [c for c in psql_calls if f" {LIVE_CONN} -c " in c]
    assert len(live_calls) == 3
    for call in live_calls:
        assert "-c SELECT count(*) FROM" in call, call
        assert "PGOPTIONS=-c default_transaction_read_only=on" in call, call
    for call in calls:
        assert not re.search(r'(CREATE|DROP) DATABASE.*"trading"', call), call
    assert psql_calls[-1].split(" | ")[0].endswith(f'postgres -c DROP DATABASE IF EXISTS "{scratch_name}";')
    assert "in backup" in result.stdout and "live now" in result.stdout
    assert re.search(r"candles\s+10\s+12", result.stdout) and "Alembic revision 0001" in result.stdout
    assert "restore drill ok: 3 tables restored" in result.stdout and "scratch database" in result.stdout and "dropped" in result.stdout
    assert "s3cr3t" not in result.stdout + result.stderr


@needs_bash
def test_restore_drill_keep_leaves_the_scratch_database(harness: Harness):
    assert harness.run("backup").returncode == 0
    result = harness.run("restore-drill", "--keep")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not [c for c in harness.calls() if "DROP DATABASE" in c]
    assert "--keep: the scratch database" in result.stdout and "DROP DATABASE" in result.stdout


@needs_bash
def test_restore_drill_failures_are_loud_and_still_drop_the_scratch_database(harness: Harness):
    assert harness.run("backup").returncode == 0
    failed = harness.run("restore-drill", env={"STUB_PG_RESTORE_FAIL": "1"})
    assert failed.returncode == 1 and "RESTORE FAILED" in failed.stderr
    assert [c for c in harness.calls() if "DROP DATABASE IF EXISTS" in c], "the scratch database is dropped on failure too"
    harness.log.unlink()
    no_createdb = harness.run("restore-drill", env={"STUB_PSQL_CREATE_FAIL": "1"})
    assert no_createdb.returncode == 1 and "could not create the scratch database" in no_createdb.stderr
    assert not [c for c in harness.calls() if c.startswith("pg_restore ") and "--list" not in c]
    bad_option = harness.run("restore-drill", "--force")
    assert bad_option.returncode == 2 and "unknown option" in bad_option.stderr


# --- the script's text ---------------------------------------------------------------------------

def test_the_script_never_traces_and_never_prints_the_connection():
    text = SCRIPT.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "set -x" not in body and "xtrace" not in body
    for forbidden in ('"$DATABASE_URL"', "${DATABASE_URL}", "$PGPASSWORD", "${PGPASSWORD"):
        for line in body.splitlines():
            if forbidden in line:
                assert "resolve_connection" in text and ("url=$DATABASE_URL" in line or "-n \"${DATABASE_URL" in line), line
    assert "export PGPASSWORD" in body and "--no-password" in body
    assert "set -euo pipefail" in body and "umask 077" in body
    for word in ("run_demo_trading", "run_shadow_period", "OKX_", "x-simulated-trading", "place_order"):
        assert word not in text, word
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "\r" not in text, "the script must keep Unix line endings for the VPS"


# --- the systemd units and the environment example -------------------------------------------------

def _unit(name: str) -> dict:
    text = (UNITS / name).read_text(encoding="utf-8")
    return {line.split("=", 1)[0]: line.split("=", 1)[1] for line in text.splitlines() if "=" in line and not line.startswith("#")}


def test_the_backup_unit_is_a_confined_oneshot_that_only_reads_the_database():
    unit = _unit("db-backup.service")
    assert unit["Type"] == "oneshot"
    assert unit["ExecStart"] == "/bin/bash /path/to/ai-trading-model/scripts/db_backup.sh backup"
    assert unit["EnvironmentFile"] == "/etc/ai-trading/db-backup.env"   # its own file, never the repository .env
    assert unit["StateDirectory"] == "ai-trading/db-backups" and unit["StateDirectoryMode"] == "0700"
    assert unit["Environment"] == "DB_BACKUP_DIR=/var/lib/ai-trading/db-backups"
    assert unit["NoNewPrivileges"] == "yes" and unit["ProtectSystem"] == "strict" and unit["CapabilityBoundingSet"] == ""
    assert unit["ProtectHome"] == "read-only" and unit["UMask"] == "0077" and unit["User"] != "root"
    assert "-/path/to/ai-trading-model/.env" in unit["InaccessiblePaths"].split()
    assert "/run/postgresql" not in unit["InaccessiblePaths"], "a local database is dumped through its socket"
    assert "ReadWritePaths" not in unit, "the StateDirectory is the only writable place"
    assert unit["TimeoutStartSec"] == "1800" and "MemoryMax" in unit and "CPUQuota" in unit and unit["Nice"] == "10"
    assert unit["After"] == "postgresql.service"
    body = "\n".join(line for line in (UNITS / "db-backup.service").read_text(encoding="utf-8").splitlines()
                     if not line.startswith("#") and not line.startswith("InaccessiblePaths="))
    for forbidden in ("run_demo_trading", "run_shadow_period", "OKX_", "sk-ant", "/.env", "shadow.service"):
        assert forbidden not in body, f"db-backup.service mentions {forbidden}"


def test_the_backup_timer_runs_nightly_and_catches_up():
    timer = _unit("db-backup.timer")
    assert timer["OnCalendar"] == "*-*-* 02:30:00 UTC" and timer["Persistent"] == "true"
    assert timer["Unit"] == "db-backup.service" and timer["WantedBy"] == "timers.target"


def test_the_backup_env_example_holds_only_an_empty_connection_and_no_other_secret():
    example = (UNITS / "db-backup.env.example").read_text(encoding="utf-8")
    settings = dict(line.split("=", 1) for line in example.splitlines() if "=" in line and not line.startswith("#"))
    assert settings == {"DATABASE_URL": ""}
    commented_out = [line for line in example.splitlines() if line.startswith("#") and "=" in line and " " not in line.split("=", 1)[0]]
    for line in commented_out:
        key = line[1:].split("=", 1)[0]
        assert key.startswith("DB_BACKUP_"), line        # no other setting, not even commented out
    assert "sk-ant" not in example
    for optional in ("DB_BACKUP_DIR", "DB_BACKUP_RETENTION_DAYS", "DB_BACKUP_KEEP_MIN", "DB_BACKUP_MIN_FREE_MB"):
        assert f"#{optional}=" in example, optional


# --- the runbook ---------------------------------------------------------------------------------

def test_the_runbook_covers_the_owner_steps_and_names_the_guards():
    text = RUNBOOK.read_text(encoding="utf-8")
    for needed in (
        "tests/test_migrations.py",          # the models-vs-migrations guard, referenced not rebuilt
        "alembic check",                     # the models-vs-live-database guard
        "alembic stamp head", "alembic current", "alembic upgrade head",
        "create_all",                        # what the VPS still runs on
        "db_backup.sh backup", "db_backup.sh verify", "db_backup.sh restore-drill", "db_backup.sh list",
        "db-backup.timer", "db-backup.service", "/etc/ai-trading/db-backup.env",
        "latest.json", "DB_BACKUP_RETENTION_DAYS",
        "0001",                              # the baseline revision, stamped or not
        "--gate-check",                      # a restore is followed by the gate
    ):
        assert needed in text, needed
    for forbidden in ("sk-ant", "OKX_DEMO_API_KEY=", "TELEGRAM_BOT_TOKEN="):
        assert forbidden not in text, forbidden
