#!/bin/bash
# PERCH: observe one stage on the staging Otto and write its report.
#   perch.sh STAGE|all [--fake]
# It restarts the staging Otto on the commit under test (staging.sh restart, and nothing of its own),
# runs the stage's canary tasks in a scratch copy of the toy repo under the staging root, stops the
# Otto, and writes ops/perch/STAGE/UTC-TIME/report.md with the raw data beside it. The canary project
# is ops/bootstrap/canary/project.json; STAGE is one of its stage names (0 today).
# --fake: the canary's worker is the fake worker (real commits in the lab, no model). A run without
# it needs a real worker, which is not built yet; stage 0 needs none, so it runs without the flag.
# A stage's scenarios add steps of their own: staging-lifecycle (stage 0) reads the status, KILLs the Otto,
# restarts it and tries a second start, which must be refused. A stage that wipes starts on an empty Store.
# PERCH_FAULT=leak,lab,pool,timeline,staging,status,restart,refuse,store,atrest,census seeds one fault per
# assertion kind, for a red run.
# Exit 0 when every assertion passes, 1 when one fails (the report is written either way), 2 on usage.
set -euo pipefail
. "$(dirname "$0")/common.sh"

CANARY="$HERE/canary"
REPORT_PY="$HERE/perch_report.py"
STAGING="$HERE/staging.sh"
STAGE_ROOT="${OTTO_STAGING_ROOT:-$LABS_DIR/_staging}"
OUT_ROOT="${PERCH_OUT:-$HERE/../perch}"
STAGING_REF="${OTTO_STAGING_REF:-refs/heads/canon/main}"
AUTHORITY=otto-staging-owner-v1
FAULTS="${PERCH_FAULT:-}"
SAMPLER=""
HOLD_POOL=""
HOLD_LEAK=""

usage() { echo "usage: perch.sh STAGE|all [--fake]" >&2; exit 2; }

