#!/bin/bash
# Start one worker: `claude -p` in the task's lab, detached, with a budget cap and a
# wall-clock limit. The run is recorded in $OPS_DIR/workers.json.
#   run-task.sh TASK [--route normal|xhard] [--days N] [--wall-seconds N]
# The route picks the model and the budget per focused day: normal is claude-haiku-5-5
# at $5 a day; xhard is claude-sonnet-5-5 at $20 a day. The wall-clock limit is 3 hours
# a focused day. claude has no timeout flag, so a watchdog stops the worker's process
# group at the deadline, and the deadline is also set in the worker's environment as
# OTTO_WORKER_DEADLINE. --wall-seconds overrides the limit (for tests only).
# Output goes to $OPS_DIR/runs/TASK/ (worker.json, worker.err, brief.md, supervisor.log),
# not into the lab, so the spend record outlives the lab.
set -euo pipefail
. "$(dirname "$0")/common.sh"

ALLOWED_TOOLS='Read Edit Write Glob Grep Bash(git:*) Bash(bash:*) Bash(/opt/homebrew/bin/python3.11:*) Bash(~/Developer/otto-claude-host/bin/otto-heavy:*)'
# Workers start clean: none of the operator's skills, slash commands or MCP connectors.
ISOLATION=(--disable-slash-commands --strict-mcp-config --mcp-config '{"mcpServers":{}}')

valid_task "${1:-}" || die "usage: run-task.sh TASK [--route normal|xhard] [--days N] [--wall-seconds N]"
TASK="$1"
shift
ROUTE=normal
DAYS=1
WALL_OVERRIDE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --route) ROUTE="${2:-}"; shift 2 ;;
    --days) DAYS="${2:-}"; shift 2 ;;
    --wall-seconds) WALL_OVERRIDE="${2:-}"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$ROUTE" in
  normal) MODEL=claude-haiku-5-5; PER_DAY=5 ;;
  xhard) MODEL=claude-sonnet-5-5; PER_DAY=20 ;;
  *) die "--route must be normal or xhard" ;;
esac
case "$DAYS" in
  ""|*[!0-9.]*) die "--days must be a number" ;;
esac
BUDGET=$(awk -v d="$DAYS" -v p="$PER_DAY" 'BEGIN { printf "%.2f", d * p }')
WALL=${WALL_OVERRIDE:-$(awk -v d="$DAYS" 'BEGIN { printf "%d", d * 3 * 3600 }')}
case "$WALL" in
  ""|*[!0-9]*) die "--wall-seconds must be a whole number" ;;
esac

LAB="$LABS_DIR/$TASK"
[ -d "$LAB" ] || die "no lab at $LAB; run otto-lab.sh create $TASK first"
[ -f "$LAB/.brief.md" ] || die "no brief at $LAB/.brief.md"
"$PY" -I "$HERE/workers.py" check --file "$WORKERS_JSON" --task "$TASK" || exit 1

SESSION="$(uuidgen | tr '[:upper:]' '[:lower:]')"
RUN="$RUNS_DIR/$TASK"
mkdir -p "$RUN"
cp "$LAB/.brief.md" "$RUN/brief.md"
read -r STARTED DEADLINE <<< "$("$PY" -I "$HERE/workers.py" times "$WALL")"

# set -m gives the worker its own process group, so the watchdog can stop all of it.
set -m
( cd "$LAB" && exec nohup env OTTO_WORKER_DEADLINE="$DEADLINE" claude -p \
    --model "$MODEL" --effort high --session-id "$SESSION" \
    --max-budget-usd "$BUDGET" --permission-mode acceptEdits \
    --allowedTools "$ALLOWED_TOOLS" "${ISOLATION[@]}" --output-format json \
    < .brief.md > "$RUN/worker.json" 2> "$RUN/worker.err" ) &
PID=$!
set +m

nohup bash -c '
  end=$(( $(date +%s) + $1 ))
  while kill -0 "$2" 2>/dev/null; do
    if [ "$(date +%s)" -ge "$end" ]; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) wall-clock limit reached; stopping process group $2" >> "$3"
      kill -TERM -- "-$2" 2>/dev/null
      sleep 30
      kill -KILL -- "-$2" 2>/dev/null
      break
    fi
    sleep 5
  done' _ "$WALL" "$PID" "$RUN/supervisor.log" >/dev/null 2>&1 &

"$PY" -I "$HERE/workers.py" add --file "$WORKERS_JSON" --task "$TASK" --pid "$PID" \
  --session "$SESSION" --model "$MODEL" --budget "$BUDGET" --lab "$LAB" \
  --started "$STARTED" --deadline "$DEADLINE" \
  || { kill -KILL -- "-$PID" 2>/dev/null || true; die "could not record the worker; stopped it"; }

echo "started $TASK: pid $PID, $MODEL, budget \$$BUDGET, wall-clock $WALL s"
echo "session $SESSION; deadline $DEADLINE"
echo "output: $RUN/worker.json (errors: $RUN/worker.err)"
