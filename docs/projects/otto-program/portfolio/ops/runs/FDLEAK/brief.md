# Brief: FDLEAK (xhard, 1.0 focused days)

**Outcome:** The owner does not leak a command socket per call, and a failed launch does not spin.

**Why it matters:** During the staging stage-2 fake launch, the owner opened roughly 40 `herzchen-command-*/owner.sock` listening sockets per second until `EMFILE` killed its command and status threads before dispatch. The owner must keep serving dispatch traffic without descriptor growth.

**Your lab:** Create/use the task's lab on branch `lab/FDLEAK`, based on the current `canon/main`. Work only there.

**Layer:** Herzchen fleet and Otto product owner dispatch. Fix the actual repeated facade construction/retry path; keep the invariant true for the owner session.

**Files you own:**
- `src/herzchen/command_ports.py`
- `src/herzchen/fleet/dispatch.py`
- `tests/test_command_dir_cleanup.py`
- `tests/test_fleet_dispatch.py`

**Other files:** You may also edit any other file your outcome directly requires, except files under “Do not touch”. List each additional file and why in your report. Do not stop to ask for a file.

**Do not touch:**
- files owned by running workers (none currently);
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex's projects, vision and Native5, or anything outside this lab.

**Build on what exists:** `command_ports._start_service` creates an owner service and socket for a facade; `_activate_transport` activates an existing service; `FleetDispatcher.dispatch` and `dispatch_ready` perform readiness and launch. Trace the owner's pump/readiness/status/admission path to find the repeated facade construction and immediate retry loop, then reuse session facades or close them deterministically and wait for a relevant input change or scheduled pump before retrying.

**Your check.** Add a regression test that counts this process's descriptors before and after 500 owner request or pump cycles, including a failing launch, and asserts the count stays flat within a small constant. Assert a failing launch is attempted at most once per input change. Run focused tests and the stage-2 fake check if the environment allows; the landing gate runs staging verification outside the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_command_dir_cleanup.py tests/test_fleet_dispatch.py`

**Regression at the level the friction appears:** Repeated owner dispatch cycles including a failing fake launch retain a bounded descriptor count and do not spin; stage 2 `--fake` no longer shows `EMFILE`.

**XHARD only:**
- invariant: the owner's descriptor count is bounded by its live sessions, not by how many calls it serves;
- plausible mistake to avoid: raising the descriptor limit or relying on finalizers so the leak still grows under load.

**Deletion budget:** Remove or replace the per-call facade construction and immediate failed-launch retry mechanism that create the unbounded sockets and repeated attempts.

**Working rules:** Never run `git stash`, check out another commit, or use a clone of the live Store/install. Never wait with a monitor, sleep loop or background job; run checks in the foreground. Keep staging isolated under its existing staging root. Give long checks a long timeout and let them finish. If a test fails with `sandbox_apply: Operation not permitted`, report it for the landing gate.
- **On Codex (Luna or Sol):** You can't commit; leave work in the lab for the launcher to commit. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**XHARD only: you lead, a cheaper model executes** (PLAN.md D10). Delegate almost all execution: exploring and reading code, writing tests, making edits, running checks. On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** Leave changes for the launcher to commit. Report the commit, the check runs, what you deleted, and anything you couldn't finish. Stop and ask if the brief contradicts the code.
