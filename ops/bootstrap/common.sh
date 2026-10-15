# Shared settings and helpers for ops/bootstrap. Sourced by the scripts, not run.
# Every location can be overridden from the environment; the scratch tests do that.

OTTO_REPO="${OTTO_REPO:-$HOME/Developer/otto-claude-host/otto}"
LABS_DIR="${LABS_DIR:-$HOME/Developer/otto-claude-host/labs}"
OPS_DIR="${OPS_DIR:-$HOME/Developer/otto-program/ops}"
PY="${OTTO_PYTHON:-/opt/homebrew/bin/python3.11}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKERS_JSON="$OPS_DIR/workers.json"
RUNS_DIR="$OPS_DIR/runs"
HEAVY="${OTTO_HEAVY:-$HOME/Developer/otto-claude-host/bin/otto-heavy}"
BASELINE_LAB="${BASELINE_LAB:-$LABS_DIR/_baseline}"
GIT_REMOTE="${OTTO_REMOTE:-github}"
# The sub-agent an xhard worker may call for legwork (copied from ops/experiments/POOLX/launch.sh).
HAIKU_WORKER_AGENTS='{"haiku-worker":{"description":"Executes one precise, self-contained sub-brief in the Otto lab: explores and reads code, writes tests, makes edits, runs checks, and reports back with evidence (diff summary, test output tail).","prompt":"You are an execution worker in a git worktree of the Otto repo. Do exactly the sub-brief you are given, within the files it names. Never push, never run git stash or check out another commit, never run ottoctl, and never touch anything outside the lab. Run tests the way the sub-brief says. Report briefly: what you changed (files and functions), the commands you ran with their result tails, and anything you could not do.","model":"claude-haiku-5-5","effort":"high","tools":["Read","Edit","Write","Glob","Grep","Bash"]}}'

die() { echo "error: $*" >&2; exit 1; }

# A task name is a plain word: letters, digits, dot, underscore, dash; no leading dot or dash.
valid_task() {
  case "$1" in
    ""|[.-]*|*[!A-Za-z0-9._-]*) return 1 ;;
  esac
}

# The lines of `git status` that are real uncommitted work in a lab. The three files the
# manager writes into a lab (the brief and the worker's output) never count.
uncommitted_work() {
  git -C "$1" status --porcelain --untracked-files=all | while IFS= read -r line; do
    case "$line" in
      "?? .brief.md" | "?? .worker.json" | "?? .worker.err") ;;
      *) echo "$line" ;;
    esac
  done
}

# Copy a lab's manager-owned files into the task's run record before the lab is removed.
archive_manager_files() {  # LAB TASK
  local src
  for src in .brief.md .worker.json .worker.err; do
    [ -f "$1/$src" ] || continue
    mkdir -p "$RUNS_DIR/$2"
    [ -e "$RUNS_DIR/$2/${src#.}" ] || cp "$1/$src" "$RUNS_DIR/$2/${src#.}"
  done
}

# The value after "FIELD:" on the first matching line of a lab's brief, e.g. "Title:".
brief_field() {  # LAB FIELD
  sed -n "s/^[*]*$2:[*]*[[:space:]]*//p" "$1/.brief.md" | head -n 1
}
