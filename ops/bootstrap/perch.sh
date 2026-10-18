#!/bin/bash
# PERCH: observe one stage on the staging Otto and write its report.
#   perch.sh STAGE|all [--fake]
# It restarts the staging Otto on the commit under test (staging.sh restart, and nothing of its own),
# runs the stage's scenario against staging, stops the staging Otto, and writes
# ops/perch/STAGE/UTC-TIME/report.md with raw evidence beside it. Stages 0 and 1
# use the harness worker; stage 2 prepares a registered and activated owner
# project and exercises task admission through the operator command. The canary
# project is ops/bootstrap/canary/project.json.
# --fake: the harness worker is fake (real commits in the lab, no model).
# A stage's scenarios add steps of their own: staging-lifecycle (stage 0) reads the status, KILLs the Otto,
# restarts it and tries a second start, which must be refused. A stage that wipes starts on an empty Store.
# Stage 1 adds the scenario save-through-socket: the canary saved from its file through the owner socket from a cold
# shell, read back, one task edited and saved again, then a save from the create's base, which is stale by then.
# PERCH_FAULT=leak,lab,pool,timeline,staging,status,restart,refuse,store,atrest,census,admit,canary,readback,typed,edit,nothing,revision,history,stale,growth,stage2_scenario,stage2_canary,stage2_review,admission_presence,admit_order,unadmitted,reserve,worker_kill,store_snapshot,stage2_census,conflict,owner
# seeds one fault per assertion kind, for a red run; each stage-1 fault is read by its own stage-1 assertion only.
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
# A fatal shell error must not exit 0. bash 3.2 gives the EXIT trap $? = 0 after a set -u abort
# (16 Oct: stage 1 died on an unbound variable, wrote no report, and exited 0), so only the normal
# end sets PERCH_FINISHED, and an exit 0 without it becomes 70.
PERCH_FINISHED=""
trap 'rc=$?; stop_background; if [ "$rc" = 0 ] && [ -z "$PERCH_FINISHED" ]; then echo "perch: stopped before finishing (a fatal shell error above)" >&2; rc=70; fi; exit "$rc"' EXIT

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
restart_staging() {  # STAGE
  local t rc=0 ref="$STAGING_REF" fake_presence=0 repo_path=""
  if [ "$1" = 2 ] && [ -n "$FAKE" ]; then fake_presence=1; fi
  if [ "$1" = 2 ]; then repo_path="$CANON"; fi
  # A seeded staging fault pins a ref that does not exist, so the restart fails before it starts anything.
  has_fault staging && ref="refs/heads/perch-seeded-missing-ref"
  t="$(date +%s)"
  if [ "$WIPE" = true ]; then
    bash "$STAGING" down < /dev/null >> "$RAW/staging-restart.log" 2>&1 \
      && bash "$STAGING" wipe < /dev/null >> "$RAW/staging-restart.log" 2>&1 || rc=$?
  fi
  if [ "$rc" -eq 0 ]; then
    OTTO_STAGING_REF="$ref" OTTO_STAGING_FAKE_PRESENCE="$fake_presence" \
      OTTO_STAGING_STAGE2_SETUP="$([ "$1" = 2 ] && echo 1 || echo 0)" \
      OTTO_STAGING_CANARY_REPO="$repo_path" \
      bash "$STAGING" restart < /dev/null >> "$RAW/staging-restart.log" 2>&1 || rc=$?
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

# The product's client from a cold shell: an empty environment, the staging home named by --home, the tree's own
# src on the path, as staging.sh runs it. Its answer is its stdout.
cold_client() {
  env -i PATH="$PATH" HOME="$HOME" PYTHONPATH="$STAGE_ROOT/tree/src" "$PY" -c \
    'import sys; from otto.hostctl.cli import main; sys.exit(main())' --home "$STAGE_ROOT/home" "$@" < /dev/null
}

# Project and manager commands belong to the admitted host's client lane. The
# owner home above is used only for operator commands (admit-host, repo map and
# service admit); it has no host-client.json.
stage2_host_client() {
  env -i PATH="$PATH" HOME="$HOME" PYTHONPATH="$STAGE_ROOT/tree/src" "$PY" -c \
    'import sys; from otto.hostctl.cli import main; sys.exit(main())' --home "$CANARY_DIR/client" "$@" < /dev/null
}

stage2_capture_fds() {  # BEFORE|AFTER
  local pid
  pid="$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["pid"])' \
    "$STAGE_ROOT/run/staging.json")" || return 1
  printf '%s\n' "$pid" > "$RAW/stage2-owner-pid.txt"
  lsof -p "$pid" > "$RAW/stage2-fds-$1.txt" 2>> "$RAW/stage2-setup-errors.txt" || {
    echo "owner lsof $1 failed for pid $pid" >> "$RAW/stage2-setup-errors.txt"
    return 1
  }
}

# Capture direct product reads around one stage-2 disturbance. These files are
# intentionally raw CLI/Store output; the report checker derives expectations.
stage2_disturb_capture() {  # STEP before|after HOST PROJECT
  local step="$1" side="$2" host="$3" project="$4" prefix="$RAW/stage2-disturb-$1-$2"
  cold_client service status > "$prefix-owner.json" 2>> "$RAW/stage2-setup-errors.txt" || \
    echo '{"outcome":"unavailable"}' > "$prefix-owner.json"
  stage2_host_client --host "$host" project status --project "$project" \
    > "$prefix-project.json" 2>> "$RAW/stage2-setup-errors.txt" || \
    echo '{"outcome":"unavailable"}' > "$prefix-project.json"
  "$PY" -I "$REPORT_PY" store --store "$STAGE_ROOT/store/staging.store" \
    --out "$prefix-store.json" || echo '{"outcome":"unavailable"}' > "$prefix-store.json"
}

# Preserve a command's product response and its process result in the action
# record. Arguments after OUTPUT are the product CLI command.
stage2_disturb_action() {  # STEP OUTPUT COMMAND...
  local step="$1" output="$2" rc=0 stdout="$RAW/stage2-disturb-$1-response.json" stderr="$RAW/stage2-disturb-$1-stderr.txt"
  shift 2
  if "$@" > "$stdout" 2> "$stderr"; then :; else rc=$?; fi
  "$PY" -I - "$output" "$rc" "$*" "$stdout" "$stderr" <<'PY'
import json, sys
from pathlib import Path
out, rc, command, stdout, stderr = sys.argv[1:]
raw = Path(stdout).read_text(errors="replace")
try:
    response = json.loads(raw)
except Exception:
    response = None
Path(out).write_text(json.dumps({"command": command, "rc": int(rc), "response": response,
    "stdout": raw, "stderr": Path(stderr).read_text(errors="replace")}, sort_keys=True, indent=2) + "\n")
PY
  return 0
}

# A one-shot fake presence decline is exercised through real operator admission.
# Keep the owner's refusal response and surrounding product projections.
stage2_disturb_operator_denial() {  # HOST TASK
  local host="$1" task_id="$2" ref revision task_ref_id request_id response="$RAW/stage2-disturb-operator-denial-response.json"
  ref="$("$PY" -I -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["activation"]["steps"]["tasks"]["task_refs"][sys.argv[2]],separators=(",",":")))' \
    "$RAW/stage2-disturb-activation.json" "$task_id")" || return 1
  revision="$("$PY" -I -c 'import json,sys; print(json.loads(sys.argv[1])["revision"])' "$ref")" || return 1
  task_ref_id="$("$PY" -I -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$ref")" || return 1
  "$PY" -I - "$STAGE_ROOT/home/run/perch-fake-presence-deny.json" "$task_ref_id" <<'PYDENY'
import json,sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"task":sys.argv[2]})+"\n")
PYDENY
  stage2_disturb_capture operator-denial before "$host" perch-disturb
  [ ! -f "$STAGE_ROOT/home/run/operator-admission.jsonl" ] || cp "$STAGE_ROOT/home/run/operator-admission.jsonl" "$RAW/stage2-disturb-operator-denial-log-before.jsonl"
  local rc=0
  if cold_client --host "$host" --wait-seconds 0 service admit --task-ref "$ref" \
      --revision "$revision" --review-ref "$(cat "$RAW/stage2-disturb-review-ref.json")" \
      --request-key "perch-stage2-disturb-denied-$task_id" > "$response" 2> "$RAW/stage2-disturb-operator-denial-stderr.txt"; then :; else rc=$?; fi
  request_id="$("$PY" -I "$REPORT_PY" stage2-admission-request --response "$response" 2>> "$RAW/stage2-setup-errors.txt" || true)"
  if [ -n "$request_id" ]; then
    local next_request retained="$RAW/stage2-disturb-operator-denial-retained.json"
    while :; do
      if ! stage2_operator_request_status "$request_id" > "$retained" 2>> "$RAW/stage2-setup-errors.txt"; then
        stage2_owner_alive || return 1
        continue
      fi
      next_request="$("$PY" -I "$REPORT_PY" stage2-admission-request --response "$retained" \
        --expected-request-id "$request_id" 2>> "$RAW/stage2-setup-errors.txt")" || return 1
      [ -n "$next_request" ] || break
      request_id="$next_request"
      stage2_owner_alive || return 1
    done
    "$PY" -I - "$retained" <<'PYDENY-ASSERT'
