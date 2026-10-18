#!/bin/bash
# Land finished tasks onto canon/main through the gate (RUNBOOK section 4): rebase the lab,
# check placement (D14) and changed test expectations (D19), run the check, sweep the tests the
# task touches (twice each) against a BASE baseline (a new failure is re-run alone, paired with
# BASE, before it refuses; flaky ones are listed in $OPS_DIR/flaky.txt), merge --no-ff, push to $GIT_REMOTE,
# remove the lab and branch. One landing at a time. Every step is logged to
# $RUNS_DIR/TASK/land.log. A gate failure before the merge leaves canon/main unchanged.
#   land.sh TASK [--title TEXT] [--check CMD] [--d19 FILE]
#   land.sh --batch TASK [TASK ...] [--d19 TASK=FILE]   (at most eight tasks)
# The check is the brief's line "Check command: `...`" unless --check is given. The title
# is the brief's "Title:" line unless --title is given, and falls back to TASK.
# Exit 4: existing test expectations changed and no --d19 decision was given.
# The last line printed is always "LAND RESULT: landed <sha>", "LAND RESULT: d19" or
# "LAND RESULT: refused <reason>", so a caller that started it detached can poll for it.
set -euo pipefail
. "$(dirname "$0")/common.sh"
REASON=""
LOCKED=""
LANDED=""
LAND_TMPDIR=""
LAND_CANDIDATE=""
LEASE_PARENT_DONE=""
LEASE_MARKER_DIR=""
LEASE_PID=""
die() { REASON="$*"; echo "error: $*" >&2; exit 1; }
finish() {
  local rc=$?
  [ -z "$LEASE_MARKER_DIR" ] || rm -rf "$LEASE_MARKER_DIR"
  [ -z "$LAND_CANDIDATE" ] || git -C "$OTTO_REPO" worktree remove --force "$LAND_CANDIDATE" >/dev/null 2>&1 || true
  [ -z "$LOCKED" ] || rmdir "$OPS_DIR/land.lock" 2>/dev/null || true
  [ -z "$LAND_TMPDIR" ] || rm -rf "$LAND_TMPDIR"
  # The leased child owns its result once it has started. If acquisition failed before that point,
  # this parent emits the same final result line as every other refusal.
  if [ -n "$LEASE_PARENT_DONE" ]; then return "$rc"; fi
  # "landed" means pushed, whatever the exit status: a run stopped by a signal can end with status 0,
  # and a cleanup failure after the push doesn't undo the landing.
  if [ -n "$LANDED" ]; then echo "LAND RESULT: landed $LANDED"; return; fi
  case "$rc" in
    4) echo "LAND RESULT: d19" ;;
    *) echo "LAND RESULT: refused ${REASON:-ended before the merge was pushed (exit $rc)}" ;;
  esac
  return "$rc"
}
trap finish EXIT
trap 'REASON="interrupted by a signal; canon/main unchanged unless the log says pushed"; exit 143' TERM INT HUP
lease_signal() {
  local sig="$1" forward_sig="$1"
  [ "$sig" != HUP ] || forward_sig=TERM
  REASON="interrupted by a signal; canon/main unchanged unless the log says pushed"
  if [ -n "$LEASE_PID" ]; then
    kill -"$forward_sig" "$LEASE_PID" 2>/dev/null || true
    wait "$LEASE_PID" 2>/dev/null || true
    [ -f "$LEASE_MARKER_DIR/started" ] && LEASE_PARENT_DONE=1
  fi
  exit 143
}

BATCH=""
TASKS=()
SCRIPT_ARGS=("$@")
TITLE=""
CHECK=""
D19=""
if [ "${1:-}" = --batch ]; then
  BATCH=1; shift
  D19_ARGS=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --d19) [ $# -ge 2 ] || die "--d19 needs TASK=FILE"; D19_ARGS+=("$2"); shift 2 ;;
      --*) die "unknown batch argument: $1" ;;
      *) valid_task "$1" || die "invalid batch task: $1"; TASKS+=("$1"); shift ;;
    esac
  done
  [ "${#TASKS[@]}" -ge 1 ] && [ "${#TASKS[@]}" -le 8 ] || die "--batch needs one to eight tasks"
  [ "$(printf '%s\n' "${TASKS[@]}" | sort -u | wc -l | tr -d ' ')" -eq "${#TASKS[@]}" ] || die "batch tasks must be distinct"
else
  valid_task "${1:-}" || die "usage: land.sh TASK [--title TEXT] [--check CMD] [--d19 FILE]"
  TASKS=("$1"); shift
  while [ $# -gt 0 ]; do
    case "$1" in
      --title) TITLE="${2:-}"; shift 2 ;;
      --check) CHECK="${2:-}"; shift 2 ;;
      --d19) D19="${2:-}"; shift 2 ;;
      *) die "unknown argument: $1" ;;
    esac
  done
fi
TASK="${TASKS[0]}"
if [ "${OTTO_LAND_LEASED:-}" != 1 ]; then
  GATE_WEIGHT="${OTTO_GATE_JOBS:-2}"
  case "$GATE_WEIGHT" in ''|*[!0-9]*) die "OTTO_GATE_JOBS must be a positive integer (got: $GATE_WEIGHT)" ;; esac
  [ "$GATE_WEIGHT" -gt 0 ] || die "OTTO_GATE_JOBS must be a positive integer (got: $GATE_WEIGHT)"
  LEASE_MARKER_DIR="$(mktemp -d /tmp/land-lease.XXXXXX)" || die "could not create a lease marker"
  trap 'lease_signal TERM' TERM
  trap 'lease_signal INT' INT
  trap 'lease_signal HUP' HUP
  "$HEAVY" --weight "$GATE_WEIGHT" --purpose "$TASK land gate" -- \
      env OTTO_LAND_LEASED=1 OTTO_LAND_CHILD_MARKER="$LEASE_MARKER_DIR/started" \
      bash "$0" "${SCRIPT_ARGS[@]}" &
  LEASE_PID=$!
  if wait "$LEASE_PID"; then
    lease_rc=0
  else
    lease_rc=$?
  fi
  LEASE_PID=""
  if [ -f "$LEASE_MARKER_DIR/started" ]; then
    LEASE_PARENT_DONE=1
  else
    REASON="heavy lease failed before the gate started (exit $lease_rc)"
    [ "$lease_rc" -ne 0 ] || lease_rc=1
  fi
  exit "$lease_rc"
