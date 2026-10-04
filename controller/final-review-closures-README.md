# Explicit continuation and supplemental lifecycle guard evidence

The ordinary `serve_manager_owner.py` remains the single Store writer. It
launches no role automatically. `report --continue-project` persists an
explicit request in the owner report and returns the supported command to
consume it:

```sh
<owner-python> manager_ctl.py manager-continue --report-key <original-report-request-key> --operation prepare
```

Prepare is the default. Status only reads the explicit request; dispatch is
separate. The report key selects an immutable report on the same manager and
project, including an explicit operator report submitted after a native turn.
The current task revision is checked before preparation. Report input and
callback instruction come from owner records, not from the continuation command.

The maintained continuation operation derives one callback ID from the manager
assignment and original report key. It verifies the retained successful native
anchor, preserves the same manager principal/generation/session, and prepares
the current task through the existing adoption/Due operations. Restart and
duplicate prepare read the same callback; they do not create another role or
provider effect. The legacy during-turn report route is unchanged.

The installed current manager occurrence is historically unknown. An explicit
new request may be prepared from the last verified same-manager anchor while
that original record remains unchanged. Dispatch is held until the lifecycle
owner resolves the current unknown; preparation is not retry permission.
Never use a new report key to replay an uncertain native effect.

`manager-continuation-service.patch` adds the ordinary IPC command and replaces
the unused in-memory report continuation flag with a durable command handoff.
Its controller baseline SHA256 is
`0402466075fbbba81b2eab36fe28f95eaa3b5c3e8b98fa7d1f70ff24657c1b31`.
Apply after graceful stop/custody release, install matching runtime modules,
and restart the same entrypoint in its supported managed-host profile:
`HERZCHEN_IN_PROCESS_COMMAND_FALLBACK=1`. Never hot-edit runtime.

Focused tests are `tests.test_manager_service_continuation.ManagerServiceContinuationTests`,
the existing canonical-report continuation test in `tests.test_execution_application`,
and `tests.test_execution_operations`. They use a fake provider in temporary
owner state. Live demonstration prepares and recovers the explicit request, and verifies held dispatch under the current unknown; no provider is called. A temporary-owner fake-provider test consumes the retained PA02 inspection action in the same session once and suppresses duplicate dispatch after restart.


The provider-free `advisor-followup-lifecycle` command requires the already
adopted PAUSED automation and exhausted existing pool. It reads persisted app
settings and calls the existing production `advisor-followup` dispatch adapter:
the live canonical paused guard suppresses dispatch. It then labels four inert
Due/resource projections. Active goes through `AdvisorExecution.wake_once` and
real `LimitService.reserve` on the unchanged exhausted pool, failing before a
provider capability; repeated unknown returns reconciliation. Pause is held by
the existing callback guard; stop and completion are suppressed by production
`DurableAttention.check`. Fixture restart rebuilds the delivery composition.
Actual service restart and paused-effect reconciliation have separate receipts.
The exercise does not activate an automation or create/reset allowance, and
these fixtures do not establish that an active app heartbeat fired. No separate
preview rule set participates in dispatch. Apply the continuation controller
patch first, then `advisor-lifecycle-service.patch` while the service is stopped.


Final review retains `required_evidence_gap` for actual supported host trigger
lifecycle. The command above manually enters the owner dispatch guard and its
other lifecycle rows are inert fixtures; they do not prove an app-host callback
or actual host pause/resume/stop/completion. Query the current composition with:

```sh
<owner-python> manager_ctl.py advisor-followup-lifecycle --schedule-id advisor-followup-27a599f6cadb57bb25884b7d9627 --decision-id decision-pa06-delivery-boundary-v1 --automation-id paused-project-advisor-effect-follow-up --operation host-capability
```

This reads the existing owner Due, pairing, persisted PAUSED settings and 3/3
pool before any effect, claim or reservation. `unsupported` with
`host_adapter_unavailable` means no owner-side HostTriggerPort was supplied.
An adapter object alone would not prove a callback; the returned evidence
status stays `required_evidence_gap` until separate actual host receipts exist.
The current supported app tool exposes view/update of automations, not a
provider-free native scheduler callback. Do not activate the exhausted advisor
or count the paused acknowledgement replay or these fixture tests as closure.
