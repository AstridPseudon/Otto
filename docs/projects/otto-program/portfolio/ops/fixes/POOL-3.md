# POOL: the rebase onto canon needs a resolution (resume message)

Your commit 7dc9c70 is good. The landing gate couldn't rebase it onto `canon/main` 198883c (HOSTKIT). The conflict is one add/add: `src/herzchen/fleet/__init__.py`. HOSTKIT and you both created that package file.

**Do this:**
1. In `lab/POOL`, rebase onto `canon/main` (198883c). When it stops on `src/herzchen/fleet/__init__.py`, keep **both** sides: HOSTKIT's exports (the `hosts` package and its contract names) and yours (the capacity names). Commit the resolution.
2. Check the rest of the rebase with the same care as the first: HOSTKIT moved the Codex host to `src/herzchen/fleet/hosts/`, and your pin hook (`process_pin`) is in `src/herzchen/adapters/host.py` and `src/otto/agents/claude_adapter.py`. Make sure the pin still reaches the Codex and Claude turns after the move, and that `test_capacity_pool.py` still passes.
3. Run the checks again on the rebased commit: `tests/test_capacity_pool.py`; `tests/test_herzchen_boundary.py`; your startup test; `tests/test_bounded_project_host.py` (ten runs, the flaky one); and every test file that imports a module you changed, each alone, twice. Use `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>` from the lab.
4. Don't change any existing assertion. Report the commit, the runs, and the net lines by layer.

**Your lab:** `~/Developer/otto-claude-host/labs/POOL`, on `lab/POOL`. Commit to `lab/POOL`, don't push.
