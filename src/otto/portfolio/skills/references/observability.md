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
Timeline shows recorded facts. Agents, Tasks/reviews, and Blockers are thin
facets over the same bounded history. Recovery only points to retained facts
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
