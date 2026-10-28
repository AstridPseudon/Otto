# Brief: WORKERSETTLE (xhard, 0.75 focused days)

**Outcome:** A worker's own successful landing, acceptance and completion do not make its start settle as unknown. The worker role keeps assignment and mandate exact and identity-fences project and task, while comparing task content with `task_content_matches` so only the worker's own lifecycle/acceptance revisions are tolerated. An assignment or mandate change, or an external task content edit, still settles unknown. Stage 2 `--fake` passes.

**Why it matters:** The stage-2 journey cannot reliably settle successful workers when their own landing changes the task and project during execution. The owner must distinguish lifecycle effects of the worker from changes to the instruction it was given.

**Your lab:** `lab/WORKERSETTLE`, on branch `lab/WORKERSETTLE`, from `canon/main` at `b284e9943fee69a0ca4a58e8d93b43c8424da25f`. Work only here.

**Layer:** Otto product. New code goes in `src/otto/agents/` or its tests. This is owner runtime scope validation, not reusable agent product behavior. Keep `tests/test_herzchen_boundary.py` green.

**Files you own:**
- `src/otto/agents/owner_runtime.py`
- `tests/test_fresh_worker_admission.py` (extend with the real worker owner-scope settlement cases)

**Other files:** You may edit other files the outcome directly requires, except the files under "Do not touch". List each in your report with the reason.

**Do not touch:**
- The files of tasks running now: none known at launch; recheck before editing.
- `production/` (the Astrid film's folder; it means nothing for code).
- Any Store, `~/.otto` or `~/.codex`.
- Codex's projects, vision and Native5.
- Anything outside this lab.

**Build on what exists:** `OwnerAgentRuntime._binding` and `validate_current_owner_scope` in `src/otto/agents/owner_runtime.py` (around lines 729-768); reuse `task_content_matches` from `herzchen.domains.work.admission` (defined in `src/herzchen/domains/work/admission.py` around line 94; used by `src/otto/portfolio/owner_bootstrap.py` and `src/otto/hostctl/product_service.py`). Preserve exact assignment and mandate snapshots and project/task identity fencing. The manager role's `completed_scope` carve-out is a reference for how role-owned mutable revisions are handled, but must not be copied in a way that drops worker task content validation.

**Your check.** Add real-owner regression coverage in the existing worker-flow fixture for: worker lands and completes and settles completed, not unknown; assignment or mandate change still settles unknown; an external task content edit still settles unknown. First demonstrate the new tests fail on canon, then pass on the change. The stage-2 `--fake` journey starts a staging owner and is not runnable in the worker sandbox; the landing gate/orchestrator must run it outside.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_fresh_worker_admission.py`

**Regression at the level the friction appears:** The full stage-2 `--fake` journey must settle a worker that lands and completes as completed, then continue to B; the same journey's owner-scope tests must show outside instruction changes still settle unknown.

**XHARD only:**
- Invariant: A role's own effects never make its settlement unknown; anyone else's change to its instruction does.
- Plausible mistake to avoid: Dropping the task from the check, so an outside content edit goes unnoticed.

**Deletion budget:** Extend the existing worker scope validator; do not add a second scope-validation mechanism.

**Working rules:** Follow `ops/brief-template.md`, including its Codex rules and long-test guidance. On Codex, do not commit; the launcher commits when you exit. Never run `ottoctl`, and never pass it `--help`. Never wait or poll. Any sub-agent you start must use `spawn_agent` with `model: "gpt-6-luna"`; keep the invariant design and review yourself. Do not run staging or owner-starting tests in the worker sandbox. Never weaken tests to pass in the sandbox. Report red and green runs, commit status, changed assertions, deletions/replacements, and anything unfinished.
