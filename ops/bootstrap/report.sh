#!/bin/bash
# Read-only status: tasks landed on canon/main, running workers, spend per task.
#   report.sh
set -euo pipefail
. "$(dirname "$0")/common.sh"

echo "landed on canon/main:"
LANDED="$(git -C "$OTTO_REPO" log canon/main --format='%h %ad %s' --date=short \
  | sed -n '/^[0-9a-f]* [0-9-]* Land /p')"
if [ -n "$LANDED" ]; then
  echo "$LANDED" | sed 's/^/  /'
else
  echo "  (none)"
fi

echo "workers:"
if [ -f "$WORKERS_JSON" ]; then
  "$PY" -I "$HERE/workers.py" list --file "$WORKERS_JSON"
else
  echo "  (no workers recorded)"
fi

echo "spend per task:"
"$PY" -I "$HERE/workers.py" spend --runs "$RUNS_DIR"