import json,sys
from pathlib import Path
v=json.loads(Path(sys.argv[1]).read_text())
assert v.get("outcome") == "rejected", v
assert (v.get("error") or {}).get("code") == "presence_declined", v
PYDENY-ASSERT
  else
    cp "$response" "$RAW/stage2-disturb-operator-denial-retained.json"
    "$PY" -I - "$response" <<'PYDENY-IMMEDIATE'
import json,sys
from pathlib import Path
v=json.loads(Path(sys.argv[1]).read_text())
assert v.get("outcome") == "rejected", v
assert (v.get("error") or {}).get("code") == "presence_declined", v
PYDENY-IMMEDIATE
  fi
  [ ! -f "$STAGE_ROOT/home/run/operator-admission.jsonl" ] || cp "$STAGE_ROOT/home/run/operator-admission.jsonl" "$RAW/stage2-disturb-operator-denial-admission.jsonl"
  local retained="$RAW/stage2-disturb-operator-denial-retained.json"
  "$PY" -I - "$RAW/stage2-disturb-operator-denial-action.json" "$rc" "$response" "$retained" <<'PYDENY2'
import json,sys
from pathlib import Path
action,rc,response_path,retained_path=sys.argv[1:]
raw=Path(response_path).read_text(errors="replace")
try:
    response=json.loads(Path(retained_path).read_text()) if Path(retained_path).is_file() else json.loads(raw)
except Exception:
    response=None
Path(action).write_text(json.dumps({"command":"service admit (operator presence declined)","rc":int(rc),
    "response":response,"stdout":raw},sort_keys=True,indent=2)+"\n")
PYDENY2
  stage2_disturb_capture operator-denial after "$host" perch-disturb
}

stage2_disturb_arm() {  # STEP TASK MODE
  "$PY" -I - "$CANARY_DIR/.perch-disturb-$2.json" "$2" "$3" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"task":sys.argv[2],"mode":sys.argv[3]})+"\n")
PY
}

stage2_disturb_finish() {  # STEP HOST PROJECT TASK
  local step="$1" host="$2" project="$3" task="$4" trace watch="$RAW/stage2-disturb-$1-trace-watch-project.json"
  local worker_pid_file="$CANARY_DIR/.perch-disturb-$4.pid" worker_pid worker_command
  stage2_disturb_capture "$step" after "$host" "$project"
  while :; do
    trace="$(find "$CANARY_DIR" -name ".perch-disturb-$task-trace.json" -print -quit 2>/dev/null || true)"
    [ -z "$trace" ] || break
    stage2_host_client --host "$host" project status --project "$project" \
      > "$watch" 2>> "$RAW/stage2-setup-errors.txt" || return 1
    if "$PY" -I - "$watch" "$step" "$task" <<'PYTRACE-TERMINAL'
import json,sys
from pathlib import Path
value=json.loads(Path(sys.argv[1]).read_text())
step,alias=sys.argv[2:]
rows=value.get("tasks") or []
row=next((item for item in rows if isinstance(item,dict) and item.get("id")==alias),{})
dispatch=(row.get("dispatch") or {}).get("state")
lifecycle=row.get("lifecycle")
terminal=(step=="refused-landing" and dispatch in {"failed","unknown"}) or lifecycle=="completed"
raise SystemExit(0 if terminal else 1)
PYTRACE-TERMINAL
    then
      worker_pid="$(cat "$worker_pid_file" 2>/dev/null || true)"
      case "$worker_pid" in *[!0-9]*|"")
        echo "task $task reached a terminal product state without a worker PID marker or raw socket trace" >> "$RAW/stage2-setup-errors.txt"
        return 1 ;;
      esac
      worker_command="$(ps -ww -p "$worker_pid" -o command= 2>/dev/null || true)"
      case "$worker_command" in
        *perch-fake-claude.py*) ;;
        *) echo "task $task reached a terminal product state and worker $worker_pid exited without its raw socket trace" >> "$RAW/stage2-setup-errors.txt"
           return 1 ;;
      esac
    fi
    stage2_owner_alive || return 1
  done
  cp "$trace" "$RAW/stage2-disturb-$step-action.json"
}

stage2_disturb_start_manager() {  # HOST
  local host="$1" schedule marker
  schedule="$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["operating_setup"]["setup"]["roles"]["manager"])' \
    "$RAW/stage2-disturb-activation.json")" || return 1
  stage2_host_client --host "$host" --wait-seconds 0 manager --project perch-disturb \
      start-manager --schedule-id "$schedule" > "$RAW/stage2-disturb-manager-start.json" \
      2>> "$RAW/stage2-setup-errors.txt" || return 1
  marker="$(stage2_wait_marker manager-perch-disturb)" || return 1
  stage2_release_marker "$marker"
}

stage2_disturb_refused_landing() {  # HOST PROJECT
  local host="$1" project="$2" marker
  stage2_disturb_seed_conflict || return 1
  stage2_disturb_capture refused-landing before "$host" "$project"
  stage2_disturb_arm refused-landing E conflict
  stage2_admit_tasks E "$RAW/stage2-disturb-activation.json" "$RAW/stage2-disturb-review-ref.json" || return 1
  marker="$(stage2_wait_marker worker-E)" || return 1
  printf "PERCH_DISTURB_SLOT = 'line'\n" > "$CANON/toy/perch_disturb_slot.py"
  git -C "$CANON" -c user.name=perch-canary -c user.email=perch-canary@localhost add toy/perch_disturb_slot.py
  git -C "$CANON" -c user.name=perch-canary -c user.email=perch-canary@localhost commit -m 'advance line during E worker' \
      >> "$RAW/stage2-disturb-refused-landing-line-update.txt" 2>&1 || return 1
  stage2_release_marker "$marker" || return 1
  stage2_wait_owner_capacity "$RAW/stage2-disturb-refused-landing-settled-owner.json" 0 0 || return 1
  stage2_disturb_finish refused-landing "$host" "$project" E || return 1

  # The second project's own manager reviews F/G through its installed client.
  # Start it after E settles and before admitting F, whose completion gates G.
  stage2_disturb_start_manager "$host" || return 1

  # Prove that the retained E work does not block the next task.
  stage2_admit_tasks F "$RAW/stage2-disturb-activation.json" "$RAW/stage2-disturb-review-ref.json" || return 1
  stage2_wait_worker "$host" F "$project" "$RAW/stage2-disturb-activation.json" || return 1
  cp "$RAW/stage2-dispatch-F-project.json" "$RAW/stage2-disturb-refused-landing-after-next-project.json"
}

stage2_disturb_queued_landings() {  # HOST PROJECT
  local host="$1" project="$2"
  stage2_disturb_capture queued-landings before "$host" "$project"
  stage2_disturb_arm queued-landings G double-done
  stage2_admit_tasks G "$RAW/stage2-disturb-activation.json" "$RAW/stage2-disturb-review-ref.json" || return 1
  stage2_wait_worker "$host" G "$project" "$RAW/stage2-disturb-activation.json" || return 1
  stage2_disturb_finish queued-landings "$host" "$project" G
}

# These steps need an independent admitted project/task so their evidence can
# coexist with the stage-2 A/B/C completion and C kill assertions. The trigger
# is still the normal host product command, and its refusal is recorded raw.
stage2_disturb_restart() {  # HOST PROJECT
  stage2_disturb_capture restart before "$1" "$2"
  stage2_host_client --host "$1" schedules --project "$2" \
      > "$RAW/stage2-disturb-restart-before-dues.json" 2>> "$RAW/stage2-setup-errors.txt" || return 1
  cp "$STAGE_ROOT/home/run/generation" "$RAW/stage2-disturb-restart-before-generation.txt" 2>/dev/null || true
  local rc=0
  if OTTO_STAGING_REF="$STAGING_REF" OTTO_STAGING_FAKE_PRESENCE=1 OTTO_STAGING_STAGE2_SETUP=1 \
      OTTO_STAGING_CANARY_REPO="$CANON" bash "$STAGING" restart < /dev/null > "$RAW/stage2-disturb-restart-response.json" \
      2> "$RAW/stage2-disturb-restart-stderr.txt"; then :; else rc=$?; fi
  "$PY" -I - "$RAW/stage2-disturb-restart-action.json" "$rc" <<'PY'
import json,sys
from pathlib import Path
path,rc=sys.argv[1:]
Path(path).write_text(json.dumps({"command":"staging restart","rc":int(rc),
 "response":Path(path.replace("-action.json","-response.json")).read_text(errors="replace")},indent=2)+"\n")
PY
  cp "$STAGE_ROOT/home/run/generation" "$RAW/stage2-disturb-restart-after-generation.txt" 2>/dev/null || true
  stage2_disturb_capture restart after "$1" "$2"
  stage2_host_client --host "$1" schedules --project "$2" \
      > "$RAW/stage2-disturb-restart-after-dues.json" 2>> "$RAW/stage2-setup-errors.txt" || return 1
}

