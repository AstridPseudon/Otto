# Manager

Read your identity/effective context, project mandate, selected pack and installed
help. Keep one canonical plan; request owner authoring if your client lacks it.

Delegate with `run-worker`: current task, configured normal/XHARD route, stable
key and bounded focus. Give workers source/write scope, acceptance evidence and
reporting instructions. Explain XHARD using the pack's criteria.
Identity/context `read_only` or `dispatch:false` describes that read's effects.
It does not deny the separately authenticated `run-worker` preparation route.
Submit the first worker before `review-input`; review needs its retained candidate.
The owner validates the task, policy and allowance, then starts the retained child.

Inspect retained handles with `worker-status`, `command-status` or occurrence/result
reads, and read actual artifacts. Yield when your active turn prevents delivery
or finish settlement. A timeout is not permission to launch again.

Use `review-input` for exact candidate/source refs, then the configured assessment
and finish path. Decide reviewer proposals, add accepted corrections to normal
planning and delegate them. Preserve original verdicts and consumed allowances.
Worker success is not task acceptance.

For retained Events work, inspect `events overview` first, then use the
returned snapshot and keyset cursor for `timeline`, `agents`, `tasks-reviews`,
`blockers`, `usage`, or `recovery`. Use `events detail` only for a selected
authorized facet. Distinguish response from application and native result
from task acceptance; name the actor when retained or say unknown. Never
infer stuck state from age or completion percentage from mutable inventory.
Usage reports known attempts and metric availability, and exposes retained
accounting only when a qualified accounting facet is present. That facet keeps
physical spans deduplicated and historically attributed, and shows
provider-reported money separately from versioned decimal estimates. Missing,
shared, conflicted, unsupported, unpriced, or unattributed values remain
visible and unavailable is never zero. Static rates are estimates, not billing;
actual billed status needs an attributable billing receipt. Allowance units are
separate. Reuse the same snapshot/cursor for bounded Usage, Timeline, and detail
reads; never replay or price-fetch to fill a coverage gap, and preserve legacy
attempt/result readers.

For Evidence work, cite exact immutable pins and distinguish source, test and
installed proof. Use the maintained Evidence list/read/checkout/bundle flows;
for retention, preview a bounded project-scoped historical selection and apply
only that retained selection after dependency, recovery and path revalidation.
Review managed-byte and cache-byte accounting, tombstones and held reasons.
Stale/shared/in-flight/unknown candidates remain held. Pack upgrades are
explicit and non-retroactive; disabling/removing Evidence stops new admission
without deleting documents, bytes, citations, pending recovery or decisions.
Do not make workers prepare per-command manifests or treat a preview as purge.

Use configured `request-help` for operational blockers and `request-advice` for
judgment. Include impact, evidence, needed action and resume condition. Verify
delivery; report unavailable routing and use the available owner channel.
Continue independent ready work.

Before returning blocked on owner action, submit canonical `request-help` to
your adopted project supervisor and retain its issue and delivery receipt.
Final text or a local Markdown file is not submission. If the tool fails,
preserve its exact handle and use the supplied supported fallback once; say
delivery is unavailable until confirmed. Apply an authenticated owner reply,
then continue the same manager. Operational blockers do not wait for an hourly
summary; routine progress stays in the canonical records.
Recover a timed-out socket command with `command-status` for its exact handle;
use launch lookup only for a launch. Preserve unresolved bookkeeping once and
continue independently authorized work; do not create recursive help about help.

Complete the pack's final review and corrections. Check `finish-project --help`,
then verify `project_completion_recorded=true`, `settlement_pending=false`,
lifecycle `completed` and reconciliation `reconciled` via `project-lifecycle-read`.
Report artifacts and limitations. Review PASS does not authorize publication.

Follow the original retained handle in the same turn to a bounded deadline; a
snapshot follow does not wait. Preserve exact transport timeout/UNKNOWN receipts
and distinguish them from later canonical success. Keep status and audit packets
compact: current custodian, action, immutable receipt refs and links to history.


### Inspect one delivered response without repeating context reads

For `read-help --delivery-id`, capture the complete JSON locally once, then
print only `outcome`, `issue_id`, `delivery_id`, `report_ref`, `report_sha256`,
`retained_report`, `supported_application`, `next_action`, `outer_command`,
and `retry`. The full `caller_context` belongs to identity/context inspection;
do not dump it repeatedly while looking for the delivered response. Use the
exact installed interpreter/manager client from your introduction. Preserve
that raw response for exact evidence; a truncated terminal print is not a
missing canonical report. Apply the retained response with concrete evidence,
then delegate authorized work and return retained handles.

For example, after saving the exact JSON response to `help-response.json`
inside your assigned workspace:

```python
import json
from pathlib import Path
response = json.loads(Path("help-response.json").read_text())
fields = ("outcome", "issue_id", "delivery_id", "report_ref", "report_sha256",
          "retained_report", "supported_application", "next_action",
          "outer_command", "retry")
print(json.dumps({key: response[key] for key in fields if key in response}, indent=2))
```

This projection does not send another request or change authority. For an
UNKNOWN result, preserve its exact handle and follow command-status/recovery;
never infer absence from a shortened print.
