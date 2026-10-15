#!/bin/bash
# The staging Otto: a fresh, empty Otto built from canon/main and started through the production
# entry point. It has its own tree, Store, socket and log under $OTTO_STAGING_ROOT (default
# $LABS_DIR/_staging). It is never a clone of the live Store and never the live install.
#   staging.sh up        start the staging Otto; creates the tree and an empty Store on first use
#   staging.sh down      stop it and every process it started; a leftover is an error
#   staging.sh restart   down, move the tree to canon/main's head, up
#   staging.sh wipe      empty the staging Store (refused while it is running)
# Each start is its own process group, so down stops the whole group. Until the production entry
# point can be rooted at the staging folder, up refuses to start it (see PROD_ENTRY below).
# OTTO_STAGING_ENTRY replaces the entry point; the tests use it with a stub.
set -euo pipefail
. "$(dirname "$0")/common.sh"

STAGE_ROOT="${OTTO_STAGING_ROOT:-$LABS_DIR/_staging}"
TREE="$STAGE_ROOT/tree"
STORE="$STAGE_ROOT/store"
RUN="$STAGE_ROOT/run"
PIDFILE="$RUN/staging.pid"
LOG="$RUN/staging.log"
SOCK="$RUN/otto.sock"
PROD_ENTRY="install/controller/shared_operating_service.py"

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

# Bring the tree to canon/main's head and nothing else. Created on first use.
sync_tree() {
  local head
  head="$(git -C "$OTTO_REPO" rev-parse --verify -q "refs/heads/canon/main^{commit}")" \
    || die "no canon/main in $OTTO_REPO"
  mkdir -p "$TREE"
  [ -d "$TREE/.git" ] || git init -q "$TREE"
  git -C "$TREE" fetch -q --force --no-tags "$OTTO_REPO" "refs/heads/canon/main:refs/staging/canon-main"
  git -C "$TREE" checkout -q --force --detach refs/staging/canon-main
  git -C "$TREE" clean -qfdx
  [ "$(git -C "$TREE" rev-parse HEAD)" = "$head" ] || die "staging tree is not at canon/main's head"
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

up() {
  guard_root
  if [ -z "${OTTO_STAGING_ENTRY:-}" ]; then
    die "up refused: $PROD_ENTRY now takes its locations from OTTO_* variables, but install/controller/operating_service.py (WORK, NATIVE_EVIDENCE_ROOT, LAUNCHER, EVIDENCE_SOURCE_STATE) and native_caller_address.py (the caller socket) still hard-code the live paths, and no staged controller state exists. Starting would touch the live owner. Nothing was started."
  fi
  local entry="$OTTO_STAGING_ENTRY" pid start before
  [ -f "$entry" ] || die "up: no entry point at $entry"
  if [ -n "$(running_pid)" ]; then die "up: already running as pid $(running_pid)"; fi
  [ -d "$TREE/.git" ] || sync_tree
  mkdir -p "$STORE" "$RUN"
  touch "$LOG"
  rm -f "$SOCK"  # a socket left by a killed run
  before="$(wc -l < "$LOG" | tr -d ' ')"
  cd "$TREE"
  set -m
  env OTTO_STAGING_ROOT="$STAGE_ROOT" OTTO_STAGING_STORE="$STORE" OTTO_STAGING_SOCKET="$SOCK" \
    OTTO_CONTROLLER_DIR="$TREE/install/controller" OTTO_PRIVATE_DIR="$STAGE_ROOT/private" \
    OTTO_VISION_CONTROLLER_DIR="$STAGE_ROOT/controllers/vision" OTTO_ASTRID_CONTROLLER_DIR="$STAGE_ROOT/controllers/astrid" \
    OTTO_HOST_HOME="$STAGE_ROOT/host-home" \
    "$PY" "$entry" </dev/null >>"$LOG" 2>&1 &
  pid=$!
  set +m
  # Written at once, so down can find the process even if the wait below fails.
  start="$(ps -o lstart= -p "$pid" 2>/dev/null | sed 's/^ *//' || true)"
  printf '%s\n%s\n' "$pid" "$start" > "$PIDFILE"
  if ! wait_ready "$pid" "$before"; then
    if stop_group "$pid"; then rm -f "$PIDFILE" "$SOCK"; fi
    die "up: the staging Otto did not report ready; see $LOG"
  fi
  echo "up: pid $pid, ready"
}

down() {
  guard_root
  local pid stale
  pid="$(running_pid)"
  if [ -n "$pid" ]; then
    stop_group "$pid" || die "down: processes in group $pid survived KILL; pidfile kept"
  else
    # The leader is gone. Its group is not signalled, since the pid may have been reused;
    # leftover members are reported instead.
    stale="$(recorded_pid)"
    if [ -n "$stale" ] && group_alive "$stale"; then
      die "down: group $stale has processes but its leader is gone; not signalled. Stop them by hand"
    fi
  fi
  rm -f "$PIDFILE" "$SOCK"
  echo "down: stopped"
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
  rm -rf "$STORE"
  mkdir -p "$STORE"
  rm -f "$SOCK"
  echo "wipe: staging Store is empty"
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  restart) restart ;;
  wipe) wipe ;;
  *) die "usage: staging.sh up|down|restart|wipe" ;;
esac
