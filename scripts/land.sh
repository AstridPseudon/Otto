#!/usr/bin/env bash
# Checked landing: rebase -> run CI on that exact commit -> fast-forward the target only.
# Refuses if the target moved while checking; never force-pushes; keeps the
# worktree on failure. Usage: scripts/land.sh <branch> [target=main]
# (The sequence comes from old Otto's landing.py; do not use astrid-install's tools/land.sh.)
set -euo pipefail
branch=${1:?usage: scripts/land.sh <branch> [target]}
target=${2:-main}
repo=$(git rev-parse --show-toplevel)
# Explicit refspecs: in a single-branch or shallow clone, a plain "git fetch origin <name>"
# does not update origin/<name>.
fetch() { git fetch -q origin "+refs/heads/$1:refs/remotes/origin/$1"; }
(cd "$repo" && fetch "$target" && fetch "$branch")
base=$(git -C "$repo" rev-parse "origin/$target")
wt=$(mktemp -d "${TMPDIR:-/tmp}/otto-land.XXXXXX")
git -C "$repo" worktree add -q --detach "$wt" "origin/$branch"
cd "$wt"
if ! git rebase -q "$base"; then
  git rebase --abort || true
  echo "land: conflict rebasing $branch onto $target; target unchanged; worktree kept at $wt" >&2
  exit 1
fi
cand=$(git rev-parse HEAD)
echo "land: checking $cand ($branch rebased onto $target@${base:0:9})"
if ! scripts/ci.sh; then
  echo "land: CI failed on $cand; target unchanged; worktree kept at $wt" >&2
  exit 1
fi
fetch "$target"
now=$(git rev-parse "origin/$target")
if [ "$now" != "$base" ]; then
  echo "land: $target moved (${base:0:9} -> ${now:0:9}) while checking; re-run to rebase and check again" >&2
  exit 2
fi
git merge-base --is-ancestor "$base" "$cand"
git push -q origin "$cand:refs/heads/$target"   # fast-forward only: no --force
echo "land: $target is now $cand (checked)"
cd "$repo" && git worktree remove --force "$wt"
