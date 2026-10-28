# Brief: TOOLS (xhard, 1.5 focused days)

**Outcome:** A worker's tools are the same on both hosts, and a worker can't produce its own acceptance. Worker tools go from `Read,Write` to Read, Write, Edit, Glob and Grep, plus one `otto` MCP server. That server is the only MCP server a worker sees. Each assignment gets a token good for that assignment alone. The MCP facade offers `task`, `check` (feedback only) and `done`, over owner operations. A `check` result is feedback and is never acceptance.

**Why it matters:** Today a worker's launch config gives it `Read,Write` only and an empty strict MCP config, so it can't run the owner's tools. Acceptance must come only from a check that ran on exactly that commit (LAND's invariant), so the worker's own `check` mustn't count. A token reused across assignments would let one worker act for another.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TOOLS`, on branch `lab/TOOLS`, from `canon/main` at `125cd84`. Work only here.

**Layer:** Herzchen fleet for the tool facade and tokens; Otto product for which role may call what (PLAN.md D14, §11). The facade and the tokens go in `src/herzchen/fleet/tools/`, and the host implementations go in `src/herzchen/fleet/hosts/`. Otto keeps only what each role may call. The test: `tests/test_herzchen_boundary.py` must stay green (D14: no Otto vocabulary in `herzchen/fleet`; the tool names and the `otto` server name are passed in from Otto).

**Files you own:**
- `src/herzchen/fleet/tools/` (new package: the facade, the tokens, the check-versus-done rule);
- `src/herzchen/fleet/hosts/` (the Claude and Codex launch pins: the tool list and the MCP config for each host);
- the Otto side: the role table that says which role may call which tool, in `src/otto/` (find the closest existing role or host table; don't invent a second one);
- `tests/test_tools.py` (new).

**Do not touch:**
- `src/herzchen/fleet/runner/` (RUNNER owns it; the facade calls the runner, it doesn't change it);
- `src/herzchen/kernel/store.py` and `src/herzchen/domains/work/` (REVS is changing them now; don't edit them, and don't import anything REVS is about to change);
- `src/otto/portfolio/cli.py`, `status.py`, `execution_host.py`;
- `install/controller/`, `production/`, any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists** (PLAN.md §11):
- The Claude launcher, its tool list and its empty MCP config: `src/otto/agents/claude_cli.py` (the tool list near `:33`, the MCP config near `:445`, the sandbox near `:174-179`). Line numbers have moved since the plan was written; find them by content.
- The adapter contract HOSTKIT landed: `src/herzchen/fleet/hosts/` (`contract.py`, `codex.py`). Put the new pins behind it.
- The owner's tool surface: the owner operations the facade calls, through the owner socket (`src/otto/hostctl/service.py`, the lane allowlist; OWNERLANE will narrow it later, so call only operations that are already on it).
- The Claude launcher qualification: `src/otto/hostctl/adapters.py:27`.

**Your check.** Make it green and keep everything else green:
- `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_tools.py tests/test_herzchen_boundary.py`. Run tests with no env prefix (`pyproject.toml` sets pytest's `pythonpath`).
- Each acceptance test below fails on `canon/main` first (where the code doesn't exist yet, say so). Show both runs.
- Probe first, on both hosts (the row's "Probe first" item): a Claude MCP server reached from the sandbox, which has no network rule (`claude_cli.py:174-179`); a Codex MCP tool call under its sandbox (unconfirmed). If a live probe can't run here, the fake harness proves the path, and say so in your report: the probe result is a finding, not a blocker.
- Run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "TOOLS check" -- <cmd>`.
- Run the test files you changed or added; don't sweep the rest. The landing gate runs every test file that imports a module you changed, twice.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_tools.py tests/test_herzchen_boundary.py`

**Callers, including production:** if you change a signature, constructor argument or default, find every caller and update it. That includes `install/controller/`, where production startup lives: no unit test starts it, but the staging Otto does at landing (D17).

**Existing tests:** don't change what an existing test asserts to make your change pass. If one must change, keep the change in its own commit and give the reason in your report. It then goes to an Opus decision (D19) before landing. The `test_hostctl_serve` xhard test is red on canon already; don't try to fix it here (REDS owns it).

**Regression at the level the friction appears:** a worker's `check` result is recorded as feedback and never gates a landing.

**XHARD only:**
- invariant: A worker can't produce its own acceptance; a token is good for one assignment only.
- the plausible mistake to avoid: the `check` result leaking into acceptance, or a token reused across assignments.
- acceptance tests (from the row): `worker_check_never_counts_as_acceptance`; `token_scoped_to_assignment`; `fake_harness_uses_tools`.

**Deletion budget:** the new tool list replaces the `Read,Write` launch list for workers. Name what you removed or replaced, or say why nothing was.

**XHARD only: you lead, Haiku executes** (PLAN.md D10). Delegate almost all execution to the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high): exploring and reading code, writing tests, making edits, running checks.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**Working rules:** commit work in progress to `lab/TOOLS` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet (the `haiku-worker` sub-agent is already Haiku).

**When done:** commit to `lab/TOOLS` and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish.
