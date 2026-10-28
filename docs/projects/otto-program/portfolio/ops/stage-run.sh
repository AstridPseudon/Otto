#!/bin/bash
# Run one perch stage (--fake) on canon/main merged with the named labs, outside any sandbox.
# The manager requests it as the effect ["stage-run", NAME, STAGE, TASK...]; the loop runs it detached
# with output ops/runs/NAME/land.out, and its last line, "LAND RESULT: ...", wakes the manager.
#   bash ops/stage-run.sh NAME STAGE [TASK ...]
# The merge is a throwaway commit (no branch moves). The report goes under ops/perch-reports/STAGE/.
# A failed run keeps its staging root for diagnosis; the next run deletes the previous run's root.
set -u
NAME="$1"; STAGE="$2"; shift 2
OTTO="$HOME/Developer/otto-claude-host/otto"
OPS="$(cd "$(dirname "$0")" && pwd)"
result() { echo "LAND RESULT: stage-run $STAGE $*"; exit 0; }
case "$STAGE" in [0-6]) ;; *) result "refused: stage must be 0-6";; esac

# One staging root per run, short (unix socket paths are limited to ~100 bytes).
ROOT="/private/tmp/sr$(date +%H%M%S)"
KEEP="$OPS/runs/.stage-run-kept"
if [ -f "$KEEP" ]; then
  old="$(cat "$KEEP")"
  case "$old" in /private/tmp/sr[0-9]*) rm -rf "$old" "$old-tree" ;; esac
  rm -f "$KEEP"
fi

sha="$(git -C "$OTTO" rev-parse canon/main)" || result "failed: no canon/main"
for task in "$@"; do
  git -C "$OTTO" rev-parse -q --verify "lab/$task" >/dev/null || result "failed: no branch lab/$task"
  tree="$(git -C "$OTTO" merge-tree --write-tree "$sha" "lab/$task")" || result "failed: lab/$task conflicts with the merge so far"
  sha="$(git -C "$OTTO" commit-tree "$tree" -p "$sha" -p "lab/$task" -m "stage-run $NAME: + $task")"
done
echo "stage-run $NAME: stage $STAGE on $sha (canon/main + ${*:-nothing})"

git -C "$OTTO" worktree add -q --detach "$ROOT-tree" "$sha" || result "failed: worktree"
before="$(ls -1 "$OPS/perch-reports/$STAGE" 2>/dev/null | sort | tail -1)"
( cd "$ROOT-tree" && OTTO_STAGING_ROOT="$ROOT" OTTO_STAGING_REF="$sha" PERCH_OUT="$OPS/perch-reports" \
    bash ops/bootstrap/perch.sh "$STAGE" --fake < /dev/null )
rc=$?
git -C "$OTTO" worktree remove --force "$ROOT-tree"; git -C "$OTTO" worktree prune
report="$(ls -1 "$OPS/perch-reports/$STAGE" 2>/dev/null | sort | tail -1)"
[ "$report" = "$before" ] && report="" || report="ops/perch-reports/$STAGE/$report"
grep -hE "^(PASS|FAIL|SKIP) " "$OPS/$report/report.txt" 2>/dev/null | head -40
if [ "$rc" = 0 ]; then
  rm -rf "$ROOT"
  result "passed on $sha; report $report"
fi
echo "$ROOT" > "$KEEP"
result "failed on $sha; report $report; staging root kept at $ROOT (owner log run/staging.log, responses home/shared-host/, Store store/)"
