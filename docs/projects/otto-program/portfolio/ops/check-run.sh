#!/bin/bash
# Run a lab's own check command outside any sandbox (PLAN.md §17.6), so a worker's socket, sandbox-exec
# and ps tests are proved before landing instead of only at the gate. The manager requests it as the
# effect ["check-run", TASK]; the loop runs it detached with output ops/runs/TASK/check.out, and the
# last line, "LAND RESULT: check-run ...", wakes the manager. Changes nothing in the lab.
#   bash ops/check-run.sh TASK
set -u
TASK="$1"
LAB="$HOME/Developer/otto-claude-host/labs/$TASK"
result() { echo "LAND RESULT: check-run $TASK $*"; exit 0; }
[ -d "$LAB" ] || result "failed: no lab $LAB"
line="$(grep -m1 -E '^\**Check command:' "$LAB/.brief.md" 2>/dev/null)" || result "failed: no Check command line in the lab's brief"
cmd="$(printf '%s' "$line" | sed -n 's/^[^`]*`\([^`]*\)`.*/\1/p')"
[ -n "$cmd" ] || result "failed: the Check command line has no backticked command"
case "$cmd" in *"<"*">"*) result "failed: the Check command still has a placeholder: $cmd";; esac
echo "check-run $TASK in $LAB: $cmd"
( cd "$LAB" && PYTHONDONTWRITEBYTECODE=1 bash -c "$cmd" < /dev/null )
rc=$?
[ "$rc" = 0 ] && result "passed (exit 0): $cmd"
result "failed (exit $rc): $cmd"
