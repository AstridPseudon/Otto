# INVARIANTS resume 1

Continue the six-invariant gate. The criteria were already recorded in the task row at `${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md` and the observations are in `${TRANSFER_ROOT}/portfolio/ops/audits/coverage/JOURNEY-COVERAGE.md` (M2a–M2e). Do not invent a different contract. Apply these six claims to recorded evidence after every scenario step; missing evidence must fail and name the step:

1. Every launch has exactly one dispatch, and the exact content launched was admitted.
2. Every turn settles exactly once; every hold or fence is released or names its next action.
3. Ordinary writes (metadata, edits, admissions, lifecycle) never block later work.
4. No process, socket, lab, or temp root outlives the run; descriptors stay flat per operation.
5. Completion cites the accepted evidence.
6. Store history is gapless.

Use the task row's detailed journeys: Store ordering and exact launch counts; content edits and re-admission; competing workers and manager reserve; approval and denial; failed-launch recovery; captured settlement; owner resources. Keep scenario-specific assertions only when no invariant expresses them; fold duplicate stage-2 checks into the invariants. Stage 2 `--fake` must report all six after every step. Add valid and doctored recorded-evidence tests for every invariant, including missing evidence.

The initial worker report's two changes are uncommitted and useful; preserve them unless the completed evidence-based implementation supersedes them. The full check's `ps`/staging failures are sandbox restrictions; do not weaken or stub process checks. Report any outside-sandbox check needed. Keep the existing check command and leave work uncommitted for the launcher.

Do not touch current workers' files: PINALL owns `src/herzchen/fleet/custody.py`, `src/otto/agents/claude_adapter.py`, `src/otto/agents/claude_cli.py`, `src/otto/agents/owner_runtime.py`, `src/otto/portfolio/execution.py`, `src/otto/portfolio/execution_host.py`, `tests/test_capacity_holds.py`, `tests/test_capacity_pool.py`, `tests/test_claude_manager_admission.py`; INTEG-PROCLIFE-PL1 owns `src/herzchen/fleet/custody.py`. Your direct outcome files remain available. Rebase was requested before this resume.