fi
[ -z "${OTTO_LAND_CHILD_MARKER:-}" ] || : > "$OTTO_LAND_CHILD_MARKER"
LAB="$LABS_DIR/$TASK"
RUN="$RUNS_DIR/$TASK"
BRANCH="lab/$TASK"
for task in "${TASKS[@]}"; do
  task_lab="$LABS_DIR/$task"
  [ -d "$task_lab" ] || die "no lab at $task_lab"
  [ -f "$task_lab/.brief.md" ] || die "no brief at $task_lab/.brief.md"
  git -C "$OTTO_REPO" show-ref --verify --quiet "refs/heads/lab/$task" || die "no branch lab/$task"
  "$PY" -I "$HERE/workers.py" check --file "$WORKERS_JSON" --task "$task" \
    || die "land $task after its worker exits"
  if [ -n "$(uncommitted_work "$task_lab")" ]; then
    uncommitted_work "$task_lab" >&2
    die "lab $task_lab has uncommitted work; the worker must commit it"
  fi
done
[ "$(git -C "$OTTO_REPO" symbolic-ref --short HEAD)" = canon/main ] \
  || die "$OTTO_REPO must have canon/main checked out"
[ -z "$(git -C "$OTTO_REPO" status --porcelain --untracked-files=no)" ] \
  || die "$OTTO_REPO has uncommitted changes"
