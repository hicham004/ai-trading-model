#!/usr/bin/env bash
# The paper fleet and the tokenized-stocks recorder on a Linux server, as two locked-down systemd
# services (docs/runbooks/PAPER_FLEET.md, "Option A1"; docs/runbooks/XSTOCKS_DATA.md).
#
# SIMULATION AND PUBLIC MARKET DATA ONLY. Nothing here holds a key, places an order or can trade.
# It never starts, stops or changes shadow.service and never reads its checkout, its .env or its
# database. It only asks systemd whether shadow.service runs, and where its folder and environment
# file are, so that both can be walled off inside the two research services.
#
# What "install" (the default; safe to run again) does:
#   1. checks the server: systemd, Python 3.11 or newer, free memory and disk; when they are short it
#      stops before changing anything; a server under 2 GB without swap gets a 1 GB swap file;
#   2. creates the unprivileged user ai-research (no password, no login shell, no sudo) and its own
#      checkout of plan/auto in /opt/ai-trading-research, outside every home folder;
#   3. builds the Python environment from the hashed lockfile and runs the fleet's offline check;
#   4. writes paper-fleet.service and xstocks-data.service from deploy/systemd/ (read-only system,
#      every home folder hidden, the shadow run's folder and environment file and the demo database
#      socket unreachable, memory and CPU capped, first in line for the out-of-memory killer) and
#      starts both.
#
# Usage, as root or with sudo:
#   bash vps_research_setup.sh             install and start (or repair)
#   bash vps_research_setup.sh status      what runs, the fleet's accounts, the recorder's pairs
#   bash vps_research_setup.sh update      the newest plan/auto: offline check, restart, and back to the
#                                          previous code if the fleet refuses it
#   bash vps_research_setup.sh uninstall   stop and remove both services (the records stay)
#
# The first line on a new server (the DigitalOcean web console logs in as root):
#   curl -fsSL https://raw.githubusercontent.com/hicham004/ai-trading-model/plan/auto/scripts/vps_research_setup.sh -o /tmp/research_setup.sh && sudo bash /tmp/research_setup.sh

set -euo pipefail
umask 022

REPO_URL="${REPO_URL:-https://github.com/hicham004/ai-trading-model.git}"
BRANCH="${BRANCH:-plan/auto}"
PREFIX="${PREFIX:-/opt/ai-trading-research}"
SERVICE_USER="${SERVICE_USER:-ai-research}"
# Free memory needed before a first install, next to whatever already runs (the demo run, PostgreSQL):
# the two programs' measured peaks plus a margin (docs/runbooks/PAPER_FLEET.md, "Disk and memory").
NEED_MEM_MB="${NEED_MEM_MB:-600}"
NEED_DISK_MB="${NEED_DISK_MB:-2500}"
WAIT_SECONDS="${WAIT_SECONDS:-45}"
UNITS="paper-fleet xstocks-data"
MODE="${1:-install}"

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die() {
    printf '\nSTOPPED: %s\n' "$*" >&2
    printf 'The demo shadow run was not touched.\n' >&2
    exit 1
}

# Run a command as the service user, from a folder that user may enter, with a home of its own, and
# first in line for the out-of-memory killer like the two services (the offline check peaks at about
# 400 MB; it must never be the reason the kernel ends the shadow run).
run_as() {
    local dir="$1"
    shift
    (
        cd "$dir"
        runuser -u "$SERVICE_USER" -- env HOME="$PREFIX" XDG_CACHE_HOME="$PREFIX/.cache" \
            PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
            sh -c 'echo 900 > /proc/self/oom_score_adj 2>/dev/null; exec "$@"' run_as "$@"
    )
}

need_root() {
    [ "$(id -u)" -eq 0 ] || die "run it as root: put sudo in front (sudo bash $0 $MODE)"
    [ -d /run/systemd/system ] || die "this machine does not run systemd"
    command -v runuser >/dev/null 2>&1 || die "the runuser command is missing (package util-linux)"
}

