# Brief: FAILCLOSED (normal, 0.5 focused days)

**Outcome:** Close the three fail-open paths in the task row: admission stamps without `reviewed_digest` do not admit edited content; every missing-operator fallback refuses; and relative `MacWriteScope` exec allowances are refused. Keep valid owner paths working.

**Your lab:** `lab/FAILCLOSED`, on branch `lab/FAILCLOSED`, from `canon/main` at `5b4a7709ec6e89aba8f8d1f8fe3876f55ee728cf`. Work only here.

**Layer:** Otto product, except the shared work-admission policy in Herzchen. Keep Otto-specific operator identity and paths in Otto.

**Files you own:** `src/herzchen/domains/work/admission.py`, `src/otto/portfolio/herzchen_binding.py`, `src/otto/portfolio/project_folder.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/otto/agents/claude_cli.py`, and focused tests in `tests/test_operator_admission.py`, `tests/test_hostctl_serve.py`, and `tests/test_host_contract.py`.

**Other files:** Edit any additional caller or fixture directly required by these three outcomes, except the running-task files below. List each extra file and its reason in your report. Do not stop for a routine file widening.

**Do not touch:** `src/otto/portfolio/perch.sh`, `src/otto/portfolio/execution_host.py`, `ops/bootstrap/perch_stage2_owner.py`, `ops/bootstrap/perch.sh` (LABCAPTURE/KILLFENCE); `src/otto/portfolio/execution.py`, `src/otto/portfolio/manager_journey_service.py`, `src/otto/portfolio/successor_entry.py`, `src/otto/portfolio/successor_runner.py` (MANUALDISPATCH); `production/`; any Store, `~/.otto` or `~/.codex`; anything outside this lab.

**Your check:** Add focused regressions for all three behaviors. Show the relevant regressions fail on canon and pass after the change. Keep normal owner admission and hostctl paths green. Stage-2 `--fake` is an orchestrator run; do not run staging from this worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_operator_admission.py tests/test_hostctl_serve.py tests/test_host_contract.py`

**Regression at the level the friction appears:** An edited body with an old admission stamp is refused; each missing operator is refused; a relative exec allowance is refused.

**Deletion budget:** Remove the fail-open fallbacks and the relative-path allowance without weakening existing checks.

**Working rules:** Follow the Codex worker rules in `${TRANSFER_ROOT}/portfolio/ops/brief-template.md`: no commit or push, no staging Otto in the worker sandbox, use a long timeout for tests, and report any extra files. Any sub-agent is `spawn_agent` with `model: "gpt-6-luna"`.
