#!/bin/bash
# Run one test file at every merge of the integration sequence in parallel; report which finish within LIMIT seconds
# (the orchestrator's judgment of a hang, not a test assertion).  bash ops/integ/hangscan.sh FILE LIMIT
F="$1"; LIMIT="$2"; OTTO="$HOME/Developer/otto-claude-host/otto"
/opt/homebrew/bin/python3.11 -I -c 'import json; st=json.load(open("ops/integ/state.json")); [print(m["task"], m["sha"]) for m in st["merged"]]' |
while read task sha; do
  ( wt="$OTTO/../labs/_hang-$task"; git -C "$OTTO" worktree add -q --detach "$wt" "$sha" 2>/dev/null
    tmp=$(mktemp -d /tmp/h.XXXXXX)
    ( cd "$wt" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src:tests:$wt/ops/bootstrap" TMPDIR="$tmp" OTTO_LAND_TMPDIR="$tmp" \
        /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider "$F" > "ops-hang-$task.txt" 2>&1 ) & pid=$!
    n=0; while kill -0 $pid 2>/dev/null && [ $n -lt "$LIMIT" ]; do sleep 5; n=$((n+5)); done
    if kill -0 $pid 2>/dev/null; then pkill -TERM -P $pid; kill -TERM $pid; echo "$task HUNG (>${LIMIT}s)"; else echo "$task finished: $(tail -1 "$wt/ops-hang-$task.txt")"; fi
    rm -rf "$tmp"; git -C "$OTTO" worktree remove --force "$wt" ) &
done; wait
