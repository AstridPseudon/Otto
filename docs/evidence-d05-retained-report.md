# D05 retained implementation report

## Delivered

- Added bounded `dat.evidence.reclaim.preview` and
  `dat.evidence.reclaim.apply` operations over existing FND identities,
  receipts and events; no new table, registry or storage framework.
- Added project-scoped exact-pin selection across current and historical
  managed Evidence revisions, explicit cutoff/cursor/page bounds, dependency
  and recovery holds, stale-preview revalidation, safe managed-file removal,
  interruption reconciliation and honest tombstones.
- Returned separate managed-byte and cache-byte accounting. Cache removal is
  explicit and bounded by the supplied cache root; no universal filesystem
  reclaim claim is made.
- Extended the Evidence resource pack with lifecycle presets, retention
  template/policy, maintained workflow guidance, and deterministic safety
  checks for lifecycle preset tampering. Existing 1.0 readers and older
  pinned 1.1 readers remain readable; lifecycle admission requires the
  lifecycle presets. Disable withdraws new mutation admission without
  deleting existing data, citations or history.
- Added Evidence triggers and retention guidance to the main Otto, manager
  and worker skill entry points.

## Verification

`PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_evidence*.py'`

Result: 14 tests passed. The fixtures cover actual managed-file removal,
historical versions, shared/in-flight/unknown holds, stale-input rejection,
interrupted purge reconciliation, tombstones, replay, and disable preservation.
Python compilation and `git diff --check` also passed.

## Limits and unresolved responsibility

The installed Astrid public discovery/loader is not available in this candidate
environment (`astrid` is not importable), so installed pack adoption and the
D06 connected journey remain host-owned follow-up work. The broader repository
suite was not a reliable completion signal: it encountered unrelated advisor
and execution-host failures and later hung in an initial-manager transport
test; the focused Evidence suite is the applicable verification here.

No owner state, controller runtime, publication, push, release, deployment or
acceptance operation was performed.
