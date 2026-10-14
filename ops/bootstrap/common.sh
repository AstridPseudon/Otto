# Shared settings and helpers for ops/bootstrap. Sourced by the scripts, not run.
# Every location can be overridden from the environment; the scratch tests do that.

OTTO_REPO="${OTTO_REPO:-$HOME/Developer/otto-claude-host/otto}"
LABS_DIR="${LABS_DIR:-$HOME/Developer/otto-claude-host/labs}"
OPS_DIR="${OPS_DIR:-$HOME/Developer/otto-program/ops}"
PY="${OTTO_PYTHON:-/opt/homebrew/bin/python3.11}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKERS_JSON="$OPS_DIR/workers.json"
RUNS_DIR="$OPS_DIR/runs"

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
