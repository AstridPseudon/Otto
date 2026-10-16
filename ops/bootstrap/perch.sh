#!/bin/bash
# PERCH: observe one stage on the staging Otto and write its report.
#   perch.sh STAGE|all [--fake]
# It restarts the staging Otto on the commit under test (staging.sh restart, and nothing of its own),
# runs the stage's canary tasks in a scratch copy of the toy repo under the staging root, stops the
# Otto, and writes ops/perch/STAGE/UTC-TIME/report.md with the raw data beside it. The canary project
# is ops/bootstrap/canary/project.json; STAGE is one of its stage names (0 today).
# --fake: the canary's worker is the fake worker (real commits in the lab, no model). A run without
# it needs a real worker, which is not built yet; stage 0 needs none.
# PERCH_FAULT=leak,lab,pool,timeline,staging seeds one fault per assertion kind, for a red run.
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
  for pid in $SAMPLER $HOLD_POOL $HOLD_LEAK; do kill "$pid" 2>/dev/null || true; done
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
# A worker that holds a lab without finishing: seeded faults only.
hold_worker() {  # LAB NAME
  "$PY" -I "$CANARY/fake_worker.py" --lab "$1" --task "$2" --project "$CANARY/project.json" \
    --events "$RAW/hold-$2.jsonl" --hold >/dev/null 2>&1 &
  started "$!" "seeded $2 hold"
  echo "$!"
}

# Restart the staging Otto on the commit under test. A seeded staging fault gives it one second to report ready.
restart_staging() {
  local t rc=0 ready="${OTTO_STAGING_READY_SECONDS:-120}"
  has_fault staging && ready=1
  t="$(date +%s)"
  OTTO_STAGING_REF="$STAGING_REF" OTTO_STAGING_READY_SECONDS="$ready" "$STAGING" restart \
    > "$RAW/staging-restart.log" 2>&1 || rc=$?
  phase staging-restart "" "$t"
  RESTART_RC=$rc
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
  "$PY" -I "$CANARY/fake_worker.py" --lab "$lab" --task "$task" --project "$CANARY/project.json" \
    --events "$RAW/worker-$task.jsonl" &
  started "$!" "worker $task"
  wait "$!" || rc=$?
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

  "$PY" -I "$REPORT_PY" census --out "$RAW/census.before.txt"
  ( while :; do "$PY" -I "$REPORT_PY" sample --raw "$RAW" --stage-root "$STAGE_ROOT" --canary "$CANARY_DIR" || true; sleep 1; done ) &
  SAMPLER=$!

  restart_staging
  STAGING_SHA="$(sed -n 's/.*"sha": "\([0-9a-f]*\)".*/\1/p' "$STAGE_ROOT/run/staging.json" 2>/dev/null | head -n 1 || true)"
  CANON_MAIN_SHA="$(git -C "$OTTO_REPO" rev-parse --short -q --verify 'canon/main^{commit}' || echo none)"

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
  for pid in $HOLD_POOL; do kill "$pid" 2>/dev/null || true; done
  HOLD_POOL=""

  if has_fault leak; then
    # A worker that outlives the run: the census after must find it.
    HOLD_LEAK="$(hold_worker "$LABS/$last" "$last")"
  fi

  t="$(date +%s)"
  "$STAGING" down > "$RAW/staging-down.log" 2>&1 || true
  phase staging-down "" "$t"
  "$PY" -I "$REPORT_PY" census --out "$RAW/census.after.txt"
  if [ -n "$HOLD_LEAK" ]; then kill "$HOLD_LEAK" 2>/dev/null || true; wait "$HOLD_LEAK" 2>/dev/null || true; HOLD_LEAK=""; fi
  kill "$SAMPLER" 2>/dev/null || true; wait "$SAMPLER" 2>/dev/null || true; SAMPLER=""

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

  "$PY" -I "$REPORT_PY" init --raw "$RAW" --project "$CANARY/project.json" --stage "$stage" --fake \
    --faults "$FAULTS" --staging-restart "$RESTART_RC" --staging-sha "${STAGING_SHA:-none}" \
    --canon-main-sha "$CANON_MAIN_SHA" --started-at "$STARTED"
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
[ -n "$FAKE" ] || die "a run without --fake needs a real worker, which is not built yet"
if [ "$STAGE" = all ]; then
  STAGES="$("$PY" -I "$REPORT_PY" stages --project "$CANARY/project.json")"
else
  case "$STAGE" in *[!0-9]*) usage ;; esac
  "$PY" -I "$REPORT_PY" stages --project "$CANARY/project.json" | grep -qx "$STAGE" \
    || die "no stage $STAGE in $CANARY/project.json"
  STAGES="$STAGE"
fi
RC=0
for s in $STAGES; do
  run_stage "$s"
  [ "$STAGE_RC" -eq 0 ] || RC=1
done
exit "$RC"
