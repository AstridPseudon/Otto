#!/bin/bash
# A lab is a git worktree of canon/main on branch lab/TASK, one per task.
#   otto-lab.sh create TASK   refuses if the lab or the branch already exists
#   otto-lab.sh remove TASK MERGE_SHA   idempotently removes a published lab and its checked branch
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
    MERGE_SHA="${3:-}"
    [ -n "$MERGE_SHA" ] || die "remove needs the published merge SHA"
    MERGE_SHA="$(git -C "$OTTO_REPO" rev-parse --verify "$MERGE_SHA^{commit}")" \
      || die "no published merge commit: ${3:-}"
    [ "$(git -C "$OTTO_REPO" log -1 --format=%s "$MERGE_SHA" | sed -n "s/^Land $TASK: //p" | wc -l | tr -d ' ')" = 1 ] \
      || die "$MERGE_SHA is not a Land $TASK merge"
    read -r _ BASE TESTED_SHA EXTRA <<< "$(git -C "$OTTO_REPO" rev-list --parents -n 1 "$MERGE_SHA")"
    [ -n "${TESTED_SHA:-}" ] && [ -z "${EXTRA:-}" ] \
      || die "$MERGE_SHA does not have the expected two parents"
    git -C "$OTTO_REPO" merge-base --is-ancestor "$MERGE_SHA" "$GIT_REMOTE/main" \
      || die "$MERGE_SHA is not confirmed on $GIT_REMOTE/main"
    "$PY" -I "$HERE/workers.py" remove --file "$WORKERS_JSON" --task "$TASK" \
      || die "worker for $TASK is still running; remove the lab after it exits"
    if git -C "$OTTO_REPO" show-ref --verify --quiet "refs/heads/$BRANCH"; then
      [ "$(git -C "$OTTO_REPO" rev-parse "$BRANCH")" = "$TESTED_SHA" ] \
        || die "$BRANCH differs from the published merge's checked parent $TESTED_SHA"
    elif [ -d "$LAB" ]; then
      die "$LAB exists without $BRANCH; inspect it before cleanup"
    fi
    if [ -d "$LAB" ]; then
      if [ -n "$(uncommitted_work "$LAB")" ]; then
        uncommitted_work "$LAB" >&2
        die "lab $LAB has uncommitted work; commit or discard it first"
      fi
      archive_manager_files "$LAB" "$TASK"
      git -C "$OTTO_REPO" worktree remove --force "$LAB"
    fi
    if git -C "$OTTO_REPO" show-ref --verify --quiet "refs/heads/$BRANCH"; then
      git -C "$OTTO_REPO" branch -D "$BRANCH" >/dev/null
      echo "removed $LAB and deleted $BRANCH (checked parent of published $MERGE_SHA)"
    else
      echo "publication cleanup already complete for $TASK ($MERGE_SHA)"
    fi
    ;;
  *)
    die "usage: otto-lab.sh create|remove TASK"
    ;;
esac
