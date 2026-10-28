# Brief: LIVENESS (normal, 0.5 focused days)

**Outcome:** Make shared-owner liveness explicit and actionable: clients fail fast with closure details, owner-down/restart events reach `otto wait`, `otto status` gives a reason and restart command for non-running states, and unrequested owner exits are non-zero.

**Why it matters:** A closed owner currently can leave a client waiting indefinitely, and sessions learn of outages only by message. Clear state and restart guidance lets clients recover without guessing.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LIVENESS`, on branch `lab/LIVENESS`, from `canon/main` at `5a99f2f183264f903df84cff6f1df54b971f33df`. Work only here.

**Layer:** Otto product. New code belongs under `src/otto/`.

**Files you own:** The relevant tests among `tests/test_hostctl_ownersafe.py`, `tests/test_ask_socket_wait.py`, `tests/test_hostctl_service_routing.py`, and `tests/test_otto_show_status.py`; and the directly exercised `src/otto/` modules needed for this outcome.

**Other files:** You may edit other files the outcome directly requires, except files under “Do not touch”.

**Do not touch:**
- REDS2's `tests/test_events_final_corrections.py`, `tests/test_project_folder_scale.py`, `tests/test_hostctl_serve.py`, `src/otto/portfolio/tests/test_worker_occurrences.py`, `tests/test_supervisor_direction_client.py`, `tests/test_hostctl_cli.py`, `tests/test_current_manager_selector.py`, `tests/test_help_completion_regression.py`, `tests/test_manager_correction_planning.py`, `tests/test_manager_journey_command.py`, `tests/test_manager_reentrant_ipc.py`, `tests/test_manager_service_continuation.py`, or `src/otto/hostctl/execution_host.py` and directly exercised production files in REDS2's scope;
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex's projects, vision and Native5, or anything outside this lab.

**Build on what exists:** `src/otto/hostctl/service.py:57-84` reads closure information and formats owner/client next-step advice; `src/otto/hostctl/service.py:89-115` interprets published status; `src/otto/hostctl/owner.py:135` composes the owner session. Trace the existing wait and status paths before extending them.

**Your check.** Add/extend the four acceptance selectors in the most relevant existing test files listed above. Run the regression tests red on canon first, then green after the fix. Run only these task-owned test files:

**Check command:** `otto-heavy --weight 1 --purpose "LIVENESS" -- /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_ownersafe.py tests/test_ask_socket_wait.py tests/test_hostctl_service_routing.py tests/test_otto_show_status.py`

**Regression at the level the friction appears:** Closed owner → client failure and useful restart guidance; owner-down event through wait; service exit status based on requested versus unrequested closure.

**Working rules:** Never run `git stash`, check out another commit, run `ottoctl`, or pass it `--help`. Never wait with a monitor, sleep loop, or background job. If a question blocks you, decide it within this brief or end your report with the question.

**On Codex:** You can't commit; leave work in the lab for `run-task.sh` to commit. Long tests must run to completion with a long timeout. A test failing with `sandbox_apply: Operation not permitted` needs a sandbox of its own; note it for the landing gate. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave the work for the launcher to commit. Report the commit, red and green checks, fixes made, and anything unfinished. Stop and ask if the brief contradicts the code.
