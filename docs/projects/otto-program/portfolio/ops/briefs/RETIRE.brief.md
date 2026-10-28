# Brief: RETIRE (normal, 1.0 focused days)

**Outcome:** One general way to retire any work record or document membership with a reason and successor, preserve history, make retirement terminal for readiness and dispatch, render successors in show/status, and refuse save dependencies on retired tasks with the successor named. A completed record cannot be retired into another record.

**Why it matters:** Retirement replaces the current lifecycle-only withdrawal path so superseded, merged, duplicate, abandoned, and done-elsewhere work can be represented without losing history or leaving ambiguous dependencies.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/RETIRE`, on branch `lab/RETIRE`, from `canon/main`. Work only here.

**Layer:** Herzchen model. Core retirement semantics belong in the work domain; Otto owns the `otto retire REF --reason ... --by REF` command and its display/save wiring.

**Files you own:**
- `src/herzchen/domains/work/model.py`
- `src/herzchen/domains/work/module.py`
- `src/herzchen/domains/work/sheet.py`
- `src/herzchen/domains/work/batches.py`
- `src/otto/portfolio/cli.py`
- `src/otto/portfolio/show.py`
- `src/otto/portfolio/status.py`
- `src/otto/portfolio/save.py`
- `src/otto/portfolio/dependencies.py`
- `tests/test_otto_show_status.py`
- `tests/test_otto_save.py`
- `tests/test_portfolio_status.py`
- `tests/test_portfolio_dependencies.py`
- `tests/test_herzchen_boundary.py`

**Do not touch:**
- other tasks' files;
- `production/`;
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** inspect `src/herzchen/domains/work/module.py`'s `withdraw` and revision operations, `sheet.py`'s withdraw facade, batch replay in `batches.py`, and Otto's existing show/status, save, and dependency paths. The task row in the program tasklist is the acceptance contract.

**Your check.** Add focused regressions for project/task/gate and document membership retirement, successor display, terminal readiness/dispatch, refusal of dependencies on retired tasks, completed-gate refusal, and preserved history. Do not weaken existing assertions. Run the task-owned tests and `tests/test_herzchen_boundary.py`. Regression tests should fail on canon first where feasible.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_otto_show_status.py tests/test_otto_save.py tests/test_portfolio_status.py tests/test_portfolio_dependencies.py tests/test_herzchen_boundary.py`

**Regression at the level the friction appears:** retiring a superseded project and then attempting to save a dependent task must display the successor and refuse the dependency without redirecting it.

**Deletion budget:** replace the lifecycle-only `withdraw` operation and its Otto command/display path with reasoned retirement; retain compatibility only where existing callers require it.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. Never wait or use background jobs you then wait on. Run tests in the foreground. If more files are needed within this row's outcome and no running worker owns them, end your report with the exact paths and why; the manager can grant routine scope widening.

- **On Codex (Luna):** you can't commit; leave work in the lab and the launcher commits it. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own; list it in your report for the landing gate. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** leave changes for the launcher to commit and report the commit, focused check runs, regression red/green evidence, what was replaced, and anything incomplete.
