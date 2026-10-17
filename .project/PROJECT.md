# PACKS: progress

Base: canon/main 163925e. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17T19:54Z | PK1 | merged 71163252a9aab2628fdd1ec604067943a05bfbd3 | +542/-145 | RolePackSelectorTests 6 passed; host-neutral defaults 15 passed; project-advisor context 6 passed; diff --check passed | Deleted 118 live instruction lines; Astra's three rounds found installed runtime root mismatch and dropped host/effective-context guidance, all fixed; 22 integration tests in test_role_context.py need the gate (Unix socket PermissionError at fixture setup).
2026-10-17T19:58Z | PK2 | merged 0710f2a4f4fba50bf4baf41a893e8a807bcf0134 | +154/-34 | test_megado_templates.py 4 passed/23 subtests; test_hostctl_skills.py 14 passed; diff --check passed | Relocated the staged Megado source (24 files/1,924 lines) to the canonical managed pack; left 101 static run-template lines for PK3 to resolve.
2026-10-17T20:04Z | PK4 | merged 25dcb7ee0e0b54bfdee91e016d57866a8b362f07 | +235/-1 | test_megado_templates.py 5 passed/26 subtests; diff --check passed | Added engineering code-task and Astrid journey/frame and film-edit templates; template origin now retains exact managed-source pin.

## Questions for the orchestrator


## Astra final review

Reviewed the merged project diff against the goal and deletion budget. Astra found two concrete defects; both are fixed in `c383807`: the immutable Megado provenance paths again match their retained source commit/digests (with regression assertions), and the role pack no longer advertises the unimplemented `route-project` or `run-worker-result` commands (with a regression check). Astra re-read that correction and confirmed both findings resolved with no further demonstrated defect. Earlier PK1 Astra findings—the installed runtime root, compatibility helper and host guidance, and complete responsibility in `effective-context`—were also fixed and re-reviewed before merge.

**Needs the gate:** `src/otto/portfolio/tests/test_role_context.py` has 22 owner-backed tests that fail at Unix socket fixture setup with `PermissionError`; `src/otto/portfolio/tests/test_d05_events_candidate_proof.py` has 5 tests blocked at the same socket setup. The focused non-socket role-pack checks and `src/otto/portfolio/tests/test_observability_contract.py` pass.

**Remaining scope:** PK3 is blocked on the requested §15 Opus decision about replacing the two Megado run templates' static profile bindings. PK5 and its cold-agent measurement are blocked by PK3. The `host_profiles.PROFILES` table and 101 static run-template lines therefore remain; this is outstanding deletion-budget work, not a defect in the merged tasks.

## Decisions

- **PK3 §15 decision approved by the orchestrator:** `tests/test_megado_templates.py::test_templates_are_json_and_match_the_host_profiles` may assert that both Megado run templates resolve their seven profile bindings from the pinned profile pack instead of carrying static values. The test intent—templates match the host profiles—remains unchanged.