stage2_disturb_overlapping_activation() {  # HOST PROJECT SECOND_PROJECT
  stage2_disturb_capture overlapping-activation before "$1" "$2"
  local rc=0
  if stage2_activate_disturb_project "$1"; then :; else rc=$?; fi
  cp "$RAW/stage2-disturb-activation.json" "$RAW/stage2-disturb-overlapping-activation-response.json" 2>/dev/null || true
  cp "$RAW/stage2-disturb-second-project-status.json" "$RAW/stage2-disturb-overlapping-activation-second-project.json" 2>/dev/null || true
  "$PY" -I - "$RAW/stage2-disturb-overlapping-activation-action.json" \
      "$RAW/stage2-disturb-overlapping-activation-response.json" \
      "$RAW/stage2-disturb-activation-errors.txt" "$rc" <<'PY'
import json,sys
from pathlib import Path
action,response,stderr,rc=sys.argv[1:]
raw=Path(response).read_text(errors="replace")
try: parsed=json.loads(raw)
except Exception: parsed=None
Path(action).write_text(json.dumps({"command":"project activate","rc":int(rc),"response":parsed,
 "stdout":raw,"stderr":Path(stderr).read_text(errors="replace")},sort_keys=True,indent=2)+"\n")
PY
  stage2_disturb_capture overlapping-activation after "$1" "$2"
}

stage2_disturb_failed_launch() {  # HOST PROJECT TASK
  local host="$1" project="$2" task="${3:-H}"
  stage2_disturb_capture failed-launch before "$host" "$project"
  stage2_disturb_arm failed-launch "$task" failed-launch
  stage2_admit_tasks "$task" "$RAW/stage2-disturb-activation.json" "$RAW/stage2-disturb-review-ref.json" || return 1
  if stage2_wait_worker "$host" "$task" "$project" "$RAW/stage2-disturb-activation.json"; then
    echo "$task unexpectedly completed despite the seeded fake launcher failure" >> "$RAW/stage2-setup-errors.txt"
    return 1
  fi
  stage2_disturb_capture failed-launch after "$host" "$project"
  stage2_host_client --host "$host" schedules --project "$project" \
      > "$RAW/stage2-disturb-failed-launch-after-dues.json" \
      2>> "$RAW/stage2-setup-errors.txt" || return 1
  cp "$RAW/stage2-dispatch-$task.json" "$RAW/stage2-disturb-failed-launch-action.json"
}

# Operator service admit retains its request on the service's owner lane. The
# public request-status command reads an admitted host lane, so read this exact
# owner-lane request with the same product retained-request reader instead.
stage2_operator_request_status() {  # REQUEST_ID
  env -i PATH="$PATH" HOME="$HOME" PYTHONPATH="$STAGE_ROOT/tree/src" "$PY" -c \
    'import json,sys; from pathlib import Path; from otto.hostctl import lanes; from otto.hostctl.service import owner_lane; token=sys.argv[2]; assert lanes.valid_token(token); print(json.dumps(lanes.wait(owner_lane(Path(sys.argv[1])), token, timeout_seconds=0), sort_keys=True))' \
    "$STAGE_ROOT/home" "$1" < /dev/null
}

# Stage 2 uses the same owner CLI setup path as an operator: join the canary host,
# map its disposable repository, register the run bundle, then activate it. Every
# command's raw answer is kept so a failed prerequisite is visible in the report.
stage2_setup() {
  local host bundle rc=0 launcher_args=()
  host="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key host | tr -d '"')"
  bundle="$CANARY_DIR/project"
  "$PY" -I "$REPORT_PY" stage2-bundle --project "$CANARY/project.json" --out "$bundle" > "$RAW/stage2-bundle-path.txt"
  if [ -n "$FAKE" ]; then
    cp "$HERE/perch_fake_claude.py" "$CANARY_DIR/perch-fake-claude.py"
    if ! /usr/bin/cc -std=c11 -O2 -Wall -Wextra "-DPERCH_PYTHON=\"$PY\"" \
        "$HERE/perch_fake_claude_launcher.c" -o "$CANARY_DIR/perch-fake-claude" \
        > "$RAW/stage2-fake-launcher-build.log" 2>&1; then
      echo "fake Claude launcher build failed; see stage2-fake-launcher-build.log" >> "$RAW/stage2-setup-errors.txt"
      return 1
    fi
    launcher_args=(--launcher "$CANARY_DIR/perch-fake-claude")
  fi
  # The owner reloads its installation when admitting a host. Map toy first so
  # the live activation view and dispatch registry receive the same checkout.
  if cold_client repo map --name toy --path "$CANON" > "$RAW/stage2-repository-map.json" 2> "$RAW/stage2-setup-errors.txt"; then :; else
    rc=$?
  fi
  if [ "$rc" -eq 0 ]; then
    if cold_client service admit-host --host "$host" --client-home "$CANARY_DIR/client" \
        "${launcher_args[@]}" > "$RAW/stage2-host-admission.json" 2>> "$RAW/stage2-setup-errors.txt"; then :; else rc=$?; fi
  fi
  if [ "$rc" -eq 0 ]; then
    if stage2_host_client --host "$host" project register --bundle "$bundle" --worktree "$CANON" > "$RAW/stage2-registration.json" 2>> "$RAW/stage2-setup-errors.txt"; then :; else rc=$?; fi
  fi
  if [ "$rc" -eq 0 ]; then
    if "$PY" -I "$REPORT_PY" stage2-plan-save --project "$CANARY/project.json" \
        --registration "$RAW/stage2-registration.json" --out "$RAW/stage2-plan-save.input.json" \
        2>> "$RAW/stage2-setup-errors.txt" \
        && stage2_host_client --host "$host" portfolio --portfolio "$host-portfolio" \
          save "$RAW/stage2-plan-save.input.json" > "$RAW/stage2-plan-save.json" \
          2>> "$RAW/stage2-setup-errors.txt"; then :; else rc=$?; fi
  fi
  if [ "$rc" -eq 0 ]; then
    if stage2_host_client --host "$host" project activate --project perch-stage2 --worktree "$CANON" > "$RAW/stage2-activation.json" 2>> "$RAW/stage2-setup-errors.txt"; then :; else rc=$?; fi
  fi
  if [ "$rc" -eq 0 ]; then
    if stage2_host_client --host "$host" project status --project perch-stage2 > "$RAW/stage2-project-status.json" 2>> "$RAW/stage2-setup-errors.txt"; then :; else rc=$?; fi
  fi
  if [ "$rc" -eq 0 ]; then
    if "$PY" -I "$REPORT_PY" stage2-review-ref --status "$RAW/stage2-project-status.json" \
        --activation "$RAW/stage2-activation.json" --bundle "$bundle" \
        > "$RAW/stage2-review-ref.json" 2>> "$RAW/stage2-setup-errors.txt"; then :; else rc=$?; fi
  fi
  if [ "$rc" -eq 0 ]; then
    cp "$STAGE_ROOT/home/installation.json" "$RAW/stage2-installation.json"
    "$PY" -I "$REPORT_PY" store --store "$STAGE_ROOT/store/staging.store" --out "$RAW/stage2-store-before.json"
    stage2_capture_fds before || rc=$?
    if [ "$rc" -eq 0 ]; then
      "$PY" -I "$REPORT_PY" note --raw "$RAW" --key stage2-setup --value ran
    fi
  else
    "$PY" -I "$REPORT_PY" note --raw "$RAW" --key stage2-setup --value "failed: owner CLI setup exited $rc"
  fi
  return "$rc"
}

