# PACKS: progress

Base: canon/main 163925e. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17T19:54Z | PK1 | merged 71163252a9aab2628fdd1ec604067943a05bfbd3 | +542/-145 | RolePackSelectorTests 6 passed; host-neutral defaults 15 passed; project-advisor context 6 passed; diff --check passed | Deleted 118 live instruction lines; Astra's three rounds found installed runtime root mismatch and dropped host/effective-context guidance, all fixed; 22 integration tests in test_role_context.py need the gate (Unix socket PermissionError at fixture setup).
2026-10-17T19:58Z | PK2 | merged 0710f2a4f4fba50bf4baf41a893e8a807bcf0134 | +154/-34 | test_megado_templates.py 4 passed/23 subtests; test_hostctl_skills.py 14 passed; diff --check passed | Relocated the staged Megado source (24 files/1,924 lines) to the canonical managed pack; left 101 static run-template lines for PK3 to resolve.
2026-10-17T20:04Z | PK4 | merged 25dcb7ee0e0b54bfdee91e016d57866a8b362f07 | +235/-1 | test_megado_templates.py 5 passed/26 subtests; diff --check passed | Added engineering code-task and Astrid journey/frame and film-edit templates; template origin now retains exact managed-source pin.
2026-10-17T20:46Z | PK3 | merged a93c79f9414477707c182f96aeefce4158fee987 | +892/-223 | test_host_contract.py 41 passed/23 subtests; test_host_neutral_defaults.py 19 passed; test_hostctl_bundle.py 26 passed; test_megado_templates.py 10 passed/26 subtests; test_manager_run_config_preflight.py 2 passed; diff --check passed | Moved live model/host defaults and duplicate role bindings into the pinned profile pack; templates carry stable profile resource pins; registration retains exact resolved choices and migrates pending legacy records. Astra reviewed the final diff with no actionable findings. `test_hostctl_cli.py` needs the gate (sandbox socket.bind PermissionError).

## Questions for the orchestrator


## Astra final review

Reviewed the merged project diff against the goal and deletion budget. Astra found two concrete defects; both are fixed in `c383807`: the immutable Megado provenance paths again match their retained source commit/digests (with regression assertions), and the role pack no longer advertises the unimplemented `route-project` or `run-worker-result` commands (with a regression check). Astra re-read that correction and confirmed both findings resolved with no further demonstrated defect. Earlier PK1 Astra findings—the installed runtime root, compatibility helper and host guidance, and complete responsibility in `effective-context`—were also fixed and re-reviewed before merge.

**Needs the gate:** `src/otto/portfolio/tests/test_role_context.py` has 22 owner-backed tests that fail at Unix socket fixture setup with `PermissionError`; `src/otto/portfolio/tests/test_d05_events_candidate_proof.py` has 5 tests blocked at the same socket setup; PK3's `tests/test_hostctl_cli.py` is blocked at owner service setup by sandbox `socket.bind` `PermissionError`. Focused non-socket role-pack and PK3 checks pass.

**Remaining scope:** PK5 and its cold-agent measurement remain. The profile table, duplicate Megado defaults, and static run-template bindings were removed in PK3; the approved §15 change preserves the test's intent by resolving all seven bindings from the pinned profile pack.

## Decisions

- **PK3 §15 decision approved by the orchestrator:** `tests/test_megado_templates.py::test_templates_are_json_and_match_the_host_profiles` may assert that both Megado run templates resolve their seven profile bindings from the pinned profile pack instead of carrying static values. The test intent—templates match the host profiles—remains unchanged.

## PK5 cold-agent acceptance

Prompt (provided as the complete role introduction, with no lookup): “Role=manager; responsibility from pinned role pack pin {pack_id:otto-roles, pack_version:1, source_revision:R, source_inventory_identity:I, resource_path:roles.json, resource_digest:D}; operating_guidance from that same exact pin; adopted project policy='Coordinate work and review receipts' source={authority:local,kind:dat.content.document,id:cfg,revision:rev-3}; tool entrypoint='python -m otto.portfolio.cli help --format text' source=that same cfg ref; available tools=[help, run-worker]; current task title='Ship onboarding fix', lifecycle='active'; model='gpt-5' and reasoning='high' from cfg; profile pin from cfg profile_pack {pack_id:profiles,source_revision:PR}; next_action='Review worker result for task T-4'. State what instructions, tools, source pins and next action you identify.”

Cold-agent answer: “Role=manager; responsibilities and operating guidance both come from the exact pinned `otto-roles` v1 source pin (revision R, inventory identity I, `roles.json`, digest D). Adopted project policy: ‘Coordinate work and review receipts,’ from local `dat.content.document` id `cfg`, revision `rev-3`. Tool entrypoint: `python -m otto.portfolio.cli help --format text`, sourced from that same cfg reference. Available tools: `help`, `run-worker`. Current task: ‘Ship onboarding fix’ (active). Model `gpt-5`, reasoning `high`, and profile pack pin `profiles` at source revision `PR`, all from cfg. Next action: review worker result for task `T-4`.”
