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
# PERCH_FAULT=leak,lab,pool,timeline,staging,status,restart,refuse,store,atrest,census,admit,canary,readback,typed,edit,nothing,revision,history,stale,growth,stage2_scenario,stage2_canary,stage2_review,admission_presence,admit_order,unadmitted,reserve,worker_kill,store_snapshot,stage2_census
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

# Stage 2 uses the same owner CLI setup path as an operator: join the canary host,
# map its disposable repository, register the run bundle, then activate it. Every
# command's raw answer is kept so a failed prerequisite is visible in the report.
stage2_setup() {
  local host bundle rc=0 launcher_args=()
  host="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key host | tr -d '"')"
  bundle="$CANARY_DIR/project"
  "$PY" -I "$REPORT_PY" stage2-bundle --project "$CANARY/project.json" --out "$bundle" > "$RAW/stage2-bundle-path.txt"
  if [ -n "$FAKE" ]; then
    cp "$HERE/perch_fake_claude.py" "$CANARY_DIR/perch-fake-claude"
    chmod 755 "$CANARY_DIR/perch-fake-claude"
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
    "$PY" -I "$REPORT_PY" store --store "$STAGE_ROOT/store/staging.store" --out "$RAW/stage2-store-before.json"
    "$PY" -I "$REPORT_PY" note --raw "$RAW" --key stage2-setup --value ran
  else
    "$PY" -I "$REPORT_PY" note --raw "$RAW" --key stage2-setup --value "failed: owner CLI setup exited $rc"
  fi
  return "$rc"
}

stage2_admit_tasks() {
  local host task ref review_ref rc=0
  host="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key host | tr -d '\"')"
  review_ref="$(cat "$RAW/stage2-review-ref.json")"
  for task in $("$PY" -I "$REPORT_PY" tasks --project "$CANARY/project.json" --stage 2); do
    ref="$("$PY" -I -c 'import json,sys; v=json.load(open(sys.argv[1])); print(json.dumps(v["activation"]["steps"]["tasks"]["task_refs"][sys.argv[2]],separators=(",",":")))' \
      "$RAW/stage2-activation.json" "$task" 2>> "$RAW/stage2-setup-errors.txt")" || return 1
    # The operator command is the sole task admission route. It performs the
    # owner-local presence proof and verifies the selected exact revision.
    if cold_client --host "$host" service admit --task-ref "$ref" \
        --revision "$("$PY" -I -c 'import json,sys; print(json.load(sys.stdin)["revision"])' <<< "$ref")" \
        --review-ref "$review_ref" --request-key "perch-stage2-admit-$task" \
        > "$RAW/stage2-admit-$task.json" 2>> "$RAW/stage2-setup-errors.txt"; then :; else
      rc=$?
      "$PY" -I "$REPORT_PY" note --raw "$RAW" --key "stage2-admit-$task" --value "failed: owner service admit exited $rc"
      return "$rc"
    fi
    if ! "$PY" -I "$REPORT_PY" stage2-admission-check --response "$RAW/stage2-admit-$task.json" \
        --task-ref "$ref" >> "$RAW/stage2-setup-errors.txt" 2>&1; then
      "$PY" -I "$REPORT_PY" note --raw "$RAW" --key "stage2-admit-$task" --value "failed: owner did not admit the exact activated revision"
      return 1
    fi
    "$PY" -I "$REPORT_PY" note --raw "$RAW" --key "stage2-admit-$task" --value ran
    stage2_wait_worker "$host" "$task" || return $?
  done
  return 0
}