stage2_prepare_disturb_project() {
  local host bundle
  host="$($PY -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key host | tr -d '\"')"
  bundle="$CANARY_DIR/disturb-project"
  "$PY" -I "$REPORT_PY" stage2-bundle --project "$CANARY/project.json" --out "$bundle" \
    --run-id perch-disturb --tasks D,E,F,G,H,I > "$RAW/stage2-disturb-bundle-path.txt" || return 1
  if stage2_host_client --host "$host" project register --bundle "$bundle" --worktree "$CANON" \
      > "$RAW/stage2-disturb-registration.json" 2>> "$RAW/stage2-setup-errors.txt"; then :; else return $?; fi
  "$PY" -I "$REPORT_PY" stage2-plan-save --project "$CANARY/project.json" \
      --registration "$RAW/stage2-disturb-registration.json" --tasks D,E,F,G,H,I \
      --project-title perch-disturb --out "$RAW/stage2-disturb-plan-save.input.json" || return 1
  stage2_host_client --host "$host" portfolio --portfolio "$host-portfolio" \
      save "$RAW/stage2-disturb-plan-save.input.json" > "$RAW/stage2-disturb-plan-save.json" \
      2>> "$RAW/stage2-setup-errors.txt" || return 1
  "$PY" -I -c 'import json,sys; assert json.load(open(sys.argv[1]))["outcome"] == "saved"' \
      "$RAW/stage2-disturb-plan-save.json" || return 1
  return 0
}

stage2_activate_disturb_project() {  # HOST
  local host="$1"
  stage2_host_client --host "$host" project activate --project perch-disturb --worktree "$CANON" \
      > "$RAW/stage2-disturb-activation.json" 2> "$RAW/stage2-disturb-activation-errors.txt" || return 1
  stage2_host_client --host "$host" project status --project perch-disturb \
      > "$RAW/stage2-disturb-second-project-status.json" 2>> "$RAW/stage2-disturb-activation-errors.txt" || return 1
  "$PY" -I "$REPORT_PY" stage2-review-ref --status "$RAW/stage2-disturb-second-project-status.json" \
      --activation "$RAW/stage2-disturb-activation.json" --bundle "$CANARY_DIR/disturb-project" \
      > "$RAW/stage2-disturb-review-ref.json" 2>> "$RAW/stage2-disturb-activation-errors.txt" || return 1
}

stage2_disturb_seed_conflict() {
  mkdir -p "$CANON/toy"
  printf "PERCH_DISTURB_SLOT = 'base'\n" > "$CANON/toy/perch_disturb_slot.py"
  git -C "$CANON" -c user.name=perch-canary -c user.email=perch-canary@localhost add toy/perch_disturb_slot.py
  git -C "$CANON" -c user.name=perch-canary -c user.email=perch-canary@localhost commit -m 'seed PERCH landing conflict' \
      > "$RAW/stage2-disturb-refused-landing-line-update.txt" 2>&1 || return 1
}

stage2_run_disturbances() {  # HOST
  local host="$1"
  # A genuine one-shot presence decline on the independent project's I task.
  stage2_disturb_operator_denial "$host" I || return 1

  # E's exact line conflict is concurrent with its owner-launched worker turn.
  stage2_disturb_refused_landing "$host" perch-disturb || return 1

  # Queue both landing requests over separate authenticated worker sockets.
  stage2_disturb_queued_landings "$host" perch-disturb || return 1

  # A failed native launch is retained on H's real owner dispatch record.
  stage2_disturb_failed_launch "$host" perch-disturb H || return 1

  return 0
}

stage2_disturb_restart_task() {  # HOST
  local host="$1" marker old_pid current_pid command new_marker trace
  stage2_disturb_arm restart D hold
  stage2_admit_tasks D "$RAW/stage2-disturb-activation.json" "$RAW/stage2-disturb-review-ref.json" || return 1
  marker="$(stage2_wait_marker worker-D)" || return 1
  old_pid="$(cat "$marker")" || return 1
  stage2_disturb_restart "$host" perch-disturb || return 1
  while :; do
    new_marker="$(find "$CANARY_DIR" -name .perch-worker-D.pid -print -quit 2>/dev/null || true)"
    current_pid="$(cat "$new_marker" 2>/dev/null || true)"
    command="$(ps -ww -p "$current_pid" -o command= 2>/dev/null || true)"
    if [ -n "$current_pid" ] && [ "$current_pid" = "$old_pid" ]; then
      break
    fi
    if [ -n "$current_pid" ] && [ "$current_pid" != "$old_pid" ]; then
      case "$command" in
        *"$CANARY_DIR/perch-fake-claude"*) stage2_release_marker "$new_marker" || return 1; break ;;
      esac
    fi
    stage2_host_client --host "$host" project status --project perch-disturb \
      > "$RAW/stage2-disturb-restart-reconcile-project.json" 2>> "$RAW/stage2-setup-errors.txt" || return 1
    if ! "$PY" -I - "$RAW/stage2-disturb-restart-reconcile-project.json" <<'PYRESTART'
import json,sys
from pathlib import Path
v=json.loads(Path(sys.argv[1]).read_text())
tasks=v.get("tasks") or []
row=next((item for item in tasks if isinstance(item,dict) and item.get("id")=="D"),{})
raise SystemExit(0 if (row.get("dispatch") or {}).get("state")=="launched" else 1)
PYRESTART
    then
      break
    fi
    if "$PY" -I - "$RAW/stage2-disturb-restart-after-owner.json" <<'PYRESTART-CAPACITY'
import json,sys
from pathlib import Path
v=json.loads(Path(sys.argv[1]).read_text())
raise SystemExit(0 if (v.get("native_capacity") or {}).get("active_or_uncertain")==0 else 1)
PYRESTART-CAPACITY
    then
      break
    fi
    stage2_owner_alive || return 1
  done
  trace="$(find "$CANARY_DIR" -name '.perch-disturb-D-trace.json' -print -quit 2>/dev/null || true)"
  [ -z "$trace" ] || cp "$trace" "$RAW/stage2-disturb-restart-worker-trace.json"
  return 0
}

stage2_wait_admission_boundary() {  # TASK
  local task="$1" status="$RAW/stage2-admit-$1-boundary-status.json"
  while :; do
    if cold_client service status > "$status" 2>> "$RAW/stage2-setup-errors.txt"; then
      if "$PY" -I "$REPORT_PY" stage2-boundary-closed --status "$status" > /dev/null 2>&1; then
        return 0
      fi
    fi
    if ! stage2_owner_alive; then
      echo "owner exited before the $task admission boundary closed; see stage2-admit-$task-boundary-status.json" >> "$RAW/stage2-setup-errors.txt"
      if [ -f "$STAGE_ROOT/run/staging.log" ]; then
        tail -n 120 "$STAGE_ROOT/run/staging.log" > "$RAW/stage2-owner-log-tail.txt"
      fi
      return 1
    fi
    sleep 0.5
  done
}

stage2_submit_admission() {  # HOST TASK REF REVIEW_REF ATTEMPT
  local host="$1" task="$2" ref="$3" review_ref="$4" attempt="$5" rc
  local request_key="perch-stage2-admit-$task" receipt="$RAW/stage2-admit-$task-attempt-$attempt.json"
  printf '%s\n' "$request_key" > "$RAW/stage2-admit-$task-attempt-$attempt.request-key"
  if cold_client --host "$host" --wait-seconds 0 service admit --task-ref "$ref" \
      --revision "$("$PY" -I -c 'import json,sys; print(json.load(sys.stdin)["revision"])' <<< "$ref")" \
      --review-ref "$review_ref" --request-key "$request_key" \
      > "$receipt" 2>> "$RAW/stage2-setup-errors.txt"; then
    return 0
  else
    rc=$?
  fi
  [ ! -s "$receipt" ] || cp "$receipt" "$RAW/stage2-admit-$task.json"
  "$PY" -I "$REPORT_PY" note --raw "$RAW" --key "stage2-admit-$task" --value "failed: owner service admit exited $rc"
  return "$rc"
}

