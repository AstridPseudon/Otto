# Operating setup and help routing

This is the point-of-use guide for the maintained `operating-setup` and help
commands. The owner records, adopted role resources and current assignment are
the source of truth; this guide does not create authority, a schedule or a
second context store.

## Setup and activation

Use the exact `tool_entrypoint` in your delivered role introduction to find the
bound command surface. Its `tool_entrypoint_source` identifies the adopted role
configuration. Invoke that command as emitted, including its interpreter and
absolute installed path; do not substitute a repository wrapper or an
uninstalled Python module. The host records this command in the selected role
configuration before role preparation. `operating-setup read` is a read-only view. `prepare`
validates the existing role schedules, BASE/resource revisions, conversations,
execution contracts, advisor policy, help route and acceptance scope without a
provider call. `activate` uses the adopted setup only after the same readiness
check and does not itself dispatch a manager.

The result has two distinct help capabilities:

- `help.advice` is project judgment from the current paired advisor and is
  available only when advisor policy is explicitly enabled.
- `help.operational` is for a blocked route and names the current orchestrator
  destination. `ready` means supported automatic delivery; `host_only` means a
  host must perform or inspect the transport; `missing_destination` means no
  current recipient exists; `unavailable` means the configured automatic route
  is not ready.

The result also includes the current role introductions, exact assignment and
generation, conversation identity, adopted resources, continuation guidance
and recovery guidance. A role replacement requires a fresh current assignment,
generation and conversation; an old introduction or destination does not route
new work.

## Advice versus operational help

Use `request-advice` for a consequential project question when the adopted
advisor policy is enabled. Use `request-help` when work is operationally
blocked, such as an unavailable worker route. Both requests should carry the
problem, impact, concrete evidence, requested decision and return condition.
Advice is a suggestion and does not become an owner prohibition. Operational
help does not accept work or grant a new budget.

`read-help` reads the retained issue and exact delivery receipt without sending
anything. `respond-help` is available to the current bound recipient. The
recipient response remains separate from resolution; the manager records what
was actually applied with `resolve-help`, which retains the existing
same-manager continuation.

Independent useful work may continue while help is pending. A missing
destination is unresolved, not a successful delivery. An `unknown` delivery
means the effect may have happened: read the exact retained receipt and owner
state before any retry. A new request key, a copied conversation ID or a role
name in prose never proves a new destination or authorizes replay.

## Recovery examples

```sh
# Read current setup; this never dispatches.
ottoctl operating-setup --operation read

# Reconcile a retained help delivery; do not resend it.
ottoctl read-help --delivery-id DELIVERY_ID

# After the current response is understood, record application and continuation.
ottoctl resolve-help --request-key RESOLVE_KEY --issue-id ISSUE_ID \
  --evidence '[{"observation":"current route verified"}]' \
  --next-action 'Continue the independent ready task'
```

If the destination is missing, repair or adopt the current owner route through
the supported owner operation and submit no delivery until the route is visible
in setup readiness. If a role was replaced, refresh the setup and use its new
assignment/generation/conversation; do not continue an old response. If the
host is the only remaining actor, perform only the supported host transport or
receipt inspection and return the observed result to the bound manager.

The canonical closeout path remains `finish-project`; a successful transport,
advice response or setup activation is not project acceptance, publication,
deployment or terminal settlement.

Owner changes to a pending task's acceptance must update the canonical task and its one required assessment scope together. `AssessmentModule.amend_required_scope` appends a revision of that same scope using the current orchestrator's exact signed `otto.owner-scope-amendment.v1` report, new task/criterion pins and stable request key. It preserves all original judgments and charges, rejects completed/accepted/disposed or foreign scopes, and grants no review allowance or PASS. Refresh the current mandate/setup/locator before another native invocation; historical occurrences remain unchanged.
