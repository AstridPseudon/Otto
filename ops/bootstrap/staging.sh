#!/bin/bash
# The staging Otto: a fresh, empty Otto started through the product CLI, from canon's own code.
# It has its own tree, home, Store and log under $OTTO_STAGING_ROOT (default $LABS_DIR/_staging).
# It is never a clone of the live Store and never the live install.
#   staging.sh up        start the staging Otto; creates the tree, the home and an empty Store on first use
#   staging.sh down      stop it and every process in its group; a leftover is an error
#   staging.sh restart   down, move the tree to the ref's head (canon/main), up
#   staging.sh wipe      empty the staging home and Store (refused while it is running)
# The start is `ottoctl service run` from the tree's own src (see ottoctl below). Each start is its
# own process group, so down stops the whole group. OTTO_STAGING_REF replaces canon/main as the ref
# (the tests pin it to a commit sha).
set -euo pipefail
. "$(dirname "$0")/common.sh"

STAGE_ROOT="${OTTO_STAGING_ROOT:-$LABS_DIR/_staging}"
REF="${OTTO_STAGING_REF:-refs/heads/canon/main}"
TREE="$STAGE_ROOT/tree"
HOME_DIR="$STAGE_ROOT/home"
STORE_DIR="$STAGE_ROOT/store"
STORE_FILE="$STORE_DIR/staging.store"
RUN="$STAGE_ROOT/run"
PIDFILE="$RUN/staging.pid"
LOG="$RUN/staging.log"
STATUS_JSON="$RUN/staging.json"

# The product CLI, run from the staging tree's own src. --home is always passed, and the variables
# that point a process at a live install are removed, so nothing can fall back to ~/.otto.
ottoctl() {
  env -u OTTO_HOST_KIND -u OTTO_MANAGER_IPC -u OTTO_CALLER_SOCKET -u OTTO_HOME \
    PYTHONPATH="$TREE/src" \
    "$PY" -c 'import sys; from otto.hostctl.cli import main; sys.exit(main())' --home "$HOME_DIR" "$@"
}

# The staging root must be an absolute folder that is not a live owner folder, a synced folder,
# the canon checkout or the home folder itself. Checked before anything is written.
guard_root() {
  local p real=""
  case "$STAGE_ROOT" in
    /*) ;;
    *) die "refused: the staging root must be an absolute path" ;;
  esac
  [ -d "$STAGE_ROOT" ] && real="$(cd "$STAGE_ROOT" && pwd -P)"
  for p in "$STAGE_ROOT" "$real"; do
    case "$p" in
      "$HOME" | "$HOME"/.otto | "$HOME"/.otto/* | "$HOME"/.codex | "$HOME"/.codex/* \
        | "$HOME"/Documents | "$HOME"/Documents/* | "$HOME"/Library/Mobile\ Documents | "$HOME"/Library/Mobile\ Documents/* \
        | "$OTTO_REPO" | "$OTTO_REPO"/*)
        die "refused: staging root $STAGE_ROOT is a live, synced, canon or home folder" ;;
    esac
  done
}

# The pid we started, from the pidfile (line 1), whether or not it is still alive.
recorded_pid() {
  [ -f "$PIDFILE" ] && sed -n 1p "$PIDFILE" || true
}

# The recorded pid, only if that process is alive and is the same one (start time matches line 2).
# A zombie is dead: it has exited and is only waiting to be reaped.
running_pid() {
  local pid start now stat
  pid="$(recorded_pid)"
  [ -n "$pid" ] || return 0
  start="$(sed -n 2p "$PIDFILE")"
  now="$(ps -o lstart= -p "$pid" 2>/dev/null | sed 's/^ *//' || true)"
  stat="$(ps -o stat= -p "$pid" 2>/dev/null | sed 's/^ *//' || true)"
  if [ -n "$now" ] && [ "$now" = "$start" ] && [ "${stat:0:1}" != "Z" ]; then echo "$pid"; fi
  return 0
}

# 0 if any member of process group PGID is alive (not a zombie).
group_alive() {
  [ "$(ps -o stat= -g "$1" 2>/dev/null | sed 's/^ *//' | grep -vc '^Z' || true)" -gt 0 ]
}

# Bring the tree to REF's head and nothing else. Created on first use. The head is fetched by its
# sha, so REF may be a branch (canon/main) or a commit.
sync_tree() {
  local head
  head="$(git -C "$OTTO_REPO" rev-parse --verify -q "$REF^{commit}")" \
    || die "no $REF in $OTTO_REPO"
  mkdir -p "$TREE"
  [ -d "$TREE/.git" ] || git init -q "$TREE"
  git -C "$TREE" fetch -q --force --no-tags "$OTTO_REPO" "$head" 2>/dev/null \
    || git -C "$TREE" fetch -q --force --no-tags "$OTTO_REPO" "$REF:refs/staging/canon-main"
  git -C "$TREE" update-ref refs/staging/canon-main "$head"
  git -C "$TREE" checkout -q --force --detach refs/staging/canon-main
  git -C "$TREE" clean -qfdx
  [ "$(git -C "$TREE" rev-parse HEAD)" = "$head" ] || die "staging tree is not at $REF's head"
  echo "tree at $(git -C "$TREE" rev-parse --short HEAD)"
}

