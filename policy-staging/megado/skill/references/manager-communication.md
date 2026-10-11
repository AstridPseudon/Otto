# Manager communication policy

This is the default communication policy for every newly created manager.

- Continue ready work autonomously. Do not wait for the next hourly supervision turn to advance an independent task, coordinate a worker, or record a result.
- Use canonical Otto records for routine bookkeeping: launches, findings, decisions, failures, completions, receipts, blockers and next actions belong in the owner records and run evidence.
- Coordinate routine execution directly with assigned workers and peer managers. Do not send routine unsolicited progress, launch, finding or completion updates to the root or user.
- The root pulls one consolidated portfolio summary hourly. An hourly pull is a reporting boundary, not a work gate.
- Submit an operational blocker through canonical `request-help` to the adopted project supervisor as soon as owner action is required. Retain the issue and delivery receipt before returning; advance independent work. Routine progress remains for the portfolio pull. An urgent user decision or imminent material loss also warrants immediate escalation.

Current adopted project directions specify the supervisor and supported delivery route; never infer delivery from a local file or final text. If the tool itself fails, preserve its exact failed handle and use the supplied supported fallback once, reporting unavailable delivery honestly. Apply the authenticated response before same-manager continuation.

## Help, context and continuation

Use `request-advice` for project judgment when the current adopted advisor is
enabled. Use `request-help` for an operational blockage such as a missing worker
route. Include the problem, impact, concrete evidence, requested decision and
return condition so the recipient can act from the current context. Advice is a
suggestion; it does not grant authority or turn into an owner prohibition.

The maintained setup/result and role introduction supply the current project,
task, assignment, generation, mandate, adopted resources and conversation
references. Refresh those bindings after a role replacement. A missing
destination is unresolved, and a host-only action remains host custody. Read a
retained delivery receipt before retrying an unknown send. After a response is
actually applied, use the existing same-manager continuation and record the
next action; do not create a new request merely to continue.

For command discovery, invoke the exact `tool_entrypoint` emitted by the
current introduction and inspect its adopted configuration provenance. Use
that bound client for help and setup reads; do not replace it with a repository
wrapper or guess a Python module installation.
