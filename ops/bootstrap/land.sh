#!/bin/bash
# Land one finished task onto canon/main through the gate (RUNBOOK section 4): rebase the lab,
# check placement (D14) and changed test expectations (D19), run the check, sweep the tests the
# task touches (twice each) against a BASE baseline (a new failure is re-run alone, paired with
# BASE, before it refuses; flaky ones are listed in $OPS_DIR/flaky.txt), merge --no-ff, push to $GIT_REMOTE,
# remove the lab and branch. One landing at a time. Every step is logged to
# $RUNS_DIR/TASK/land.log. A gate failure before the merge leaves canon/main unchanged.
#   land.sh TASK [--title TEXT] [--check CMD] [--d19 FILE]
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
die() { REASON="$*"; echo "error: $*" >&2; exit 1; }
finish() {
  local rc=$?
  [ -z "$LOCKED" ] || rmdir "$OPS_DIR/land.lock" 2>/dev/null || true
  # "landed" means pushed, whatever the exit status: a run stopped by a signal can end with status 0,
  # and a cleanup failure after the push doesn't undo the landing.
  if [ -n "$LANDED" ]; then echo "LAND RESULT: landed $LANDED"; return; fi
  case "$rc" in
    4) echo "LAND RESULT: d19" ;;
    *) echo "LAND RESULT: refused ${REASON:-ended before the merge was pushed (exit $rc)}" ;;
  esac
}
trap finish EXIT
trap 'REASON="interrupted by a signal; canon/main unchanged unless the log says pushed"; exit 143' TERM INT HUP

valid_task "${1:-}" || die "usage: land.sh TASK [--title TEXT] [--check CMD] [--d19 FILE]"
TASK="$1"
shift
TITLE=""
CHECK=""
D19=""
while [ $# -gt 0 ]; do
  case "$1" in
    --title) TITLE="${2:-}"; shift 2 ;;
    --check) CHECK="${2:-}"; shift 2 ;;
    --d19) D19="${2:-}"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done
LAB="$LABS_DIR/$TASK"
RUN="$RUNS_DIR/$TASK"
BRANCH="lab/$TASK"
[ -d "$LAB" ] || die "no lab at $LAB"
[ -f "$LAB/.brief.md" ] || die "no brief at $LAB/.brief.md"
git -C "$OTTO_REPO" show-ref --verify --quiet "refs/heads/$BRANCH" || die "no branch $BRANCH"
"$PY" -I "$HERE/workers.py" check --file "$WORKERS_JSON" --task "$TASK" \
  || die "land $TASK after its worker exits"
[ "$(git -C "$OTTO_REPO" symbolic-ref --short HEAD)" = canon/main ] \
  || die "$OTTO_REPO must have canon/main checked out"
[ -z "$(git -C "$OTTO_REPO" status --porcelain --untracked-files=no)" ] \
  || die "$OTTO_REPO has uncommitted changes"
if [ -n "$(uncommitted_work "$LAB")" ]; then
  uncommitted_work "$LAB" >&2
  die "lab $LAB has uncommitted work; the worker must commit it"
fi

if [ -z "$CHECK" ]; then
  CHECK_RAW="$(brief_field "$LAB" 'Check command')"
  CHECK="${CHECK_RAW#\`}"
  CHECK="${CHECK%\`}"
fi
[ -n "$CHECK" ] || die "no check command: add a 'Check command:' line to the brief, or pass --check"
if [ -z "$TITLE" ]; then
  TITLE="$(brief_field "$LAB" 'Title')"
fi
TITLE="${TITLE:-$TASK}"

mkdir -p "$RUN" "$OPS_DIR"
mkdir "$OPS_DIR/land.lock" 2>/dev/null || die "another landing is running ($OPS_DIR/land.lock); wait for it"
LOCKED=1
LOG="$RUN/land.log"
log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }
fail() { REASON="$*"; log "FAIL: $*"; echo "gate failed: $* (log: $LOG)" >&2; exit 1; }

BASE="$(git -C "$OTTO_REPO" rev-parse canon/main)"
log "land $TASK: BASE $BASE"
echo "rebasing $BRANCH onto canon/main ($(git -C "$OTTO_REPO" rev-parse --short canon/main))"
if ! git -C "$LAB" rebase --quiet canon/main; then
  git -C "$LAB" rebase --abort || true
  die "rebase onto canon/main conflicts; resume the worker's session with the conflict"
fi
log "tested commit $(git -C "$LAB" rev-parse HEAD) (the lab tip after the rebase; the merge's tree)"

gitl() { git -C "$OTTO_REPO" "$@"; }

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
  VERDICT="$(grep -m1 -E 'LAND|SEND BACK' "$D19" || true)"
  case "$VERDICT" in
    *"SEND BACK"*) fail "D19: review says SEND BACK ($D19)" ;;
    *LAND*) log "D19: review says LAND ($D19) for $D19_FILES" ;;
    *) fail "D19: no LAND or SEND BACK in $D19" ;;
  esac