# Owner automatic dispatch is the scenario's dispatch path. The admitted host
# reads project status; the staging owner includes a copy of its retained
# worker record in that read. Manager status requires a native manager caller.
stage2_wait_worker() {  # HOST TASK
  local host="$1" task="$2" saw_dispatch="" deadline=$(( $(date +%s) + 180 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if ! stage2_host_client --host "$host" project status --project perch-stage2 \
        > "$RAW/stage2-dispatch-$task.json" 2>> "$RAW/stage2-setup-errors.txt"; then
      echo "owner project status failed while waiting for $task; see stage2-dispatch-$task.json" >> "$RAW/stage2-setup-errors.txt"
      return 1
    fi
    if ! "$PY" -I "$REPORT_PY" stage2-dispatch-no-failure \
          --status "$RAW/stage2-dispatch-$task.json" --task "$task" \
          >> "$RAW/stage2-setup-errors.txt" 2>&1; then return 1; fi
    if "$PY" -I "$REPORT_PY" stage2-dispatch-check \
          --status "$RAW/stage2-dispatch-$task.json" --activation "$RAW/stage2-activation.json" \
          --admission "$RAW/stage2-admit-$task.json" --task "$task" \
          > /dev/null 2>&1; then
      saw_dispatch=1
      cp "$RAW/stage2-dispatch-$task.json" "$RAW/stage2-dispatch-$task-project.json"
      cold_client service status > "$RAW/stage2-owner-$task.json" 2>> "$RAW/stage2-setup-errors.txt" || return $?
      if [ "$task" = C ] || "$PY" -I "$REPORT_PY" stage2-task-complete \
          --project-status "$RAW/stage2-dispatch-$task-project.json" \
          --owner-status "$RAW/stage2-owner-$task.json" --task "$task" > /dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 0.5
  done
  if [ -n "$saw_dispatch" ]; then
    echo "owner dispatched admitted task $task but did not complete it and release capacity in 180 seconds; see stage2-dispatch-$task-project.json and stage2-owner-$task.json" >> "$RAW/stage2-setup-errors.txt"
  else
    echo "owner did not dispatch admitted task $task in 180 seconds; see stage2-dispatch-$task.json" >> "$RAW/stage2-setup-errors.txt"
  fi
  return 1
}

# Probe an unadmitted revision through the same operator path only after the
# three positive admission log lines have been preserved. A nonzero CLI answer
# is evidence; the report also checks its error and the exact requested ref.
stage2_probe_unadmitted() {
  local ref revision review_ref rc=0
  ref="$("$PY" -I -c 'import json,sys; v=json.load(open(sys.argv[1])); ref=dict(v["activation"]["steps"]["tasks"]["task_refs"]["C"]); ref.pop("revision",None); print(json.dumps(ref,separators=(",",":")))' \
    "$RAW/stage2-activation.json")" || return 1
  revision="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key admission | \
    "$PY" -I -c 'import json,sys; print(json.load(sys.stdin)["unadmitted_revision"]["revision"])')" || return 1
  review_ref="$(cat "$RAW/stage2-review-ref.json")"
  "$PY" -I -c 'import json,sys; print(json.dumps({"task_ref":json.loads(sys.argv[1]),"revision":sys.argv[2],"review_ref":json.loads(sys.argv[3])},sort_keys=True))' \
    "$ref" "$revision" "$review_ref" > "$RAW/stage2-unadmitted-request.json"
  cold_client service admit --task-ref "$ref" --revision "$revision" --review-ref "$review_ref" \
    --request-key perch-stage2-unadmitted-probe > "$RAW/stage2-unadmitted-response.json" \
    2>> "$RAW/stage2-setup-errors.txt" || rc=$?
  "$PY" -I "$REPORT_PY" note --raw "$RAW" --key stage2-unadmitted-exit --value "$rc"
  [ "$rc" -ne 0 ]
}

stage2_kill_worker() {
  [ -n "$FAKE" ] || return 0
  local marker="" pid owner deadline=$(( $(date +%s) + 45 )) command
  while [ "$(date +%s)" -lt "$deadline" ]; do
    marker="$(find "$CANARY_DIR/canon.otto-labs" -name .perch-worker-C.pid -print -quit 2>/dev/null || true)"
    [ -z "$marker" ] || break
    sleep 0.25
  done
  [ -n "$marker" ] || { echo "C worker never published its lab PID marker" >> "$RAW/stage2-setup-errors.txt"; return 1; }
  pid="$(cat "$marker")"
  owner="$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["pid"])' "$STAGE_ROOT/run/staging.json")"
  case "$pid" in *[!0-9]*|"") return 1 ;; esac
  [ "$pid" != "$owner" ] || return 1
  command="$(ps -ww -p "$pid" -o command= 2>/dev/null || true)"
  case "$command" in *"$CANARY_DIR/perch-fake-claude"*) ;; *)
    echo "C PID $pid does not name the pinned fake worker: $command" >> "$RAW/stage2-setup-errors.txt"; return 1 ;; esac
  "$PY" -I -c 'import json,sys; print(json.dumps({"pid":int(sys.argv[1]),"owner_pid":int(sys.argv[2]),"marker":sys.argv[3]}))' \
    "$pid" "$owner" "$marker" > "$RAW/stage2-killed-worker.json"
  deadline=$(( $(date +%s) + 30 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    cold_client service status > "$RAW/stage2-capacity-before-kill.json" 2>> "$RAW/stage2-setup-errors.txt" || return 1
    if "$PY" -I "$REPORT_PY" stage2-capacity-held --status "$RAW/stage2-capacity-before-kill.json" \
        > /dev/null 2>&1; then break; fi
    sleep 0.25
  done
  "$PY" -I "$REPORT_PY" stage2-capacity-held --status "$RAW/stage2-capacity-before-kill.json" \
    >> "$RAW/stage2-setup-errors.txt" 2>&1 || return 1
  "$PY" -I "$REPORT_PY" census --out "$RAW/stage2-census-before-kill.txt" --stage-root "$STAGE_ROOT"
  kill -KILL "$pid" || return 1
  deadline=$(( $(date +%s) + 45 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    cold_client service status > "$RAW/stage2-capacity-after-kill.json" 2>> "$RAW/stage2-setup-errors.txt" || return 1
    "$PY" -I "$REPORT_PY" census --out "$RAW/stage2-census-after-kill.txt" --stage-root "$STAGE_ROOT"
    if "$PY" -I "$REPORT_PY" stage2-kill-check --raw "$RAW" > /dev/null 2>&1; then return 0; fi
    sleep 0.25
  done
  echo "C worker kill did not release its owner capacity slot while staging owner survived" >> "$RAW/stage2-setup-errors.txt"
  return 1
}

stage2_cleanup_owner_labs() {
  # These are disposable clones in the canary staging root. The fake owner
  # reports cleanup_pending so artifact capture can finish before teardown.
  case "$CANARY_DIR/canon.otto-labs" in
    "$STAGE_ROOT"/perch-canary/*/canon.otto-labs)
      rm -rf "$CANARY_DIR/canon.otto-labs" ;;
  esac
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
  local stage=$1 stamp run task first="" last="" host setup_rc dispatch_rc
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
        elif stage2_setup; then
          if stage2_admit_tasks; then
            if [ -f "$STAGE_ROOT/home/run/operator-admission.jsonl" ]; then
              cp "$STAGE_ROOT/home/run/operator-admission.jsonl" "$RAW/stage2-operator-admission.jsonl"
            fi
            stage2_kill_worker || true
            "$PY" -I "$REPORT_PY" note --raw "$RAW" --key admit-and-dispatch --value ran
            host="$("$PY" -I "$REPORT_PY" stage --project "$CANARY/project.json" --stage 2 --key host | tr -d '\"')"
            stage2_host_client --host "$host" project status --project perch-stage2 > "$RAW/stage2-dispatch-status.json" 2>> "$RAW/stage2-setup-errors.txt" || true
            cold_client service status > "$RAW/stage2-owner-status.json" 2>> "$RAW/stage2-setup-errors.txt" || true
            "$PY" -I "$REPORT_PY" store --store "$STAGE_ROOT/store/staging.store" --out "$RAW/stage2-store-after.json"
            stage2_probe_unadmitted || true
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
  if [ "$stage" != 2 ]; then
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

  t="$(date +%s)"
  bash "$STAGING" down < /dev/null > "$RAW/staging-down.log" 2>&1 || true
  phase staging-down "" "$t"
  if [ "$stage" = 2 ] && [ -d "$CANON/.git" ]; then stage2_cleanup_owner_labs; fi
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
  if [ "$stage" = 2 ]; then
    "$PY" -I "$REPORT_PY" stage2-observations --raw "$RAW"
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
  for kind in census store restart admit canary readback typed edit nothing revision history stale growth stage2_scenario stage2_canary stage2_review admission_presence admit_order unadmitted reserve worker_kill store_snapshot stage2_census; do
    # A fault whose observation this run does not have is named in seeded.txt, not left to look like a clean run.
    if has_fault "$kind"; then
      "$PY" -I "$REPORT_PY" seed --raw "$RAW" --fault "$kind" \
        || printf 'seeded %s not applied: this run has no such observation\n' "$kind" >> "$RAW/seeded.txt"
    fi
  done

  INIT_ARGS=()
  [ -z "$FAKE" ] || INIT_ARGS+=(--fake)
  "$PY" -I "$REPORT_PY" init --raw "$RAW" --project "$CANARY/project.json" --stage "$stage" ${INIT_ARGS[@]+"${INIT_ARGS[@]}"} \
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
