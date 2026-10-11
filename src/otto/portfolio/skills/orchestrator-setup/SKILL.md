---
name: otto-orchestrator-setup
description: Request or inspect an Otto orchestrator's scoped enrollment for an existing chat, then verify its own identity and adopted project supervision. Use when a chat needs to become an orchestrator or its registration is unclear.
---

# Orchestrator setup

A conversation or coordination message does not register an orchestrator. Enrollment issues an authenticated identity; project supervision is a separate canonical adoption. Use the owner-provided installed `orchestrator_client_ctl.py` invocation, interpreter, connection locator, inbox and binding locator exactly as supplied. Start with `discover` and `status`; a missing installed connection requires the accountable owner's setup. Do not guess a module entrypoint, open the Store, borrow another role's binding, or create another owner service.

## Request and approval

If no binding has been issued, use the installed client's `request-enrollment` with `--owner-inbox PATH`, one stable `--request-key KEY`, `--conversation-ref JSON`, and `--project-id ID` for each requested project. Keep the scope finite and retain the returned request handle. A supplied conversation reference identifies the requested recipient; it is not proof of identity or authority. Recover a pending request with `request-status --request-id HANDLE` using the same connection's owner inbox; once bound, supply `--binding LOCATOR` to inspect an exact request on that client lane. An unchanged retry uses the same key and body; reconcile an unknown result before any new request.

The request grants no authority. Admission requires an existing authorized orchestrator's approval or trusted explicit human authorization, applied through the protected owner operation to the authenticated recipient binding. A requester cannot approve itself or supply a `human-approved` flag. Preserve authorization already given in the current task; do not ask for it again. Denied or pending requests remain unprivileged.

## Verify the issued binding

With the returned locator, use `--binding LOCATOR status`, then `--binding LOCATOR whoami`. Distinguish `unregistered`, `requested`, `assigned` and `revoked`; check `supervision_adopted` separately. Read back the exact principal, orchestrator assignment and generation, portfolio, conversation binding and project scope. Stop using revoked or mismatched bindings and retain the exact error for the issuing owner.

Use `--binding LOCATOR portfolio` to inspect the intended projects. An assigned orchestrator does not supervise a project until the canonical project relation names its assignment. Have the authorized owner apply any missing specific project adoption; do not substitute a chat acknowledgment. Once adopted, use `--binding LOCATOR effective-context --project-id ID` and `--binding LOCATOR read-manager --project-id ID` to verify current project context and manager bindings. A second orchestrator may share the existing portfolio without replacing its default orchestrator.

## Operate and receive blockers

Use only the scoped commands exposed by the installed client. `--binding LOCATOR read-help --project-id ID` reads retained issues; `--binding LOCATOR respond-help --project-id ID --request-key KEY --request JSON` submits the authorized response using the installed help schema. Choose a stable key for each distinct mutation and retain it for reconciliation; do not reuse it for a different response. Ordinary reads use fresh default handles; `request-status` reads an exact retained result rather than refreshing current state. Current identity, assignment, project scope and revocation checks apply on each newly executed call.

Track the exact issue, report and delivery handles. A persisted issue, transport acknowledgment, supervisor response and manager application are different facts. Verify that the intended supervisor receives the issue and the same manager adopts the response before claiming the blockage resolved. Retain unresolved delivery state if the host has no working notification transport; a readable mailbox or active assistant bridge does not establish unattended desktop notifications.

For ordinary project work, continue with the installed Otto orchestrator guide. Setup does not expand project authority, execution budgets or provider permissions.