fi

# ---- gate ----
G="$RUN/.gate"; rm -rf "$G"; mkdir -p "$G"  # dot-folders: portfolio applies skip scratch

# Staging owners (`service run`) whose home is under a temporary root, one "pid home" per line.
# A swept test can leave one behind even when its temporary home has no pidfile (TOOLING21, 17 Oct).
temp_owners() {
  "$PY" - "${TMPDIR:-/tmp}" <<'PY'
import os
import re
import subprocess
import sys

roots = []
for candidate in (sys.argv[1], "/tmp", "/private/tmp"):
    if candidate:
        root = os.path.realpath(candidate)
        if root not in roots:
            roots.append(root.rstrip(os.sep) + os.sep)
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
    if any(home.startswith(root) for root in roots):
        print("%s %s" % (match.group(1), home))
PY
}
temp_owners > "$G/owners.before" || fail "could not inspect temporary service owners"

# Run one test file in DIR with output to OUT; the last line records pytest's exit status.
run_pytest() {  # DIR FILE OUT
  local rc=0
  ( cd "$1" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src:tests:$HERE" PYTEST_ADDOPTS="-p otto_gate_exit --continue-on-collection-errors" \
      "$HEAVY" --weight 1 --purpose "$TASK gate" -- \
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
CHECK_RUN="$("$PY" - "$CHECK" <<'PY'
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
)"

# 0. The task's own check, on the rebased commit (D19, rule 1). Until 15 Oct the gate parsed it and never ran it.
# otto_gate_exit (beside this script): a run is over when pytest has reported, even if a test leaked a thread.
( cd "$LAB" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src:tests:$HERE" PYTEST_ADDOPTS="-p otto_gate_exit --continue-on-collection-errors" \
    "$HEAVY" --weight 1 --purpose "$TASK check" -- \
    bash -c "$CHECK_RUN" ) > "$G/check.txt" 2>&1 || CHECK_FAILED=1
if grep -q -E 'no tests ran|Interrupted:' "$G/check.txt" \
    || { ! grep -q -E '[0-9]+ (passed|failed|skipped|xfailed|xpassed)' "$G/check.txt" \
         && { [ -z "${CHECK_FAILED:-}" ] || grep -q -E '^(ERROR|FAILED|SUBFAILED\([^)]*\)) ' "$G/check.txt"; }; }; then
  fail "the task's check did not complete a test run: $CHECK (output: $G/check.txt)"
fi
[ -n "${CHECK_FAILED:-}" ] || log "check passed: $CHECK"

# a. Sweep
CHANGED_SRC="$(gitl diff --name-only "$BASE...$BRANCH" -- src | grep '\.py$' || true)"
TESTS_TOUCHED="$(gitl diff --name-only --diff-filter=ACMR "$BASE...$BRANCH" -- 'tests/test_*.py' || true)"
TESTS_ADDED="$(gitl diff --name-only --diff-filter=A "$BASE...$BRANCH" -- 'tests/test_*.py' || true)"
SWEEP="$( { printf '%s\n' "$CHANGED_SRC" | "$PY" -I -c '
import os, re, sys
lab = sys.argv[1]
mods = []
for line in sys.stdin.read().split():
    m = line[len("src/"):-3].replace("/", ".")
    mods.append(m[:-9] if m.endswith(".__init__") else m)
pats = []
for m in mods:
    parent, _, leaf = m.rpartition(".")
    pats.append(re.compile(r"^\s*(import\s+%s\b|from\s+%s\s+import\b)" % ((re.escape(m),) * 2), re.M))
    if parent:
        pats.append(re.compile(r"^\s*from\s+%s\s+import\b[^\n]*\b%s\b" % (re.escape(parent), re.escape(leaf)), re.M))
td = os.path.join(lab, "tests")
for f in sorted(os.listdir(td)):
    if f.startswith("test_") and f.endswith(".py"):
        text = open(os.path.join(td, f), encoding="utf-8", errors="replace").read()
        if any(p.search(text) for p in pats):
            print("tests/" + f)
' "$LAB"; printf '%s\n' "$TESTS_TOUCHED" tests/test_herzchen_boundary.py; } | grep . | sort -u)"
log "sweep: $(echo "$SWEEP" | wc -l | tr -d ' ') test files from $(printf '%s\n' "$CHANGED_SRC" | grep -c . || true) changed modules"

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

# A check that failed only on tests canon fails too (the same ids, red on BASE) is not refused for them:
# they are pre-existing, as in the sweep, and go to canon-reds.txt for REDS. Anything else refuses
# (16 Oct: canon's manager-loop red refused CHANGE, A4 and COMPOSEFLEET until the check was narrowed).
if [ -n "${CHECK_FAILED:-}" ]; then
  check_ids="$(ids_of "$G/check.txt" check)"
  [ -n "$check_ids" ] || fail "the task's check failed: $CHECK (output: $G/check.txt)"
  for id in $check_ids; do
    f="${id%%::*}"
    case "$id" in *::exit-*) fail "the task's check failed: $CHECK (output: $G/check.txt)" ;; esac
    gitl cat-file -e "$BASE:$f" 2>/dev/null || fail "the task's check failed: $id (output: $G/check.txt)"
    ids_of "$(baseline_out "$f")" "$f" | grep -qxF "$id" || fail "the task's check failed: $id (output: $G/check.txt)"
  done
  for id in $check_ids; do echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $TASK $id (check; also red on BASE)" >> "$OPS_DIR/canon-reds.txt"; done
  log "check passed except failures also red on BASE: $(echo $check_ids) (listed in ops/canon-reds.txt)"
fi

NEW_FAILS=""
for f in $SWEEP; do
  : > "$G/lab.ids"
  first=1
  # A file the passing check ran whole (named in it, with no -k or :: selection) has had its first run.
  case " $CHECK " in *" -k "*|*::*) ;; *" $f "*) first=2; log "sweep $f run 1/2: 0 failing (the check's run)" ;; esac
  for n in $(seq "$first" 2); do
    run_pytest "$LAB" "$f" "$G/run$n.txt"
    ids="$(ids_of "$G/run$n.txt" "$f")"; kept=""
    if [ -n "$ids" ]; then
      printf '%s\n' "$ids" >> "$G/lab.ids"
      kept="$G/fail-$(basename "$f")-run$n.txt"; cp "$G/run$n.txt" "$kept"
    fi
    log "sweep $f run $n/2: $(printf '%s' "$ids" | grep -c . || true) failing${kept:+ (output: $kept)}"
  done
  sort -u "$G/lab.ids" -o "$G/lab.ids"
  [ -s "$G/lab.ids" ] || continue
  if ! gitl cat-file -e "$BASE:$f" 2>/dev/null; then
    # a file the task added has no baseline: all its failures are new
    NEW_FAILS="$NEW_FAILS$(cat "$G/lab.ids")"$'\n'; continue
  fi
  bo="$(baseline_out "$f")"
  ids_of "$bo" "$f" | sort -u > "$G/base.ids"
  while IFS= read -r id; do
    if grep -qxF -- "$id" "$G/base.ids"; then log "pre-existing failure (also on BASE): $id"
    elif reproduces "$f" "$id"; then NEW_FAILS="$NEW_FAILS$id"$'\n'; fi
  done < "$G/lab.ids"
