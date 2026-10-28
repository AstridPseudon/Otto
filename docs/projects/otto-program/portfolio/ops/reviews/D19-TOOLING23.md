# D19 decision: TOOLING23, tests/test_bootstrap_gate.py (the orchestrator, 17 Oct 2026)

**Decision: LAND.** No Opus call was made.

- `test_temporary_service_owner_left_before_the_landing_is_logged_not_refused` becomes `test_temporary_service_owner_under_another_root_is_ignored`: the gate no longer compares a before and after snapshot of every temp root (TOOLING21); it scans only its own private root (`OTTO_LAND_TMPDIR`, `/tmp/l.XXXXXX`), so an owner elsewhere (another session's, an orchestrator investigation's) isn't reported at all. That is the row's change: two landings were refused on 17 Oct for owners that weren't theirs.
- The orphan-named test now plants the owner under the landing's own root and asserts the gate used a short private root; its expectation that the orphan is named and refused is unchanged.