stage2_admit_tasks() {
  local host task ref review_ref attempt receipt request_id next_request retained selected activation_file review_file
  host="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key host | tr -d '\"')"
  activation_file="${2:-$RAW/stage2-activation.json}"
  review_file="${3:-$RAW/stage2-review-ref.json}"
  review_ref="$(cat "$review_file")"
  selected="${1:-$("$PY" -I "$REPORT_PY" tasks --project "$CANARY/project.json" --stage 2)}"
  # Submit the selected tasks before waiting for their results. A pending
  # admission retains its one owner-lane request.
  for task in $selected; do
    ref="$("$PY" -I -c 'import json,sys; v=json.load(open(sys.argv[1])); print(json.dumps(v["activation"]["steps"]["tasks"]["task_refs"][sys.argv[2]],separators=(",",":")))' \
      "$activation_file" "$task" 2>> "$RAW/stage2-setup-errors.txt")" || return 1
    # The operator command is the sole task admission route. It performs the
    # owner-local presence proof and verifies the selected exact revision.
    stage2_submit_admission "$host" "$task" "$ref" "$review_ref" 1 || return $?
    cp "$RAW/stage2-admit-$task-attempt-1.json" "$RAW/stage2-admit-$task.json"
  done
  for task in $selected; do
    ref="$("$PY" -I -c 'import json,sys; v=json.load(open(sys.argv[1])); print(json.dumps(v["activation"]["steps"]["tasks"]["task_refs"][sys.argv[2]],separators=(",",":")))' \
      "$activation_file" "$task" 2>> "$RAW/stage2-setup-errors.txt")" || return 1
    attempt=0
    while :; do
      attempt=$(( attempt + 1 ))
      receipt="$RAW/stage2-admit-$task-attempt-$attempt.json"
      if ! request_id="$("$PY" -I "$REPORT_PY" stage2-admission-request \
          --response "$receipt" 2>> "$RAW/stage2-setup-errors.txt")"; then return 1; fi
      if [ -n "$request_id" ]; then
        retained="$RAW/stage2-admit-$task-retained-$attempt.json"
      fi
      while [ -n "$request_id" ]; do
        sleep 0.5
        if ! stage2_operator_request_status "$request_id" \
            > "$retained" 2>> "$RAW/stage2-setup-errors.txt"; then
          if ! stage2_owner_alive; then
            echo "owner exited while waiting for retained admission request $request_id for $task; see $(basename "$retained")" >> "$RAW/stage2-setup-errors.txt"
            return 1
          fi
          continue
        fi
        if ! next_request="$("$PY" -I "$REPORT_PY" stage2-admission-request \
            --response "$retained" --expected-request-id "$request_id" \
            2>> "$RAW/stage2-setup-errors.txt")"; then return 1; fi
        request_id="$next_request"
        if [ -z "$request_id" ]; then
          receipt="$retained"
        elif ! stage2_owner_alive; then
          echo "owner exited while retained admission request $request_id stayed pending for $task" >> "$RAW/stage2-setup-errors.txt"
          return 1
        fi
      done
      cp "$receipt" "$RAW/stage2-admit-$task.json"
      if "$PY" -I "$REPORT_PY" stage2-admission-held --response "$receipt"; then
        if ! stage2_wait_admission_boundary "$task"; then
          "$PY" -I "$REPORT_PY" note --raw "$RAW" --key "stage2-admit-$task" --value "failed: held admission boundary did not close"
          return 1
        fi
        stage2_submit_admission "$host" "$task" "$ref" "$review_ref" "$(( attempt + 1 ))" || return $?
        continue
      fi
      if ! "$PY" -I "$REPORT_PY" stage2-admission-check --response "$receipt" \
          --task-ref "$ref" >> "$RAW/stage2-setup-errors.txt" 2>&1; then
        "$PY" -I "$REPORT_PY" note --raw "$RAW" --key "stage2-admit-$task" --value "failed: owner did not admit the exact activated revision"
        return 1
      fi
      break
    done
    "$PY" -I "$REPORT_PY" note --raw "$RAW" --key "stage2-admit-$task" --value ran
  done
  return 0
}

stage2_owner_alive() {
  local record="$STAGE_ROOT/run/staging.pid" pid start now state
  [ -f "$record" ] || return 1
  pid="$(sed -n 1p "$record")"
  start="$(sed -n 2p "$record")"
  case "$pid" in *[!0-9]*|"") return 1 ;; esac
  [ -n "$start" ] || return 1
  now="$(ps -o lstart= -p "$pid" 2>/dev/null | sed 's/^ *//' || true)"
  state="$(ps -o stat= -p "$pid" 2>/dev/null | sed 's/^ *//' || true)"
  [ "$now" = "$start" ] && [ -n "$state" ] && [ "${state:0:1}" != Z ]
}

stage2_wait_marker() {  # NAME
  local marker=""
  while :; do
    marker="$(find "$CANARY_DIR" -name ".perch-$1.pid" -print -quit 2>/dev/null || true)"
    [ -z "$marker" ] || { printf '%s\n' "$marker"; return 0; }
    if ! stage2_owner_alive; then
      echo "owner exited before the $1 PID marker appeared" >> "$RAW/stage2-setup-errors.txt"
      return 1
    fi
    sleep 0.25
  done
}

stage2_release_marker() {  # PATH
  local pid command
  pid="$(cat "$1")" || return 1
  case "$pid" in *[!0-9]*|"") return 1 ;; esac
  command="$(ps -ww -p "$pid" -o command= 2>/dev/null || true)"
  case "$command" in *"$CANARY_DIR/perch-fake-claude"*) kill -USR1 "$pid" ;;
    *) echo "refusing to release unrelated pid $pid: $command" >> "$RAW/stage2-setup-errors.txt"; return 1 ;;
  esac
}

stage2_wait_owner_capacity() {  # RECEIPT ACTIVE MANAGERS
  while :; do
    if cold_client service status > "$1" 2>> "$RAW/stage2-setup-errors.txt" && \
        "$PY" -I -c 'import json,sys; v=json.load(open(sys.argv[1]));
assert (v.get("native_capacity") or {}).get("active_or_uncertain") == int(sys.argv[2]);
assert (v.get("manager_turns") or {}).get("active") == int(sys.argv[3])' "$1" "$2" "$3" \
        > /dev/null 2>&1; then
      return 0
    fi
    if ! stage2_owner_alive; then
      echo "owner exited before capacity status showed active=$2 manager=$3 in $1" >> "$RAW/stage2-setup-errors.txt"
      return 1
    fi
    sleep 0.25
  done
}

stage2_capacity_turn() {
  local host first="" second manager schedule
  host="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key host | tr -d '\"')"
  while :; do
    first="$(find "$CANARY_DIR" \( -name .perch-worker-A.pid -o -name .perch-worker-B.pid \) -print -quit 2>/dev/null || true)"
    [ -z "$first" ] || break
    if ! stage2_owner_alive; then
      echo "owner exited before either ready worker A/B PID marker appeared" >> "$RAW/stage2-setup-errors.txt"
      return 1
    fi
    sleep 0.25
  done
  schedule="$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["operating_setup"]["setup"]["roles"]["manager"])' \
    "$RAW/stage2-activation.json")" || return 1
  if [ -n "$FAKE" ]; then
    stage2_disturb_overlapping_activation "$host" perch-stage2 perch-disturb || return 1
  fi
  stage2_host_client --host "$host" --wait-seconds 0 manager --project perch-stage2 \
    start-manager --schedule-id "$schedule" > "$RAW/stage2-manager-start.json" \
    2>> "$RAW/stage2-setup-errors.txt" || return 1
  manager="$(stage2_wait_marker manager)" || return 1
  stage2_wait_owner_capacity "$RAW/stage2-contention-owner.json" 2 1 || return 1
  stage2_host_client --host "$host" project status --project perch-stage2 \
    > "$RAW/stage2-contention-project.json" 2>> "$RAW/stage2-setup-errors.txt" || return 1
  stage2_release_marker "$manager" || return 1
  stage2_release_marker "$first" || return 1
  if [ "${first##*/}" = .perch-worker-A.pid ]; then second="$(stage2_wait_marker worker-B)" || return 1
  else second="$(stage2_wait_marker worker-A)" || return 1; fi
  cold_client service status > "$RAW/stage2-second-worker-owner.json" 2>> "$RAW/stage2-setup-errors.txt" || return 1
  stage2_release_marker "$second" || return 1
  stage2_wait_worker "$host" A && stage2_wait_worker "$host" B
}

stage2_edit_C() {
  local host
  host="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key host | tr -d '\"')"
  stage2_host_client --host "$host" project status --project perch-stage2 \
    > "$RAW/stage2-before-C-edit.json" 2>> "$RAW/stage2-setup-errors.txt" || return 1
  "$PY" -I - "$RAW/stage2-plan-save.input.json" "$RAW/stage2-before-C-edit.json" \
    "$RAW/stage2-instruction-edit-C.input.json" <<'PY' || return 1
import json, sys
from pathlib import Path
plan, status = (json.load(open(path)) for path in sys.argv[1:3])
task = next(row for row in plan["tasks"] if row["id"] == "C")
task["instructions"] += " (post-admission edit)"
Path(sys.argv[3]).write_text(json.dumps({"project_ref": status["project_ref"],
    "project": {}, "tasks": [task]}, indent=2, sort_keys=True) + "\n")
PY
  stage2_host_client --host "$host" portfolio --portfolio "$host-portfolio" \
    save "$RAW/stage2-instruction-edit-C.input.json" > "$RAW/stage2-instruction-edit-C.json" \
    2>> "$RAW/stage2-setup-errors.txt" || return 1
  "$PY" -I -c 'import json,sys; assert json.load(open(sys.argv[1]))["outcome"] == "saved"' \
    "$RAW/stage2-instruction-edit-C.json" || return 1
}

