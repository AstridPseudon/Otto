# Brief: LAND (xhard, 2.0 focused days). Written by the manager 2026-10-16; copy to the lab as `.brief.md` at launch.

**Outcome:** Implement the landing lifecycle in `herzchen/fleet/landing.py`: commit a lab, rebase it onto its line, run the task's admitted check through the runner on that exact rebased commit, validate the runner result, accept via `accept`, `completion_blockers` and `completion_gate`, then advance the line and remove the lab. A conflict or failure returns to the worker. Gates with checks use this same path. Keep line advancement single-file and safe when two passing labs race. The facade's `done` starts landing; its `check` provides feedback only and never accepts work. The criteria bullet moved to SAVEFIX and belongs in the work domain.

**Why it matters:** D4 makes acceptance one verified path: the line can move only after the admitted check passes on the exact rebased commit and its result is explicitly validated. This protects against stale, forged, or lab-edited results being accepted.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LAND`, on branch `lab/LAND`, from `canon/main` at the launch base. Work only here.

**Layer:** Herzchen fleet (PLAN.md D14, §11). New code goes in `src/herzchen/fleet/landing.py`; Otto keeps which line a project lands on. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/herzchen/fleet/landing.py` (new landing orchestration; keep the line advance guarded and use the existing runner and assessment paths);
- `tests/test_landing.py` (new acceptance/regression coverage);
- `src/herzchen/fleet/tools/facade.py`: bind the existing facade's `done`/`check` operations to landing, using authoritative `TokenBook` assignment tokens; change nothing else outside this binding.

If an existing facade test needs changes, keep assertion changes in a separate commit and list each changed assertion as file:line for the D19 decision.

**Do not touch:**
- other tasks' files, especially `src/herzchen/domains/work/` (SAVEFIX), `src/herzchen/fleet/runner/` (RUNNER), `src/herzchen/fleet/labs.py` (LAB), `src/herzchen/domains/assessment/` (EVIDENCE), and `src/herzchen/domains/work/admission.py` (ADMIT);
- `src/otto/agents/claude_cli.py`, `src/otto/hostctl/`, and the production worker launch path (DISPATCH owns the launch token, MCP config and owner-side assignment resolution);
- `production/` (the film folder), any Store, `~/.otto` or `~/.codex`;
- `ops/bootstrap/land.sh` (do not retire or edit it; it remains the program's landing tool until a later row);
- anything outside this lab.

**Build on what exists:** PLAN.md §11 names `commit_local_checkpoint`, writer lease, `lab.sh`'s steps, `fleet/runner/`, `fleet/labs.py`, and the assessment's `accept`/`completion_blockers` as the existing mechanisms. Inspect their landed implementations and reuse their contracts rather than introducing parallel commit, check, or acceptance paths.

**Your check.** Add acceptance tests for every criterion below, each failing on `canon/main` first and passing in the lab. Run changed/new test files only, then the check command below; the landing gate covers importing test files. Include `tests/test_herzchen_boundary.py`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_landing.py tests/test_herzchen_boundary.py`

**Acceptance:** `forged_lab_result_ignored`; `lab_edited_check_ignored`; `stale_criterion_refused`; `two_passing_labs_conflict_caught`; `check_gate_refuses_free_text`; `facade_done_starts_landing`; `facade_check_is_feedback_only`. A runner result for a different commit or altered lab check is refused; stale criteria and free-text checks are refused; two passing labs cannot advance the line together; `done` starts this path and `check` never accepts.

**Assignment binding:** `done`/`check` must use a real `TokenBook` token bound to the assignment; never trust a host request to supply its own assignment identity. Production launch wiring and assignment resolution are DISPATCH's.

**Existing tests:** Do not change existing assertions to make the work pass. If an expectation must change, isolate it in its own commit, report each changed assertion as file:line and explain why. D19 requires an Opus decision before it lands.

**Regression at the level the friction appears:** a forged or altered check result is refused, and two passing labs cannot both move the same line.

**XHARD only:**
- invariant: The line only moves to a commit whose admitted check passed on exactly that commit.
- plausible mistake: Checking the lab commit instead of the rebased commit.

**Deletion budget:** Reuse and retire the existing separate landing/acceptance steps rather than adding another acceptance mechanism; identify any redundant path removed in your report.

**Working rules:** Never run `git stash`, check out another commit in the lab, run `ottoctl`, or pass it `--help`. Never wait or poll. Do not modify `.brief.md`. Codex cannot commit; leave work for `run-task.sh` to commit. If a test fails with `sandbox_apply: Operation not permitted`, report it for the landing gate. On Codex XHARD, delegate execution to Luna sub-agents, keep design and review, and list each sub-agent and any corrections in your report. **Every sub-agent is `spawn_agent` with `model: "gpt-6-luna"`** (never Sol or Astra): give it the goal, the exact files and functions, what not to touch, the command to run and what to report; run sub-agents in parallel only when their files don't overlap.

**When done:** leave the result on `lab/LAND`, don't push, and report commit, red then green checks, what was replaced, and anything unfinished. Stop and ask if the brief contradicts the code.
