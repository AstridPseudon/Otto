# Brief: DISPATCH (xhard, 1.5 focused days)

**Outcome:** Implement ready-task selection and the fleet dispatcher. Every launch path must recheck admission and dependency gates immediately before launch, select by role through capacity, issue an assignment token, and pass a strict MCP config containing only the TOOLS `otto` server. Record the admitted revision on the dispatch record. On the owner side, resolve a worker token to its assignment and bind the worker facade to LAND's landing port so `done` and `check` reach that assignment. Routine dispatch must not wake managers.

**Why it matters:** No current launch path checks dependencies. A worker must not start before it is admitted and its dependencies are accepted, and its tools must route actions to its own assignment.

**Your lab:** `labs/DISPATCH`, on branch `lab/DISPATCH`, from `canon/main` at `c365152108383d687091a6c36fd01f470464504c`. Work only here.

**Layer:** Herzchen fleet and work domain for reusable readiness/dispatch behavior; Otto product for roles, policies, and owner-side wiring. Keep the dispatcher in `herzchen/fleet/dispatch.py`; implement `ready()` in the work domain. Otto passes its roles and policies into the reusable fleet layer.

**Files you own:**
- `src/herzchen/domains/work/readiness.py` (new; `ready()` query)
- `src/herzchen/fleet/dispatch.py` (new; ready → capacity → launch)
- `src/otto/portfolio/execution_operations.py` (launch integration and last-moment admission/dependency recheck)
- `src/otto/portfolio/execution_host.py` (owner token resolution and landing-port binding)
- `src/otto/portfolio/dependencies.py` (reuse existing dependency semantics; change only if required)
- `src/herzchen/fleet/tools/tokens.py` (reuse TokenBook; change only if required)
- `src/herzchen/fleet/runner/admission.py` and `src/herzchen/fleet/runner/runner.py` (strict worker MCP config and token propagation; change only if required)
- `tests/test_work_readiness.py` (new)
- `tests/test_fleet_dispatch.py` (new)
- `tests/test_execution_operations.py`
- `tests/test_portfolio_dependencies.py`
- `tests/test_admit.py`
- `tests/test_fleet_custody.py`

All existing paths above were checked against `canon/main` at the SHA above; only the two readiness/dispatch modules and their focused test modules are new. Do not edit TOOLS-owned files unless this row cannot be completed without them; TOOLS has landed and owns the server implementation.

**Do not touch:**
- other tasks' files;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** `src/otto/portfolio/dependencies.py` defines dependency/gate semantics; `src/otto/portfolio/execution_operations.py` has the current read-side execution operations; `src/otto/portfolio/execution_host.py` owns execution host operations; `src/herzchen/fleet/capacity.py` handles capacity; `src/herzchen/fleet/tools/tokens.py` contains `TokenBook`; `src/herzchen/fleet/landing.py` owns the landing port; `src/herzchen/fleet/runner/admission.py` and `runner.py` own worker startup. Preserve the existing admission entry point `admit_execution`.

**Your check.** Add focused tests for the row's six selectors: `unadmitted_never_dispatches_any_path`, `blocked_dep_waits`, `gate_dep_waits`, `manager_not_woken_for_routine`, `launch_carries_assignment_token`, and `worker_done_reaches_its_own_assignment`. Reproduce each new regression on canon where practical, then run the task-owned tests:

`/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_work_readiness.py tests/test_fleet_dispatch.py tests/test_execution_operations.py tests/test_portfolio_dependencies.py tests/test_admit.py tests/test_fleet_custody.py`

Run tests with no env prefix. The landing gate runs imported test files and checks against canon. Do not change existing assertions to make a new behavior pass; report any necessary expectation change for D19.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_work_readiness.py tests/test_fleet_dispatch.py tests/test_execution_operations.py tests/test_portfolio_dependencies.py tests/test_admit.py tests/test_fleet_custody.py`

**Callers, including production:** If you change a signature, constructor argument, or default, find and update every caller, including `install/controller/`.

**Regression at the level the friction appears:** Exercise every launch route, including resume/retry; prove an unadmitted task and a task with blocked or gate dependencies never launches, and prove worker `done` and `check` resolve to the correct assignment.

**XHARD only:**
- invariant: Every launch path checks admission and dependencies.
- plausible mistake to avoid: Missing one path (resume or retry), allowing unadmitted work to run.

**Deletion budget:** Replace the existing path that launches without an admission/dependency check; identify the exact removed or superseded mechanism in your report.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**
- **XHARD only: you lead, a cheaper model executes** (PLAN.md D10). Delegate almost all execution: exploring and reading code, writing tests, making edits, running checks. On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`.
  - Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
  - Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
  - Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
  - Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
  - In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** commit to `lab/DISPATCH` (on Codex, leave it for the launcher) and don't push. Report the commit, red then green evidence for each new regression, what changed, what was replaced, each sub-agent's work, and anything unfinished. Stop and ask if the brief contradicts the code.
