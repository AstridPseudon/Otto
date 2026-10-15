#!/bin/bash
# Land one finished task onto canon/main through the gate (RUNBOOK section 4): rebase the lab,
# run the check, sweep the tests the task touches (twice each) against a BASE baseline, check
# placement (D14) and changed test expectations (D19), merge --no-ff, push to $GIT_REMOTE,
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


# ---- gate ----
G="$RUN/.gate"; rm -rf "$G"; mkdir -p "$G"  # dot-folders: portfolio applies skip scratch
gitl() { git -C "$OTTO_REPO" "$@"; }

# Run one test file in DIR with output to OUT; the last line records pytest's exit status.
run_pytest() {  # DIR FILE OUT
  local rc=0
  ( cd "$1" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests "$HEAVY" --weight 1 --purpose "$TASK gate" -- \
      "$PY" -m pytest -q -rfE -p no:cacheprovider "$2" ) > "$3" 2>&1 || rc=$?
  echo "=== exit $rc" >> "$3"
}
# Failing test ids in a run's output; a nonzero exit with no FAILED/ERROR line becomes one id.
ids_of() {  # OUT FILE
  local rc; rc="$(sed -n 's/^=== exit //p' "$1" | tail -n 1)"
  sed -n -E 's/^(FAILED|ERROR) ([^ ]+).*/\2/p' "$1"
  if [ "$rc" != 0 ] && [ "$rc" != 5 ] && ! grep -q -E '^(FAILED|ERROR) ' "$1"; then echo "$2::exit-$rc"; fi
}

# 0. The task's own check, on the rebased commit (D19, rule 1). Until 15 Oct the gate parsed it and never ran it.
( cd "$LAB" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests "$HEAVY" --weight 1 --purpose "$TASK check" -- \
    bash -c "$CHECK" ) > "$G/check.txt" 2>&1 || fail "the task's check failed: $CHECK (output: $G/check.txt)"
log "check passed: $CHECK"

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

NEW_FAILS=""
for f in $SWEEP; do
  : > "$G/lab.ids"
  for n in 1 2; do
    run_pytest "$LAB" "$f" "$G/run$n.txt"
    ids_of "$G/run$n.txt" "$f" >> "$G/lab.ids"
    log "sweep $f run $n/2: $(grep -c . < <(ids_of "$G/run$n.txt" "$f") || true) failing"
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
    else log "NEW failure: $id"; NEW_FAILS="$NEW_FAILS$id"$'\n'; fi
  done < "$G/lab.ids"
done
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
if [ -x "$HERE/staging.sh" ] && [ -x "$HERE/perch.sh" ]; then
  SHA="$(git -C "$LAB" rev-parse HEAD)"
  ( cd "$LAB" && OTTO_COMMIT="$SHA" "$HERE/staging.sh" restart ) >> "$G/staging.log" 2>&1 || fail "staging.sh restart failed ($G/staging.log)"
  ( cd "$LAB" && OTTO_COMMIT="$SHA" "$HERE/perch.sh" all --fake ) >> "$G/staging.log" 2>&1 || fail "perch.sh all --fake failed ($G/staging.log)"
  log "staging: restart and perch --fake passed on $SHA"
else
  log "staging: skipped (STAGE/PERCH not landed)"
fi

# e. placement (D14)
read -r HZ_ADD HZ_DEL OT_ADD OT_DEL <<< "$(gitl diff --numstat "$BASE...$BRANCH" | awk '
  $1 ~ /^[0-9]+$/ { if ($3 ~ /^src\/herzchen\//) { ha += $1; hd += $2 } else if ($3 ~ /^src\/otto\//) { oa += $1; od += $2 } }
  END { print ha+0, hd+0, oa+0, od+0 }')"
LAYER="$(brief_field "$LAB" Layer)"
log "placement: src/herzchen +$HZ_ADD -$HZ_DEL; src/otto +$OT_ADD -$OT_DEL; Layer: ${LAYER:-none}"
case "$LAYER" in
  *[Hh]erzchen*) if [ "$OT_ADD" -gt 0 ] && [ "$HZ_ADD" -eq 0 ]; then
    fail "D14: Layer says Herzchen but the task added $OT_ADD lines under src/otto and none under src/herzchen"; fi ;;
esac

# f. existing tests (D19)
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
  VERDICT="$(grep -m1 -E 'LAND|SEND BACK' "$D19" || true)"
  case "$VERDICT" in
    *"SEND BACK"*) fail "D19: review says SEND BACK ($D19)" ;;
    *LAND*) log "D19: review says LAND ($D19) for $D19_FILES" ;;
    *) fail "D19: no LAND or SEND BACK in $D19" ;;
  esac
fi

# g. remote
git -C "$OTTO_REPO" fetch --quiet "$GIT_REMOTE" || fail "cannot fetch $GIT_REMOTE"
gitl merge-base --is-ancestor "$GIT_REMOTE/main" canon/main \
  || fail "$GIT_REMOTE main has commits canon/main lacks; reconcile first"

# h. merge and push
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

# i. clean up and record
"$HERE/otto-lab.sh" remove "$TASK" | tee -a "$LOG"
SHORT="$(gitl diff --shortstat "$BASE" HEAD)"
REMOVED="$(gitl diff --numstat "$BASE" HEAD | awk '{ d += $2 } END { print d+0 }')"
log "net: ${SHORT:-no change}; lines removed: $REMOVED"
echo "landed $TASK: $(gitl rev-parse --short HEAD) $(gitl log -1 --format=%s)"
