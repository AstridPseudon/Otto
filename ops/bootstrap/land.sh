#!/bin/bash
# Land one finished task onto canon/main: rebase the lab, run the check, merge --no-ff,
# remove the lab and its branch. Never pushes.
#   land.sh TASK [--title TEXT] [--check CMD]
# The check is the brief's line "Check command: `...`" unless --check is given. The title
# is the brief's "Title:" line unless --title is given, and falls back to TASK.
# A failed rebase, check or merge leaves canon/main unchanged.
set -euo pipefail
. "$(dirname "$0")/common.sh"

valid_task "${1:-}" || die "usage: land.sh TASK [--title TEXT] [--check CMD]"
TASK="$1"
shift
TITLE=""
CHECK=""
while [ $# -gt 0 ]; do
  case "$1" in
    --title) TITLE="${2:-}"; shift 2 ;;
    --check) CHECK="${2:-}"; shift 2 ;;
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

mkdir -p "$RUN"
BASE="$(git -C "$OTTO_REPO" rev-parse canon/main)"
echo "rebasing $BRANCH onto canon/main ($(git -C "$OTTO_REPO" rev-parse --short canon/main))"
if ! git -C "$LAB" rebase --quiet canon/main; then
  git -C "$LAB" rebase --abort || true
  die "rebase onto canon/main conflicts; resume the worker's session with the conflict"
fi

echo "check: $CHECK"
if ! ( cd "$LAB" && bash -c "$CHECK" ) > "$RUN/check.log" 2>&1; then
  tail -n 40 "$RUN/check.log" >&2
  die "check failed; nothing landed (full log: $RUN/check.log)"
fi
tail -n 3 "$RUN/check.log"

[ "$(git -C "$OTTO_REPO" rev-parse canon/main)" = "$BASE" ] \
  || die "canon/main moved during the check; run land.sh $TASK again"
if ! git -C "$OTTO_REPO" merge --no-ff -m "Land $TASK: $TITLE" "$BRANCH" > "$RUN/merge.log" 2>&1; then
  git -C "$OTTO_REPO" merge --abort 2>/dev/null || true
  die "merge failed; canon/main unchanged (see $RUN/merge.log)"
fi

"$HERE/otto-lab.sh" remove "$TASK"
echo "landed $TASK: $(git -C "$OTTO_REPO" rev-parse --short HEAD) $(git -C "$OTTO_REPO" log -1 --format=%s)"
