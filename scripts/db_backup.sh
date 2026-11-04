#!/usr/bin/env bash
# scripts/db_backup.sh - nightly PostgreSQL backup of the trading database, with retention,
# a verification and a restore drill. Tooling only (plan row R15; docs/runbooks/DB_MIGRATIONS.md).
#
# It reads the database (pg_dump takes no exclusive lock and blocks no writer), never changes
# the schema, never writes to the live database, holds no OKX keys and places no orders. The
# connection comes from the service environment and is never printed: a password inside
# DATABASE_URL is moved into PGPASSWORD for the child processes (so it is not on any command
# line), and every line of tool output shown here passes through a redaction filter.
#
#   bash scripts/db_backup.sh backup                   pg_dump (custom format) -> DIR/<prefix>-<UTC time>.pgdump
#                                                      + .sha256, checked as a readable archive, then the
#                                                      dumps older than the retention are removed
#   bash scripts/db_backup.sh verify [FILE]            checksum + archive listing of FILE (default: the newest dump)
#   bash scripts/db_backup.sh restore-drill [FILE] [--keep]
#                                                      restore FILE into a NEW scratch database next to the live
#                                                      one, compare the row counts table by table, drop it
#                                                      (--keep leaves the scratch database for a look)
#   bash scripts/db_backup.sh list                     the dumps on disk and the last result
#
# Environment (under systemd: /etc/ai-trading/db-backup.env; see deploy/systemd/db-backup.env.example):
#   DATABASE_URL               the SQLAlchemy URL the application uses (postgresql+psycopg://user:pw@host:port/db),
#                              or a plain libpq URL; the driver suffix is dropped. Alternatively leave it unset
#                              and use the libpq variables (PGDATABASE required; PGHOST, PGPORT, PGUSER,
#                              PGPASSWORD or ~/.pgpass).
#   DB_BACKUP_DIR              where the dumps go (default /var/lib/ai-trading/db-backups)
#   DB_BACKUP_RETENTION_DAYS   remove dumps older than this many days (default 14; 0 never removes)
#   DB_BACKUP_KEEP_MIN         never remove the newest N dumps, whatever their age (default 7)
#   DB_BACKUP_MIN_FREE_MB      refuse to start a dump with less free space than this (default 500)
#   DB_BACKUP_PREFIX           file name prefix (default ai-trading-<database name>)
#
# Exit codes: 0 ok; 1 the dump, the verification or the drill failed (the timer tries again the next
# night; nothing is pruned after a failure); 2 a setup problem a retry cannot fix (a missing tool, no
# connection setting, a folder that cannot be written, too little free space, a bad argument).

set -euo pipefail
umask 077

SCRIPT_NAME=db_backup
DB_BACKUP_DIR=${DB_BACKUP_DIR:-/var/lib/ai-trading/db-backups}
DB_BACKUP_RETENTION_DAYS=${DB_BACKUP_RETENTION_DAYS:-14}
DB_BACKUP_KEEP_MIN=${DB_BACKUP_KEEP_MIN:-7}
DB_BACKUP_MIN_FREE_MB=${DB_BACKUP_MIN_FREE_MB:-500}
export PGCONNECT_TIMEOUT=${PGCONNECT_TIMEOUT:-15}

# Set by resolve_connection: how to reach the live database and its name.
CONN_MODE=            # url | env
URL_AUTHORITY=        # user@host:port (password removed; it goes to PGPASSWORD)
URL_QUERY=            # ?options, if any
LIVE_DB=
LIVE_HOST=

