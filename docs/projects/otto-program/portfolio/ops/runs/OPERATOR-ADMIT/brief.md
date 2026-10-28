# Brief: OPERATOR-ADMIT (xhard, 1.5 focused days)

**Outcome:** The operator principal is the user of every project Otto creates. A revision is admitted only by the owner, writing as the operator after its own presence check. No lane request chooses its write actor. The oracle decision in `ops/reviews/ORACLE-ADMIT.md` is the detailed specification and acceptance contract; follow its seven acceptance items and invariant.

**Why it matters:** Agents must not be able to admit their own work by posing as the project creator. Admission must require a presence check performed by the owner itself.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/OPERATOR-ADMIT`, on branch `lab/OPERATOR-ADMIT`, from `canon/main` at `589d184888ffbd8e25f61eb9fa7eb7a40e19ec3d`. Work only here.

**Layer:** Otto product and Herzchen work-domain binding. Keep the owner command and macOS presence check in Otto; preserve the admission invariant in Herzchen.

**Files you own:**
- `src/otto/hostctl/config.py`, `cli.py`, `register.py`, `owner_bootstrap.py`, `service.py`, and new `presence.py`
- `src/otto/portfolio/herzchen_binding.py`, `admit.py`
- `src/herzchen/domains/work/orchestration.py`
- `tests/test_owner_lane.py`, `tests/test_admit.py`, and new `tests/test_operator_admission.py`

**Other files:** You may change other files directly required by this outcome, except files listed under Do not touch. Report each such file and why it is required.

**Do not touch:**
- `src/otto/hostctl/config.py`, `cli.py`, `register.py`, `ops/bootstrap/staging.sh`, and `tests/test_hostctl_cli.py` while STAGESETUP is running;
- files owned by any other task running when you start;
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects, vision and Native5, or anything outside this lab.

**Build on what exists:** Keep `admit` out of `OWNER_PORTFOLIO_COMMANDS`; bind lane writes with `bound_actor`; use an owner-side, injectable LocalAuthentication prover that is never sourced from a request. Preserve the owner curator role and make the operator the project creator.

**Your check.** Implement regression coverage for every oracle acceptance item, including the no-write/byte-identical refusal cases and the real-Mac no-presence probe. Run changed and new test files, showing regression red on canon and green in the lab. Do not run `ottoctl` or pass it `--help`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_owner_lane.py tests/test_admit.py tests/test_operator_admission.py`

**XHARD invariant:** Only the operator principal is a project's user; the owner writes as it only after a presence check the owner runs itself; a lane request never names its write actor. Avoid putting the check in the client, reading presence from a request, adding `admit` to the generic owner command set, or leaving `--actor` unbound.

**Working rules:** Never run `git stash`, check out another commit, run `ottoctl`, or pass it `--help`. Never wait with a monitor, sleep loop, or background job you then wait on. On Codex, don't commit; leave work for `run-task.sh` to commit. Run long test commands to completion with a long timeout. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave the work for the launcher to commit. Report the commit, checks, behavior removed, and anything unfinished. Stop if the brief contradicts the code.
