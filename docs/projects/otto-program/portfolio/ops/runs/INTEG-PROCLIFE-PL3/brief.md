# Brief: INTEG-PROCLIFE-PL3 (xhard, 1.0 focused days)

**Outcome:** Reconcile PL3 (`f9d18e3`) with PINALL: only an empty process group releases physical capacity; a live replacement leader remains held. Give the production metadata reader durable owner-recoverable custody and close the public `run_turn()` custody contract. Preserve FAILEDFENCE disposition behavior.

**Why it matters:** Capacity must not be released while a replacement process can still be running, and every production launch path must remain recoverable after owner death.

**Your lab:** created by the launcher from current `canon/main`; work only there.

**Layer:** Herzchen fleet for reusable custody and runner behavior; Otto keeps production launch wiring.

**Files you own:** `src/otto/portfolio/execution_host.py`, `src/otto/agents/codex_host_reader.py`, `src/herzchen/fleet/hosts/contract.py`, `tests/test_capacity_holds.py`, `tests/test_codex_host_reader.py`, `tests/test_host_contract.py`, `tests/test_worker_custody.py`.

**Other files:** you may edit another file directly required by this outcome, except files under “Do not touch.” Explain each added path and why in your report.

**Do not touch:** `ops/bootstrap/perch.sh` and `tests/test_perch.py` (DISTURB owns these); `src/herzchen/fleet/runner/runner.py` and `tests/test_runner.py` (recently landed PL2); `production/`, any Store, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**Build on what exists:** `ProcessExecutionHost._group_state` and `_reconcile_hold` in `src/otto/portfolio/execution_host.py` (around lines 890-907) decide physical capacity; `CodexAppServerThreadReader` in `src/otto/agents/codex_host_reader.py` (around line 170) owns the production metadata reader; `run_turn()` in `src/herzchen/fleet/hosts/contract.py` (around line 335) is the public launch contract. Preserve current FAILEDFENCE disposition semantics and PINALL's live-group holds.

**Your check:** Keep both reused-PID capacity tests held; only the empty-group case releases. Prove reader cleanup uncertainty survives owner death in recoverable custody, and prove the public `run_turn()` custody contract. Keep existing assertions intact unless an explicit D19 decision permits a change. Run the four focused test files below and `git diff --check` to completion.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_capacity_holds.py tests/test_codex_host_reader.py tests/test_host_contract.py tests/test_worker_custody.py`

**Regression at the level the friction appears:** A live replacement leader in the same process group remains held; metadata-reader cleanup uncertainty is recovered after owner death; a launched process through public `run_turn()` has durable custody.

**Invariant:** Capacity releases only when the recorded group is provably empty, and every launched process has durable custody.
**Plausible mistake:** Releasing a live same-group replacement or omitting a production launch path.
**Surfaces:** Over-admission or an untracked escapee.

**Working rules:** Never stash or check out another commit. Don't run `ottoctl`; never pass it `--help`. Never wait or poll. Run tests to completion with a long timeout. On Codex, leave work for the launcher to commit; don't work around read-only `.git`. Any sub-agent uses `spawn_agent` with `model: "gpt-6-luna"`.

**XHARD only: lead, cheaper model executes.** Delegate almost all execution to Luna sub-agents with `spawn_agent` and `model: "gpt-6-luna"`; keep the design, invariant review, and final report for yourself. Sub-briefs must name exact files, functions, constraints, command, and expected report. Run sub-agents in parallel only when their files do not overlap. Never commit or push.
