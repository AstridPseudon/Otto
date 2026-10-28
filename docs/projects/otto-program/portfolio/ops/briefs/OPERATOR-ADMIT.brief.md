# Brief: OPERATOR-ADMIT (xhard, 1.5 focused days)

**Outcome and invariant:** The operator is the user of every Otto project. The owner admits a revision only after running its own macOS LocalAuthentication presence check; requests never choose the write actor. The owner stays curator and acting actor. Keep `admit` out of `OWNER_PORTFOLIO_COMMANDS`, bind lane writes with `bound_actor`, and preserve the owner curator role.

**Authoritative decision:** The oracle decision was recorded in the manager's `ops/reviews/ORACLE-ADMIT.md`; its acceptance contract is reproduced below because that ops file is not present in task labs.

**Acceptance:**
1. Registration sets the project creator to the operator. Tasks checked in by the host have no admission stamp and dispatch refuses them.
2. Dedicated owner-lane `admit` with an approving injected prover admits the task, records operator as `admitted_by`, and permits dispatch.
3. A declined, absent, or timed-out prover refuses admission and leaves Store byte-identical.
4. With no writes, refuse host-lane `portfolio admit`; `save --actor <operator>` or `save --actor <project creator>` on every lane with `bound_actor_mismatch`; forged presence fields in a direct owner-lane request; and `admit` through manager lane or worker facade.
5. `complete-task` remains refused on owner lane.
6. Each admission writes one log line with task, revision, review, prover result, and outcome.
7. Probe on the real Mac: an agent session sends `admit` with no person present; it must time out and refuse. Report explicitly if this machine cannot support the probe.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/OPERATOR-ADMIT`, branch `lab/OPERATOR-ADMIT`, based on current `canon/main` (now `cc716ece81423f221f664ece0150f83d0cbad501`, after CONV landed). Work only here.

**Layer:** Otto product and Herzchen work-domain binding. Keep owner command and macOS presence check in Otto; preserve the admission invariant in Herzchen.

**Files you own:** `src/otto/hostctl/config.py`, `cli.py`, `register.py`, `owner_bootstrap.py`, `service.py`, new `presence.py`; `src/otto/portfolio/herzchen_binding.py`, `admit.py`; `src/herzchen/domains/work/orchestration.py`; `tests/test_owner_lane.py`, `tests/test_admit.py`, new `tests/test_operator_admission.py`.

**Other files:** You may edit other files directly required for this outcome, except files listed under Do not touch. Report each such file and why required.

**Do not touch:** `ops/bootstrap/staging.sh`, `tests/test_hostctl_cli.py`, and files owned by any other task running when you start. Also do not touch `production/`, any Store, `~/.otto`, `~/.codex`, Codex's projects, vision, Native5, or anything outside this lab.

**Check:** Add regression coverage for each acceptance item, including no-write/byte-identical refusal and the real-Mac no-presence probe. Show regression red on canon and green in the lab. Run changed and new test files. Never run `ottoctl` or pass it `--help`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_owner_lane.py tests/test_admit.py tests/test_operator_admission.py`

**Working rules:** Never stash, check out another commit, or commit. Leave work for the launcher to commit. Run long tests to completion with a long timeout. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`. Stop if this corrected brief still contradicts the code.
