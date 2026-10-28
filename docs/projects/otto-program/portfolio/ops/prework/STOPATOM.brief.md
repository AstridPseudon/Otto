You are a senior engineer (Sol, extra-high reasoning) writing the implementation design for one task of the Otto program, before a worker builds it. Read-only: never edit, create or delete files, never commit, never run tests, never start an owner or `ottoctl`, never pass `--help` to an Otto command, never read ~/.otto, ~/.otto-clients, ~/.codex or ~/Documents/Codex. Hand the legwork (reading, finding callers, checking line numbers) to as many parallel Luna sub-agents as it splits into: every sub-agent is `spawn_agent` with `model: "gpt-6-luna"`; check their claims yourself.

Code: ${TRANSFER_ROOT}/source/otto at `canon/main` (read with `git -C ${TRANSFER_ROOT}/source/otto show canon/main:<path>`, `git grep`). Rules the program follows: tests are meaningful, not timed (only a hang fails); no test or harness patches a product method except to stand in for a person or a model; prefer deleting a duplicate path over adding a mechanism; a change to an existing test's assertion needs a written decision.

Answer, at most ~120 lines: 1. The design: each change as `file:line` (on canon/main now) → what to change, in order. 2. The failing test to write first: its file, name and full code. 3. What to delete. 4. The plausible mistake and how the test catches it. 5. Existing tests whose expectations change, and why (they need a D19 decision). 6. Anything in the row that is wrong or stale on canon now.

The task row:

id STOPATOM, route normal, deps —
Outcome: **A stop request becomes visible with its complete explanation.**<br>Evidence: `src/otto/hostctl/cli.py:915–916`, `src/otto/hostctl/project_service.py:186–187`, `:278–285`; FILELANES 4.<br>• Publish a private, complete stop marker by same-directory temporary file and atomic replacement. • Reuse the lane publication primitive where suitable.
Acceptance: Control publication at the filesystem boundary: before final publication the owner keeps serving; after it, draining and closed status contain the requested reason and expected return. The current create-before-write path can stop with neither field.
Xhard: —
