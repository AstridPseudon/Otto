# Brief: BOUNDARY (normal, 0.5 focused days)

Title: Herzchen imports nothing from Otto

**Outcome:** the Herzchen package (`src/herzchen`) imports nothing from `otto`. The usage stream and contract and `timing_from_receipt` move into Herzchen; Otto imports them from there. A test enforces it.

**Why it matters:** D14's import rule: the fleet and the model import down only, and nothing imports Otto. Today `src/herzchen/domains/work/usage.py:157-159` and `src/herzchen/adapters/host.py:29-30` import Otto.

**Your lab:** `~/Developer/otto-claude-host/labs/BOUNDARY`, on branch `lab/BOUNDARY`, from `canon/main` at `b68b3a4`. Work only here.

**Files you own:**
- `src/otto/agents/usage_capture.py`, `src/otto/agents/usage_contract.py` and `src/otto/portfolio/recovery_timing.py`: move into `src/herzchen/` (pick the package; the move, not a copy, so there is one copy);
- `src/herzchen/domains/work/usage.py` and `src/herzchen/adapters/host.py`, `src/herzchen/adapters/receipt.py`: point at the moved code;
- every Otto module that imports the moved names: update the imports only (the list is from `grep -rlE "usage_capture|usage_contract|timing_from_receipt|usage_accounting|adapters\.host|domains\.work\.usage" src tests`);
- `src/herzchen/kernel/tests/test_events_final_corrections.py` and `src/herzchen/kernel/tests/test_project_history.py` import `otto.portfolio.observability_views`: move those two tests out of Herzchen into `tests/` (they test Otto's views);
- `tests/test_herzchen_boundary.py` (new): `test_herzchen_imports_no_otto`, an AST scan of every `.py` under `src/herzchen`.

**Do not touch:**
- other tasks' files (STATUSREAD owns `src/otto/portfolio/dependencies.py`, `status.py` and `tests/test_portfolio_status.py`; HOLD, POOL, DISPATCH and ACT own `execution_host.py`);
- `production/`;
- any Store, `~/.otto` or `~/.codex`, and the running Otto service;
- `ottoctl` (do not run it, and never pass it `--help`);
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** move, don't re-implement. Keep every public name the same (only the module path changes).

**Your check.** Make it green:
- `test_herzchen_imports_no_otto` must FAIL on `canon/main` first; show that run, then the green run;
- the check command below, all green.

Check command: `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "BOUNDARY check" -- env PYTHONPATH=src:tests /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_herzchen_boundary.py tests/test_usage_accounting.py tests/test_usage_capture.py tests/test_usage_claude_streams.py tests/test_usage_contract.py tests/test_usage_late.py tests/test_usage_retained_native.py tests/test_recovery_timing.py tests/test_coordinator_host_contract.py tests/test_native_resume_trace.py`

Heavy commands go through `~/Developer/otto-claude-host/bin/otto-heavy`, as in the check command. Show the output of the red run and the green run in your report.

**Regression at the level the friction appears:** a Herzchen-only import (`import herzchen.domains.work.usage`) loads with Otto absent from `sys.modules`.

**Deletion budget:** the Herzchen-to-Otto import edges are the things removed (two files, and the two tests moved out). Name anything else you remove, or say "none".

**When done:** commit to `lab/BOUNDARY` (only the files you own; never `.brief.md`, `.worker.json` or `.worker.err`) and don't push. Report the commit, the red and green runs, what you deleted, and anything you couldn't finish.
