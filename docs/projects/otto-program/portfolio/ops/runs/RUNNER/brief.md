# Brief: RUNNER (xhard, 1.0 focused day)

**Outcome:** A runner daemon on `runner.sock` serves `otto run submit`, `otto run await` and `otto run status`. It takes heavy units from POOL's capacity pool for each command. A nested call is recognised by its lease identity, not by an inherited environment variable. A result is kept as verifiable evidence, with restart reconciliation. `otto run report` gives heavy seconds and tokens per task. `OTTO_HEAVY_*` is stripped from agent environments. Priority tickets and caching are deferred (CACHE is a later row).

**Why it matters:** Today a long render can hold most of the machine while a 1-unit gate check waits behind it (15 Oct, 20+ minutes with a unit free), and a restart can rerun a settled check. TOOLS, LAND and SKEL0 all depend on the runner. Every check a worker runs through the gate needs to count once against the pool.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/RUNNER`, on branch `lab/RUNNER`, from `canon/main` at `db1ac48`. Work only here.

**Layer:** Herzchen fleet for the daemon, leases and evidence; Otto product for the `otto run` verbs and the environment strip (PLAN.md D14, §11). The daemon, leases and custody are fleet mechanisms and go in Herzchen. The verbs and the choice of which agents get which environment are Otto's. The test: `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/herzchen/fleet/runner/` (new package: the daemon, leases, result store, reconciliation);
- the `otto run` verbs in a new Otto module, `src/otto/runner_cli.py` (new);
- the one function in Otto that builds an agent's environment, where `OTTO_HEAVY_*` must be stripped (find it with `grep -rn 'environ\|env=' src/otto/agents src/otto/hostctl | head`; change that function only);
- `tests/test_runner.py` (new) and `tests/test_runner_cli.py` (new).

**Do not touch:**
- `src/otto/hostctl/heavy.py` beyond reading it. It stays the flock pool for the bootstrap (DELETE retires it later). Read it for the lease logic at `:260` and do not change it;
- `src/herzchen/fleet/capacity.py` and `custody.py` beyond calling them (POOL and CUSTODY own them);
- `src/otto/portfolio/cli.py`, `status.py`, `execution_host.py` (DISPATCH and ACT touch that later);
- `install/controller/`, `production/`, any Store, `~/.otto` or `~/.codex`;
- anything outside this lab.

**Build on what exists** (PLAN.md §11):
- The capacity pool and its ledgers: `src/herzchen/fleet/capacity.py` (POOL, landed in `2efc109`). Take units from `CapacityPool`; don't add a second ledger.
- Process custody for any launched command: `src/herzchen/fleet/custody.py` (CUSTODY, landed `db1ac48`). A command the runner starts is launched through custody, so a timeout kills its group.
- The current heavy queue and its nested-call rule: `src/otto/hostctl/heavy.py` (the `:260` lease code, the arrival-order queue and the backfill rule from TOOLING6). Copy the behaviour, not the flock.
- The `otto-heavy` wrapper is the bootstrap's client; it stays working until DELETE.

**Your check.** Make it green and keep everything else green:
- `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_runner.py tests/test_runner_cli.py tests/test_herzchen_boundary.py`. Run tests with no env prefix (`pyproject.toml` sets pytest's `pythonpath`).
- Each acceptance test in the list below fails on `canon/main` first (for the ones that exercise new code, that means import fails; say so). Show both runs.
- Run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "RUNNER check" -- <cmd>`.
- Run the test files you changed or added; don't sweep the rest. The landing gate runs every test file that imports a module you changed, twice.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_runner.py tests/test_runner_cli.py tests/test_herzchen_boundary.py`

**Callers, including production:** if you change a signature, constructor argument or default, find every caller and update it. That includes `install/controller/`, where production startup lives: the staging Otto starts there at landing (D17). The runner socket must not start before the owner's startup refusal and reconcile (COMPOSE will wire it; don't wire it yourself beyond the daemon's own start).

**Existing tests:** don't change what an existing test asserts to make your change pass. If one must change, keep the change in its own commit and give the reason in your report. It then goes to an Opus decision (D19) before landing.

**Regression at the level the friction appears:** a budget case: a narrow check runs while a wide job waits at the head of the queue (`narrow_check_not_blocked_behind_wide_waiter`).

**XHARD only:**
- invariant: A result binds exactly one command at one commit. A settled command never reruns after a restart, and a result is never returned for a different command or commit.
- the plausible mistake to avoid: re-running a settled command after a restart, or returning a stale result. Reconcile from the result store before any launch.
- acceptance tests (from the row): `narrow_check_not_blocked_behind_wide_waiter` (backfill a narrower job only when the holders' leases show it can't delay the head); `await` returns the exit code; `lab_cannot_write_store`; `restart_never_reruns_settled`; the report totals equal the results; also (ASTRA0): nested and standalone commands through the real runner under a full pool are each counted once, checks still progress, and an agent's environment can't bypass the count.

**Deletion budget:** the runner replaces the runner-side flock in `heavy.py` for `otto run` callers only. Name what you removed or replaced, or say why nothing was. Don't touch `heavy.py` (see above).

**XHARD only: you lead, Haiku executes** (PLAN.md D10). Delegate almost all execution to the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high): exploring and reading code, writing tests, making edits, running checks.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**Working rules:** commit work in progress to `lab/RUNNER` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet (the `haiku-worker` sub-agent is already Haiku).

**When done:** commit to `lab/RUNNER` and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish.
