# D19 decision: FAKECOMPLETE, tests/test_perch.py (the orchestrator, 17 Oct 2026)

**Decision: LAND.** No Opus call was made.

- The stand-in completion's request now cites the managed evidence the landing's accepted assessment recorded (with its stored digest) instead of the landing candidate: since LANDEVIDENCE, the product's completion gate verifies managed evidence, and the candidate was refused as `completion_evidence_unverified` on staging.
- C is now completed as well (the hook used to return None for it): the row asks for A, B and C to complete in dependency order, and C lands after its kill-recovery probe like the others. The call counts and request ids follow from completing three tasks instead of two.
- The worker checked first whether a passing `done` completes the task itself; it doesn't (it lands and accepts), so the stand-in for the manager's completion stays.