done

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

# e. remote
git -C "$OTTO_REPO" fetch --quiet "$GIT_REMOTE" || fail "cannot fetch $GIT_REMOTE"
gitl merge-base --is-ancestor "$GIT_REMOTE/main" canon/main \
  || fail "$GIT_REMOTE main has commits canon/main lacks; reconcile first"

# f. merge and push
[ "$(gitl rev-parse canon/main)" = "$BASE" ] \
  || fail "canon/main moved during the gate; run land.sh $TASK again"
if ! gitl merge --no-ff -m "Land $TASK: $TITLE" "$BRANCH" > "$RUN/merge.log" 2>&1; then
  gitl merge --abort 2>/dev/null || true
  fail "merge failed; canon/main unchanged (see $RUN/merge.log)"
fi
log "merged $(gitl rev-parse --short HEAD)"
if ! gitl push --quiet "$GIT_REMOTE" canon/main:main >> "$RUN/merge.log" 2>&1; then
  REASON="push to $GIT_REMOTE failed; local merge kept at $(gitl rev-parse --short HEAD)"
  log "FAIL: push to $GIT_REMOTE failed; the local merge stays on canon/main (see $RUN/merge.log)"
  echo "push to $GIT_REMOTE failed; local merge kept at $(gitl rev-parse --short HEAD) (log: $LOG)" >&2
  exit 1
fi
log "pushed canon/main to $GIT_REMOTE/main"
LANDED="$(gitl rev-parse --short HEAD)"

# g. clean up and record
"$HERE/otto-lab.sh" remove "$TASK" | tee -a "$LOG"
SHORT="$(gitl diff --shortstat "$BASE" HEAD)"
REMOVED="$(gitl diff --numstat "$BASE" HEAD | awk '{ d += $2 } END { print d+0 }')"
log "net: ${SHORT:-no change}; lines removed: $REMOVED"
echo "landed $TASK: $(gitl rev-parse --short HEAD) $(gitl log -1 --format=%s)"
