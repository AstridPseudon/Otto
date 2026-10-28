#!/bin/bash
# One launcher for every premium call in the program (PLAN.md §16): stage reviews, the final
# review, Astra reviews and D19 decisions.
#   ops/launch_review.sh ID opus|astra [--write] [--dry-run]
# The brief is ops/reviews/ID.brief.md, written from ops/review-brief-template.md.
# The answer is saved to ops/reviews/ID.md; raw output goes to ops/reviews/.raw/ (a dot-folder, so
# portfolio applies skip it: logs are not plan documents).
# Opus runs as claude -p with the haiku-worker sub-agent (Haiku 5.5 high); Astra runs as
# codex exec with Luna sub-agents (spawn_agent, gpt-6-luna). Both are read-only unless --write
# (Astra's cold Codex journey on staging). Runs in the foreground: callers background it.
# Budgets (the user, 15 Oct): 15 Opus calls, 5 Astra calls, counted from ops/STATUS.log.
set -euo pipefail
ROOT="${PROGRAM_ROOT:-$HOME/Developer/otto-program}"  # PROGRAM_ROOT: tests only
ID="${1:-}"; KIND="${2:-}"; shift 2 || true
WRITE=0; DRY=0
for a in "$@"; do case "$a" in --write) WRITE=1 ;; --dry-run) DRY=1 ;; *) echo "unknown flag $a" >&2; exit 2 ;; esac; done
[[ "$ID" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "usage: launch_review.sh ID opus|astra [--write] [--dry-run]" >&2; exit 2; }
case "$KIND" in opus) LIMIT=15 ;; astra) LIMIT=5 ;; *) echo "kind must be opus or astra" >&2; exit 2 ;; esac
BRIEF="$ROOT/ops/reviews/$ID.brief.md"; OUT="$ROOT/ops/reviews/$ID.md"; RAW="$ROOT/ops/reviews/.raw"
[ -s "$BRIEF" ] || { echo "missing brief $BRIEF (copy ops/review-brief-template.md)" >&2; exit 2; }
[ -e "$OUT" ] && { echo "$OUT exists; use a new ID for a re-review (e.g. ${ID}-r2)" >&2; exit 2; }
# Only the launcher's own "launched" lines count (a manager's note that names the kind is not a call).
USED=$(awk -F' [|] ' -v k="$KIND" '$3==k && $4 ~ /^launched/' "$ROOT/ops/STATUS.log" | wc -l | tr -d ' ')
[ "$USED" -lt "$LIMIT" ] || { echo "$KIND budget used: $USED of $LIMIT (only the user raises it)" >&2; exit 3; }

if [ "$KIND" = opus ]; then
  AGENTS='{"haiku-worker":{"description":"Gathers evidence for a reviewer: reads and searches code, runs read-only commands and tests, queries the staging Store, and reports facts with file:line and output tails.","prompt":"You gather evidence for an independent reviewer of the Otto program. Do exactly the sub-brief. Never edit, create or delete files; never commit, push, stash or check out; never run ottoctl or pass --help to any Otto command; never open the live Store or list ~/Documents/Codex or ~/.codex. Report facts, not verdicts: what you looked at (file:line), the commands you ran with their output tails, and anything you could not check.","model":"claude-haiku-5-5","effort":"high","tools":["Read","Glob","Grep","Bash"]}}'
  CMD=(claude -p --model claude-opus-5-5 --effort high --max-budget-usd 15 --permission-mode acceptEdits
       --allowedTools "Read Glob Grep Agent Bash" --disallowedTools "Edit Write NotebookEdit" --agents "$AGENTS"
       --disable-slash-commands --strict-mcp-config --mcp-config '{"mcpServers":{}}'
       --add-dir ~/Developer/otto-claude-host --output-format json)
else
  SANDBOX=read-only; [ "$WRITE" = 1 ] && SANDBOX=workspace-write
  CMD=(codex exec -m gpt-6-astra -c 'model_reasoning_effort="high"' --skip-git-repo-check -C "$ROOT"
       -s "$SANDBOX" --json -o "$OUT")
fi
if [ "$DRY" = 1 ]; then printf '%q ' "${CMD[@]}"; echo; echo "budget: $USED of $LIMIT $KIND calls used"; exit 0; fi

mkdir -p "$RAW"
NOW() { date -u +%Y-%m-%dT%H:%M:%SZ; }
echo "$(NOW) | $ID | $KIND | launched (call $((USED + 1)) of $LIMIT); brief ops/reviews/$ID.brief.md" >> "$ROOT/ops/STATUS.log"
cd "$ROOT"
if [ "$KIND" = opus ]; then
  "${CMD[@]}" < "$BRIEF" > "$RAW/$ID.json" 2> "$RAW/$ID.err" || true
  SUMMARY=$(/opt/homebrew/bin/python3.11 - "$RAW/$ID.json" "$OUT" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
open(sys.argv[2], "w").write(r.get("result") or "")
by = "; ".join(f"{m} ${u.get('costUSD', 0):.2f}" for m, u in (r.get("modelUsage") or {}).items())
print(f"${r.get('total_cost_usd', 0):.2f} ({by}), {r.get('num_turns')} turns, error={r.get('is_error')}")
PY
)
else
  "${CMD[@]}" "$(cat "$BRIEF")" < /dev/null > "$RAW/$ID.jsonl" 2> "$RAW/$ID.err" || true
  # exec's event stream doesn't show spawns; the helpers' own session files name Astra's thread as parent.
  SUMMARY=$(/opt/homebrew/bin/python3.11 - "$RAW/$ID.jsonl" <<'PY'
import glob, json, os, sys
usage, thread = {}, None
for line in open(sys.argv[1]):
    try: e = json.loads(line)
    except ValueError: continue
    thread = e.get("thread_id") or thread
    if e.get("usage"): usage = e["usage"]
helpers, h_in, h_cached, h_out = 0, 0, 0, 0
pattern = os.path.expanduser("~/.codex/sessions/*/*/*/rollout-*.jsonl")
for path in sorted(glob.glob(pattern), key=os.path.getmtime)[-400:]:
    with open(path) as f:
        if f'"parent_thread_id":"{thread}"' not in f.readline(): continue
        helpers += 1
        last = None
        for line in f:
            if '"total_token_usage"' in line: last = line
    if last:
        t = json.loads(last)["payload"]["info"]["total_token_usage"]
        h_in += t["input_tokens"]; h_cached += t["cached_input_tokens"]; h_out += t["output_tokens"]
print(f"Astra in {usage.get('input_tokens')} (cached {usage.get('cached_input_tokens')}), out {usage.get('output_tokens')}; "
      f"{helpers} Luna helpers: in {h_in} (cached {h_cached}), out {h_out}")
PY
)
fi
# A review counts as done only with a non-empty answer; otherwise it is recorded as failed (ASTRA0, 15 Oct).
if [ -s "$OUT" ] && grep -q '[^[:space:]]' "$OUT"; then
  echo "$(NOW) | $ID | review-done | $KIND: $SUMMARY; answer ops/reviews/$ID.md" >> "$ROOT/ops/STATUS.log"
  echo "$SUMMARY"
else
  rm -f "$OUT"
  echo "$(NOW) | $ID | review-failed | $KIND: no answer (${SUMMARY:-no usage}); see ops/reviews/.raw/$ID.err" >> "$ROOT/ops/STATUS.log"
  echo "review failed: no answer; see $RAW/$ID.err" >&2; exit 1
fi