shadow_note() {
    local state
    state="$(systemctl is-active shadow.service 2>/dev/null || true)"
    say "demo shadow run (shadow.service): ${state:-not installed} - this script never touches it"
}

mem_mb() { awk -v key="$1:" '$1 == key { print int($2 / 1024) }' /proc/meminfo; }

ours() {  # true when the unit file exists and runs from our checkout
    [ -f "/etc/systemd/system/$1.service" ] && grep -qx "WorkingDirectory=$PREFIX" "/etc/systemd/system/$1.service"
}

all_active() {
    local unit
    for unit in $UNITS; do
        systemctl is-active --quiet "$unit.service" || return 1
    done
}

check_room() {
    local avail total swap disk parent
    avail="$(mem_mb MemAvailable)"
    total="$(mem_mb MemTotal)"
    swap="$(mem_mb SwapTotal)"
    parent="$(dirname "$PREFIX")"
    mkdir -p "$parent"
    disk="$(df -Pm "$parent" | awk 'NR == 2 { print $4 }')"
    say "server: ${total} MB of memory (${avail} MB free), ${swap} MB of swap, ${disk} MB of free disk, $(nproc) CPU"
    if ours paper-fleet && ours xstocks-data && all_active; then
        return 0  # already running: a repair needs no new room
    fi
    [ "$avail" -ge "$NEED_MEM_MB" ] || die "only ${avail} MB of memory is free, and the two programs need about ${NEED_MEM_MB} MB next to what already runs. Nothing was installed. Choose a bigger server size, or put them on a second small server."
    [ "$disk" -ge "$NEED_DISK_MB" ] || die "only ${disk} MB of disk is free; about ${NEED_DISK_MB} MB are needed. Nothing was installed."
}

# A small server (under 2 GB of memory) with no swap gets a 1 GB swap file: a margin for the moments when
# the offline check of an update runs next to both services. An existing swap or /swapfile is left alone;
# where swap cannot be switched on (some containers), the file is removed again and the setup goes on.
ensure_swap() {
    local total swap
    total="$(mem_mb MemTotal)"
    swap="$(mem_mb SwapTotal)"
    [ "$total" -lt "${SWAP_BELOW_MB:-2000}" ] && [ "$swap" -eq 0 ] || return 0
    [ -e /swapfile ] && return 0
    say "adding a 1 GB swap file (${total} MB of memory and no swap: a margin for updates)"
    if { fallocate -l 1G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=1024 status=none; } \
        && chmod 600 /swapfile && mkswap /swapfile >/dev/null 2>&1 && swapon /swapfile 2>/dev/null; then
        grep -q '^/swapfile ' /etc/fstab || printf '/swapfile none swap sw 0 0\n' >>/etc/fstab
        say "swap on: $(mem_mb SwapTotal) MB"
    else
        swapoff /swapfile 2>/dev/null || true
        rm -f /swapfile
        say "swap could not be switched on here; going on without it"
    fi
}

ensure_packages() {
    local need=""
    command -v git >/dev/null 2>&1 || need="$need git"
    command -v python3 >/dev/null 2>&1 || need="$need python3"
    python3 -c 'import ensurepip, venv' >/dev/null 2>&1 || need="$need python3-venv"
    [ -s /etc/ssl/certs/ca-certificates.crt ] || need="$need ca-certificates"
    if [ -n "$need" ]; then
        command -v apt-get >/dev/null 2>&1 || die "missing:$need (and no apt-get to install it)"
        say "installing:$need"
        DEBIAN_FRONTEND=noninteractive apt-get update -qq
        # shellcheck disable=SC2086
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $need >/dev/null
    fi
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
        || die "Python 3.11 or newer is needed; this server has $(python3 --version 2>&1)"
}

ensure_user() {
    if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
        useradd --system --user-group --home-dir "$PREFIX" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
        say "created the user $SERVICE_USER (no password, no login shell, no sudo)"
    fi
}

