# Current-project operating setup

Use the interpreter and installed command path from your current role
introduction. That command's `operating-setup --help` describes these fields.
The examples use `ottoctl` as a placeholder for that exact entrypoint.
Candidate source is available after owner installation; it does not upgrade a
running controller.

1. Select existing project, assignment, task and mandate revisions from current
   owner reads. Create/import project content with `project-authoring`, and
   author/adopt directives with the existing direction operations first.
2. Preview with `operating-setup --operation preview --request-key KEY --setup
   JSON`. Preview reads adopted resources, effective directions and actual
   conversation bindings, resolves defaults, and validates the same readiness
   used by apply. It writes nothing and calls no provider.
3. Apply the unchanged input with `--operation apply`. This prepares missing
   role occurrences through `prepare_role` and commits one canonical setup
   document. It creates no assignment, budget, direction adoption or provider
   effect. `--operation read` returns the current `setup_ref`, configuration,
   role introductions, and readiness.
4. For ordinary changes, preview with `--expected-setup-ref REF`, then use
   `--operation update` with the same ref/input/key. Update appends an immutable
   revision under the existing content owner's revision check. Stale refs fail.
   Role replacement is an owner assignment operation first; update then selects
   its current assignment, generation, mandate and conversation.

The input is JSON (substitute exact refs, never names guessed from sessions):

```json
{
  "schema": "otto.operating-composition.v1",
  "mode": "manual",
  "defaults": {"timeout_seconds": 1200},
  "roles": {
    "manager": {
      "assignment_ref": {"authority": "OWNER", "kind": "wrk.assignment", "id": "ASSIGNMENT", "revision": "rev-2"},
      "generation": 1,
      "task_ref": {"authority": "OWNER", "kind": "work.task", "id": "TASK", "revision": "rev-1"},
      "mandate_ref": {"authority": "OWNER", "kind": "dat.content.document", "id": "MANDATE", "revision": "rev-1"}
    }
  },
  "advisor_policy": {"mode": "disabled", "reason": "Explicit owner supervision"},
  "acceptance_tasks": []
}
```

Each role may instead select an existing schedule ID. Supported role keys are
`manager`, `orchestrator`, and `project_advisor`; one manager is required.
The legacy `otto.operating-setup.v1` schedule-only object remains supported.
`defaults` may supply model, reasoning and timeout_seconds; a role's explicit
values override them. Omitted model/reasoning follow its adopted configuration.
Omitted instructions, optional context and session binding follow its adopted
BASE and current assignment. Required effective directions remain pinned even
when optional context is overridden. Preview/read expose the resulting
selection provenance and directive context in existing role introductions.
The profile defaults to workspace-write for manager and read-only otherwise;
the adopted mandate must authorize it. Exact model/provider qualification and
fresh periodic advisory sessions use the supervision/provider surface.

Autonomous mode requires an existing orchestrator, acceptance task refs, a
supported help-delivery route, and explicit advisor policy. Enabling advice
requires its existing assignment, bound conversation, canonical pairing and
allowance. Workstream leads retain their existing task assignments. Portfolio
coverage and recurring intervals remain with their existing owning operations.
The manager command is bound to its project; setup input cannot select a
different project, owner, authority or acceptance budget.

Partial apply returns a stage, immutable request ref and committed role handles.
Inspect those exact handles and repeat only the same operation/key/input to
complete preparation. A lost successful reply returns its original immutable
setup revision and committed receipt, plus the current head; replay cannot
overwrite a later update. Preview never settles a retained occurrence.
UNKNOWN, in-flight, paused and stopped occurrences remain held until their
supported reconciliation. Setup never retries a provider effect. An adopted
setup is distinct from dispatch, acceptance and task/project completion.

The owner-bound API is
`ExecutionApplication.compose_operating_setup(project_ref=..., operation=...,
setup=..., request_key=..., expected_setup_ref=...)` and
`read_operating_setup(project_ref=...)`. Use the existing owner bootstrap to
issue that application; the configuration file supplies input, not authority.
