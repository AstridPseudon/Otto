# Brief: COMPLETECITE (xhard, 0.75 focused days)

**Outcome:** Completion requires citations equal to the accepted decision's evidence refs, verifies each digest in list and map form, and refuses a governed task with no required scope. The stage-2 completion stand-in then uses the product check instead of duplicating it.

**Your lab:** `lab/COMPLETECITE`, branch `lab/COMPLETECITE`, from `canon/main` at `5b4a7709ec6e89aba8f8d1f8fe3876f55ee728cf`. Work only here.

**Layer:** Herzchen model/domain: task completion evidence policy is shared domain behavior.

**Files you own:** `src/herzchen/domains/work/assignments.py`, tests beside the real completion domain (`tests/test_completed_worker_support_pins.py`, `tests/test_assignment_observation_lookup.py` as appropriate), and the stage-2 completion stand-in in `ops/bootstrap/perch_stage2_owner.py` only to remove duplicate validation after product enforcement.

**Other files:** Edit another direct caller/fixture only when required and report each. Keep changes to accepted-evidence equality, digest verification and required-scope enforcement. `perch_stage2_owner.py` overlaps LABCAPTURE; remove only the completion stand-in, preserving its independent lab-lifecycle edits.

**Do not touch:** The files or changes owned by concurrently launched LABCAPTURE, KILLFENCE, and ORPHANWORKER; `production/`; any Store, `~/.otto` or `~/.codex`; Codex project configuration; anything outside this lab.

**Build on what exists:** `WorkAssignments.complete` and its accepted decision/evidence pin predicates in `src/herzchen/domains/work/assignments.py`; inspect current line numbers in the lab.

**Your check:** On canon demonstrate refusal for another task's retained ref, wrong digest in list and map forms, and missing required scope; demonstrate correct citation succeeds. Then run focused regressions and stage 2 `--fake` completion A/B as an orchestrator run only.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_completed_worker_support_pins.py tests/test_assignment_observation_lookup.py`

**Regression at the level the friction appears:** Real governed task completion with exact pinned evidence.

**Invariant:** A task completes only on the evidence its accepted check produced.
**Plausible mistake:** Comparing refs by retention or name instead of against accepted pinned digests.
**Deletion budget:** Remove the stage-2 completion stand-in once the product enforces the same evidence rule.

**Orchestrator-run acceptance:** Do not start a staging Otto in your sandbox. Report that stage 2 `--fake` completing A and B requires the orchestrator run.

**Codex rules:** You can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A long test runs to its end: use a long timeout or keep reading its session until it exits; never stop it because a window passed. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**XHARD:** Lead the design and invariant review; delegate execution to Luna sub-agents using `spawn_agent` with `model: "gpt-6-luna"`. Review the diff and test tail yourself. Report each sub-agent and any corrections. Never run staging-owner tests in your sandbox.
