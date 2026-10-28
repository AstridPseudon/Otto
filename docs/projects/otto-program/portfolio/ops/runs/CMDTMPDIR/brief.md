# Brief: CMDTMPDIR (normal, 0.5 focused days)

**Outcome:** A bound command facade removes its `herzchen-command-*` temp folder when its transport closes and when the process exits, including error paths; a facade that is never bound creates no folder. The temp census and gate orphan check report any folder left by a run.

**Why it matters:** The command transport leaves temp folders behind; over time this exhausted disk space and forced an emergency sweep.

**Your lab:** Launcher creates this from current `canon/main`; work only there.

**Layer:** Herzchen runtime. Keep temp directory ownership and cleanup in `src/herzchen/command_ports.py`; Otto-specific wiring stays in Otto.

**Files you own:** `src/herzchen/command_ports.py`, `tests/test_tools.py`, and directly required tests for the temp census or gate orphan check.

**Other files:** Edit any file the outcome directly requires, except Do not touch; explain each in your report.

**Do not touch:** PINALL-owned files while PINALL runs: `src/herzchen/fleet/custody.py`, `src/otto/agents/claude_adapter.py`, `src/otto/agents/claude_cli.py`, `src/otto/agents/owner_runtime.py`, `src/otto/portfolio/execution.py`, `src/otto/portfolio/execution_host.py`, `tests/test_capacity_holds.py`, `tests/test_capacity_pool.py`, `tests/test_claude_manager_admission.py`; `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on what exists:** `src/herzchen/command_ports.py:499` creates the `herzchen-command-*` directory, `_OwnerService.close` removes the socket, and `_close_owned_services` is registered with `atexit` at line 491. Preserve the ownership checks around socket deletion and extend cleanup to the directory. Add the close/process-exit regressions in `tests/test_tools.py`.

**Your check:** Cover a bound facade closed normally, process exit without explicit close, error cleanup, and an unbound facade creating no folder. Run `tests/test_tools.py` with a private `TMPDIR`, counting the matching folders before and after.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_tools.py`

**Regression at the level the friction appears:** A full tools test run leaves no `herzchen-command-*` folder in its private `TMPDIR`.

**Working rules:** Follow the Codex normal rules in the manager brief template. No `ottoctl`; never stash or switch commits; leave changes uncommitted for the launcher. Give long test commands a long timeout and let them finish. Do not run a staging-owner test in the worker sandbox.
