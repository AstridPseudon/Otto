# SUP-03 canonical-owner seam (bounded finding)

Source inspected: published Otto `e6cdd8733529415a278eac2b2869ef33b7ecd17b`.
Runtime inspected: controller-installed `otto-local-candidate` wheel SHA-256
`19e8b35822a1bd6c2209cebd36abb5c87df2a0fd08b82aa28c258e7fee723201`.

`PortfolioLifecycleIntegration` currently receives constructor project snapshots
and changes only its private `_projects` map.  Its existing durable chain is
limited to `DurableAttention.prepare_host` / `acknowledge_host`, which persists
the typed schedule effect and host observation through the configured due-record
port.  It is not a canonical project lifecycle transition.

The published public owner surfaces available to Otto are:

- `FiniteWorkOperations.read("work.pending.read", ...)` and
  `FiniteWorkOperations.manager_inbox(...)` for read-only project/task views;
- `FiniteWorkOperations.execute("work.task.complete", ...)` for a governed
  task completion; and
- the `DurableAttention` due-record port for schedule effect persistence.

None exposes a command that atomically records a lifecycle intent
(`active`/`closing`/`blocked`/`terminal`), pins current project/task/manager
revisions and generation, emits the associated host effect, then accepts the
exact readback acknowledgement.  Adding that state to Otto or directly mutating
the owner store would create the prohibited second ledger/private-SQL path.

The required supported owner seam is therefore a serialized, owner-issued
operation with paired readback, for example
`work.lifecycle.transition` and `work.lifecycle.read`.  The transition must
return the Herzchen receipt and persisted typed effect; readback must return the
current project/task/manager refs, assignment generation, lifecycle state, and
effect acknowledgement.  SUP-03 should remain HALTED until that owner surface
is supplied.

This bounded change strengthens only the pre-existing local terminal gate:
all four evidence records now require their successful outcomes and nonblank
refs, while `task_completion` must carry a current project/task-pinned completed
or replayed result plus a typed logical-request receipt.  It does not claim a
canonical lifecycle write, owner acknowledgement after owner reopening, or live
automation execution.

Validated with the source tree plus the controller's installed Herzchen package:
`pytest -c /dev/null -q tests/otto` completed with `153 passed`.  The focused
SUP-03, host-bridge, and owner-bootstrap set completed with `29 passed`.
