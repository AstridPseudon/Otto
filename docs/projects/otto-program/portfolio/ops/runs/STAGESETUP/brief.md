# Brief: STAGESETUP (normal, 0.75 focused days)

**Outcome:** Setting up a project for dispatch takes commands rather than hand edits: an owner repo map command, `project register` writes task `otto.plan` repo and branch from the bundle tasklist, the run policy assessment scope comes from bundle `run.json` and appears in `show`, and `staging.sh` names the 100-byte socket-path limit before startup fails.

**Your lab:** `~/Developer/otto-claude-host/labs/STAGESETUP`, on branch `lab/STAGESETUP`, from `canon/main` at `589d184888ffbd8e25f61eb9fa7eb7a40e19ec3d`. Work only here.

**Layer:** Otto product/bootstrap tooling. New code belongs in `src/otto/hostctl/` and `ops/bootstrap/` as appropriate.

**Files you own:**
- `src/otto/hostctl/config.py`
- `src/otto/hostctl/register.py`
- `src/otto/hostctl/cli.py`
- `ops/bootstrap/staging.sh`
- `tests/test_hostctl_cli.py`
- `tests/test_hostctl_bundle.py`
- `tests/test_staging_startup.py`

**Other files:** You may edit any other file directly required by the outcome, except files under Do not touch; explain each in your report.

**Do not touch:**
- Files owned by running tasks: AUTODISPATCH2 owns `src/otto/portfolio/manager_journey_service.py`, `src/otto/hostctl/product_service.py`, `tests/test_manager_journey_service.py`, and `tests/test_fleet_dispatch.py`; MGR landing is in progress. Keep changes disjoint.
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects/vision/Native5, or anything outside this lab.

**Build on what exists:** `config.py:new_installation` already validates and persists `repositories`; extend the existing hostctl CLI/config path to update it. `register.py` builds each task's `custom.megado` metadata from the bundle tasklist; preserve that parser and add the declared repo/branch in `otto.plan`. Use bundle `run.json` for assessment scope and expose it through existing `show`. `ops/bootstrap/staging.sh` has `guard_root` and checks the root before writing; validate the derived socket path there with a clear limit and fix guidance.

**Your check:** Add focused command-level tests proving all four setup requirements, including clear refusal for a too-long socket path. No hand-editing config or task records in the canary path.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_cli.py tests/test_hostctl_bundle.py tests/test_staging_startup.py`

**Regression at the level the friction appears:** The canary project setup commands and an actionable socket-path refusal.

**Working rules:** Never run `git stash`; don't check out another commit in the lab; don't run `ottoctl`; never wait or poll. Run tests in the foreground. On Codex, don't commit or work around read-only `.git`; the launcher commits on exit. Give long tests a long timeout. Any sub-agent is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Report commit, checks, and anything incomplete; leave edits in the lab for the launcher.
