# FAILEDFENCE resume 2 (xhard)

The latest landing refusal is in `${TRANSFER_ROOT}/portfolio/ops/runs/FAILEDFENCE/land.log`. Fix the confirmed NEW failure:
`tests/test_manager_journey_service.py::ManagerJourneyWorkerWorkspaceTests::test_execution_control_uses_worker_schedule_as_execution_binding` (3/3 candidate, 0/3 BASE).

The failures in `tests/test_perch.py` and `tests/test_review_input_contract.py` are pre-existing on BASE; do not change those tests or their behavior. The required `tests/test_capacity_holds.py` focused check passed in your prior attempt. Make the smallest product fix for the new failure, add or update regression coverage as needed, rerun the focused check, and leave the lab ready for the launcher to commit.

Keep the prior scope and blocker: do not invent the missing TRIAGE worker-turn value or change `claude_adapter.py` for that absent decision. Follow the FAILEDFENCE brief and design, preserve its invariant, and report the fix and checks. Do not touch the active PARITYFIX worker's files (`tests/test_evidence_lifecycle.py`, `tests/fixtures/managed_source_provenance/record_astrid_provenance.py`, `tests/fixtures/managed_source_provenance/recorded_source.json`) or CAPTUREEDIT's landing files (`src/otto/agents/claude_adapter.py`, `tests/test_landing.py`).
