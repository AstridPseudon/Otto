# Brief: LANEFIX (normal, 0.5 focused days)

**Outcome:** Lane and IPC listing never crash the owner when a file vanishes mid-poll, and answered request/response pairs are pruned after a retention window, in the lanes, client lanes and manager-ipc listings. Today a pruned pair closes the owner, and answered pairs pile up (138 MB in one lane, 4.1 GB of IPC on 15 Oct).

**Why it matters:** The owner globs these listings about 20 times a second. A file that disappears between the glob and the stat kills it.

**Your lab:** `~/Developer/otto-claude-host/labs/LANEFIX`, on branch `lab/LANEFIX`, from `canon/main` at f49e17c. Work only here.

**Layer:** Otto product (takeover). Nothing in Herzchen.

**Files you own:**
- `src/otto/hostctl/lanes.py` (the row cites lines 128-138);
- `src/otto/portfolio/client_lanes.py` (the row cites line 204, a stat inside the sort key);
- the manager-ipc listing (find where answered pairs are listed; grep for the same stat-in-sort pattern);
- one new test file, `tests/test_lane_listing_robustness.py`.

**Do not touch:** other tasks' files, especially `src/otto/portfolio/execution_host.py`, `src/otto/hostctl/project_service.py` and anything under `install/controller/` (POOL is landing those); `production/`; any Store, `~/.otto` or `~/.codex`; anything outside this lab. Don't change existing assertions.

**Your check.** Make it green and keep everything else green:
- `vanished_request_never_stops_owner`: a listing where a file disappears between glob and stat returns the rest and doesn't raise;
- `answered_pairs_pruned_after_window`: answered pairs older than the window are removed, newer ones kept;
- `pending_relays_kept`: unanswered pairs are never pruned.
- Regression tests must fail on canon first; show both runs.

Run tests with no env prefix: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`. Also run every test file that imports a module you changed, each file alone, once (the landing gate runs them twice).

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_lane_listing_robustness.py`

**Callers:** if you change a signature or default, find every caller and update it.

**Deletion budget:** the pruning replaces nothing; say so in your report.

**Working rules:** commit work in progress to `lab/LANEFIX` as you go; never run `git stash`; never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`.

**When done:** commit to `lab/LANEFIX` and don't push. Report the commit, the check runs (red, then green), the net lines by file, and anything you couldn't finish.
