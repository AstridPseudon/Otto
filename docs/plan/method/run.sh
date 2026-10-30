#!/usr/bin/env bash
# run.sh <name> <brief-file> [effort]  -> out/<name>.md, out/<name>.log
R=/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/retro
cd $R && codex exec -m gpt-6-luna -c model_reasoning_effort=${3:-high} --skip-git-repo-check -s read-only \
  -o out/$1.md "$(cat tools/CONTEXT.md "$2")" </dev/null > out/$1.log 2>&1; echo $? > out/$1.exit
