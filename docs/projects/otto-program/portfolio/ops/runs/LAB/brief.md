# Brief: LAB (xhard, 1.5 focused days)

**Outcome:** The lab lifecycle (D12) lives in Herzchen. Labs are APFS-cloned from a template (`node_modules` and `.venv` via `cp -c`, the editable-finder and shebang rewrite, the partial-create trap, and the dirty-tree refusal, using lab.sh's proven steps). Parking commits through `commit_local_checkpoint` (`execution_operations.py:79`). Sweeps and deletion follow Herzchen's capture-before-unlink rule (`authoring/writer_lease.py`). Labs live outside the line checkout, so the nested-workspace guard (`execution_host.py:345-349`) holds. Codex workers get workspace-write confined to their own lab (today they run `-s read-only`, `codex_cli.py:236`). Otto keeps only the policy of when to park and sweep.

**Why it matters:** Uncommitted worker output must never be discarded. Lost worker output is the failure this task prevents.

**Your lab:** `~/Developer/otto-claude-host/labs/LAB`, on branch `lab/LAB`, from `canon/main` at f49e17c. Work only here.

**Layer:** Herzchen fleet (PLAN.md D14). New code goes in `src/herzchen/fleet/labs.py`. Otto passes in its policy. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/herzchen/fleet/labs.py` (new);
- `tests/test_labs.py` (new);
- `src/herzchen/adapters/codex_cli.py`, only the sandbox setting near line 236 (workspace-write confined to the lab).

**Do not touch:** `src/otto/portfolio/execution_host.py` (POOL is landing changes there; you only read the guard at 345-349); `src/herzchen/fleet/__init__.py`, `src/herzchen/fleet/capacity.py` and `src/herzchen/adapters/host.py` (POOL's); `src/otto/hostctl/project_service.py` and `install/controller/` (POOL, ACT and CUSTODY); `production/`; any Store, `~/.otto` or `~/.codex`; anything outside this lab. Don't change existing assertions.

**Your check.** Make these green and keep everything else green:
- `two_workers_parallel`: two labs run at once, each edits its own tree, neither touches the other's or the line checkout;
- `refuses_uncaptured_removal`: removing a lab with uncommitted work is refused;
- `sweep_commits_orphan`: a sweep commits orphaned work instead of discarding it;
- `park_resume_same_tree`: parking then resuming returns the same tree;
- (ASTRA0) Claude and Codex launched through the production adapters into two labs: each edits its own tree, and neither can edit the other's or the line checkout.
- Regression tests must fail on canon first; show both runs.

Run tests with no env prefix: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`. Also run every test file that imports a module you changed, each file alone, once (the landing gate runs them twice).

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_labs.py`

**XHARD only:**
- invariant: uncommitted work is never discarded;
- the plausible mistake to avoid: a sweep or park that works only on clean labs. Test a dirty lab first.

**XHARD: you lead, Haiku executes** (PLAN.md D10). Delegate almost all execution to the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`): exploring and reading code, writing tests, making edits, running checks. Keep the design, the invariant check, the review of each result (`git diff`, the test tail) and the final commit and report. Each sub-brief is self-contained. In your report, list each sub-agent: what it did, and whether you corrected it.

**Callers:** if you change a signature or default, find every caller and update it.

**Deletion budget:** lab.sh retires afterwards (DELETE). Name what your new code replaces, if anything.

**Working rules:** commit work in progress to `lab/LAB` as you go; never run `git stash`; never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`. Don't use sleep or timers; nothing in this environment can wake you later.

**When done:** commit to `lab/LAB` and don't push. Report the commit, the check runs (red, then green), the net lines by file, the sub-agents and what you corrected, and anything you couldn't finish.
