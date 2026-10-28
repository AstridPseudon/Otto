# D19 decision: POLICYPIN, tests/test_fleet_custody.py, tests/test_evidence_status_owner_facade.py (the orchestrator, 17 Oct 2026)

**Decision: LAND.** No Opus call was made.

- `tests/test_fleet_custody.py`: the foreign-token refusal still answers `error: owner_unavailable` (unchanged); the test now also asserts its `detail` names the exception and its message (`LookupError: assignment has no active dispatch record`). The worker's version changed the error code itself to the Python type name; I kept the stable code (54ef6ad) and put the name in the detail: a type name isn't an API code, and a domain error's own `code` still passes through.
- `tests/test_evidence_status_owner_facade.py`: new cases only (the landing refusal's reason is visible in the detail; the generic fallback stays). The new case was aligned with the same rule.
- The policy change itself (identity plus content binding, `local_assessment_policy.py`) is covered by new tests; no existing expectation of the policy changed.

## Addendum (after the get_revision fix)

- `tests/test_local_assessment_composition.py`: extended to assert, through the serialized reader, that a lifecycle-only revision still binds and a changed task content refuses; no existing expectation removed. Still LAND.
