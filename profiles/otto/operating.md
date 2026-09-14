# Otto operating profile — pending intake and manager admission

This profile is the OTT-03 manager-facing entry point. Use the public
`otto.portfolio` operations over the accepted Herzchen work-operation binding:

```text
python -m otto.portfolio.cli help
```

Create a rough idea with `create_pending` or use the same operation with
`open_project=True` / the CLI `--open`. If no template is selected, the
canonical work handler supplies the built-in blank starter. A selected
template is an explicit name or versioned object; invalid selections must be
rejected before creation. The result carries the canonical durable project
reference and receipt, plus an exact open status (`opened`, `occupied`,
`not_requested`, or recovery/unsupported detail).

Pending is an ordinary Herzchen work record with a sparse title/outcome,
curator, why-pending text, document/link references, revisit information, and
unknown JSON fields preserved by the canonical handler. It is not a task,
manager, allowance, session, accepted result, or launch. Reopening reads the
same durable reference. Repeat the same request ID to recover the recorded
canonical result; changing inputs under an existing request ID is an error.

Use `revisit` or `satisfied_prerequisite` to create attention/readiness only.
They do not activate, dispatch, or allocate work. A manager separately calls
`admit` with one of `admit`, `investigate`, `merge`, `park`, or `drop`, and
frames outcome, recipient, route, and authority. `assign_roles` records one
parent, one accountable manager, and bounded executor(s). `handoff` is an
explicit replacement operation and must carry the parent obligation plus
evidence and consumption references.

The portfolio facade has no Otto-private database, SQL, queue, scheduler, or
duplicate event/session engine. If the accepted Herzchen work binding is not
installed, operations return an explicit unavailable result. Host launch,
live session, Runtime, and Astrid consumer behavior are outside this profile;
the proposed EX-HOST boundary is an intended host/adapter boundary, not
delivered OTT-03 behavior. Astrid consumer cutover remains deferred.

Preserve the P01 custody and operating guidance. This profile adds only the
OTT-03 intake surface and does not grant authority to merge, publish, deploy,
transfer control, or alter parent accounting.
