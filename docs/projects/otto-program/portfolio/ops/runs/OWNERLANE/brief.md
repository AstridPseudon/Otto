# Brief: OWNERLANE (normal, 0.5 focused days). Written by the manager 12:40Z; copy to the lab as `.brief.md` at launch.

**Outcome:** The owner lane admits only `save`, `show` and `read` for the portfolio command, and each of the four `("project", …)` entries is named with its caller or deleted. `show` and `read` from a client go through the owner lane, as `save` does. `ottoctl service run` sets up the project-history projection.

**Why it matters:** STAGE1 F6, F7 and F8b (`ops/reviews/STAGE1.md`). The manager checked `src/otto/hostctl/service.py:362-375`: `("portfolio", None)` runs any portfolio subcommand with `owner_authorized=True`, so a client can reach owner authority through any subcommand. `HostSession` opens the Store directly outside the owner (`owner.py:157-171`), and `read` breaks on `--portfolio` (`portfolio.py:80-90`).

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/OWNERLANE`, on branch `lab/OWNERLANE`, from `canon/main` at `2880f74`. Work only here.

**Layer:** Otto product (PLAN.md D14, §11). The owner lane and its allowlist are Otto's wiring. Herzchen must not gain Otto's names. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/otto/hostctl/service.py` (the `portfolio-operation` allowlist at `:362-375`);
- `src/otto/hostctl/owner.py` (`HostSession`, `:135` onward, and the direct Store open at `:157-171`);
- `src/otto/hostctl/portfolio.py` (the `--portfolio` read at `:80-90`);
- `install/controller/operating_service.py` (the history projection at `:55`, `store.configure_history_projection`);
- `tests/test_owner_lane.py` (new).

**Do not touch:**
- `src/otto/portfolio/cli.py`, `status.py` (A3FIX and others use them);
- `src/herzchen/*` (the Store's revision work is REVS's; don't change it);
- `src/herzchen/fleet/*`, `src/otto/hostctl/claude_cli.py` (TOOLS's files);
- `production/`, any Store, `~/.otto` or `~/.codex`;
- anything outside this lab.

**Build on what exists:**
- The owner's `save` path and its explicit allowlist check at `service.py:362-375`;
- the existing `HostSession` owner composition in `owner.py`;
- `tests/test_hostctl_ownersafe.py` and `tests/test_hostctl_portfolio.py`, which already cover the owner lane. Read them first; keep what they assert unless the row changes it.

**Your check.** Make it green and keep everything else green:
- The acceptance tests in `tests/test_owner_lane.py`, which must fail on `canon/main` first. Show both runs.
- `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_owner_lane.py tests/test_hostctl_ownersafe.py tests/test_hostctl_portfolio.py tests/test_herzchen_boundary.py`. Run tests with no env prefix (`pyproject.toml` sets pytest's `pythonpath`).
- Run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "OWNERLANE check" -- <cmd>`.
- Run the test files you changed or added; don't sweep the rest. The landing gate runs every test file that imports a module you changed, twice.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_owner_lane.py tests/test_hostctl_ownersafe.py tests/test_hostctl_portfolio.py tests/test_herzchen_boundary.py`

**Acceptance (from the row):**
- `admit` and `complete-task` sent through the owner lane are refused with `PermissionError`;
- `show` from `env -i` returns the saved tasks while staging is up (in tests: a show through the lane returns saved tasks);
- at rest, `history_checkpoint` equals the last append position.

**Callers, including production:** if you change a signature, a constructor argument or a default, find every caller and update it. That includes `install/controller/`, where production startup lives: no unit test starts it, but the staging Otto does at landing (D17).

**Existing tests:** don't change what an existing test asserts to make your change pass. If an expectation really must change, keep the change in its own commit and give the reason in your report. It lands only after an Opus decision (D19).

**Regression at the level the friction appears:** a client's `admit` through the owner lane is refused with `PermissionError`, and nothing is written.

**Deletion budget:** the four unnamed `("project", …)` entries are each named with a caller or deleted. Name which you deleted.

**Working rules:** commit work in progress to `lab/OWNERLANE` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet.

**When done:** commit to `lab/OWNERLANE` and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish.