stage2_finish_C() {
  local host review_ref ref revision
  host="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key host | tr -d '\"')"
  stage2_capacity_turn || return 1
  stage2_host_client --host "$host" project status --project perch-stage2 \
    > "$RAW/stage2-edited-C-no-launch.json" 2>> "$RAW/stage2-setup-errors.txt" || return 1
  stage2_wait_owner_capacity "$RAW/stage2-edited-C-owner.json" 0 0 || return 1
  # The second operator admission writes the new stamp in task metadata. Its
  # Store revision is separate from the instruction edit's content revision.
  ref="$("$PY" -I -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["task_refs"]["C"],separators=(",",":")))' \
    "$RAW/stage2-instruction-edit-C.json")" || return 1
  revision="$("$PY" -I -c 'import json,sys; print(json.loads(sys.argv[1])["revision"])' "$ref")" || return 1
  review_ref="$(cat "$RAW/stage2-review-ref.json")"
  cold_client --host "$host" service admit --task-ref "$ref" --revision "$revision" \
    --review-ref "$review_ref" --request-key perch-stage2-readmit-C \
    > "$RAW/stage2-metadata-only-C.json" 2>> "$RAW/stage2-setup-errors.txt" || return 1
  "$PY" -I "$REPORT_PY" stage2-admission-check --response "$RAW/stage2-metadata-only-C.json" \
    --task-ref "$ref" >> "$RAW/stage2-setup-errors.txt" 2>&1 || return 1
  "$PY" -I - "$RAW/stage2-activation.json" "$RAW/stage2-instruction-edit-C.json" \
    "$RAW/stage2-current-activation.json" <<'PY' || return 1
import json, sys
from pathlib import Path
activation = json.load(open(sys.argv[1]))
edited = json.load(open(sys.argv[2]))
activation["activation"]["steps"]["tasks"]["task_refs"]["C"] = edited["task_refs"]["C"]
Path(sys.argv[3]).write_text(json.dumps(activation, indent=2, sort_keys=True) + "\n")
PY
}

stage2_dispatch_tasks() {
  local host task
  host="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key host | tr -d '\"')"
  for task in $("$PY" -I "$REPORT_PY" tasks --project "$CANARY/project.json" --stage 2); do
    stage2_wait_worker "$host" "$task" || return $?
  done
  return 0
}

# Owner automatic dispatch is the scenario's dispatch path. The admitted host
# reads each task's retained dispatch state through product project status.
# Manager status requires a native manager caller.
stage2_wait_worker() {  # HOST TASK [PROJECT ACTIVATION ADMISSION]
  local host="$1" task="$2" project="${3:-perch-stage2}" saw_dispatch="" request_id="" next_request="" activation admission
  activation="${4:-$RAW/stage2-activation.json}"; admission="${5:-$RAW/stage2-admit-$task.json}"
  if [ "$project" = perch-stage2 ] && [ "$task" = C ] && [ -f "$RAW/stage2-current-activation.json" ]; then
    activation="$RAW/stage2-current-activation.json"; admission="$RAW/stage2-metadata-only-C.json"
  fi
  while :; do
    # Return a retained receipt promptly; only request-status may read it until terminal.
    if ! stage2_host_client --host "$host" --wait-seconds 0 project status --project "$project" \
        > "$RAW/stage2-dispatch-$task.json" 2>> "$RAW/stage2-setup-errors.txt"; then
      if ! stage2_owner_alive; then
        echo "owner exited while waiting for $task project status; see stage2-dispatch-$task.json" >> "$RAW/stage2-setup-errors.txt"
        return 1
      fi
      sleep 0.5
      continue
    fi
    if ! request_id="$("$PY" -I "$REPORT_PY" stage2-dispatch-request \
          --status "$RAW/stage2-dispatch-$task.json" 2>> "$RAW/stage2-setup-errors.txt")"; then return 1; fi
    if [ -n "$request_id" ]; then
      cp "$RAW/stage2-dispatch-$task.json" "$RAW/stage2-dispatch-$task-pending.json"
    fi
    while [ -n "$request_id" ]; do
      sleep 0.5
      if ! stage2_host_client --host "$host" request-status --request-id "$request_id" \
          > "$RAW/stage2-dispatch-$task.json" 2>> "$RAW/stage2-setup-errors.txt"; then
        if ! stage2_owner_alive; then
          echo "owner exited while waiting for retained project status request $request_id; see stage2-dispatch-$task.json" >> "$RAW/stage2-setup-errors.txt"
          return 1
        fi
        continue
      fi
      if ! next_request="$("$PY" -I "$REPORT_PY" stage2-dispatch-request \
            --status "$RAW/stage2-dispatch-$task.json" --expected-request-id "$request_id" \
            2>> "$RAW/stage2-setup-errors.txt")"; then return 1; fi
      request_id="$next_request"
      if [ -n "$request_id" ] && ! stage2_owner_alive; then
        echo "owner exited while retained project status request $request_id stayed pending" >> "$RAW/stage2-setup-errors.txt"
        return 1
      fi
    done
    if ! "$PY" -I "$REPORT_PY" stage2-dispatch-no-failure \
          --status "$RAW/stage2-dispatch-$task.json" --task "$task" \
          >> "$RAW/stage2-setup-errors.txt" 2>&1; then return 1; fi
    if "$PY" -I "$REPORT_PY" stage2-dispatch-check \
          --status "$RAW/stage2-dispatch-$task.json" --activation "$activation" \
          --admission "$admission" --task "$task" \
          > /dev/null 2>&1; then
      saw_dispatch=1
      cp "$RAW/stage2-dispatch-$task.json" "$RAW/stage2-dispatch-$task-project.json"
      cold_client service status > "$RAW/stage2-owner-$task.json" 2>> "$RAW/stage2-setup-errors.txt" || return $?
      if [ "$task" = C ]; then
        stage2_kill_worker || return $?
        return 0
      fi
      if "$PY" -I "$REPORT_PY" stage2-task-landed \
          --project-status "$RAW/stage2-dispatch-$task-project.json" --task "$task" > /dev/null 2>&1; then
        return 0
      fi
    fi
    if ! stage2_owner_alive; then
      if [ -n "$saw_dispatch" ]; then
        echo "owner exited before admitted task $task completed and released capacity" >> "$RAW/stage2-setup-errors.txt"
      else
        echo "owner exited before dispatch evidence appeared for admitted task $task" >> "$RAW/stage2-setup-errors.txt"
      fi
      return 1
    fi
    sleep 0.5
  done
}

stage2_kill_worker() {
  [ -n "$FAKE" ] || return 0
  local marker="" pid owner command
  while :; do
    marker="$(find "$CANARY_DIR/canon.otto-labs" -name .perch-worker-C.pid -print -quit 2>/dev/null || true)"
    [ -z "$marker" ] || break
    if ! stage2_owner_alive; then
      echo "owner exited before C worker published its lab PID marker" >> "$RAW/stage2-setup-errors.txt"
      return 1
    fi
    sleep 0.25
  done
  pid="$(cat "$marker")"
  owner="$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["pid"])' "$STAGE_ROOT/run/staging.json")"
  case "$pid" in *[!0-9]*|"") return 1 ;; esac
  [ "$pid" != "$owner" ] || return 1
  command="$(ps -ww -p "$pid" -o command= 2>/dev/null || true)"
  case "$command" in *"$CANARY_DIR/perch-fake-claude"*) ;; *)
    echo "C PID $pid does not name the pinned fake worker: $command" >> "$RAW/stage2-setup-errors.txt"; return 1 ;; esac
  "$PY" -I -c 'import json,sys; print(json.dumps({"pid":int(sys.argv[1]),"owner_pid":int(sys.argv[2]),"marker":sys.argv[3]}))' \
    "$pid" "$owner" "$marker" > "$RAW/stage2-killed-worker.json"
  while :; do
    if cold_client service status > "$RAW/stage2-capacity-before-kill.json" 2>> "$RAW/stage2-setup-errors.txt" && \
        "$PY" -I "$REPORT_PY" stage2-capacity-held --status "$RAW/stage2-capacity-before-kill.json" \
        > /dev/null 2>&1; then break; fi
    if ! stage2_owner_alive; then
      echo "owner exited before C worker capacity was observed held" >> "$RAW/stage2-setup-errors.txt"
      return 1
    fi
    sleep 0.25
  done
  "$PY" -I "$REPORT_PY" stage2-capacity-held --status "$RAW/stage2-capacity-before-kill.json" \
    >> "$RAW/stage2-setup-errors.txt" 2>&1 || return 1
  "$PY" -I "$REPORT_PY" census --out "$RAW/stage2-census-before-kill.txt" --stage-root "$STAGE_ROOT"
  kill -KILL "$pid" || return 1
  while :; do
    if cold_client service status > "$RAW/stage2-capacity-after-kill.json" 2>> "$RAW/stage2-setup-errors.txt"; then
      "$PY" -I "$REPORT_PY" census --out "$RAW/stage2-census-after-kill.txt" --stage-root "$STAGE_ROOT"
      if "$PY" -I "$REPORT_PY" stage2-kill-check --raw "$RAW" > /dev/null 2>&1; then
        while :; do
          if cold_client service status > "$RAW/stage2-recovery-owner.json" 2>> "$RAW/stage2-setup-errors.txt"; then
            if "$PY" -I "$REPORT_PY" stage2-boundary-closed --status "$RAW/stage2-recovery-owner.json" \
                > /dev/null 2>&1; then return 0; fi
          fi
          if ! stage2_owner_alive; then
            echo "owner exited before C's retained kill fence was settled" >> "$RAW/stage2-setup-errors.txt"
            return 1
          fi
          sleep 0.25
        done
      fi
    fi
    if ! stage2_owner_alive; then
      echo "owner exited before C worker kill evidence showed its capacity slot released" >> "$RAW/stage2-setup-errors.txt"
      return 1
    fi
    sleep 0.25
  done
}

