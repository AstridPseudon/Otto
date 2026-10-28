# Brief: PACKPARITY (normal, 0.5 focused day)

**Outcome:** Herzchen's managed pack provenance matches a recorded Astrid provenance record field by field without importing Astrid, and Herzchen source names no product above it. Make the inventory identity equal by construction, or document a precise justified difference. Move Otto authority and host path values into Otto callers so Herzchen holds no Otto-specific constants. Extend the boundary test to reject `otto`, `astrid`, and `Documents/Codex` in Herzchen source outside tests.

**Why it matters:** STAGE2 review finding 9 found the parity test is skipped because Astrid is unavailable, inventory identity differs without `ASTRID_SOURCE_STATE`, and the Herzchen usage contract embeds Otto authority and a `Documents/Codex` path. The boundary test currently checks only Otto imports and fleet names.

**Your lab:** created by the launcher from `canon/main`. Work only there.

**Layer:** Herzchen model. Keep reusable provenance and usage contract behavior product-neutral; Otto supplies its own constants at its boundary.

**Files you own:**
- `src/herzchen/packs/authoring.py`
- `src/herzchen/usage/contract.py`
- `tests/test_evidence_lifecycle.py`
- `tests/test_herzchen_boundary.py`
- the recorded Astrid provenance fixture, kept inline in the parity test (no Astrid import at test time)

**Other files:** you may edit direct Otto callers and focused tests needed to pass the removed constants into Herzchen, except running-task files below. List each additional file and why in your report.

**Do not touch:**
- `src/otto/portfolio/execution_host.py`, `src/otto/portfolio/worker_custody.py`, `src/otto/portfolio/manager_journey_service.py`, `src/otto/hostctl/project_service.py`, `src/otto/portfolio/project_services.py`, `src/otto/portfolio/owner_bootstrap.py`, and tests owned by active tasks;
- `production/`, any Store, `~/.otto`, `~/.codex`, or anything outside this lab.

**Build on what exists:** `src/herzchen/packs/authoring.py:80` defines the provenance identity; `:638-640` computes inventory identity from configured Astrid state or a fallback. `src/herzchen/usage/contract.py` defines the shared usage contract and currently embeds product authority and a host-specific path near its constants. Preserve the existing injection and validation behavior while making values explicit at the Otto boundary.

**Your check:** add tests that load the recorded provenance fixture without Astrid import, compare every provenance field, and fail on a doctored Herzchen file containing `Documents/Codex`; verify `grep -rn Documents/Codex src/herzchen` finds no source matches outside tests. Regression tests must fail on canon first and pass after the fix. Do not run the staging owner in the worker sandbox; the landing gate runs it if required.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_evidence_lifecycle.py tests/test_herzchen_boundary.py`

**Regression at the level the friction appears:** provenance parity with an offline recorded source plus product-neutrality boundary checks.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. **A long test runs to its end:** give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed (REDS and DISPATCH stopped at "30 seconds", 16 Oct). A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**

**When done:** leave changes uncommitted for the launcher and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish. Stop and ask (the `ask` route, or end your report with a question) if the brief contradicts the code.
