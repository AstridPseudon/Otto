# Brief: SCRIPTMGR (xhard, 1.0 focused days)

**Outcome:** Stage 2's stand-in acts as a scripted manager through the installed client: it completes landed A and B with citations to their accepted decision evidence, and recovers killed worker C through `execution-control recover`. Remove `install_fake_completion`; each completion belongs to an owner-started manager turn and the final status has no holds or names each hold's next action.

**Why it matters:** The current harness patches the product completion port and directly finishes work, so the journey can pass without the manager path working. Recovery must also settle the retained fence after a worker is killed.

**Your lab:** Launcher creates this from current `canon/main`; work only there.

**Layer:** Otto proof harness and portfolio worker custody. Keep the manager journey through the installed client; fix `src/otto/portfolio/worker_custody.py` only if the SIGKILLed-worker recovery record itself is not accepted.

**Files you own:** `ops/bootstrap/perch_stage2_owner.py`, `ops/bootstrap/perch_fake_claude.py`, `src/otto/portfolio/worker_custody.py`, `tests/test_perch.py`, `tests/test_worker_custody.py`, and directly required tests.

**Other files:** You may edit any other file the outcome directly requires except Do not touch; report each with its reason.

**Do not touch:** SESSIONFD-owned `src/herzchen/command_ports.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/otto/hostctl/owner.py`, `src/otto/hostctl/cli.py`, `src/otto/hostctl/serve.py`, `src/otto/portfolio/reviewed_activation.py`, and its tests; `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab. `PERCHUNTIME` and `HOLDSTATUS` also target `tests/test_perch.py`; don't edit files they own if they start while you run.

**Build on:** The current `install_fake_completion` and owner-started manager turn in `ops/bootstrap/perch_stage2_owner.py`; the stand-in manager turn in `ops/bootstrap/perch_fake_claude.py`; retained terminal recovery in `src/otto/portfolio/worker_custody.py`.

**Your check:** Add a regression that SIGKILLs a held worker and recovers its retained terminal record through the real manager command. Assert completion events are emitted only by a manager turn started by the owner, citations use accepted-decision evidence, and the final holds are empty or name their next action. Demonstrate new regressions fail on canon first, then run focused tests without weakening assertions. Stage 2 `--fake` needs process access and writes outside the lab; do not run it in the worker sandbox. The landing gate/orchestrator runs it outside.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py tests/test_worker_custody.py`

**Regression at the level the friction appears:** Stage 2 `--fake` completes A and B through owner-started manager turns and recovers C through the manager command.

**Invariant:** Completion and recovery happen through the owner's own manager path. Plausible mistake: Calling the product's completion function directly from the stand-in with owner authority, even under a different helper name.

**Working rules:** Follow the Codex XHARD rules in the manager brief template. Do not run staging-owner tests in the worker sandbox. The stage-run is run outside the worker sandbox by the orchestrator. No commit or push; the launcher commits when you exit.
