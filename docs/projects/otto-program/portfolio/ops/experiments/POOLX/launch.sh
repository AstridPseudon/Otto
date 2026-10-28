#!/bin/bash
# POOLX experiment: run-task.sh's exact worker flags (xhard, 1.25 d: Sonnet high, $25, 3.75 h),
# plus the Agent tool and a haiku-worker sub-agent (Haiku 5.5, high effort).
set -euo pipefail
LAB=~/Developer/otto-claude-host/labs/POOLX
RUN=~/Developer/otto-program/ops/experiments/POOLX
ALLOWED='Read Edit Write Glob Grep Agent Bash(git:*) Bash(bash:*) Bash(/opt/homebrew/bin/python3.11:*) Bash(~/Developer/otto-claude-host/bin/otto-heavy:*)'
AGENTS='{"haiku-worker":{"description":"Executes one precise, self-contained sub-brief in the Otto lab: explores and reads code, writes tests, makes edits, runs checks, and reports back with evidence (diff summary, test output tail).","prompt":"You are an execution worker in a git worktree of the Otto repo. Do exactly the sub-brief you are given, within the files it names. Never push, never run git stash or check out another commit, never run ottoctl, and never touch anything outside the lab. Run tests the way the sub-brief says. Report briefly: what you changed (files and functions), the commands you ran with their result tails, and anything you could not do.","model":"claude-haiku-5-5","effort":"high","tools":["Read","Edit","Write","Glob","Grep","Bash"]}}'
SESSION=$(uuidgen | tr '[:upper:]' '[:lower:]')
WALL=13500
mkdir -p "$RUN"; cp "$LAB/.brief.md" "$RUN/brief.md"
date -u +%Y-%m-%dT%H:%M:%SZ > "$RUN/started"
set -m
( cd "$LAB" && exec nohup claude -p --model claude-sonnet-5-5 --effort high --session-id "$SESSION" \
    --max-budget-usd 25.00 --permission-mode acceptEdits --allowedTools "$ALLOWED" \
    --agents "$AGENTS" --disable-slash-commands --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
    --output-format json < "$LAB/.brief.md" > "$RUN/worker.json" 2> "$RUN/worker.err" ) &
PID=$!
set +m
nohup bash -c 'end=$(( $(date +%s) + $1 )); while kill -0 "$2" 2>/dev/null; do if [ "$(date +%s)" -ge "$end" ]; then echo "$(date -u +%FT%TZ) wall limit; stopping $2" >> "$3"; kill -TERM -- "-$2"; sleep 30; kill -KILL -- "-$2"; break; fi; sleep 5; done; date -u +%Y-%m-%dT%H:%M:%SZ > "$4"' _ "$WALL" "$PID" "$RUN/supervisor.log" "$RUN/finished" >/dev/null 2>&1 &
echo "{\"task\":\"POOLX\",\"pid\":$PID,\"session\":\"$SESSION\",\"started\":\"$(cat $RUN/started)\"}" | tee "$RUN/run.json"
