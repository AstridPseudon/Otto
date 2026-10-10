# Retained Events operator views

The maintained Otto entrypoint exposes seven read-only Events presets:
`overview`, `timeline`, `agents`, `tasks-reviews`, `blockers`, `usage`, and
`recovery`. Each request supplies the authorized project scope and, when
needed, a recorded-time range. The response retains projection coverage,
lag, snapshot identity, and keyset continuation. Reuse the returned snapshot
and cursor for the next page; refresh after a grant or projection-generation
change.

Overview is an attention and handoff page, not a live scheduler. It keeps the
responsible actor known when retained or explicitly unknown, and separates a
retained response from application and a native result from task acceptance.
Timeline shows recorded facts. Agents, Tasks/reviews, and Blockers page the
latest captured subject state immediately before exclusive `to`, including
carry-in responsibilities and issues. Overview combines period facts with a
separate `historical_state` section. Its opaque continuation advances both
streams and remembers a completed stream; pass it unchanged with the snapshot.
Unknown fields remain unknown. Historical active discovery uses bounded indexed
project-subject predecessor/transition seeks, preserves overlapping activity
after an in-period closure, and labels unknown interval candidates; current
heads never establish earlier activity. Recovery only points to retained facts
and inspection; it never launches, repairs, backfills, or gives stale
historical mutation advice.

Usage initially exposes known retained attempts and explicit metric
availability only. Missing metrics are unavailable, never zero. Events does
not calculate usage, cost, physical spans, or billing; those belong to the
separately queued Usage/cost successor.

Use `events detail` only with a facet reference returned by a page and its
original snapshot. Details remain authorization-checked, Evidence-linked when
available, and bounded. Legacy gaps, projection lag, unavailable Evidence,
and unknown actors remain visible. Do not infer stuck work from age or
completion percentage from mutable inventory.

The CLI needs an authenticated, injected `ObservabilityViews` facade and
grant; bare `python -m otto.portfolio.cli` does not open an owner or Store.
An installed owner host exposes the same parser, views and text rendering
through its protected `owner-context` / `events-read` operation. Submit a
finite owner-authoring envelope using that host's current protected sender:

```json
{"schema":"otto.owner-authoring-grant.v1","request":{"command":"owner-context","operation":"events-read","request_key":"unique-read-key","handle":{"view":"overview","limit":1,"format":"text"}}}
```

The host binds the authenticated current enrolled root and current project;
the caller cannot supply actor, project, domain or budget. For JSON use
`format:"json"`; for detail use `view:"detail"`, the returned `facet_id`,
original `snapshot`, and `max_detail_bytes` (up to 65536). Pages accept the
existing range, timezone, filters, cursor and snapshot inputs, up to 50 rows.
These reads do not start work, migrate, rebuild projections or accept tasks.

Projection maintenance persists exact JSONL byte/facet progress with projected
rows. A partial source position stays outside published snapshot coverage.
Arbitrary byte splits, including Unicode, are supported; final count/digest
verification streams the declared maximum 8 MiB manifest without retaining its
body, reports that verification I/O, and advances the checkpoint only on success.