CHECKS=(); TITLES=(); D19S=()
for task in "${TASKS[@]}"; do
  task_lab="$LABS_DIR/$task"
  task_check="$CHECK"
  if [ -z "$task_check" ]; then
  CHECK_RAW="$(brief_field "$task_lab" 'Check command')"
  CHECK_LINE="$(awk '/^[*]*Check command:/ { print NR; exit }' "$task_lab/.brief.md")"
  if [[ "$CHECK_RAW" == \`*\`* ]]; then
    task_check="${CHECK_RAW#\`}"
    task_check="${task_check%%\`*}"
  fi
  if [ -n "$task_check" ] && "$PY" - "$task_check" <<'PY'
import re
import sys

raise SystemExit(0 if re.search(r"<[^>]*>", sys.argv[1]) else 1)
PY
  then
    die "$task: Check command on brief line ${CHECK_LINE:-unknown} contains a placeholder; fill it in before landing"
  fi
  fi
  [ -n "$task_check" ] || die "no backticked check command: add a 'Check command: \`...\`' line to the brief, or pass --check"
  CHECKS+=("$task_check")
  task_title="$TITLE"
  [ -n "$task_title" ] || task_title="$(brief_field "$task_lab" 'Title')"
  TITLES+=("${task_title:-$task}")
  task_d19="$D19"
  if [ -n "$BATCH" ]; then
    task_d19=""
    for arg in "${D19_ARGS[@]-}"; do
      case "$arg" in "$task="*) task_d19="${arg#*=}" ;; esac
    done
    if [ -z "$task_d19" ] && [ -f "$OPS_DIR/reviews/D19-$task.md" ]; then
      task_d19="$OPS_DIR/reviews/D19-$task.md"
    fi
  fi
  D19S+=("$task_d19")
done
CHECK="${CHECKS[0]}"; TITLE="${TITLES[0]}"; D19="${D19S[0]}"

LOGS=()
for task in "${TASKS[@]}"; do
  mkdir -p "$RUNS_DIR/$task"
  LOGS+=("$RUNS_DIR/$task/land.log")
done
mkdir -p "$OPS_DIR"
mkdir "$OPS_DIR/land.lock" 2>/dev/null || die "another landing is running ($OPS_DIR/land.lock); wait for it"
LOCKED=1
# Give this landing a short, private TMPDIR so staging sockets stay within Unix socket limits and
# the owner census below can attribute leftovers to this run alone.
LAND_TMPDIR="$(mktemp -d /tmp/l.XXXXXX)" || die "could not create a private temporary root"
TMPDIR="$LAND_TMPDIR"
export TMPDIR
# The staging tests root themselves here when it is set (outside the gate, macOS's own TMPDIR is too
# long for the 100-byte socket limit, so they fall back to /tmp).
OTTO_LAND_TMPDIR="$LAND_TMPDIR"
export OTTO_LAND_TMPDIR
LOG="$RUN/land.log"
log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "${LOGS[@]}"; }
fail() { REASON="$*"; log "FAIL: $*"; echo "gate failed: $* (log: $LOG)" >&2; exit 1; }

BASE="$(git -C "$OTTO_REPO" rev-parse canon/main)"
gitl() { git -C "$OTTO_REPO" "$@"; }
if [ -n "$BATCH" ]; then
  log "land batch ${TASKS[*]}: BASE $BASE"
  # Pytest walks parent directories while choosing its root; a checkout under /tmp would cross
  # unrelated private entries there. Keep the candidate beside the labs and clean it in finish.
  LAND_CANDIDATE="$LABS_DIR/_batch-$$"
  gitl worktree add --detach --quiet "$LAND_CANDIDATE" "$BASE" || fail "cannot create batch candidate"
else
  log "land $TASK: BASE $BASE"
fi

ACCEPTED=(); ACCEPTED_INDEX=()
textual_conflicts() {  # WORKTREE newline-separated paths
  local root="$1" paths="$2" path
  [ -n "$paths" ] || return 1
  while IFS= read -r path; do
    [ -f "$root/$path" ] && grep -q '^<<<<<<< ' "$root/$path" || return 1
  done <<< "$paths"
}
for i in "${!TASKS[@]}"; do
  TASK="${TASKS[$i]}"; LAB="$LABS_DIR/$TASK"; BRANCH="lab/$TASK"
  CHECK="${CHECKS[$i]}"; TITLE="${TITLES[$i]}"; D19="${D19S[$i]}"
  echo "rebasing $BRANCH onto canon/main ($(gitl rev-parse --short canon/main))"
  if ! git -C "$LAB" rebase --quiet canon/main; then
    conflicts="$(git -C "$LAB" diff --name-only --diff-filter=U)"
    textual=""; textual_conflicts "$LAB" "$conflicts" && textual=1
    git -C "$LAB" rebase --abort || true
    if [ -n "$BATCH" ] && [ -n "$textual" ]; then
      log "DROP $TASK: textual conflict while rebasing onto canon/main; task stays in its lab"
      continue
    fi
    die "rebase onto canon/main conflicts; resume the worker's session with the conflict"
  fi
  log "tested commit $(git -C "$LAB" rev-parse HEAD) (the lab tip after the rebase; the merge's tree)"

# Cheap checks first, so an exit 4 or a D14 refusal costs seconds, not a sweep.
# placement (D14)
read -r HZ_ADD HZ_DEL OT_ADD OT_DEL <<< "$(gitl diff --numstat "$BASE...$BRANCH" | awk '
  $1 ~ /^[0-9]+$/ { if ($3 ~ /^src\/herzchen\//) { ha += $1; hd += $2 } else if ($3 ~ /^src\/otto\//) { oa += $1; od += $2 } }
  END { print ha+0, hd+0, oa+0, od+0 }')"
LAYER="$(brief_field "$LAB" Layer)"
log "placement: src/herzchen +$HZ_ADD -$HZ_DEL; src/otto +$OT_ADD -$OT_DEL; Layer: ${LAYER:-none}"
case "$LAYER" in  # the Layer's leading word names it ("Otto … nothing in src/herzchen" is Otto)
  [Hh]erzchen*) if [ "$OT_ADD" -gt 0 ] && [ "$HZ_ADD" -eq 0 ]; then
    fail "D14: Layer says Herzchen but the task added $OT_ADD lines under src/otto and none under src/herzchen"; fi ;;
esac

# existing tests (D19)
D19_FILES=""
for f in $(gitl diff --name-only --diff-filter=M "$BASE...$BRANCH" -- 'tests/*.py'); do
  if gitl diff -U0 "$BASE...$BRANCH" -- "$f" | grep -E '^-[^-]' | grep -q -E 'assert|pytest\.raises'; then
    D19_FILES="$D19_FILES $f"
  fi
done
if [ -n "$D19_FILES" ]; then
  D19_FILES="${D19_FILES# }"
  if [ -z "$D19" ]; then
    log "D19: existing test expectations changed in $D19_FILES"
    echo "D19: existing test expectations changed in $D19_FILES; write ops/reviews/D19-$TASK.brief.md and run ops/launch_review.sh D19-$TASK opus, then re-run land.sh $TASK --d19 ops/reviews/D19-$TASK.md" >&2
    exit 4
  fi
  [ -f "$D19" ] || D19="$(dirname "$OPS_DIR")/$D19"
  [ -f "$D19" ] || fail "D19 decision file not found: $D19"
  decision_names_file() {  # DECISION PATH
    "$PY" - "$1" "$2" <<'PY'
from pathlib import Path
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
path = sys.argv[2]
start = 0
while True:
    index = text.find(path, start)
    if index < 0:
        raise SystemExit(1)
    end = index + len(path)
    token_chars = lambda c: c.isalnum() or c in "_./-"
    if (index == 0 or not token_chars(text[index - 1])) and (end == len(text) or not token_chars(text[end])):
        raise SystemExit(0)
    start = index + 1
PY
  }
  D19_MISSING=""
  for f in $D19_FILES; do
    # Require the complete path as a token. In particular, test_a.py must not be
    # covered by test_a.pyx or test_a_extra.py in the decision text.
    if ! decision_names_file "$D19" "$f"; then
      D19_MISSING="$D19_MISSING $f"
    fi
  done
  if [ -n "$D19_MISSING" ]; then
    D19_MISSING="${D19_MISSING# }"
    # The decision is the orchestrator's, not the worker's: stop as a missing decision does (exit 4), so
    # the manager asks the orchestrator instead of resuming the worker (TOOLING20, 17 Oct).
    log "D19: decision does not name changed test file(s): $D19_MISSING ($D19)"
    echo "D19: $D19 does not name changed test file(s): $D19_MISSING; extend the decision, then re-run land.sh $TASK --d19 $D19" >&2
    exit 4
  fi
  VERDICT=""
  if VERDICT="$("$PY" - "$D19" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
for line in text.splitlines():
    if re.match(r"^\s*Decision:", line):
        match = re.match(r"^\s*Decision:\s*(LAND|SEND BACK)(?:\s|$)", line)
        if match:
            print(match.group(1))
        break
PY
  )"; then
    :
  fi
  case "$VERDICT" in
    "SEND BACK") fail "D19: review says SEND BACK ($D19)" ;;
    LAND) log "D19: review says LAND ($D19) for $D19_FILES" ;;
    *) fail "D19: missing explicit LAND or SEND BACK Decision in $D19" ;;
  esac
fi
  if [ -n "$BATCH" ]; then
    before_merge="$(git -C "$LAND_CANDIDATE" rev-parse HEAD)"
    if ! git -C "$LAND_CANDIDATE" merge --no-ff -m "Land $TASK: $TITLE" "$BRANCH" > "$RUN/merge-$TASK.log" 2>&1; then
      conflicts="$(git -C "$LAND_CANDIDATE" diff --name-only --diff-filter=U)"
      textual=""; textual_conflicts "$LAND_CANDIDATE" "$conflicts" && textual=1
      git -C "$LAND_CANDIDATE" merge --abort >/dev/null 2>&1 || true
      if [ -n "$textual" ]; then
        log "DROP $TASK: textual conflict with earlier batch task in $(echo "$conflicts" | tr '\n' ' '); task stays in its lab"
        continue
      fi
      fail "cannot merge $TASK into candidate (output: $RUN/merge-$TASK.log)"
    fi
    if [ "$(git -C "$LAND_CANDIDATE" rev-parse HEAD)" = "$before_merge" ]; then
      log "DROP $TASK: its commit is already included in the batch candidate; task stays in its lab"
      continue
    fi
  fi
  ACCEPTED+=("$TASK"); ACCEPTED_INDEX+=("$i")
done
if [ -n "$BATCH" ]; then
  [ "${#ACCEPTED[@]}" -gt 0 ] || fail "all batch tasks had textual conflicts; nothing to land"
  LAB="$LAND_CANDIDATE"
  DIFF_REF="$(git -C "$LAB" rev-parse HEAD)"
  TASK="${ACCEPTED[0]}"; RUN="$RUNS_DIR/$TASK"
  CHECK=""  # each check runs separately; the union sweep must run every selected file twice
  log "tested commit $DIFF_REF (ordered batch candidate: ${ACCEPTED[*]})"
else
  TASK="${TASKS[0]}"; LAB="$LABS_DIR/$TASK"; BRANCH="lab/$TASK"
  CHECK="${CHECKS[0]}"; RUN="$RUNS_DIR/$TASK"; DIFF_REF="$BRANCH"
fi

# ---- gate ----
G="$RUN/.gate"; rm -rf "$G"; mkdir -p "$G"  # dot-folders: portfolio applies skip scratch
if [ -n "$BATCH" ]; then
  : > "$G/task-files.tsv"
  for i in "${ACCEPTED_INDEX[@]}"; do
    task="${TASKS[$i]}"
    gitl diff --name-only "$BASE...lab/$task" -- src ops tests | while IFS= read -r path; do
      printf '%s\t%s\n' "$task" "$path"
    done >> "$G/task-files.tsv"
  done
fi

# Staging owners (`service run`) whose home is under a temporary root, one "pid home" per line.
# A swept test can leave one behind even when its temporary home has no pidfile (TOOLING21, 17 Oct).
temp_owners() {
  "$PY" - "$TMPDIR" <<'PY'
import os
import re
import subprocess
import sys

root = os.path.realpath(sys.argv[1]).rstrip(os.sep) + os.sep
try:
    listing = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], check=True,
                             text=True, capture_output=True).stdout
except (OSError, subprocess.CalledProcessError) as exc:
    print("cannot inspect processes: %s" % exc, file=sys.stderr)
    raise SystemExit(2)
for line in listing.splitlines():
    # Only an orphan counts: a test's owner while its test runs has the test as its parent (another
    # worker's run, 17 Oct); one its test left behind is reparented to launchd (pid 1).
    match = re.match(r"\s*(\d+)\s+1\s+(.*)", line)
    if not match or "service run" not in match.group(2):
        continue
    home_match = re.search(r"--home(?:=|\s+)(\S+)", match.group(2))
    if not home_match:
        continue
    home = os.path.realpath(home_match.group(1))
    if home.startswith(root):
        print("%s %s" % (match.group(1), home))
PY
}
temp_owners > "$G/owners.before" || fail "could not inspect temporary service owners"

# Run one test file in DIR with output to OUT; the last line records pytest's exit status.
run_pytest() {  # DIR FILE OUT
  local rc=0
  ( cd "$1" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src:tests:$HERE" PYTEST_ADDOPTS="-p otto_gate_exit --continue-on-collection-errors" \
      "$PY" -m pytest -q -rfE -p no:cacheprovider "$2" ) > "$3" 2>&1 || rc=$?
  echo "=== exit $rc" >> "$3"
}
# Failing test ids in a run's output; a nonzero exit with no failure line becomes one id.
ids_of() {  # OUT FILE
  local rc; rc="$(sed -n 's/^=== exit //p' "$1" | tail -n 1)"
  sed -n -E 's/^(FAILED|ERROR|SUBFAILED\([^)]*\)) ([^ ]+).*/\2/p' "$1"
  if [ "$rc" != 0 ] && [ "$rc" != 5 ] && ! grep -q -E '^(FAILED|ERROR|SUBFAILED\([^)]*\)) ' "$1"; then echo "$2::exit-$rc"; fi
}

# Build a shell script that runs every top-level &&-joined check part and remembers any failure.
check_script() { "$PY" - "$1" <<'PY'
import sys

command = sys.argv[1]
parts = []
start = 0
quote = None
escaped = False
for index, char in enumerate(command):
    if escaped:
        escaped = False
        continue
    if char == "\\" and quote != "'":
        escaped = True
        continue
    if quote:
        if char == quote:
            quote = None
        continue
    if char in ("'", '"'):
        quote = char
    elif command[index:index + 2] == "&&":
        parts.append(command[start:index].strip())
        start = index + 2
parts.append(command[start:].strip())
print("set +e\nfailed=0")
for part in parts:
    if part:
        print("{\n%s\n}\nrc=$?\nif [ \"$rc\" -ne 0 ]; then failed=1; fi" % part)
print('exit "$failed"')
PY
}

# 0. The task's own check, on the rebased commit (D19, rule 1). Until 15 Oct the gate parsed it and never ran it.
# otto_gate_exit (beside this script): a run is over when pytest has reported, even if a test leaked a thread.
CHECK_FAILED_TASKS=(); CHECK_FAILED_OUTS=(); CHECK_FAILED_COMMANDS=()
for i in "${ACCEPTED_INDEX[@]}"; do
  check_task="${TASKS[$i]}"; task_check="${CHECKS[$i]}"
  check_out="$G/check.txt"
  [ -z "$BATCH" ] || check_out="$G/check-$check_task.txt"
  CHECK_RUN="$(check_script "$task_check")"
  check_failed=""
  ( cd "$LAB" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src:tests:$HERE" PYTEST_ADDOPTS="-p otto_gate_exit --continue-on-collection-errors" \
      bash -c "$CHECK_RUN" ) > "$check_out" 2>&1 || check_failed=1
  CHECK_SKIPPED="$(grep -m1 '^otto-gate: all skipped in ' "$check_out" || true)"
  [ -z "$CHECK_SKIPPED" ] || fail "the task's check has no executed tests: $CHECK_SKIPPED (output: $check_out)"
  if grep -q -E 'no tests ran|Interrupted:' "$check_out" \
      || { ! grep -q -E '[0-9]+ (passed|failed|skipped|xfailed|xpassed)' "$check_out" \
           && { [ -z "$check_failed" ] || grep -q -E '^(ERROR|FAILED|SUBFAILED\([^)]*\)) ' "$check_out"; }; }; then
    fail "the task's check did not complete a test run: $task_check (output: $check_out)"
  fi
  if [ -n "$check_failed" ]; then
    CHECK_FAILED_TASKS+=("$check_task"); CHECK_FAILED_OUTS+=("$check_out"); CHECK_FAILED_COMMANDS+=("$task_check")
  elif [ -n "$BATCH" ]; then
    log "check $check_task passed: $task_check"
  else
    log "check passed: $task_check"
  fi
done

# a. Sweep
CHANGED_CODE="$(gitl diff --name-only "$BASE...$DIFF_REF" -- src ops)"
TESTS_TOUCHED="$(gitl diff --name-only --diff-filter=ACMR "$BASE...$DIFF_REF" -- 'tests/test_*.py' || true)"
TESTS_ADDED="$(gitl diff --name-only --diff-filter=A "$BASE...$DIFF_REF" -- 'tests/test_*.py' || true)"
SWEEP="$( { printf '%s\n' "$CHANGED_CODE" | "$PY" -I -c '
import os, re, sys
lab = sys.argv[1]
src_mods = []
ops_names = []
for line in sys.stdin.read().split():
    if line.startswith("src/") and line.endswith(".py"):
        m = line[len("src/"):-3].replace("/", ".")
        src_mods.append(m[:-9] if m.endswith(".__init__") else m)
    elif line.startswith("ops/"):
        leaf = os.path.basename(line)
        ops_names.append(leaf)
        if leaf.endswith(".py"):
            ops_names.append(leaf[:-3])
pats = []
for m in src_mods:
    parent, _, leaf = m.rpartition(".")
    pats.append(re.compile(r"^\s*(import\s+%s\b|from\s+%s\s+import\b)" % ((re.escape(m),) * 2), re.M))
    if parent:
        pats.append(re.compile(r"^\s*from\s+%s\s+import\b[^\n]*\b%s\b" % (re.escape(parent), re.escape(leaf)), re.M))
for name in ops_names:
    # Bootstrap tests often load scripts by filename or importlib module name rather than import.
    pats.append(re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(name)))
td = os.path.join(lab, "tests")
for f in sorted(os.listdir(td)):
    if f.startswith("test_") and f.endswith(".py"):
        text = open(os.path.join(td, f), encoding="utf-8", errors="replace").read()
        if any(p.search(text) for p in pats):
            print("tests/" + f)
' "$LAB"; printf '%s\n' "$TESTS_TOUCHED" tests/test_herzchen_boundary.py; } | grep . | sort -u)"
log "sweep: $(echo "$SWEEP" | wc -l | tr -d ' ') test files from $(printf '%s\n' "$CHANGED_CODE" | grep -c . || true) changed files"

BASELINE_READY=""
ensure_baseline() {
  [ -z "$BASELINE_READY" ] || return 0
  if [ ! -e "$BASELINE_LAB/.git" ]; then
    mkdir -p "$(dirname "$BASELINE_LAB")"
    gitl worktree add --detach --quiet "$BASELINE_LAB" "$BASE" || fail "cannot create baseline lab $BASELINE_LAB"
  fi
  [ -z "$(git -C "$BASELINE_LAB" status --porcelain --untracked-files=no)" ] \
    || fail "baseline lab $BASELINE_LAB has uncommitted changes; clean it first"
  git -C "$BASELINE_LAB" checkout --quiet --detach "$BASE" || fail "cannot check out $BASE in $BASELINE_LAB"
  BASELINE_READY=1
}
baseline_out() {  # FILE -> path of its cached output on BASE
  local out="$OPS_DIR/.baseline/$BASE/$1.txt"
  if [ ! -f "$out" ]; then
    ensure_baseline
    mkdir -p "$(dirname "$out")"
    run_pytest "$BASELINE_LAB" "$1" "$out.tmp"; mv "$out.tmp" "$out"
  fi
  echo "$out"
}

# A new failing id in a file that exists on BASE is re-run alone, 3 times on the lab and 3 on BASE,
# interleaved so both see the same load. A failure BASE shows too, or one the lab doesn't repeat, is
# flaky: listed in flaky.txt, not refused. Returns 0 only for a failure that reproduces on the lab alone.
failed_run() { local rc; rc="$(sed -n 's/^=== exit //p' "$1" | tail -n 1)"; [ "$rc" != 0 ] && [ "$rc" != 5 ] && [ "$rc" != 4 ]; }
PAIRN=0
reproduces() {  # FILE ID
  local f="$1" id="$2" target="$2" k lab_f=0 base_f=0 p flaky
  case "$id" in *::exit-*) target="$f" ;; esac  # a run that died without a FAILED line: re-run the file
  ensure_baseline
  PAIRN=$((PAIRN + 1)); p="$G/pair-$PAIRN"
  for k in 1 2 3; do
    run_pytest "$LAB" "$target" "$p-lab$k.txt"; ! failed_run "$p-lab$k.txt" || lab_f=$((lab_f + 1))
    run_pytest "$BASELINE_LAB" "$target" "$p-base$k.txt"; ! failed_run "$p-base$k.txt" || base_f=$((base_f + 1))
  done
  flaky="$id lab $lab_f/3 base $base_f/3"
  if [ "$base_f" -gt 0 ]; then log "flaky on BASE too: $id (lab $lab_f/3, base $base_f/3; outputs $p-*.txt)"
  elif [ "$lab_f" -ge 2 ]; then log "NEW failure: $id (reproduced $lab_f/3 alone, BASE 0/3; outputs $p-*.txt)"; return 0
  else log "flaky, not reproduced: $id (lab $lab_f/3, base 0/3; outputs $p-*.txt)"; fi
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $TASK $flaky" >> "$OPS_DIR/flaky.txt"
  return 1
}

# Name each task that changed the failing test or a source file it imports. Shared changed files
# name every contributor; an unowned failure stays unattributed so the manager can split the batch.
owners_of() {  # TEST FILE
  "$PY" - "$LAB/$1" "$1" "$G/task-files.tsv" <<'PY'
from pathlib import Path
import re
import sys

test_path, relative, manifest = sys.argv[1:]
source = Path(test_path).read_text(encoding="utf-8", errors="replace") if Path(test_path).is_file() else ""
owners = []
for row in Path(manifest).read_text().splitlines():
    task, path = row.split("\t", 1)
    match = path == relative
    if path.startswith("src/") and path.endswith(".py"):
        module = path[4:-3].replace("/", ".")
        if module.endswith(".__init__"):
            module = module[:-9]
        parent, _, leaf = module.rpartition(".")
        patterns = [r"^\s*import\s+%s\b" % re.escape(module),
                    r"^\s*from\s+%s\s+import\b" % re.escape(module)]
        if parent:
            patterns.append(r"^\s*from\s+%s\s+import\b[^\n]*\b%s\b" % (re.escape(parent), re.escape(leaf)))
        match |= any(re.search(pattern, source, re.M) for pattern in patterns)
    elif path.startswith("ops/"):
        leaf = Path(path).name
        names = [leaf, leaf[:-3]] if leaf.endswith(".py") else [leaf]
        match |= any(re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(name), source)
                     for name in names)
    if match and task not in owners:
        owners.append(task)
print(" ".join(owners) if owners else "unattributed")
PY
}
record_new() {  # ID
  local id="$1" f owners
  FILE_NEW_IDS="$FILE_NEW_IDS$id"$'\n'
  if [ -n "$BATCH" ]; then
    f="${id%%::*}"
    owners="$(owners_of "$f")"
    log "NEW failure: $id (tasks: $owners)"
    NEW_FAILS="$NEW_FAILS$id [tasks: $owners]"$'\n'
  else
    log "NEW failure: $id"
    NEW_FAILS="$NEW_FAILS$id"$'\n'
  fi
}

# A check that failed only on tests canon fails too (the same ids, red on BASE) is not refused for them:
# they are pre-existing, as in the sweep, and go to canon-reds.txt for REDS. Anything else refuses
# (16 Oct: canon's manager-loop red refused CHANGE, A4 and COMPOSEFLEET until the check was narrowed).
NEW_FAILS=""
FILE_NEW_IDS=""
for i in "${!CHECK_FAILED_TASKS[@]}"; do
  check_task="${CHECK_FAILED_TASKS[$i]}"; check_out="${CHECK_FAILED_OUTS[$i]}"; task_check="${CHECK_FAILED_COMMANDS[$i]}"
  check_ids="$(ids_of "$check_out" check)"
  [ -n "$check_ids" ] || fail "the task's check failed: $task_check (output: $check_out)"
  check_preexisting=""
  for id in $check_ids; do
    f="${id%%::*}"
    if [ -z "$BATCH" ]; then
      case "$id" in *::exit-*) fail "the task's check failed: $task_check (output: $check_out)" ;; esac
      gitl cat-file -e "$BASE:$f" 2>/dev/null || fail "the task's check failed: $id (output: $check_out)"
      ids_of "$(baseline_out "$f")" "$f" | grep -qxF "$id" || fail "the task's check failed: $id (output: $check_out)"
    else
      if gitl cat-file -e "$BASE:$f" 2>/dev/null \
          && ids_of "$(baseline_out "$f")" "$f" | grep -qxF "$id"; then
        :
      else
        record_new "$id"
        continue
      fi
    fi
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $check_task $id (check; also red on BASE)" >> "$OPS_DIR/canon-reds.txt"
    check_preexisting="$check_preexisting $id"
  done
  [ -z "$check_preexisting" ] || log "check passed except failures also red on BASE: ${check_preexisting# } (listed in ops/canon-reds.txt)"
done

# GATEPAR's bounded parallel waves preserve run order within each file. Judge each completed wave
# in sweep order before scheduling another, so a confirmed new failure stops later waves cleanly.
GATE_JOBS="${OTTO_GATE_JOBS:-2}"
case "$GATE_JOBS" in ''|*[!0-9]*) fail "OTTO_GATE_JOBS must be a positive integer (got: $GATE_JOBS)" ;; esac
[ "$GATE_JOBS" -gt 0 ] || fail "OTTO_GATE_JOBS must be a positive integer (got: $GATE_JOBS)"
mkdir -p "$G/sweep"
run_sweep_file() {  # FILE
  local f="$1" dir first n
  dir="$G/sweep/$f"
  mkdir -p "$dir"
  first=1
  case " $CHECK " in *" -k "*|*::*) ;; *" $f "*) first=2 ;; esac
  for n in $(seq "$first" 2); do
    run_pytest "$LAB" "$f" "$dir/run$n.txt"
  done
}
judge_sweep_file() {  # FILE
  local f="$1" first n out ids kept
  FILE_NEW_IDS=""
  : > "$G/lab.ids"
  first=1
  # A file the passing check ran whole (named in it, with no -k or :: selection) has had its first run.
  case " $CHECK " in *" -k "*|*::*) ;; *" $f "*) first=2; log "sweep $f run 1/2: 0 failing (the check's run)" ;; esac
  for n in $(seq "$first" 2); do
    out="$G/sweep/$f/run$n.txt"
    SKIPPED="$(grep -m1 '^otto-gate: all skipped in ' "$out" || true)"
    [ -z "$SKIPPED" ] || fail "sweep $f has no executed tests: $SKIPPED (output: $out)"
    ids="$(ids_of "$out" "$f")"; kept=""
    if [ -n "$ids" ]; then
      printf '%s\n' "$ids" >> "$G/lab.ids"
      kept="$G/fail-$(basename "$f")-run$n.txt"; cp "$out" "$kept"
    fi
    log "sweep $f run $n/2: $(printf '%s' "$ids" | grep -c . || true) failing${kept:+ (output: $kept)}"
  done
  sort -u "$G/lab.ids" -o "$G/lab.ids"
  [ -s "$G/lab.ids" ] || return 0
  if ! gitl cat-file -e "$BASE:$f" 2>/dev/null; then
    # a file the task added has no baseline: all its failures are new
    while IFS= read -r id; do record_new "$id"; done < "$G/lab.ids"
    STOP_NEW=1
    return
  fi
  bo="$(baseline_out "$f")"
  ids_of "$bo" "$f" | sort -u > "$G/base.ids"
  while IFS= read -r id; do
    if grep -qxF -- "$id" "$G/base.ids"; then log "pre-existing failure (also on BASE): $id"
    elif reproduces "$f" "$id"; then record_new "$id"; fi
  done < "$G/lab.ids"
  if [ -n "$FILE_NEW_IDS" ]; then STOP_NEW=1; fi
}
STOP_NEW=""
WAVE_FILES=(); WAVE_PIDS=(); WAVE_COUNT=0
for f in $SWEEP; do
  run_sweep_file "$f" &
  WAVE_FILES+=("$f"); WAVE_PIDS+=("$!")
  WAVE_COUNT=$((WAVE_COUNT + 1))
  if [ "$WAVE_COUNT" -ge "$GATE_JOBS" ]; then
    for pid in "${WAVE_PIDS[@]}"; do wait "$pid" || fail "sweep run phase failed for a worker (pid $pid)"; done
    for wave_file in "${WAVE_FILES[@]}"; do
      judge_sweep_file "$wave_file"
      [ -z "$STOP_NEW" ] || break
    done
    WAVE_FILES=(); WAVE_PIDS=(); WAVE_COUNT=0
    [ -z "$STOP_NEW" ] || break
  fi
done
if [ "$WAVE_COUNT" -gt 0 ]; then
  for pid in "${WAVE_PIDS[@]}"; do wait "$pid" || fail "sweep run phase failed for a worker (pid $pid)"; done
  for wave_file in "${WAVE_FILES[@]}"; do
    judge_sweep_file "$wave_file"
    [ -z "$STOP_NEW" ] || break
  done
fi

# Only an owner that appeared during this landing is its own: one left by something else (another
# session, an earlier run) is logged, not held against this task.
temp_owners > "$G/owners.after" || fail "could not inspect temporary service owners"
NEW_OWNERS="$(grep -vxF -f "$G/owners.before" "$G/owners.after" || true)"
OLD_OWNERS="$(grep -xF -f "$G/owners.before" "$G/owners.after" || true)"
[ -z "$OLD_OWNERS" ] || log "staging owner(s) under a temporary root left before this landing (not its own): $(echo $OLD_OWNERS)"
[ -z "$NEW_OWNERS" ] || fail "orphan service run(s) after sweep: $(echo "$NEW_OWNERS" | sed 's/^/pid /; s/ \// home \//' | tr '\n' ' ')"

[ -z "$NEW_FAILS" ] || fail "new test failures: $(echo "$NEW_FAILS" | grep . | tr '\n' ' ')"

# c. regression tests the task added should fail on BASE
for f in $TESTS_ADDED; do
  ensure_baseline
  mkdir -p "$BASELINE_LAB/$(dirname "$f")"; cp "$LAB/$f" "$BASELINE_LAB/$f"
  run_pytest "$BASELINE_LAB" "$f" "$G/added.txt"; rm -f "$BASELINE_LAB/$f"
  if [ "$(sed -n 's/^=== exit //p' "$G/added.txt" | tail -n 1)" = 0 ]; then
    log "WARN: $f passes on canon/main; the regression test does not fail without the change"
  fi
done

# d. staging hook
# The tested commit's own staging scripts (-f, not -x: they land as 100644, and -x skipped this step
# silently after PERCH landed).
ST="$LAB/ops/bootstrap"
if [ -f "$ST/staging.sh" ] && [ -f "$ST/perch.sh" ]; then
  SHA="$(git -C "$LAB" rev-parse HEAD)"
  # perch restarts staging on OTTO_STAGING_REF itself. Until 16 Oct the gate passed OTTO_COMMIT, which
  # nothing reads, so staging ran BASE (STAGE0 F1); its reports now outlive the lab (F6).
  # Only the stages that have passed gate a landing ($OPS_DIR/stages-gated, default "0 1"). A stage whose
  # scenario can't run yet is the orchestrator's to run, and it must not refuse every landing (17 Oct:
  # PERCH2's stage 2 canary refused PERCH2 itself). The orchestrator adds a stage once it passes.
  GATED="$(cat "$OPS_DIR/stages-gated" 2>/dev/null || echo "0 1")"
  for stage in $GATED; do
    ( cd "$LAB" && OTTO_STAGING_REF="$SHA" PERCH_OUT="$OTTO_REPO/ops/perch" bash "$ST/perch.sh" "$stage" --fake ) \
      >> "$G/staging.log" 2>&1 || fail "perch.sh $stage --fake failed ($G/staging.log)"
  done
  for report in $(sed -n 's/^perch: stage .* report at //p' "$G/staging.log"); do
    grep -q "staging tree sha $SHA" "$report" \
      || fail "staging did not run the tested commit $SHA: $(grep -m1 'staging tree sha' "$report") ($report)"
  done
  log "staging: perch --fake passed on $SHA (reports under $OTTO_REPO/ops/perch)"
else
  log "staging: skipped (STAGE/PERCH not landed)"
fi
if [ -n "$BATCH" ] && [ -n "$(git -C "$LAB" status --porcelain --untracked-files=no)" ]; then
  fail "batch candidate changed during checks or staging; tested commit no longer matches its tree"
fi

# e. remote
git -C "$OTTO_REPO" fetch --quiet "$GIT_REMOTE" || fail "cannot fetch $GIT_REMOTE"
gitl merge-base --is-ancestor "$GIT_REMOTE/main" canon/main \
  || fail "$GIT_REMOTE main has commits canon/main lacks; reconcile first"

# f. merge and push
[ "$(gitl rev-parse canon/main)" = "$BASE" ] \
  || fail "canon/main moved during the gate; run land.sh $TASK again"
if [ -n "$BATCH" ]; then
  gitl merge --ff-only "$DIFF_REF" > "$RUN/merge.log" 2>&1 \
    || fail "candidate fast-forward failed; canon/main unchanged (see $RUN/merge.log)"
else
  if ! gitl merge --no-ff -m "Land $TASK: $TITLE" "$BRANCH" > "$RUN/merge.log" 2>&1; then
    gitl merge --abort 2>/dev/null || true
    fail "merge failed; canon/main unchanged (see $RUN/merge.log)"
  fi
fi
log "merged $(gitl rev-parse --short HEAD)"
if ! gitl push --quiet "$GIT_REMOTE" canon/main:main >> "$RUN/merge.log" 2>&1; then
  if [ -n "$BATCH" ]; then
    # One ref push contains the entire accepted history. A failed push must not leave a local
    # partial landing that a later command might accidentally publish.
    if [ "$(gitl ls-remote "$GIT_REMOTE" refs/heads/main 2>/dev/null | awk '{print $1}')" = "$(gitl rev-parse HEAD)" ]; then
      log "push response failed, but $GIT_REMOTE/main has the complete batch tip"
    else
      gitl reset --hard "$BASE" >> "$RUN/merge.log" 2>&1 || true
      fail "push to $GIT_REMOTE failed; batch canon/main restored to $BASE (see $RUN/merge.log)"
    fi
  else
  REASON="push to $GIT_REMOTE failed; local merge kept at $(gitl rev-parse --short HEAD)"
  log "FAIL: push to $GIT_REMOTE failed; the local merge stays on canon/main (see $RUN/merge.log)"
  echo "push to $GIT_REMOTE failed; local merge kept at $(gitl rev-parse --short HEAD) (log: $LOG)" >&2
  exit 1
  fi
fi
log "pushed canon/main to $GIT_REMOTE/main"
LANDED="$(gitl rev-parse --short HEAD)"

# g. clean up and record
if [ -n "$BATCH" ]; then
  for task in "${ACCEPTED[@]}"; do
    "$HERE/otto-lab.sh" remove "$task" | tee -a "${LOGS[@]}"
  done
else
  "$HERE/otto-lab.sh" remove "$TASK" | tee -a "$LOG"
fi
SHORT="$(gitl diff --shortstat "$BASE" HEAD)"
REMOVED="$(gitl diff --numstat "$BASE" HEAD | awk '{ d += $2 } END { print d+0 }')"
log "net: ${SHORT:-no change}; lines removed: $REMOVED"
if [ -n "$BATCH" ]; then
  echo "landed batch ${ACCEPTED[*]}: $(gitl rev-parse --short HEAD)"
else
  echo "landed $TASK: $(gitl rev-parse --short HEAD) $(gitl log -1 --format=%s)"
fi