# One save of the stage's document NAME through the owner socket, from REF_FROM's project ref when it is an edit or a
# stale base. Its answer is raw/save-NAME.json; a client that gives none is recorded as unavailable, which fails.
save_step() {  # NAME REF_FROM
  local name=$1 ref=${2:-} doc="$RAW/save-$1.input.json"
  local args=(--name "$name")
  # No save runs before the admission is recorded and checked: the save is recorded unavailable instead.
  if [ -z "$ADMITTED" ]; then echo '{"outcome": "unavailable"}' > "$RAW/save-$name.json"; return 0; fi
  [ -z "$ref" ] || args+=(--ref-from "$ref")
  if "$PY" -I "$REPORT_PY" save-doc --project "$CANARY/project.json" --stage "$SAVE_STAGE" "${args[@]}" --out "$doc" \
      && cold_client portfolio --portfolio "$SAVE_PORTFOLIO" save "$doc" > "$RAW/save-$name.json" 2>> "$RAW/save-errors.txt"; then
    return 0
  fi
  echo '{"outcome": "unavailable"}' > "$RAW/save-$name.json"
}

# The scenario save-through-socket: a Store snapshot before, then create, read back, edit, stale; a snapshot after each save.
save_through_socket() {  # STAGE
  local project_id
  SAVE_STAGE="$1"
  SAVE_HOST="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage "$SAVE_STAGE" --key host | tr -d '"')"
  SAVE_PORTFOLIO="$("$PY" -I "$REPORT_PY" portfolio --project "$CANARY/project.json" --stage "$SAVE_STAGE")"
  SAVE_ACTOR="$(env -i PATH="$PATH" HOME="$HOME" PYTHONPATH="$STAGE_ROOT/tree/src" "$PY" -c \
    'import sys; from pathlib import Path; from otto.hostctl import config; print(config.load(Path(sys.argv[1]))["owner"]["actor"])' "$STAGE_ROOT/home")"
  # The owner admits the host, the same admit-host the host fixture runs; that names the portfolio the saves go to.
  cold_client service admit-host --host "$SAVE_HOST" > "$RAW/admission.json" 2>> "$RAW/save-errors.txt" \
    || echo '{"outcome": "unavailable"}' > "$RAW/admission.json"
  ADMITTED=""
  "$PY" -I "$REPORT_PY" admission --raw "$RAW" --project "$CANARY/project.json" --stage "$SAVE_STAGE" && ADMITTED=1
  "$PY" -I "$REPORT_PY" store --store "$STAGE_ROOT/store/staging.store" --admission "$RAW/admission.json" --out "$RAW/store-before-saves.json"
  save_step create ""
  "$PY" -I "$REPORT_PY" store --store "$STAGE_ROOT/store/staging.store" --refs "$RAW/save-create.json" --out "$RAW/store-after-create.json"
  project_ref="$("$PY" -I -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1])).get("project_ref") or {}, separators=(",", ":")))' \
    "$RAW/save-create.json" 2>/dev/null || true)"
  cold_client portfolio --portfolio "$SAVE_PORTFOLIO" show project --project-ref "$project_ref" --actor "$SAVE_ACTOR" > "$RAW/read-back.json" 2>> "$RAW/save-errors.txt" \
    || echo '{"outcome": "unavailable"}' > "$RAW/read-back.json"
  save_step edit "$RAW/save-create.json"
  "$PY" -I "$REPORT_PY" store --store "$STAGE_ROOT/store/staging.store" --refs "$RAW/save-create.json" \
    --refs "$RAW/save-edit.json" --out "$RAW/store-after-edit.json"
  save_step stale "$RAW/save-create.json"
  "$PY" -I "$REPORT_PY" store --store "$STAGE_ROOT/store/staging.store" --refs "$RAW/save-edit.json" --out "$RAW/store-after-stale.json"
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
  local task=$1 t rc=0 check_rc=0 conflict_task=0 merge_rc=0
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

  conflict_task="$($PY -I -c 'import json,sys; print(int(json.load(open(sys.argv[1]))["tasks"][sys.argv[2]].get("landing_conflict", False)))' "$CANARY/project.json" "$task")"
  if [ "$check_rc" -eq 0 ] && [ "$conflict_task" -eq 1 ] && ! has_fault conflict; then
    # Both branches change the same canary line. The fake worker's check is green, so only landing can refuse it.
    "$PY" -I -c 'from pathlib import Path; import sys; p=Path(sys.argv[1]) / "toy/mathx.py"; s=p.read_text(); q=chr(34); p.write_text(s.replace("STAGE4_CONFLICT_SLOT = " + q + "base" + q, "STAGE4_CONFLICT_SLOT = " + q + "owner" + q, 1))' "$CANON"
    git -C "$CANON" add toy/mathx.py
    git -C "$CANON" -c user.name=perch-canary -c user.email=perch-canary@localhost commit -q -m "Canary concurrent edit"
  fi

  if [ "$check_rc" -eq 0 ] && git -C "$CANON" -c user.name=perch-canary -c user.email=perch-canary@localhost \
      merge -q --no-ff -m "Land $task" "lab/$task"; then
    event landed "$task" "$(git -C "$CANON" rev-parse --short HEAD)"
  else
    merge_rc=$?
    if [ "$check_rc" -eq 0 ] && [ "$conflict_task" -eq 1 ] && [ "$merge_rc" -ne 0 ]; then
      event landing-conflict "$task" "merge rc $merge_rc"
      git -C "$CANON" merge --abort >/dev/null 2>&1 || true
      event refused "$task" "landing conflict"
    else
      event refused "$task" "check rc $check_rc"
    fi
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
  local stage=$1 stamp run task first="" last="" host setup_rc dispatch_rc
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  run="$OUT_ROOT/$stage/$stamp"
  RAW="$run/raw"
  CANARY_DIR="$STAGE_ROOT/perch-canary/$stage-$stamp"
  CANON="$CANARY_DIR/canon"
  LABS="$CANARY_DIR/labs"
  mkdir -p "$RAW"
  if [ "$stage" = 2 ]; then
    "$PY" -I "$REPORT_PY" stage2-owner-labs --root "$CANON.otto-labs" \
      --out "$RAW/stage2-owner-labs-before.json"
  fi
  mkdir -p "$LABS" "$CANARY_DIR/ops"
  : > "$RAW/events.tsv"; : > "$RAW/started.tsv"; : > "$RAW/durations.tsv"
  STARTED="$(now)"
  RESTART_RC=0

  if ! "$PY" -I "$REPORT_PY" census --out "$RAW/census.before.txt" --stage-root "$STAGE_ROOT" --fail-workers; then
    echo "perch: worker or perch-fake-claude process is already alive in a staging root" >&2
    return 1
  fi
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
  if [ "$stage" = 2 ]; then
    t="$(date +%s)"; make_canon; phase canary-setup "" "$t"
  fi
  restart_staging "$stage"
  STAGING_SHA="$(sed -n 's/.*"sha": "\([0-9a-f]*\)".*/\1/p' "$STAGE_ROOT/run/staging.json" 2>/dev/null | head -n 1 || true)"
  CANON_MAIN_SHA="$(git -C "$OTTO_REPO" rev-parse --short -q --verify 'canon/main^{commit}' || echo none)"

  if [ "$stage" != 2 ]; then
    t="$(date +%s)"; make_canon; phase canary-setup "" "$t"
  fi

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
      save-through-socket)
        if [ "$RESTART_RC" -eq 0 ]; then
          save_through_socket "$stage"
          "$PY" -I "$REPORT_PY" note --raw "$RAW" --key save-through-socket --value ran
        else
          "$PY" -I "$REPORT_PY" note --raw "$RAW" --key save-through-socket --value "skipped: staging did not start"
        fi ;;
      admit-and-dispatch)
        # Stage 2 is a proof gate: never turn missing prerequisites into a skip. Record why
        # execution could not proceed, and let the stage-2 assertions fail with that evidence.
        if [ "$RESTART_RC" -ne 0 ]; then
          "$PY" -I "$REPORT_PY" note --raw "$RAW" --key admit-and-dispatch --value "failed: staging did not start (rc $RESTART_RC)"
        elif [ "$("$PY" -I "$REPORT_PY" composefleet --stage-root "$STAGE_ROOT")" != true ]; then
          "$PY" -I "$REPORT_PY" note --raw "$RAW" --key admit-and-dispatch --value "failed: COMPOSEFLEET prerequisites are absent from the staging tree"
        elif stage2_setup && { [ -z "$FAKE" ] || stage2_prepare_disturb_project; }; then
          host="$($PY -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key host | tr -d '\"')"
          if stage2_admit_tasks C && stage2_edit_C && stage2_admit_tasks "A B"; then
            if stage2_finish_C && stage2_dispatch_tasks && \
                { [ -z "$FAKE" ] || stage2_run_disturbances "$host"; }; then
              if [ -f "$STAGE_ROOT/home/run/operator-admission.jsonl" ]; then
                cp "$STAGE_ROOT/home/run/operator-admission.jsonl" "$RAW/stage2-operator-admission.jsonl"
              fi
              "$PY" -I "$REPORT_PY" note --raw "$RAW" --key admit-and-dispatch --value ran
              host="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key host | tr -d '\"')"
              stage2_host_client --host "$host" project status --project perch-stage2 > "$RAW/stage2-dispatch-status.json" 2>> "$RAW/stage2-setup-errors.txt" || true
              cold_client service status > "$RAW/stage2-owner-status.json" 2>> "$RAW/stage2-setup-errors.txt" || true
              "$PY" -I "$REPORT_PY" store --store "$STAGE_ROOT/store/staging.store" --out "$RAW/stage2-store-after.json"
              stage2_capture_fds after || true
              if [ -n "$FAKE" ] && ! stage2_disturb_restart_task "$host"; then
                "$PY" -I "$REPORT_PY" note --raw "$RAW" --key admit-and-dispatch \
                    --value "failed: owner restart disturbance did not settle from captured owner evidence"
              fi
            else
              if [ -f "$STAGE_ROOT/home/run/operator-admission.jsonl" ]; then
                cp "$STAGE_ROOT/home/run/operator-admission.jsonl" "$RAW/stage2-operator-admission.jsonl"
              fi
              "$PY" -I "$REPORT_PY" note --raw "$RAW" --key admit-and-dispatch --value "failed: admitted tasks did not dispatch and settle"
            fi
          else
            if [ -f "$STAGE_ROOT/home/run/operator-admission.jsonl" ]; then
              cp "$STAGE_ROOT/home/run/operator-admission.jsonl" "$RAW/stage2-operator-admission.jsonl"
            fi
            "$PY" -I "$REPORT_PY" note --raw "$RAW" --key admit-and-dispatch --value "failed: operator task admission did not complete"
          fi
        else
          setup_rc=$?
          "$PY" -I "$REPORT_PY" note --raw "$RAW" --key admit-and-dispatch --value "failed: stage-2 owner setup failed (rc $setup_rc)"
        fi ;;
      landing-conflict)
        # The task's normal worker/check/landing flow seeds the conflict after a passing check.
        # This observation names the harness mode; it is not a product-owned real-worker proof.
        if [ -n "$FAKE" ]; then
          "$PY" -I "$REPORT_PY" note --raw "$RAW" --key landing-conflict --value "fake-harness"
        else
          "$PY" -I "$REPORT_PY" note --raw "$RAW" --key landing-conflict --value "owner-managed-landing-conflict-not-wired"
        fi ;;
      owner-driven-canary)
        if [ -n "$FAKE" ]; then
          "$PY" -I "$REPORT_PY" note --raw "$RAW" --key owner-driven-canary --value "fake-harness-only"
        else
          "$PY" -I "$REPORT_PY" note --raw "$RAW" --key owner-driven-canary --value "owner-project-activation-and-dispatch-not-wired"
        fi ;;
      *) die "perch.sh has no scenario called $scenario" ;;
    esac
  done

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
  if [ "$stage" != 2 ] && { [ "$stage" != 4 ] || [ -n "$FAKE" ]; }; then
    for task in $("$PY" -I "$REPORT_PY" tasks --project "$CANARY/project.json" --stage "$stage"); do
      run_task "$task" "$([ "$task" = "$first" ] && echo yes || echo no)" "$([ "$task" = "$last" ] && echo yes || echo no)"
    done
  fi
  for pid in $HOLD_POOL; do stop_hold "$pid"; done
  HOLD_POOL=""
  if [ -n "$RUN_LIFECYCLE" ]; then lifecycle_recover; fi

  if has_fault leak; then
    # A worker that outlives the run: the census after must find it.
    HOLD_LEAK="$(hold_worker "$LABS/$last" "$last")"
  fi

  if [ -f "$STAGE_ROOT/home/shared-host/capacity-process-groups.json" ]; then
    cp "$STAGE_ROOT/home/shared-host/capacity-process-groups.json" "$RAW/recorded-process-groups.json"
  else
    printf '{}\n' > "$RAW/recorded-process-groups.json"
  fi

  t="$(date +%s)"
  bash "$STAGING" down < /dev/null > "$RAW/staging-down.log" 2>&1 || true
  phase staging-down "" "$t"
  kill -- "-$SAMPLER" 2>/dev/null || true; wait "$SAMPLER" 2>/dev/null || true
  # Its group, a status call it may still be running included, must be gone before the census reads the root.
  for i in $(seq 1 50); do kill -0 -- "-$SAMPLER" 2>/dev/null || break; sleep 0.2; done
  SAMPLER=""
  if [ -n "$RUN_LIFECYCLE" ]; then status_to "$RAW/status-stopped.json"; fi
  "$PY" -I "$REPORT_PY" census --out "$RAW/census.after.txt" --stage-root "$STAGE_ROOT" \
    --groups-file "$RAW/recorded-process-groups.json"
  if [ -n "$HOLD_LEAK" ]; then kill "$HOLD_LEAK" 2>/dev/null || true; wait "$HOLD_LEAK" 2>/dev/null || true; HOLD_LEAK=""; fi

  "$PY" -I "$REPORT_PY" snapshot --canon "$CANON" --labs "$LABS" --out "$RAW/leftovers.txt"
  if [ "$stage" = 2 ]; then
    "$PY" -I "$REPORT_PY" stage2-owner-labs --root "$CANON.otto-labs" \
      --out "$RAW/stage2-owner-labs-after.json"
  fi
  "$PY" -I "$REPORT_PY" timeline --src "$STAGE_ROOT/tree/src" --store "$STAGE_ROOT/store/staging.store" \
    --authority "$AUTHORITY" --out "$RAW/timeline.json" \
    || printf '{"error": "the Store timeline read failed; see the run log", "store_events": 0, "tasks": []}\n' > "$RAW/timeline.json"
  if [ "$stage" = 2 ]; then
    "$PY" -I "$HERE/perch_stage2_evidence.py" --src "$STAGE_ROOT/tree/src" \
      --store "$STAGE_ROOT/store/staging.store" --authority "$AUTHORITY" \
      --out "$RAW/stage2-store-events.json" || true
  fi

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
  INIT_ARGS=()
  [ -z "$FAKE" ] || INIT_ARGS+=(--fake)
  "$PY" -I "$REPORT_PY" init --raw "$RAW" --project "$CANARY/project.json" --stage "$stage" ${INIT_ARGS[@]+"${INIT_ARGS[@]}"} \
    --faults "$FAULTS" --staging-restart "$RESTART_RC" --staging-sha "${STAGING_SHA:-none}" \
    --canon-main-sha "$CANON_MAIN_SHA" --started-at "$STARTED" --stage-root "$STAGE_ROOT"
  if [ "$stage" = 2 ]; then
    "$PY" -I "$REPORT_PY" stage2-observations --raw "$RAW"
  fi
  for kind in census store restart admit canary readback typed edit nothing revision history stale growth stage2_scenario stage2_canary stage2_review admission_presence admit_order unadmitted reserve worker_kill store_snapshot stage2_census conflict owner; do
    # A fault whose observation this run does not have is named in seeded.txt, not left to look like a clean run.
    if has_fault "$kind"; then
      "$PY" -I "$REPORT_PY" seed --raw "$RAW" --fault "$kind" \
        || printf 'seeded %s not applied: this run has no such observation\n' "$kind" >> "$RAW/seeded.txt"
    fi
  done
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
# Stage 1 is owner-lane save/read only and has no worker tasks; it runs without --fake.
for s in $STAGES; do
  [ -n "$FAKE" ] || [ "$s" = 0 ] || [ "$s" = 1 ] || [ "$s" = 2 ] || die "stage $s needs a real worker, which is not built yet"
done
RC=0
for s in $STAGES; do
  run_stage "$s"
  [ "$STAGE_RC" -eq 0 ] || RC=1
done
PERCH_FINISHED=1
exit "$RC"
