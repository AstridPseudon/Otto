#!/bin/bash
# Start one worker in the task's lab, detached, with a wall-clock limit (and, on claude, a budget
# cap). The run is recorded in $OPS_DIR/workers.json.
#   run-task.sh TASK [--route normal|xhard] [--host claude|codex] [--days N] [--wall-seconds N] [--resume SESSION --message FILE]
# --host picks the agent CLI; the default is $OTTO_WORKER_HOST, else the program's choice in
# $OPS_DIR/worker-host, else claude. On codex, normal is gpt-6-luna (high) and xhard gpt-6-sol
# (xhigh), sandboxed to the lab (workspace-write). Codex keeps every .git read-only inside its
# sandbox, so the worker can't commit: when it exits, this script commits what it left in the lab.
# Codex has no budget flag; its usage is in worker.jsonl (turn.completed events).
# --resume continues a stopped worker's session in the same lab, with FILE as its next prompt;
# its output goes to worker.N.json beside the first run's, so spend sums over all of them.
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
ROUTE_ARGS=()
ISOLATION=(--disable-slash-commands --strict-mcp-config --mcp-config '{"mcpServers":{}}')
# A headless worker has no use for self-scheduling: each wake re-reads its whole context.
ISOLATION+=(--disallowedTools "ScheduleWakeup CronCreate Monitor")  # workers never wait: no self-scheduling, no monitors

valid_task "${1:-}" || die "usage: run-task.sh TASK [--route normal|xhard] [--host claude|codex] [--days N] [--wall-seconds N] [--resume SESSION --message FILE]"
TASK="$1"
shift
ROUTE=normal
HOST="$(default_worker_host)"
DAYS=1
WALL_OVERRIDE=""
RESUME=""
MESSAGE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --route) ROUTE="${2:-}"; shift 2 ;;
    --host) HOST="${2:-}"; shift 2 ;;
    --days) DAYS="${2:-}"; shift 2 ;;
    --wall-seconds) WALL_OVERRIDE="${2:-}"; shift 2 ;;
    --resume) RESUME="${2:-}"; shift 2 ;;
    --message) MESSAGE="${2:-}"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$HOST:$ROUTE" in
  claude:normal) MODEL=claude-haiku-5-5; PER_DAY=5 ;;
  claude:xhard) MODEL=claude-sonnet-5-5; PER_DAY=20; ALLOWED_TOOLS="Agent $ALLOWED_TOOLS"; ROUTE_ARGS=(--agents "$HAIKU_WORKER_AGENTS") ;;
  codex:normal) MODEL=gpt-6-luna; EFFORT=high; PER_DAY=0 ;;
  codex:xhard) MODEL=gpt-6-sol; EFFORT=xhigh; PER_DAY=0 ;;
  claude:*|codex:*) die "--route must be normal or xhard" ;;
  *) die "--host must be claude or codex" ;;
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

RUN="$RUNS_DIR/$TASK"
mkdir -p "$RUN"
if [ -n "$RESUME" ]; then
  [ -f "$MESSAGE" ] || die "--resume needs --message FILE"
  SESSION="$RESUME"; SESSION_ARG=(--resume "$SESSION"); PROMPT="$(cd "$(dirname "$MESSAGE")" && pwd)/$(basename "$MESSAGE")"
  N=1; while [ -e "$RUN/worker.$N.json" ] || [ -e "$RUN/worker.$N.jsonl" ]; do N=$((N + 1)); done
  OUT="$RUN/worker.$N.json"; ERR="$RUN/worker.$N.err"; LAST="$RUN/worker.$N.last.md"
else
  SESSION="$(uuidgen | tr '[:upper:]' '[:lower:]')"; SESSION_ARG=(--session-id "$SESSION"); PROMPT="$LAB/.brief.md"
  OUT="$RUN/worker.json"; ERR="$RUN/worker.err"; LAST="$RUN/worker.last.md"
  cp "$LAB/.brief.md" "$RUN/brief.md"
fi
[ "$HOST" = codex ] && OUT="${OUT%.json}.jsonl"
read -r STARTED DEADLINE <<< "$("$PY" -I "$HERE/workers.py" times "$WALL")"

# set -m gives the worker its own process group, so the watchdog can stop all of it.
set -m
if [ "$HOST" = claude ]; then
( cd "$LAB" && exec nohup env OTTO_WORKER_DEADLINE="$DEADLINE" claude -p \
    --model "$MODEL" --effort high "${SESSION_ARG[@]}" \
    --max-budget-usd "$BUDGET" --permission-mode acceptEdits \
    --allowedTools "$ALLOWED_TOOLS" "${ISOLATION[@]}" ${ROUTE_ARGS[@]+"${ROUTE_ARGS[@]}"} --output-format json \
    < "$PROMPT" > "$OUT" 2> "$ERR" ) &
PID=$!
else
# The sandbox is set with -c, which `exec resume` also takes. The heavy pool's state must be writable.
# network_access: without it the sandbox refuses AF_UNIX bind/connect, and most Otto tests start an
# owner on a Unix socket (16 Oct: SAVEFIX couldn't run its tests). .git stays read-only either way.
CODEX_ARGS=(-m "$MODEL" -c "model_reasoning_effort=\"$EFFORT\"" -c 'sandbox_mode="workspace-write"'
  -c "sandbox_workspace_write.writable_roots=[\"$HEAVY_STATE_DIR\"]" -c 'sandbox_workspace_write.network_access=true'
  --ignore-user-config --skip-git-repo-check --json -o "$LAST")
if [ -n "$RESUME" ]; then CODEX_RUN=(codex exec resume "${CODEX_ARGS[@]}" "$SESSION" -); else CODEX_RUN=(codex exec "${CODEX_ARGS[@]}" -); fi
( cd "$LAB" || exit 1
  # The watchdog's TERM stops codex; this shell still commits what it left (a handler, unlike
  # an ignored signal, isn't inherited by codex), before the KILL that follows 30 s later.
  trap 'echo "run-task.sh: stopped by the wall-clock watchdog" >&2' TERM
  rc=0
  nohup env OTTO_WORKER_DEADLINE="$DEADLINE" "${CODEX_RUN[@]}" < "$PROMPT" > "$OUT" 2> "$ERR" || rc=$?
  commit_worker_changes "$LAB" "$TASK" "$OUT" >> "$ERR" 2>&1 || echo "run-task.sh: commit failed" >> "$ERR"
  exit $rc ) < /dev/null > /dev/null 2>> "$ERR" &  # detached: holds no pipe of the caller's (16 Oct: it hung the manager loop)
PID=$!
fi
set +m
if [ "$HOST" = codex ] && [ -z "$RESUME" ]; then
  # Codex names its own session: the first event is {"type":"thread.started","thread_id":...}.
  SESSION="$("$PY" -I "$HERE/workers.py" codex-session --events "$OUT" --pid "$PID")" \
    || { kill -TERM -- "-$PID" 2>/dev/null || true; die "codex didn't start a session; see $ERR"; }
fi

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
echo "output: $OUT (errors: $ERR)"
[ "$HOST" = codex ] && echo "last message: $LAST"
true
