#!/bin/bash
# A lab is a git worktree of canon/main on branch lab/TASK, one per task.
#   otto-lab.sh create TASK   refuses if the lab or the branch already exists
#   otto-lab.sh remove TASK   refuses a lab with uncommitted work or a running worker;
#                             deletes the branch only if it is merged into canon/main
# This replaces lab.sh, which retires in DELETE (later).
set -euo pipefail
. "$(dirname "$0")/common.sh"

valid_task "${2:-}" || die "usage: otto-lab.sh create|remove TASK"
TASK="$2"
LAB="$LABS_DIR/$TASK"
BRANCH="lab/$TASK"

case "${1:-}" in
  create)
    [ ! -e "$LAB" ] || die "lab already exists: $LAB"
    if git -C "$OTTO_REPO" show-ref --verify --quiet "refs/heads/$BRANCH"; then
      die "branch $BRANCH already exists"
    fi
    git -C "$OTTO_REPO" rev-parse --verify --quiet canon/main >/dev/null || die "no canon/main in $OTTO_REPO"
    mkdir -p "$LABS_DIR"
    git -C "$OTTO_REPO" worktree add --quiet -b "$BRANCH" "$LAB" canon/main
    echo "created $LAB on $BRANCH from canon/main ($(git -C "$LAB" rev-parse --short HEAD))"
    ;;
  remove)
    [ -d "$LAB" ] || die "no lab at $LAB"
    "$PY" -I "$HERE/workers.py" remove --file "$WORKERS_JSON" --task "$TASK" \
      || die "worker for $TASK is still running; remove the lab after it exits"
    if [ -n "$(uncommitted_work "$LAB")" ]; then
      uncommitted_work "$LAB" >&2
      die "lab $LAB has uncommitted work; commit or discard it first"
    fi
    archive_manager_files "$LAB" "$TASK"
    git -C "$OTTO_REPO" worktree remove --force "$LAB"
    if git -C "$OTTO_REPO" merge-base --is-ancestor "$BRANCH" canon/main; then
      git -C "$OTTO_REPO" branch -D "$BRANCH" >/dev/null
      echo "removed $LAB and deleted $BRANCH (merged into canon/main)"
    else
      echo "removed $LAB; kept $BRANCH because it is not merged into canon/main"
    fi
    ;;
  *)
    die "usage: otto-lab.sh create|remove TASK"
    ;;
esac