ensure_checkout() {
    if [ -d "$PREFIX/.git" ]; then
        say "checkout: $PREFIX at $(run_as / git -C "$PREFIX" log --oneline -1)"
        return 0
    fi
    if [ -e "$PREFIX" ] && [ -n "$(ls -A "$PREFIX" 2>/dev/null)" ]; then
        die "$PREFIX exists and is not a checkout; move it away first"
    fi
    install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$PREFIX"
    run_as / git clone --quiet --branch "$BRANCH" --single-branch "$REPO_URL" "$PREFIX"
    say "checkout: $PREFIX at $(run_as / git -C "$PREFIX" log --oneline -1)"
}

ensure_venv() {
    if [ ! -x "$PREFIX/.venv/bin/python" ]; then
        run_as / python3 -m venv "$PREFIX/.venv"
    fi
    say "installing the Python packages from the hashed lockfile (a few minutes the first time)"
    run_as / "$PREFIX/.venv/bin/pip" install --quiet --no-cache-dir -r "$PREFIX/requirements.txt"
    run_as / "$PREFIX/.venv/bin/pip" install --quiet --no-cache-dir --no-deps -e "$PREFIX"
}

ensure_dirs() {
    local dir
    for dir in logs logs/paper_fleet data data/lake data/lake/xstocks; do
        install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$PREFIX/$dir"
    done
}

fleet_check() {
    local log
    log="$(mktemp /tmp/paper-fleet-check.XXXXXX)"
    say "the fleet's offline check (no network, a temporary folder)"
    if ! run_as "$PREFIX" "$PREFIX/.venv/bin/python" scripts/run_paper_fleet.py --dry-run >"$log" 2>&1; then
        tail -n 25 "$log"
        say "full output: $log"
        return 1
    fi
    grep -E '^[[:space:]]+check: ' "$log" | sed -e 's/^[[:space:]]*/  /'
    rm -f "$log"
}

