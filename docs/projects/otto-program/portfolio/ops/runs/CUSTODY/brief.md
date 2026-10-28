# Brief: CUSTODY (xhard, 0.75 focused days)

**Outcome:** every process tree Otto launches is under custody: a birth-fenced group kill, a fail-closed census, and a cleanup latch. The runner's jobs and the agent turns (Claude and Codex) are all covered, so a timed-out turn kills its whole group, not only the direct process. The full row is `CUSTODY` in `~/Developer/otto-program/projects/program/tasklist.md` (line 21). Read that row first. Its acceptance evidence is the contract.

**Why it matters:** today a Codex timeout kills only the direct process, so grandchildren leak. And an empty census is read as "all gone", which is wrong.

**Your lab:** `~/Developer/otto-claude-host/labs/CUSTODY`, on branch `lab/CUSTODY`, from `canon/main` at `2def964`. Work only here.

**Layer:** Herzchen fleet (PLAN.md D14, §11). The custody mechanism is generic: it lands in `src/herzchen/fleet/custody.py`. Otto only calls it. Nothing Otto-specific goes into that module. `tests/test_herzchen_boundary.py` must stay green, and Herzchen must import nothing from Otto or from Astrid.

**Reference, read only:** Astrid's `process_group.py` (`~/Developer/astrid-video/astrid/astrid/core/execution/process_group.py`, lines 121–181 and 250–481, as the row says). Read it. Copy the ideas, not the code, and never import from Astrid. Do not edit anything under `~/Developer/astrid-video`.

**Files you own:**
- `src/herzchen/fleet/custody.py` (new);
- `tests/test_fleet_custody.py` (new);
- the kill and timeout wiring in `src/otto/agents/claude_cli.py`, `src/otto/agents/codex_host_reader.py` and `src/herzchen/adapters/host.py`, only where a turn or job is launched and timed out or interrupted. Find these with grep for `killpg`, `start_new_session` and the timeout paths.

**Hot file, touch with care:** `src/otto/portfolio/execution_host.py` (SL12 and later tasks). Change it only if the call site is unavoidable, keep the edit to the launch and kill lines, and report the exact lines.

**Do not touch:**
- other tasks' files;
- `~/.otto`, `~/.codex`, `~/Documents/Codex`, `production/`, and any Store;
- the live owner, and any process you didn't launch. Do not run `ottoctl`, and never pass it `--help`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** `src/herzchen/fleet/hosts/claude.py` and `codex.py` (the host contract, HOSTKIT), and `src/herzchen/fleet/capacity.py` (POOL). Use the existing host contract; don't add a second one.

**Your check.** Make it green and keep everything else green:
- `tests/test_fleet_custody.py` covers the row's test names: `empty_census_is_uncertain`, `cleanup_latch_resumes_after_crash`, `codex_timeout_kills_group`, `codex_interrupt_after_usage_is_unknown`, `reused_pgid_never_signalled`; plus the ASTRA0 case: a timed-out fake CLI launched through the real adapter leaves no child or grandchild, and an unrelated process with a reused pid is untouched;
- `codex_interrupt_after_usage_is_unknown`: a turn interrupted after usage is `unknown` with `usage_capture` kept, never `failed` (HOSTKIT's D19 F1);
- regression tests must fail on `canon/main` first; show that run too;
- run only the test files you changed or added. The landing gate sweeps every test file that imports a module you changed, twice (D19);
- run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "CUSTODY check" -- <cmd>`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_fleet_custody.py`

**Callers, including production:** if you change a signature, a constructor argument or a default, find every caller and update it. That includes `install/controller/`, where production startup lives (D17).

**Existing tests:** do not change what an existing test asserts to make your change pass. If an expectation really must change, keep it in its own commit and give the reason in your report. It then needs an Opus decision (D19).

**Regression at the level the friction appears:** a Codex turn timed out through the real adapter leaves no grandchild process.

**XHARD: you lead, Haiku executes** (PLAN.md D10). Delegate almost all execution to the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high): exploring and reading code, writing tests, making edits, running checks.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**XHARD invariant:** no process is leaked or wrongly killed.
**The plausible mistake to avoid:** treating an empty census as "all gone", or signalling a reused group id.

**Deletion budget:** name what your change replaces (for example, the direct-process kill in the Codex timeout path).

**Working rules:** commit work in progress to `lab/CUSTODY` as you go. Never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Never run a process you didn't launch, and never signal a group id you can't prove is yours (pgid plus start time). **Never wait:** no Monitor, no sleep loops and no background job you wait on. Run tests in the foreground. If a question blocks you, decide it within this brief and say so in your report, or end your report with the question. Nobody answers mid-run.

**When done:** commit to `lab/CUSTODY` and don't push. Report the commit, the check runs (red, then green), each sub-agent and what it did, what you deleted, and anything you couldn't finish.
