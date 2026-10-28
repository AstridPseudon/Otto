# Brief: CLIARGS (normal, 0.5 focused days)

**Outcome:** Maintained manager commands send only operation-specific arguments, distinguish absent values from recovery requests, preserve required/unknown-field refusal, and apply this to route and execution control.
**Why it matters:** Valid manager requests currently fail when irrelevant null fields are forwarded.
**Your lab:** Launcher creates this from current `canon/main`; work only there.
**Layer:** Otto dispatch and manager client.
**Files you own:** `src/otto/hostctl/manager_client.py`, `src/otto/portfolio/manager_journey_client.py`, `src/otto/portfolio/manager_journey_service.py`, `tests/test_shared_manager_client_routing.py`, `tests/test_manager_journey_command.py`, and directly required tests.
**Other files:** Edit any additional file directly required by the outcome except Do not touch; report each.
**Do not touch:** `src/otto/hostctl/owner.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/otto/hostctl/cli.py`, `src/otto/hostctl/serve.py`, `src/otto/portfolio/reviewed_activation.py` (SESSIONFD owns these); `production/`, Stores, `~/.otto`, `~/.codex`, Codex configuration, or anything outside this lab.
**Build on:** Existing command parsing, `ManagerJourneyClient`, route and execution-control service methods named in the task row.
**Your check:** Drive parser → launched client → authenticated service for reroute, retry, read, recover and resume. Cover valid forms, missing required values and unknown/foreign fields; do not weaken assertions.
**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_shared_manager_client_routing.py tests/test_manager_journey_command.py`
**Regression:** End-to-end argument forwarding across the actual command path.
**Working rules:** Follow the Codex rules in `ops/brief-template.md`; no stash, commit, push or `ottoctl`; leave commit to launcher.
