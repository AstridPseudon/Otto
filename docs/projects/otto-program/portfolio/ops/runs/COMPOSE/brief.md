# Brief: COMPOSE (xhard, 1.25 focused days)

**Outcome:** The product start is the live start. `ottoctl service run` composes the same owner that the live owner runs, so staging proves the start production uses. Concretely: `ProjectOwnerService` with the `ProjectServices` router; `reconcile_startup` settles retained handles before any new admission; the dispatch hold; a startup refusal record with exit 78; closed status only after the hosts and Store are released; a bounded closeout scan; a clean close that seals the Store. Per-role turn limits come from POOL's capacity pool, not the onboarding wrapper's pins. Authoring, external-execution and delegation policies come from the installation config, not `canonical-state.json`. `launchd_definition` gets a product form that runs `service run` directly.

**Why it matters:** Today staging and the new live Otto start through `ottoctl service run`, which composes the plain `OwnerService`, while the live owner gets the rest from the onboarding wrapper (`install/controller/shared_operating_service.py`). A start that is not composed the same way can look healthy and then admit a killed run's handle twice, or dispatch while a retained handle is unsettled. CUTOVER depends on this.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/COMPOSE`, on branch `lab/COMPOSE`, from `canon/main` at `89f2005`. Work only here.

**Layer:** Otto composition (`src/otto/hostctl/`, `src/otto/portfolio/`); nothing in Herzchen (PLAN.md D14, §11). The test: `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/otto/hostctl/project_service.py` (`ProjectOwnerService`, the close and status paths);
- `src/otto/hostctl/supervision.py` (`launchd_definition`, and the exit-78 refusal record the supervisor reads at `:106`, `:132`, `:191`);
- `src/otto/hostctl/cli.py` (the `service run` entry only);
- `src/otto/portfolio/project_services.py` (the router and `reconcile_startup` wiring, `:16` and `:132`);
- `src/otto/hostctl/service.py` (the plain `OwnerService`'s closed status at `:210`, only if the composition needs it);
- `tests/test_compose*.py` (new).

**Do not touch:**
- `src/otto/hostctl/heavy.py`, `src/herzchen/fleet/*` (RUNNER, POOL own them);
- `src/otto/portfolio/cli.py`, `status.py` (A3 and ADMIT changed them; leave them as they are);
- `install/controller/shared_operating_service.py` itself. You read it to decide what the product composition must carry over. The wrapper retires at CUTOVER, not here;
- `execution_host.py`: call the existing dispatch hold; don't reshape it (DISPATCH and ACT own that file later);
- `production/`, any Store, `~/.otto` or `~/.codex`; the live Otto or its socket. Staging only.

**Build on what exists** (PLAN.md §11):
- The router: `src/otto/portfolio/project_services.py:16` (`ProjectServices`) and `reconcile_startup` at `:132`.
- The owner: `src/otto/hostctl/project_service.py:25` (`ProjectOwnerService(OwnerService)`) and its close at `:163`.
- The dispatch hold: `src/otto/portfolio/execution_host.py:258` (read it; call it).
- The supervisor's exit-78 contract: `src/otto/hostctl/supervision.py:106-191`.
- The onboarding wrapper's bounded closeout scan (`install/controller/shared_operating_service.py:79`) and the per-role pins (3/2/3) that POOL's capacity pool replaces. Read them to match behaviour; don't import the wrapper.
- Staging's startup test already uses the product entry point (`ops/bootstrap/staging.sh`, `ops/bootstrap/perch.sh`).

**Your check.** Make it green and keep everything else green:
- `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_compose.py tests/test_herzchen_boundary.py` (the file you create; name it `tests/test_compose.py`). Run tests with no env prefix (`pyproject.toml` sets pytest's `pythonpath`).
- Each acceptance test below fails on `canon/main` first (where the code doesn't exist yet, say so). Show both runs.
- Run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "COMPOSE check" -- <cmd>`.
- Run the test files you changed or added; don't sweep the rest. The landing gate runs every test file that imports a module you changed, twice.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_compose.py tests/test_herzchen_boundary.py`

**Callers, including production:** if you change a signature, constructor argument or default, find every caller and update it. That includes `install/controller/`, where production startup lives: no unit test starts it, but the staging Otto does at landing (D17). A product composition must not change what the wrapper does for the live owner until CUTOVER.

**Existing tests:** don't change what an existing test asserts to make your change pass. If one must change, keep the change in its own commit and give the reason in your report. It then goes to an Opus decision (D19) before landing.

**Regression at the level the friction appears:** a killed run leaves a retained handle; the restarted service must settle it before admitting any new work (`reconcile_before_admission`).

**XHARD only:**
- invariant: The start that staging proves is the start production runs, and nothing is admitted before retained work is settled.
- the plausible mistake to avoid: a composition that starts and serves status but leaves out the router or the reconcile, so it looks healthy until a project attaches or a killed run's handle is admitted twice.
- acceptance tests (from the row): `service_run_attaches_registered_project` (a canary project's manager lane serves through `service run`); `reconcile_before_admission` (a handle retained by a killed run is settled before the first new admission); `startup_refusal_records_exit_78`; `dispatch_hold_refuses_admission`; `closed_only_after_store_release`; `closeout_scan_bounded`; `orderly_close_seals_store`.

**Deletion budget:** the product composition replaces the plain `OwnerService` start for `ottoctl service run` only. Name what you removed or replaced, or say why nothing was. Keep the wrapper's own start untouched.

**XHARD only: you lead, Haiku executes** (PLAN.md D10). Delegate almost all execution to the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high): exploring and reading code, writing tests, making edits, running checks.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**Working rules:** commit work in progress to `lab/COMPOSE` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet (the `haiku-worker` sub-agent is already Haiku).

**When done:** commit to `lab/COMPOSE` and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish.
