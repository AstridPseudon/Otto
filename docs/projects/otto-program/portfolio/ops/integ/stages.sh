#!/bin/bash
# Run perch stages (fake) on the integration head, one after another: bash ops/integ/stages.sh 0 1
OTTO="$HOME/Developer/otto-claude-host/otto"; OPS="$HOME/Developer/otto-program/ops"
sha="$(git -C "$OTTO" rev-parse integ/run)"
for STAGE in "$@"; do
  ROOT="/private/tmp/si$STAGE$(date +%H%M%S)"
  git -C "$OTTO" worktree add -q --detach "$ROOT-tree" "$sha" || { echo "STAGE $STAGE failed: worktree"; continue; }
  ( cd "$ROOT-tree" && OTTO_STAGING_ROOT="$ROOT" OTTO_STAGING_REF="$sha" PERCH_OUT="$OPS/perch-reports" \
      bash ops/bootstrap/perch.sh "$STAGE" --fake < /dev/null )
  rc=$?
  git -C "$OTTO" worktree remove --force "$ROOT-tree"; git -C "$OTTO" worktree prune
  [ "$rc" = 0 ] && rm -rf "$ROOT"
  echo "STAGE $STAGE $([ "$rc" = 0 ] && echo passed || echo "failed (exit $rc; root kept at $ROOT)") on ${sha:0:8}"
done