log() { printf '%s %s: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SCRIPT_NAME" "$*"; }
die() { local code=$1; shift; log "ERROR: $*" >&2; exit "$code"; }

# Redact anything that could carry a password: the password part of a URL, PGPASSWORD=...,
# and the libpq "password=" keyword. Applied to every tool message this script prints.
redact() {
  sed -E -e 's#(://[^/@[:space:]]*:)[^@[:space:]]*@#\1***@#g' \
         -e 's#(PGPASSWORD=)[^[:space:]]*#\1***#g' \
         -e 's#(password=)[^[:space:]]*#\1***#g'
}

show_err() {  # print a captured stderr file, redacted and indented, at most 30 lines
  local file=$1 tool=$2
  if [ -s "$file" ]; then
    tail -n 30 "$file" | redact | sed "s/^/  $tool: /" >&2
  fi
}

json_escape() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }

usage() {
  sed -n '2,38p' "$0" | sed 's/^# \{0,1\}//'
}

is_uint() { case "$1" in ''|*[!0-9]*) return 1;; *) return 0;; esac; }

url_decode() {  # percent-decoding (%40 -> @), as SQLAlchemy and libpq encode a password inside a URL
  local s=${1//%/\\x}
  printf '%b' "$s"
}

resolve_connection() {
  if [ -n "${DATABASE_URL:-}" ]; then
    local url=$DATABASE_URL scheme rest authority path userinfo hostport password
    scheme=${url%%://*}
    [ "$scheme" != "$url" ] || die 2 "DATABASE_URL is not a URL"
    case "$scheme" in
      postgresql|postgres|postgresql+*|postgres+*) ;;
      *) die 2 "DATABASE_URL is not a PostgreSQL URL (scheme '$scheme'); only PostgreSQL is backed up here (a SQLite file is copied, not dumped)" ;;
    esac
    rest=${url#*://}
    authority=${rest%%/*}
    path=${rest#"$authority"}
    path=${path#/}
    LIVE_DB=${path%%\?*}
    case "$path" in *\?*) URL_QUERY="?${path#*\?}";; *) URL_QUERY=;; esac
    [ -n "$LIVE_DB" ] || die 2 "DATABASE_URL names no database"
    case "$authority" in
      *@*) userinfo=${authority%@*}; hostport=${authority##*@} ;;
      *)   userinfo=; hostport=$authority ;;
    esac
    LIVE_HOST=${hostport%%:*}
    [ -n "$LIVE_HOST" ] || LIVE_HOST="(local socket)"
    if [ -n "$userinfo" ]; then
      case "$userinfo" in
        *:*)
          password=${userinfo#*:}
          userinfo=${userinfo%%:*}
          if [ -n "$password" ]; then
            PGPASSWORD=$(url_decode "$password")
            export PGPASSWORD
          fi
          ;;
      esac
      URL_AUTHORITY="${userinfo}@${hostport}"
    else
      URL_AUTHORITY=$hostport
    fi
    CONN_MODE=url
  elif [ -n "${PGDATABASE:-}" ]; then
    CONN_MODE=env
    LIVE_DB=$PGDATABASE
    LIVE_HOST=${PGHOST:-"(local socket)"}
  else
    die 2 "no database connection: set DATABASE_URL (the application's URL) or the libpq variables (PGDATABASE, PGHOST, PGUSER, PGPASSWORD / ~/.pgpass)"
  fi
  DB_BACKUP_PREFIX=${DB_BACKUP_PREFIX:-"ai-trading-${LIVE_DB}"}
  case "$DB_BACKUP_PREFIX" in
    *[!A-Za-z0-9._-]*) die 2 "DB_BACKUP_PREFIX may only contain letters, digits, '.', '_' and '-'" ;;
  esac
}

# conn_for_db NAME -> what pg_dump/psql/pg_restore take as the database argument (never a password).
conn_for_db() {
  if [ "$CONN_MODE" = url ]; then
    printf 'postgresql://%s/%s%s' "$URL_AUTHORITY" "$1" "$URL_QUERY"
  else
    printf '%s' "$1"
  fi
}

check_tools() {
  local missing=
  for tool in pg_dump pg_restore psql sha256sum; do
    command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
  done
  [ -z "$missing" ] || die 2 "missing tool(s):$missing (Ubuntu: sudo apt install postgresql-client)"
}

check_settings() {
  is_uint "$DB_BACKUP_RETENTION_DAYS" || die 2 "DB_BACKUP_RETENTION_DAYS must be a whole number of days"
  is_uint "$DB_BACKUP_KEEP_MIN" || die 2 "DB_BACKUP_KEEP_MIN must be a whole number"
  is_uint "$DB_BACKUP_MIN_FREE_MB" || die 2 "DB_BACKUP_MIN_FREE_MB must be a whole number of megabytes"
}

ensure_dir() {
  if [ ! -d "$DB_BACKUP_DIR" ]; then
    mkdir -p "$DB_BACKUP_DIR" 2>/dev/null || die 2 "cannot create the backup folder $DB_BACKUP_DIR (under systemd: StateDirectory/ReadWritePaths must name it)"
  fi
  [ -w "$DB_BACKUP_DIR" ] || die 2 "the backup folder $DB_BACKUP_DIR is not writable by $(id -un) (under systemd: StateDirectory/ReadWritePaths must name it)"
}

free_mb_in_dir() {
  local kb
  kb=$(df -Pk "$DB_BACKUP_DIR" 2>/dev/null | awk 'NR==2 {print $4}')
  is_uint "$kb" || kb=0
  printf '%s' $((kb / 1024))
}

list_dumps() {  # oldest first, names only
  find "$DB_BACKUP_DIR" -maxdepth 1 -type f -name "${DB_BACKUP_PREFIX}-*.pgdump" -printf '%f\n' | sort
}

newest_dump() { list_dumps | tail -n 1; }

resolve_dump_arg() {  # a bare name in the backup folder, a path, or nothing (newest) -> absolute path
  local arg=${1:-} name
  if [ -z "$arg" ]; then
    name=$(newest_dump)
    [ -n "$name" ] || die 2 "no dump found in $DB_BACKUP_DIR"
    printf '%s/%s' "$DB_BACKUP_DIR" "$name"
  elif [ -f "$arg" ]; then
    printf '%s' "$arg"
  elif [ -f "$DB_BACKUP_DIR/$arg" ]; then
    printf '%s/%s' "$DB_BACKUP_DIR" "$arg"
  else
    die 2 "no such dump: $arg"
  fi
}

# write_status STATUS FILE BYTES SHA ENTRIES SECONDS PRUNED KEPT REASON
write_status() {
  local status=$1 file=$2 bytes=$3 sha=$4 entries=$5 seconds=$6 pruned=$7 kept=$8 reason=$9 line
  line=$(printf '{"status":"%s","finished_at_utc":"%s","database":"%s","host":"%s","file":"%s","bytes":%s,"sha256":"%s","archive_entries":%s,"duration_seconds":%s,"pruned":%s,"kept":%s,"retention_days":%s,"keep_min":%s,"reason":"%s"}' \
    "$status" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(json_escape "$LIVE_DB")" "$(json_escape "$LIVE_HOST")" \
    "$(json_escape "$file")" "${bytes:-0}" "$sha" "${entries:-0}" "${seconds:-0}" "${pruned:-0}" "${kept:-0}" \
    "$DB_BACKUP_RETENTION_DAYS" "$DB_BACKUP_KEEP_MIN" "$(json_escape "$reason")")
  { printf '%s\n' "$line" > "$DB_BACKUP_DIR/latest.json" && printf '%s\n' "$line" >> "$DB_BACKUP_DIR/history.jsonl"; } 2>/dev/null || true
}

PRUNE_REMOVED=0
prune() {  # only after a successful, verified backup; sets PRUNE_REMOVED
  local all=() total candidates=() f
  PRUNE_REMOVED=0
  if [ "$DB_BACKUP_RETENTION_DAYS" -eq 0 ]; then
    log "prune: retention disabled (DB_BACKUP_RETENTION_DAYS=0); nothing removed"
    return
  fi
  mapfile -t all < <(list_dumps)
  total=${#all[@]}
  if [ "$total" -le "$DB_BACKUP_KEEP_MIN" ]; then
    log "prune: $total dump(s) on disk, all kept (never fewer than $DB_BACKUP_KEEP_MIN)"
    return
  fi
  # Only the dumps beyond the newest DB_BACKUP_KEEP_MIN are candidates, and only when old enough.
  candidates=("${all[@]:0:$((total - DB_BACKUP_KEEP_MIN))}")
  for f in "${candidates[@]}"; do
    if [ -n "$(find "$DB_BACKUP_DIR" -maxdepth 1 -type f -name "$f" -mtime +"$DB_BACKUP_RETENTION_DAYS" -print)" ]; then
      rm -f -- "$DB_BACKUP_DIR/$f" "$DB_BACKUP_DIR/$f.sha256"
      PRUNE_REMOVED=$((PRUNE_REMOVED + 1))
      log "prune: removed $f (older than $DB_BACKUP_RETENTION_DAYS days)"
    fi
  done
  log "prune: $PRUNE_REMOVED removed, $((total - PRUNE_REMOVED)) kept"
}

do_backup() {
  local ts name tmp err toc free_mb start entries size sha seconds pruned kept
  ensure_dir
  free_mb=$(free_mb_in_dir)
  if [ "$free_mb" -lt "$DB_BACKUP_MIN_FREE_MB" ]; then
    write_status failed "" 0 "" 0 0 0 "$(list_dumps | wc -l | tr -d ' ')" "too little free space: ${free_mb} MB, need ${DB_BACKUP_MIN_FREE_MB} MB"
    die 2 "only ${free_mb} MB free in $DB_BACKUP_DIR; need at least ${DB_BACKUP_MIN_FREE_MB} MB (DB_BACKUP_MIN_FREE_MB); no dump started, nothing pruned"
  fi
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  name="${DB_BACKUP_PREFIX}-${ts}.pgdump"
  tmp=$(mktemp "$DB_BACKUP_DIR/.partial-${ts}-XXXXXX")
  err="$tmp.err"; toc="$tmp.toc"
  # shellcheck disable=SC2064
  trap "rm -f -- '$tmp' '$err' '$toc'" EXIT
  log "backup of database '$LIVE_DB' on $LIVE_HOST starting (-> $name; ${free_mb} MB free)"
  start=$(date +%s)
  if ! pg_dump --format=custom --no-password --lock-wait-timeout=120000 --file="$tmp" "$(conn_for_db "$LIVE_DB")" 2>"$err"; then
    show_err "$err" pg_dump
    write_status failed "$name" 0 "" 0 $(( $(date +%s) - start )) 0 "$(list_dumps | wc -l | tr -d ' ')" "pg_dump failed"
    die 1 "pg_dump failed; no new backup written; the older dumps are untouched (nothing pruned)"
  fi
  # A dump nobody can read back is not a backup: the archive listing must parse.
  if ! pg_restore --list "$tmp" >"$toc" 2>"$err"; then
    show_err "$err" pg_restore
    write_status failed "$name" 0 "" 0 $(( $(date +%s) - start )) 0 "$(list_dumps | wc -l | tr -d ' ')" "the new dump is not a readable archive"
    die 1 "the new dump is not a readable archive (pg_restore --list failed); discarded; nothing pruned"
  fi
  entries=$(grep -c -E '^[0-9]+; ' "$toc" || true)
  mv -f -- "$tmp" "$DB_BACKUP_DIR/$name"
  chmod 600 "$DB_BACKUP_DIR/$name"
  (cd "$DB_BACKUP_DIR" && sha256sum "$name" > "$name.sha256")
  sha=$(cut -d' ' -f1 "$DB_BACKUP_DIR/$name.sha256")
  size=$(stat -c %s "$DB_BACKUP_DIR/$name")
  seconds=$(( $(date +%s) - start ))
  log "backup ok: $name ($size bytes, $entries archive entries, ${seconds}s)"
  prune
  pruned=$PRUNE_REMOVED
  kept=$(list_dumps | wc -l | tr -d ' ')
  write_status ok "$name" "$size" "$sha" "$entries" "$seconds" "$pruned" "$kept" ""
  log "done: $kept dump(s) kept in $DB_BACKUP_DIR; latest.json updated"
}

do_verify() {
  local file name dir err toc entries size
  file=$(resolve_dump_arg "${1:-}")
  name=$(basename "$file"); dir=$(dirname "$file")
  [ -f "$file.sha256" ] || die 1 "no checksum file $name.sha256 next to the dump (was it written by this script?)"
  if ! (cd "$dir" && sha256sum -c --quiet "$name.sha256" >/dev/null 2>&1); then
    die 1 "CHECKSUM MISMATCH: $name differs from $name.sha256 (damaged or altered); do not restore from it"
  fi
  err=$(mktemp); toc=$(mktemp)
  # shellcheck disable=SC2064
  trap "rm -f -- '$err' '$toc'" EXIT
  if ! pg_restore --list "$file" >"$toc" 2>"$err"; then
    show_err "$err" pg_restore
    die 1 "NOT A READABLE ARCHIVE: $name (pg_restore --list failed)"
  fi
  entries=$(grep -c -E '^[0-9]+; ' "$toc" || true)
  size=$(stat -c %s "$file")
  log "verify ok: $name ($size bytes, checksum matches, $entries archive entries)"
  if grep -q -E ' TABLE (DATA )?public alembic_version ' "$toc"; then
    log "verify: the archive contains the alembic_version table (the database was under Alembic when dumped)"
  else
    log "verify: no alembic_version table in the archive (the database was not yet stamped when dumped)"
  fi
  log "verify: a listing proves the file is readable; only a restore drill proves it restores (restore-drill)"
  rm -f -- "$err" "$toc"
  trap - EXIT
}

psql_q() {  # psql_q CONN SQL -> rows, unaligned, tuples only; fails loudly
  psql -X -q -A -t -v ON_ERROR_STOP=1 --no-password "$1" -c "$2"
}

do_restore_drill() {
  local file keep=0 arg scratch maint live err tables=() t c_backup c_live width rev start seconds
  for arg in "$@"; do
    case "$arg" in
      --keep) keep=1 ;;
      -*) die 2 "unknown option for restore-drill: $arg" ;;
      *) file=$arg ;;
    esac
  done
  file=$(resolve_dump_arg "${file:-}")
  do_verify "$file"
  scratch=$(printf '%s_drill_%s' "$LIVE_DB" "$(date -u +%Y%m%dT%H%M%SZ)" | tr 'A-Z' 'a-z')
  [ "$scratch" != "$LIVE_DB" ] || die 2 "refusing: the scratch name equals the live database name"
  case "$scratch" in *[!a-z0-9_]*) die 2 "refusing: the scratch database name '$scratch' is not a plain identifier" ;; esac
  maint=$(conn_for_db postgres)
  live=$(conn_for_db "$LIVE_DB")
  err=$(mktemp)
  log "restore drill: creating the scratch database '$scratch' (the live database '$LIVE_DB' is only read)"
  if ! psql_q "$maint" "CREATE DATABASE \"$scratch\" TEMPLATE template0;" >/dev/null 2>"$err"; then
    show_err "$err" psql
    rm -f -- "$err"
    die 1 "could not create the scratch database (the role needs CREATEDB, or run the drill as the postgres user; see the runbook)"
  fi
  if [ "$keep" -eq 1 ]; then
    # shellcheck disable=SC2064
    trap "rm -f -- '$err'; log 'restore drill: --keep: the scratch database $scratch stays; drop it later with: DROP DATABASE \"$scratch\";'" EXIT
  else
    # shellcheck disable=SC2064
    trap "rm -f -- '$err'; psql_q '$maint' 'DROP DATABASE IF EXISTS \"$scratch\";' >/dev/null 2>&1 && log 'restore drill: scratch database $scratch dropped' || log 'WARNING: could not drop the scratch database $scratch; drop it by hand'" EXIT
  fi
  start=$(date +%s)
  if ! pg_restore --no-owner --no-privileges --single-transaction --no-password --dbname="$(conn_for_db "$scratch")" "$file" 2>"$err"; then
    show_err "$err" pg_restore
    die 1 "RESTORE FAILED into the scratch database: the dump $(basename "$file") does not restore cleanly"
  fi
  seconds=$(( $(date +%s) - start ))
  log "restore drill: restored $(basename "$file") into $scratch in ${seconds}s; comparing row counts"
  mapfile -t tables < <(psql_q "$(conn_for_db "$scratch")" "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1;")
  [ "${#tables[@]}" -gt 0 ] || die 1 "the restored database has no tables"
  width=24
  for t in "${tables[@]}"; do [ ${#t} -le $width ] || width=${#t}; done
  printf '  %-*s  %12s  %12s\n' "$width" "table" "in backup" "live now"
  for t in "${tables[@]}"; do
    c_backup=$(psql_q "$(conn_for_db "$scratch")" "SELECT count(*) FROM \"$t\";" 2>/dev/null || printf '?')
    # The live database is read in a read-only transaction: this drill cannot write to it even by mistake.
    c_live=$(PGOPTIONS="-c default_transaction_read_only=on" psql_q "$live" "SELECT count(*) FROM \"$t\";" 2>/dev/null || printf '?')
    printf '  %-*s  %12s  %12s\n' "$width" "$t" "$c_backup" "$c_live"
  done
  printf '  (live counts at or above the backup are expected: the shadow run keeps writing; "?" = the table does not exist on that side)\n'
  rev=
  for t in "${tables[@]}"; do [ "$t" = alembic_version ] && rev=$(psql_q "$(conn_for_db "$scratch")" "SELECT version_num FROM alembic_version;" 2>/dev/null || true); done
  if [ -n "$rev" ]; then
    log "restore drill: the restored database is at Alembic revision $rev"
  else
    log "restore drill: the restored database has no alembic_version table (not stamped when dumped)"
  fi
  log "restore drill ok: ${#tables[@]} tables restored from $(basename "$file")"
}

do_list() {
  local n
  if [ ! -d "$DB_BACKUP_DIR" ]; then
    log "no backup folder yet: $DB_BACKUP_DIR"
    return
  fi
  n=$(list_dumps | wc -l | tr -d ' ')
  log "$n dump(s) in $DB_BACKUP_DIR (prefix ${DB_BACKUP_PREFIX}; retention ${DB_BACKUP_RETENTION_DAYS} days, never fewer than ${DB_BACKUP_KEEP_MIN})"
  find "$DB_BACKUP_DIR" -maxdepth 1 -type f -name "${DB_BACKUP_PREFIX}-*.pgdump" -printf '  %TY-%Tm-%Td %TH:%TM  %12s  %f\n' | sort
  if [ -f "$DB_BACKUP_DIR/latest.json" ]; then
    log "last result (latest.json):"
    sed 's/^/  /' "$DB_BACKUP_DIR/latest.json"
  fi
}

main() {
  local cmd=${1:-backup}
  case "$cmd" in
    -h|--help|help) usage; exit 0 ;;
  esac
  shift || true
  check_settings
  case "$cmd" in
    backup)
      [ $# -eq 0 ] || die 2 "backup takes no arguments"
      check_tools; resolve_connection; do_backup ;;
    verify)
      [ $# -le 1 ] || die 2 "verify takes at most one argument (a dump file)"
      check_tools; resolve_connection; do_verify "${1:-}" ;;
    restore-drill)
      check_tools; resolve_connection; do_restore_drill "$@" ;;
    list)
      [ $# -eq 0 ] || die 2 "list takes no arguments"
      resolve_connection; do_list ;;
    *)
      usage >&2; die 2 "unknown command: $cmd" ;;
  esac
}

main "$@"
