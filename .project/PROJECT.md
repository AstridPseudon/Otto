# PACKS: progress

Base: canon/main 163925e. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17T20:04Z | PK4 | merged 25dcb7ee0e0b54bfdee91e016d57866a8b362f07 | +235/-1 | test_megado_templates.py 5 passed/26 subtests; diff --check passed | Added engineering code-task and Astrid journey/frame and film-edit templates; template origin now retains exact managed-source pin.

## Questions for the orchestrator
2026-10-17T19:54Z | PK1 | merged 71163252a9aab2628fdd1ec604067943a05bfbd3 | +542/-145 | RolePackSelectorTests 6 passed; host-neutral defaults 15 passed; project-advisor context 6 passed; diff --check passed | Deleted 118 live instruction lines; Astra's three rounds found installed runtime root mismatch and dropped host/effective-context guidance, all fixed; 22 integration tests in test_role_context.py need the gate (Unix socket PermissionError at fixture setup).
2026-10-17T19:58Z | PK2 | merged 0710f2a4f4fba50bf4baf41a893e8a807bcf0134 | +154/-34 | test_megado_templates.py 4 passed/23 subtests; test_hostctl_skills.py 14 passed; diff --check passed | Relocated the staged Megado source (24 files/1,924 lines) to the canonical managed pack; left 101 static run-template lines for PK3 to resolve.

2026-10-17T20:04Z | PK4 | merged 25dcb7ee0e0b54bfdee91e016d57866a8b362f07 | +235/-1 | test_megado_templates.py 5 passed/26 subtests; diff --check passed | Added engineering code-task and Astrid journey/frame and film-edit templates; template origin now retains exact managed-source pin.

## Questions for the orchestrator

- **PK3 §15 decision:** May PK3 update `tests/test_megado_templates.py::test_templates_are_json_and_match_the_host_profiles` so the two Megado run templates stop carrying seven static profile bindings and instead resolve them from the new pinned profile pack? The current test explicitly asserts those static values. §15 requires an Opus decision when an existing test's expected behavior changes; no such decision is recorded here. PK3 has no committed implementation. Its draft tests were not accepted: the source scan was overbroad and there is no production change to validate yet. PK5 depends on PK3. PK4 is independent and continues.