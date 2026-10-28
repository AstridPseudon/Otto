# Brief: LIMITFD (normal, 0.25 focused days)

**Outcome:** Reuse one `LimitService` per owner, including the other per-call sites in `owner_bootstrap.py`; 200 `role_runtime()` calls keep this process's descriptor count within +3. The stage-2 `--fake` perch records and passes the bound (orchestrator run; do not run staging from this worker).

**Your lab:** `lab/LIMITFD`, on branch `lab/LIMITFD`, from `canon/main` at `5b4a7709ec6e89aba8f8d1f8fe3876f55ee728cf`. Work only here.

**Layer:** Otto product. Reuse the existing owner service lifecycle and the shared `LimitService`; do not create a service per role call.

**Files you own:** `src/otto/portfolio/owner_bootstrap.py`, `tests/test_completed_occurrence_readiness.py` (it already exercises `role_runtime`).

**Other files:** Edit only additional callers or fixtures required by this outcome. List each in your report with the reason.

**Do not touch:** `src/otto/portfolio/perch.sh` and `src/otto/portfolio/execution_host.py` (LABCAPTURE and KILLFENCE); `production/`; any Store, `~/.otto` or `~/.codex`; anything outside this lab.

**Your check:** Add a regression that performs 200 `role_runtime()` calls and asserts descriptor growth stays within +3; run it red on canon and green after the fix. The stage-2 `--fake` check is an orchestrator run and belongs to the landing gate.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_completed_occurrence_readiness.py`

**Deletion budget:** Replace the per-call `LimitService` instances with one owner-scoped service.

**Working rules:** Follow the Codex worker rules in the template: no commit or push, no staging Otto in the worker sandbox, long test timeout, report any extra files. Any sub-agent is `spawn_agent` with `model: "gpt-6-luna"`.