has_fault() { case ",$FAULTS," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Stop what this run started and may still hold; runs on every exit. Pids are numbers, so the words split.
stop_background() {
  local pid
  if [ -n "$SAMPLER" ]; then kill -- "-$SAMPLER" 2>/dev/null || true; fi
  for pid in $HOLD_POOL $HOLD_LEAK; do kill "$pid" 2>/dev/null || true; done
}
trap stop_background EXIT

# One line of the observation record: time, task, event, detail. The worker's own events are in worker-TASK.jsonl.
event() { printf '%s\t%s\t%s\t%s\n' "$(now)" "$2" "$1" "$3" >> "$RAW/events.tsv"; }
# A duration: phase, task, start epoch. The seconds are measured now; the start is written as a UTC time.
phase() {
  printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$(date -u -r "$3" +%Y-%m-%dT%H:%M:%SZ)" "$(( $(date +%s) - $3 ))" >> "$RAW/durations.tsv"
}
# A process this run started, so the census can tell a wrong kill from one perch made.
started() { printf '%s\t%s\n' "$1" "$2" >> "$RAW/started.tsv"; }
# A worker started (+1) or stopped (-1), with its time, in pool.tsv: the pool's peak comes from these.
pool_mark() { printf '%s\t%s\n' "$("$PY" -I -c 'import time; print(time.time())')" "$1" >> "$RAW/pool.tsv"; }
# A worker that holds a lab without finishing: seeded faults only.
hold_worker() {  # LAB NAME
  "$PY" -I "$CANARY/fake_worker.py" --lab "$1" --task "$2" --project "$CANARY/project.json" \
    --events "$RAW/hold-$2.jsonl" --hold >/dev/null 2>&1 &
  started "$!" "seeded $2 hold"
  pool_mark +1
  echo "$!"
}
stop_hold() { kill "$1" 2>/dev/null || true; pool_mark -1; }

# Restart the staging Otto on the commit under test. A stage that wipes starts on an empty Store: the Otto is
# brought down, its home and Store are removed, and only then is it started.
restart_staging() {
  local t rc=0 ref="$STAGING_REF"
  # A seeded staging fault pins a ref that does not exist, so the restart fails before it starts anything.
  has_fault staging && ref="refs/heads/perch-seeded-missing-ref"
  t="$(date +%s)"
  if [ "$WIPE" = true ]; then
    bash "$STAGING" down < /dev/null >> "$RAW/staging-restart.log" 2>&1 \
      && bash "$STAGING" wipe < /dev/null >> "$RAW/staging-restart.log" 2>&1 || rc=$?
  fi
  if [ "$rc" -eq 0 ]; then
    OTTO_STAGING_REF="$ref" bash "$STAGING" restart < /dev/null >> "$RAW/staging-restart.log" 2>&1 || rc=$?
  fi
  phase staging-restart "" "$t"
  RESTART_RC=$rc
}

# The product's reading of the staging Otto, written to FILE: `staging.sh status`, or an unavailable outcome when
# it prints nothing. Read-only, so it is safe while the Otto runs.
status_to() {  # FILE
  bash "$STAGING" status < /dev/null > "$1" 2>/dev/null || true
  [ -s "$1" ] || echo '{"outcome": "unavailable"}' > "$1"
}

# The scenario staging-lifecycle, from its first start: the status it reports, the census that must hold its pid,
# and the identity it must match (staging.json, installation.json and the generation as they are now).
lifecycle_up() {
  cp "$STAGE_ROOT/run/staging.json" "$RAW/staging-up.json"
  cp "$STAGE_ROOT/home/installation.json" "$RAW/installation.json"
  cp "$STAGE_ROOT/home/run/generation" "$RAW/generation-up.txt"
  "$PY" -I "$REPORT_PY" census --out "$RAW/census.up.txt" --stage-root "$STAGE_ROOT"
  status_to "$RAW/status-up.json"
}

# The rest of staging-lifecycle, after the canary tasks: a KILL of the whole group, as a crash takes it; a start
# after it; then a second start while the first owner holds the Store, which must be refused.
lifecycle_recover() {
  local pid rc aside t
  pid="$(sed -n 's/.*"pid": \([0-9][0-9]*\).*/\1/p' "$STAGE_ROOT/run/staging.json" | head -n 1)"
  "$PY" -I "$REPORT_PY" store --store "$STAGE_ROOT/store/staging.store" --out "$RAW/store-before-kill.json"
  kill -KILL -- "-$pid" 2>/dev/null || true
  for i in $(seq 1 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
  if has_fault status; then
    # The seeded fault: the probe reads the raw file the Otto wrote before it died, which still says "serving".
    cp "$STAGE_ROOT/home/run/service.json" "$RAW/status-killed.json"
  else
    status_to "$RAW/status-killed.json"
  fi

  t="$(date +%s)"; rc=0
  bash "$STAGING" up < /dev/null > "$RAW/restart-after-kill.log" 2>&1 || rc=$?
  phase restart-after-kill "" "$t"
  "$PY" -I "$REPORT_PY" note --raw "$RAW" --key restart_after_kill_rc --value "$rc"
  "$PY" -I "$REPORT_PY" store --store "$STAGE_ROOT/store/staging.store" --out "$RAW/store-restarted.json"
  status_to "$RAW/status-restarted.json"

  # The pidfile is set aside, so the wrapper no longer knows the running owner and attempts a second start.
  aside="$STAGE_ROOT/run/staging.pid.aside"
  cp "$STAGE_ROOT/run/staging.pid" "$aside"
  rm -f "$STAGE_ROOT/run/staging.pid"
  rc=0
  bash "$STAGING" up < /dev/null > "$RAW/refused-start.log" 2>&1 || rc=$?
  mv "$aside" "$STAGE_ROOT/run/staging.pid"
  if has_fault refuse; then rm -f "$STAGE_ROOT/run/staging.refused.json"; fi
  if [ -f "$STAGE_ROOT/run/staging.refused.json" ]; then cp "$STAGE_ROOT/run/staging.refused.json" "$RAW/refused.json"; fi
  "$PY" -I "$REPORT_PY" note --raw "$RAW" --key refused_start_rc --value "$rc"
}

# The canary: a fresh copy of the toy repo as canon/main, with the lab folder beside it.
make_canon() {
  cp -R "$CANARY/toy/." "$CANON/"
  git -C "$CANON" init -q
  git -C "$CANON" symbolic-ref HEAD refs/heads/canon/main
  git -C "$CANON" add -A
  git -C "$CANON" -c user.name=perch-canary -c user.email=perch-canary@localhost commit -q -m "canary: the toy repo"
}

# One task: lab, worker, check, land or refuse, lab removed. The seeded timeline fault drops the
# first task's check event; the seeded lab fault leaves the last task's lab behind.
run_task() {  # TASK FIRST LAST
  local task=$1 t rc=0 check_rc=0
  local lab="$LABS/$task"
  t="$(date +%s)"
  git -C "$CANON" worktree add -q -b "lab/$task" "$lab" canon/main
  event lab-created "$task" "canon/main $(git -C "$CANON" rev-parse --short canon/main)"
  phase lab-create "$task" "$t"

  t="$(date +%s)"
  pool_mark +1
  "$PY" -I "$CANARY/fake_worker.py" --lab "$lab" --task "$task" --project "$CANARY/project.json" \
    --events "$RAW/worker-$task.jsonl" >"$RAW/worker-$task.out" 2>&1 &
  started "$!" "worker $task"
  wait "$!" || rc=$?
  pool_mark -1
  phase worker "$task" "$t"
  [ "$rc" -eq 0 ] || echo "worker $task exited $rc" >> "$RAW/worker-errors.txt"

  t="$(date +%s)"
  (cd "$lab" && bash -c "$CHECK") > "$RAW/check-$task.log" 2>&1 || check_rc=$?
  phase check "$task" "$t"
  if ! { has_fault timeline && [ "$2" = yes ]; }; then
    if [ "$check_rc" -eq 0 ]; then event check-passed "$task" "rc 0"; else event check-failed "$task" "rc $check_rc"; fi
  fi

  if [ "$check_rc" -eq 0 ] && git -C "$CANON" -c user.name=perch-canary -c user.email=perch-canary@localhost \
      merge -q --no-ff -m "Land $task" "lab/$task"; then
    event landed "$task" "$(git -C "$CANON" rev-parse --short HEAD)"
  else
    event refused "$task" "check rc $check_rc"
  fi

  if has_fault lab && [ "$3" = yes ]; then
    echo "seeded lab fault: $lab left behind" >> "$RAW/seeded.txt"
    return 0
  fi
  t="$(date +%s)"
  git -C "$CANON" worktree remove --force "$lab"
  git -C "$CANON" branch -D "lab/$task" >/dev/null
  event lab-deleted "$task" ""
  phase lab-remove "$task" "$t"
}

# One stage. Its result is left in STAGE_RC: a failed assertion is a red report, not an aborted run.
run_stage() {  # STAGE
  local stage=$1 stamp run task first="" last=""
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  run="$OUT_ROOT/$stage/$stamp"
  RAW="$run/raw"
  CANARY_DIR="$STAGE_ROOT/perch-canary/$stage-$stamp"
  CANON="$CANARY_DIR/canon"
  LABS="$CANARY_DIR/labs"
  mkdir -p "$RAW" "$LABS" "$CANARY_DIR/ops"
  : > "$RAW/events.tsv"; : > "$RAW/started.tsv"; : > "$RAW/durations.tsv"
  STARTED="$(now)"
  RESTART_RC=0

  "$PY" -I "$REPORT_PY" census --out "$RAW/census.before.txt" --stage-root "$STAGE_ROOT"
  # The sampler records the product's reading of the staging Otto, not its raw file. It has a process group of its
  # own, so stopping it also stops a status call it is waiting on.
  set -m
  ( while :; do
      if bash "$STAGING" status < /dev/null > "$RAW/.status" 2>/dev/null; then
        mv -f "$RAW/.status" "$RAW/status-sampled.json"
      else
        rm -f "$RAW/status-sampled.json"
      fi
      "$PY" -I "$REPORT_PY" sample --raw "$RAW" --stage-root "$STAGE_ROOT" --canary "$CANARY_DIR" \
        --status "$RAW/status-sampled.json" || true
      sleep 0.5
    done ) >/dev/null 2>&1 &
  SAMPLER=$!
  set +m

  WIPE="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage "$stage" --key wipe)"
  restart_staging
  STAGING_SHA="$(sed -n 's/.*"sha": "\([0-9a-f]*\)".*/\1/p' "$STAGE_ROOT/run/staging.json" 2>/dev/null | head -n 1 || true)"
  CANON_MAIN_SHA="$(git -C "$OTTO_REPO" rev-parse --short -q --verify 'canon/main^{commit}' || echo none)"

  # The stage's scenarios. One whose staging never came up is skipped, and the report says why.
  RUN_LIFECYCLE=""
  for scenario in $("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage "$stage" --key scenarios); do
    case "$scenario" in
      staging-lifecycle)
        if [ "$RESTART_RC" -eq 0 ]; then
          lifecycle_up
          RUN_LIFECYCLE=1
          "$PY" -I "$REPORT_PY" note --raw "$RAW" --key staging-lifecycle --value ran
        else
          "$PY" -I "$REPORT_PY" note --raw "$RAW" --key staging-lifecycle --value "skipped: staging did not start"
        fi ;;
      *) die "perch.sh has no scenario called $scenario" ;;
    esac
  done

  t="$(date +%s)"; make_canon; phase canary-setup "" "$t"
  CHECK="$("$PY" -I "$REPORT_PY" field --project "$CANARY/project.json" --key check)"
  CHECK="${CHECK//'{python}'/$PY}"
  for task in $("$PY" -I "$REPORT_PY" tasks --project "$CANARY/project.json" --stage "$stage"); do
    [ -n "$first" ] || first="$task"
    last="$task"
  done
  if has_fault pool; then
    # Two workers held on the first task's lab for the whole run: two units against a limit of one.
    HOLD_POOL="$(hold_worker "$LABS/$first" "$first") $(hold_worker "$LABS/$first" "$first")"
  fi
  for task in $("$PY" -I "$REPORT_PY" tasks --project "$CANARY/project.json" --stage "$stage"); do
    run_task "$task" "$([ "$task" = "$first" ] && echo yes || echo no)" "$([ "$task" = "$last" ] && echo yes || echo no)"
  done
  for pid in $HOLD_POOL; do stop_hold "$pid"; done
  HOLD_POOL=""
  if [ -n "$RUN_LIFECYCLE" ]; then lifecycle_recover; fi

  if has_fault leak; then
    # A worker that outlives the run: the census after must find it.
    HOLD_LEAK="$(hold_worker "$LABS/$last" "$last")"
  fi

  t="$(date +%s)"
  bash "$STAGING" down < /dev/null > "$RAW/staging-down.log" 2>&1 || true
  phase staging-down "" "$t"
  kill -- "-$SAMPLER" 2>/dev/null || true; wait "$SAMPLER" 2>/dev/null || true
  # Its group, a status call it may still be running included, must be gone before the census reads the root.
  for i in $(seq 1 50); do kill -0 -- "-$SAMPLER" 2>/dev/null || break; sleep 0.2; done
  SAMPLER=""
  if [ -n "$RUN_LIFECYCLE" ]; then status_to "$RAW/status-stopped.json"; fi
  "$PY" -I "$REPORT_PY" census --out "$RAW/census.after.txt" --stage-root "$STAGE_ROOT"
  if [ -n "$HOLD_LEAK" ]; then kill "$HOLD_LEAK" 2>/dev/null || true; wait "$HOLD_LEAK" 2>/dev/null || true; HOLD_LEAK=""; fi

  "$PY" -I "$REPORT_PY" snapshot --canon "$CANON" --labs "$LABS" --out "$RAW/leftovers.txt"
  "$PY" -I "$REPORT_PY" timeline --src "$STAGE_ROOT/tree/src" --store "$STAGE_ROOT/store/staging.store" \
    --authority "$AUTHORITY" --out "$RAW/timeline.json" \
    || printf '{"error": "the Store timeline read failed; see the run log", "store_events": 0, "tasks": []}\n' > "$RAW/timeline.json"

  # The line's git history: report.sh's own landed and spend sections, read-only. OPS_DIR is an empty
  # folder, so nothing of the operator's ops is read.
  mkdir -p "$RAW/ops-none"
  OPS_DIR="$RAW/ops-none" OTTO_REPO="$OTTO_REPO" bash "$HERE/report.sh" > "$RAW/report-product.txt" 2>&1 || true
  OPS_DIR="$RAW/ops-none" OTTO_REPO="$CANON" bash "$HERE/report.sh" > "$RAW/report-canary.txt" 2>&1 || true

  case "$CANARY_DIR" in
    "$STAGE_ROOT"/perch-canary/*) rm -rf "$CANARY_DIR" ;;
  esac

  # The staging root and the Store, at rest: after down and after the canary scratch is gone.
  if has_fault atrest; then
    # The seeded fault: a socket file the Otto left in its run folder.
    mkdir -p "$STAGE_ROOT/home/run"
    touch "$STAGE_ROOT/home/run/c-leftover.sock"
  fi
  "$PY" -I "$REPORT_PY" store --store "$STAGE_ROOT/store/staging.store" --out "$RAW/store-at-rest.json"
  "$PY" -I "$REPORT_PY" at-rest --stage-root "$STAGE_ROOT" --out "$RAW/at-rest.json"
  for kind in census store restart; do
    if has_fault "$kind"; then "$PY" -I "$REPORT_PY" seed --raw "$RAW" --fault "$kind"; fi
  done

  "$PY" -I "$REPORT_PY" init --raw "$RAW" --project "$CANARY/project.json" --stage "$stage" --fake \
    --faults "$FAULTS" --staging-restart "$RESTART_RC" --staging-sha "${STAGING_SHA:-none}" \
    --canon-main-sha "$CANON_MAIN_SHA" --started-at "$STARTED" --stage-root "$STAGE_ROOT"
  STAGE_RC=0
  "$PY" -I "$REPORT_PY" check --raw "$RAW" || STAGE_RC=$?
  "$PY" -I "$REPORT_PY" render --raw "$RAW" --out "$run/report.md"
  echo "perch: stage $stage report at $run/report.md"
}

[ -n "${1:-}" ] || usage
STAGE="$1"
shift
FAKE=""
for arg in "$@"; do
  case "$arg" in
    --fake) FAKE=1 ;;
    *) usage ;;
  esac
done
if [ "$STAGE" = all ]; then
  STAGES="$("$PY" -I "$REPORT_PY" stages --project "$CANARY/project.json")"
else
  case "$STAGE" in *[!0-9]*) usage ;; esac
  "$PY" -I "$REPORT_PY" stages --project "$CANARY/project.json" | grep -qx "$STAGE" \
    || die "no stage $STAGE in $CANARY/project.json"
  STAGES="$STAGE"
fi
# Stage 0 needs no real worker, so it runs without --fake; every later stage needs one, which is not built yet.
for s in $STAGES; do
  [ -n "$FAKE" ] || [ "$s" = 0 ] || die "stage $s needs a real worker, which is not built yet; only stage 0 runs without --fake"
done
RC=0
for s in $STAGES; do
  run_stage "$s"
  [ "$STAGE_RC" -eq 0 ] || RC=1
done
exit "$RC"