# TERM the group, then KILL what is left. Succeeds only when no member of the group remains.
stop_group() {
  local pid=$1 i
  kill -TERM -- "-$pid" 2>/dev/null || true
  for i in $(seq 1 50); do
    group_alive "$pid" || return 0
    sleep 0.2
  done
  kill -KILL -- "-$pid" 2>/dev/null || true
  for i in $(seq 1 25); do
    group_alive "$pid" || return 0
    sleep 0.2
  done
  return 1
}

# 0 once process group PGID has no live member, or 1 if one is still there after SECONDS.
wait_group_gone() {
  local pgid=$1 i
  for i in $(seq 1 $(( $2 * 5 ))); do
    group_alive "$pgid" || return 0
    sleep 0.2
  done
  ! group_alive "$pgid"
}

# 0 once the entry has printed its ready line after LINES_BEFORE lines of log; 1 if it died or timed out.
wait_ready() {
  local pid=$1 before=$2 i
  for i in $(seq 1 $(( ${OTTO_STAGING_READY_SECONDS:-120} * 5 ))); do
    if [ "$(tail -n +"$((before + 1))" "$LOG" | grep -c '"outcome": "ready"' || true)" -gt 0 ]; then
      return 0
    fi
    kill -0 "$pid" 2>/dev/null || return 1
    sleep 0.2
  done
  return 1
}

# The record of a ready start (run/staging.json): what runs, from which commits, where its state lives.
write_status() {  # PID
  "$PY" -c '
import json, sys
pid, sha, canon, py, home, store, lane, status, stop, started = sys.argv[1:]
print(json.dumps({"sha": sha, "canon_main_sha": canon, "python": py, "pid": int(pid), "home": home,
                  "store": store, "owner_lane": lane, "status": status, "stop_file": stop,
                  "started_at": started}, indent=2))
' "$1" "$(git -C "$TREE" rev-parse HEAD)" "$(git -C "$OTTO_REPO" rev-parse --verify -q "$REF^{commit}")" "$PY" \
    "$HOME_DIR" "$STORE_FILE" "$HOME_DIR/owner-lane" "$HOME_DIR/run/service.json" \
    "$HOME_DIR/run/service-stop" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STATUS_JSON"
}

up() {
  guard_root
  local pid start before
  if [ -n "$(running_pid)" ]; then die "up: already running as pid $(running_pid)"; fi
  [ -d "$TREE/.git" ] || sync_tree
  mkdir -p "$HOME_DIR" "$STORE_DIR" "$RUN"
  touch "$LOG"
  if [ ! -f "$HOME_DIR/installation.json" ]; then
    # A fresh home gets a new, empty Store. A Store file without an installation is never reused.
    [ ! -e "$STORE_FILE" ] || die "up: a Store exists at $STORE_FILE but $HOME_DIR/installation.json does not; run wipe first"
    ottoctl install --create --store "$STORE_FILE" --authority otto-staging-owner-v1 \
      --owner otto-staging-owner --credential-ref otto-staging-credential-v1 >>"$LOG" 2>&1 \
      || die "up: could not create the staging installation; see $LOG"
  fi
  before="$(wc -l < "$LOG" | tr -d ' ')"
  cd "$TREE"
  set -m
  ottoctl service run </dev/null >>"$LOG" 2>&1 &
  pid=$!
  set +m
  # Written at once, so down can find the process even if the wait below fails.
  start="$(ps -o lstart= -p "$pid" 2>/dev/null | sed 's/^ *//' || true)"
  printf '%s\n%s\n' "$pid" "$start" > "$PIDFILE"
  if ! wait_ready "$pid" "$before"; then
    stop_group "$pid" || die "up: the staging Otto did not report ready and group $pid survived KILL; pidfile kept; see $LOG"
    rm -f "$PIDFILE"
    die "up: the staging Otto did not report ready; see $LOG"
  fi
  write_status "$pid"
  echo "up: pid $pid, sha $(git -C "$TREE" rev-parse HEAD), ready"
}

down() {
  guard_root
  local pid stale forced=""
  pid="$(running_pid)"
  if [ -n "$pid" ]; then
    # The service drains and closes on its stop marker; TERM and KILL are the fallback.
    ottoctl service stop >>"$LOG" 2>&1 || echo "down: the stop request failed; see $LOG" >&2
    if ! wait_group_gone "$pid" "${OTTO_STAGING_STOP_SECONDS:-60}"; then
      forced=" (forced)"
      stop_group "$pid" || die "down: processes in group $pid survived KILL; pidfile kept"
    fi
  else
    # The leader is gone. Its group is not signalled, since the pid may have been reused;
    # leftover members are reported instead.
    stale="$(recorded_pid)"
    if [ -n "$stale" ] && group_alive "$stale"; then
      die "down: group $stale has processes but its leader is gone; not signalled. Stop them by hand"
    fi
  fi
  rm -f "$PIDFILE" "$STATUS_JSON"
  echo "down: stopped$forced"
}

restart() {
  down
  sync_tree
  up
}

wipe() {
  guard_root
  [ -z "$(running_pid)" ] || die "wipe: the staging Otto is running; run down first"
  [ -f "$PIDFILE" ] && die "wipe: a pidfile is left; run down first"
  rm -rf "$HOME_DIR" "$STORE_DIR"
  echo "wipe: staging home and Store removed; the next up creates an empty Store"
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  restart) restart ;;
  wipe) wipe ;;
  *) die "usage: staging.sh up|down|restart|wipe" ;;
esac
