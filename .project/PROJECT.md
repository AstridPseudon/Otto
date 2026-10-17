# PACKS: progress

Base: canon/main 163925e. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

## Questions for the orchestrator
2026-10-17T19:54Z | PK1 | merged 71163252a9aab2628fdd1ec604067943a05bfbd3 | +542/-145 | RolePackSelectorTests 6 passed; host-neutral defaults 15 passed; project-advisor context 6 passed; diff --check passed | Deleted 118 live instruction lines; Astra's three rounds found installed runtime root mismatch and dropped host/effective-context guidance, all fixed; 22 integration tests in test_role_context.py need the gate (Unix socket PermissionError at fixture setup).
2026-10-17T19:58Z | PK2 | merged 0710f2a4f4fba50bf4baf41a893e8a807bcf0134 | +154/-34 | test_megado_templates.py 4 passed/23 subtests; test_hostctl_skills.py 14 passed; diff --check passed | Relocated the staged Megado source (24 files/1,924 lines) to the canonical managed pack; left 101 static run-template lines for PK3 to resolve.
