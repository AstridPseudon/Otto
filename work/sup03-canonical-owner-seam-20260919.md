# SUP-03 canonical owner seam (isolated implementation record)

Base provenance was Otto `e6cdd8733529415a278eac2b2869ef33b7ecd17b` and the
controller-installed wheel SHA-256
`19e8b35822a1bd6c2209cebd36abb5c87df2a0fd08b82aa28c258e7fee723201`.

The paired Herzchen source now exposes public
`ResponsibilityAssignments.transition_project(...)` and
`read_project_lifecycle(...)`.  The transition uses the existing Herzchen
command facade, transaction, `work.report.append`, and `work.revise` path.  It
persists the lifecycle intent, current project/task/manager refs, assignment
generation, evidence, and obligation on the existing project payload.  A
project remains `active` until a terminal transition verifies the managed task
is already `completed`; terminal then writes project lifecycle `completed`.

Otto forwards this surface as
`work.project.lifecycle.transition` / `work.project.lifecycle.read` through
`FiniteWorkOperations` and `OttoPortfolio`.  When `PortfolioLifecycleIntegration`
receives that owner client, its project cache is only a schedule projection:
each mutation first reads current owner refs/generation, submits the fenced owner
transition, and then records the exact schedule effect/readback acknowledgement
as a second owner transition.  No private SQL, additional ledger, canonical
database mutation, or live automation was used.

Isolated owner-to-host coverage proves: owner intent receipt, persisted typed
project transition, supported `automation_update` callback, exact readback, and
owner-persisted host-effect acknowledgement.  Separate owner tests cover stale
revision, foreign actor, pending task, successful completion, same-key replay,
changed-key conflict, and owner reopen/readback.

The canonical owner experiment is isolated.  Cleanup remains HALTED and no
acceptance or production closure is claimed.

## Follow-up implementation (2026-09-19)

The bounded seam identified above has now been implemented in the paired Herzchen owner source and routed through Otto. `ResponsibilityAssignments.transition_project()` and `read_project_lifecycle()` use the existing owner transaction path (`work.revise` plus `work.report.append`) and persist lifecycle intent, current refs, manager generation, evidence, and reconciliation obligation on the existing project payload. Otto exposes the finite `work.project.lifecycle.transition/read` operations and uses owner reads/transitions while retaining only a schedule projection locally.

The paired isolated validation passed 47 Herzchen work tests, 155 Otto tests, and 17 focused owner/SUP-03 tests. The isolated owner-to-host integration persists the intent/receipt, typed effect, exact host readback, and owner acknowledgement. No canonical owner database or live automation was touched. The paired wheels were built for isolated validation; publication/installation of the compatible pair remains a separate release gate.
