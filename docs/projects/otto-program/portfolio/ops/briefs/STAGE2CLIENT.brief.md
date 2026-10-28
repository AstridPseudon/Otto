# STAGE2CLIENT (xhard, 0.75 focused days)

**Outcome:** A fresh install delivers the manager client it advertises, stage 2 runs to completion, and worker-marker waits fail on a retained terminal manager failure while the owner remains alive.

**Why it matters:** Stage 2 hung on canon because registration advertised `home/bin/ottoctl`, installation never created it, the scripted manager failed, and B was never dispatched. The harness must report that retained failure rather than wait forever.

**Your lab:** `~/Developer/otto-claude-host/labs/STAGE2CLIENT`, on branch `lab/STAGE2CLIENT`, from `canon/main`. Work only here.

**Layer:** Otto product and staging harness. Product installation and registration custody belong in `src/otto/hostctl/`; the stage marker wait belongs in `ops/bootstrap/perch.sh`.

**Files you own:**
- `src/otto/hostctl/cli.py` — `cmd_install` currently writes installation config and receipt (~216); `cmd_register` computes the advertised client path (~411).
- `ops/bootstrap/perch.sh` — stage-2 worker marker wait (~421).
- `ops/bootstrap/perch_fake_claude.py` — fake manager requires and invokes the advertised client (~101 onward).
- `tests/test_hostctl_bundle.py`, `tests/test_hostctl_cli.py`, `tests/test_perch.py` — installation/registration and stage-2 regression coverage.

**Other files:** You may edit any directly required caller, fixture, or test except files under Do not touch. Report each extra path and why.

**Do not touch:**
- No other task is running, so no task-owned files are excluded.
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**Build on what exists:** Reuse `cmd_install` and `cmd_register` in `src/otto/hostctl/cli.py`, plus the existing fake-manager entrypoint check in `ops/bootstrap/perch_fake_claude.py`. Install the actual staged client before registration and reject registration if the advertised entrypoint is missing. Make marker waits observe retained terminal failure state without a timeout.

**Your check:** Add a fresh-install test that runs the delivered client through the owner-started fake turn (no test-created `ottoctl`, no mocked invocation), and requires A and B to settle before C dispatch. Cover missing-entrypoint registration refusal and retained terminal failure while the owner is alive. Run the focused changed test files; stage 2's full outside-sandbox check will be requested by the manager after commit.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_bundle.py tests/test_hostctl_cli.py tests/test_perch.py`

**Regression at the level the friction appears:** Fresh installation through the real delivered client, followed by stage 2's A/B settlement before C dispatch; retained manager failure exits the marker wait.

**XHARD only:**
- **Invariant:** Installation and registration custody: the registered manager entrypoint exists and is the client actually delivered by installation; a retained terminal manager failure cannot leave an owner alive with an indefinite worker-marker wait.
- **Plausible mistake to avoid:** Do not create or mock `ottoctl` in tests, add a harness shim, or add a time limit. Those hide the installation gap or mask failure state.

**Deletion budget:** No new mechanism; replace the indefinite marker wait on retained terminal failure with a state-based failure.

**Working rules:** Follow the brief template's Codex rules. Never run staging-owner tests inside the worker sandbox; the manager will run the full stage-2 check outside it. On Codex, leave the work for the launcher to commit. For xhard work, lead and delegate execution to Luna sub-agents using `spawn_agent` with `model: "gpt-6-luna"`; review their diffs and checks against the invariant.