# The shadow run's folder and environment file, wherever they live, as -PATH words for InaccessiblePaths=.
# ProtectHome already hides every home folder; this covers a checkout in /opt, /srv or elsewhere. It only
# asks systemd for two properties of shadow.service (read-only) and never walls off our own folder or a
# system folder the services need.
shadow_paths() {
    local raw path
    systemctl cat shadow.service >/dev/null 2>&1 || return 0
    raw="$(systemctl show -p WorkingDirectory --value shadow.service 2>/dev/null || true)
$(systemctl show -p EnvironmentFiles --value shadow.service 2>/dev/null | awk '{ print $1 }' || true)"
    while IFS= read -r path; do
        path="${path#[-!+]}"
        case "$path" in
            /?*) ;;
            *) continue ;;
        esac
        path="${path%/}"
        case "$path" in
            /*/*) ;;
            *) continue ;;  # a top-level folder such as /opt or /srv: too wide
        esac
        case "$path" in
            /usr/* | /etc/* | /bin/* | /sbin/* | /lib*/* | /proc/* | /sys/* | /dev/* | /run/* | /boot/* | /tmp/* | /var/tmp/*) continue ;;
        esac
        case "$PREFIX/" in
            "$path"/*) continue ;;  # never our own folder or one of its parents
        esac
        printf ' -%s' "$path"
    done <<EOF
$raw
EOF
}

render_units() {
    local unit src dst tmp walls dropin
    walls="$(shadow_paths)"
    for unit in $UNITS; do
        src="$PREFIX/deploy/systemd/$unit.service"
        dst="/etc/systemd/system/$unit.service"
        [ -f "$src" ] || die "$src is missing (an older checkout?)"
        if [ -f "$dst" ] && ! ours "$unit"; then
            die "$dst already exists for another folder ($(grep '^WorkingDirectory=' "$dst" || true)). One record, one place: stop and remove that service first."
        fi
        tmp="$(mktemp)"
        sed -e "s#/path/to/ai-trading-model#$PREFIX#g" \
            -e "s#CHANGE_ME_USER#$SERVICE_USER#g" \
            -e 's#^ProtectHome=read-only$#ProtectHome=yes#' "$src" >"$tmp"
        if grep -q -e 'CHANGE_ME_USER' -e '/path/to/ai-trading-model' "$tmp"; then
            rm -f "$tmp"
            die "the unit template $unit.service kept a placeholder"
        fi
        install -m 0644 "$tmp" "$dst"
        rm -f "$tmp"
        dropin="/etc/systemd/system/$unit.service.d"
        if [ -n "$walls" ]; then
            install -d -m 0755 "$dropin"
            {
                printf '# Written by scripts/vps_research_setup.sh: the shadow run%ss folder and environment file are off limits.\n' "'"
                printf '[Service]\nInaccessiblePaths=%s\n' "${walls# }"
            } >"$dropin/10-shadow-off-limits.conf"
            chmod 0644 "$dropin/10-shadow-off-limits.conf"
        else
            rm -f "$dropin/10-shadow-off-limits.conf"
        fi
        systemd-analyze verify "$dst" 2>&1 | grep -v -e '^$' | sed -e 's/^/  systemd-analyze: /' || true
    done
    if [ -n "$walls" ]; then say "off limits inside both services, besides every home folder:${walls}"; fi
    systemctl daemon-reload
}

wait_running() {  # $1: "die" or "report"; returns 1 when the fleet failed
    local unit state failed=0
    sleep "$WAIT_SECONDS"
    for unit in $UNITS; do
        state="$(systemctl is-active "$unit.service" 2>/dev/null || true)"
        case "$state" in
            active) say "$unit: running" ;;
            activating) say "$unit: restarting after a temporary error (no network yet?); look again with: sudo bash $PREFIX/scripts/vps_research_setup.sh status" ;;
            *)
                journalctl -u "$unit.service" -n 30 --no-pager 2>/dev/null || true
                failed=1
                if [ "$1" = die ]; then die "$unit did not stay running (its last log lines are above)"; fi
                ;;
        esac
    done
    return "$failed"
}

do_install() {
    need_root
    step "1/4 the server"
    shadow_note
    check_room
    ensure_swap
    ensure_packages
    step "2/4 the user and the checkout"
    ensure_user
    ensure_checkout
    step "3/4 the Python environment and the offline check"
    ensure_venv
    ensure_dirs
    fleet_check || die "the fleet's offline check failed; the services were not started"
    step "4/4 the two services"
    render_units
    systemctl enable --quiet paper-fleet.service xstocks-data.service
    systemctl restart paper-fleet.service xstocks-data.service
    wait_running die
    printf '\nDONE. On this server:\n'
    say "  - paper fleet: running; its first start downloads about 2.5 years of public prices (1-3 minutes)"
    say "  - tokenized-stocks recorder: running; its first pass takes about 5 minutes"
    say "  - $(shadow_note)"
    say "Look at them any time with:  sudo bash $PREFIX/scripts/vps_research_setup.sh status"
}

do_status() {
    need_root
    shadow_note
    local unit
    for unit in $UNITS; do
        if ! ours "$unit"; then
            say "$unit: not installed from $PREFIX"
            continue
        fi
        printf '%s: %s since %s, memory %s\n' "$unit" \
            "$(systemctl is-active "$unit.service" 2>/dev/null || true)" \
            "$(systemctl show -p ActiveEnterTimestamp --value "$unit.service")" \
            "$(systemctl show -p MemoryCurrent --value "$unit.service" | awk '{ if ($1 ~ /^[0-9]+$/) printf "%d MB", $1 / 1048576; else print $1 }')"
    done
    [ -d "$PREFIX/.git" ] || return 0
    say "checkout: $(run_as / git -C "$PREFIX" log --oneline -1)"
    printf '\n'
    run_as "$PREFIX" "$PREFIX/.venv/bin/python" scripts/run_paper_fleet.py --status 2>&1 | head -n 80 || true
    printf '\n'
    run_as "$PREFIX" "$PREFIX/.venv/bin/python" scripts/collect_xstocks.py --status 2>&1 | head -n 20 || true
}

# Phase 1 of an update, run from a copy of the CURRENT script (the pull rewrites this very file): fetch
# and fast-forward only. Phase 2 (update-apply) then runs from a copy of the NEW script, so a change to
# this script's own checks or unit rules takes effect in the same update.
do_update() {
    need_root
    if [ "${VPS_RESEARCH_COPY:-}" != 1 ]; then
        local copy
        copy="$(mktemp /tmp/vps_research_setup.XXXXXX)"
        cp "$0" "$copy"
        VPS_RESEARCH_COPY=1 exec bash "$copy" update
    fi
    case "$0" in /tmp/vps_research_setup.*) rm -f "$0" ;; esac  # this copy; bash keeps reading it from the open file
    [ -d "$PREFIX/.git" ] || die "nothing is installed yet: run it once without a word after it"
    ours paper-fleet || die "paper-fleet.service is not installed from $PREFIX"
    shadow_note
    local old new copy
    old="$(run_as / git -C "$PREFIX" rev-parse HEAD)"
    run_as / git -C "$PREFIX" fetch --quiet origin "$BRANCH"
    new="$(run_as / git -C "$PREFIX" rev-parse FETCH_HEAD)"
    if [ "$old" = "$new" ]; then
        say "already up to date: $(run_as / git -C "$PREFIX" log --oneline -1)"
        return 0
    fi
    say "new code:"
    run_as / git -C "$PREFIX" log --oneline "$old..$new" | head -n 20
    run_as / git -C "$PREFIX" merge --quiet --ff-only "$new" \
        || die "the checkout has local changes or has diverged from $BRANCH; nothing was updated"
    copy="$(mktemp /tmp/vps_research_setup.XXXXXX)"
    cp "$PREFIX/scripts/vps_research_setup.sh" "$copy"
    VPS_RESEARCH_OLD="$old" exec bash "$copy" update-apply
}

# Phase 2 of an update (internal): the new code's offline check, units and restart, or the old code back.
do_update_apply() {
    need_root
    case "$0" in /tmp/vps_research_setup.*) rm -f "$0" ;; esac
    local old new
    old="${VPS_RESEARCH_OLD:?run update, not update-apply}"
    new="$(run_as / git -C "$PREFIX" rev-parse HEAD)"
    ensure_swap
    if ! run_as / git -C "$PREFIX" diff --quiet "$old" "$new" -- requirements.txt pyproject.toml; then
        ensure_venv
    fi
    if ! fleet_check; then
        run_as / git -C "$PREFIX" reset --quiet --keep "$old"
        die "the new code failed the fleet's offline check: back to ${old:0:7}; the services kept running"
    fi
    ensure_dirs
    render_units
    systemctl restart paper-fleet.service xstocks-data.service
    if ! wait_running report; then
        run_as / git -C "$PREFIX" reset --quiet --keep "$old"
        render_units
        systemctl restart paper-fleet.service xstocks-data.service
        wait_running report || true
        die "a service refused the new code (its log lines are above): back to ${old:0:7} and restarted"
    fi
    say "updated ${old:0:7} -> ${new:0:7}; both services running"
}

do_uninstall() {
    need_root
    local unit
    for unit in $UNITS; do
        if ours "$unit"; then
            systemctl disable --now --quiet "$unit.service" || true
            rm -f "/etc/systemd/system/$unit.service"
            say "$unit: stopped and removed"
        else
            say "$unit: not installed from $PREFIX, left alone"
        fi
    done
    systemctl daemon-reload
    say "The records stay in $PREFIX (logs/paper_fleet, data/lake/xstocks); delete that folder yourself if you no longer want them."
    shadow_note
}

case "$MODE" in
    install) do_install ;;
    status) do_status ;;
    update) do_update ;;
    update-apply) do_update_apply ;;
    uninstall) do_uninstall ;;
    *) die "unknown command '$MODE' (install, status, update or uninstall)" ;;
esac
