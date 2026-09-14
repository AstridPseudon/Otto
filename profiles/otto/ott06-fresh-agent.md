# OTT-06 public manager journey

This profile is the shipped handoff for a fresh manager using the installed
Otto package. The manager starts with a disposable Herzchen owner bootstrap;
the consumer receives only the finite serialized operation port and reader.
The manager may create or reopen a pending project, export its typed public
records, and pass the resulting `otto.project-transfer.v1` snapshot to a
second owner with `work.project.import`. Import is passive adoption: it keeps
the source reference and snapshot digest, creates a new pending destination
identity, restores linked document revisions through the receiving owner's DAT
command port, and never copies a session, assignment, dispatch, budget, or writer.

The supported command sequence is:

1. `work.pending.create` with a pending edit.
2. `work.project.export` with the returned `project_ref` and, when a linked
   document is part of the transfer, its typed `document_refs` from the
   content link result.
3. `work.project.import` with the exported snapshot in the destination owner.
4. Retry the same import request to obtain the original result; a changed
   snapshot under that request key must return `replay_conflict` with no new
   event.
5. Before responsibility transfer, call `work.responsibility.fence` with the
   typed manager assignment reference and its expected generation, then use
   `work.responsibility.handoff`. After a fresh owner/store reopen, an old
   `work.responsibility.dispatch` request with the prior generation must return
   a typed stale-generation rejection with no event. The generation check
   prevents an old dispatch from being reused after a replacement manager is
   recorded.

## Public bootstrap and discovery path

The host creates the Herzchen owner graph once and gives the manager only the
finite consumer operations. The supported setup is:

```python
from herzchen.authoring import register_authoring
from herzchen.content import domain_contribution as content_contribution
from herzchen.domains.work import register_work
from herzchen.kernel.store import Store
from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap

store = Store.create(path, authority=authority)
register_work(store)
store.register_domain_handler((content_contribution(),))
register_authoring(store)
binding = HerzchenBindingConfig(authority, credential_ref)
owner = PortfolioOwnerBootstrap(store, binding=binding, owner_actor=actor)
portfolio = OttoPortfolio(owner.consumer_operations())
```

`owner` retains the Store and trusted domain services. A manager uses only
`portfolio` and its finite public methods (`create_pending`, `create_and_open`,
`edit_pending`, `read_pending`, `create_document`, `link_document`,
`revisit`, `satisfied_prerequisite`, `admit`, `assign_roles`, and `handoff`).
The host must close the Store after the journey and reopen it through the same
owner bootstrap for restart evidence. Do not construct `Store`, a domain
handler, a database path, SQL, or an owner callback inside the consumer.

For command-shape discovery, call `portfolio.help()` first. It returns the
operation names, their inert/read/admission semantics, and the replay and
no-auto-action invariants. Use the returned typed references and receipts as
the next command's inputs; do not inspect implementation modules to infer
private constructor or engine details.

Pending edits intentionally reject protected fields such as `tasks`,
`documents`, assignments, and receipts. To add typed tasks or dependencies,
use the finite ProjectSheet command port issued with the consumer operations:

```python
from herzchen.contracts import ResourceRef

operations = owner.consumer_operations()
actor_ref = operations.binding.authenticated_actor(actor)
batch = operations.sheet_port.apply(
    ResourceRef.from_dict(project_ref),
    {"tasks": [
        {"id": "foundation", "title": "Capture the baseline", "order": 0},
        {"id": "follow-up", "title": "Review the baseline", "order": 1,
         "dependencies": ["foundation"]},
    ]},
    logical_request_key="task-batch-1",
    actor=actor_ref,
    base_revision=project_ref["revision"],
)
```

This is a finite serialized public port; it does not expose Store, a domain
handler, a database descriptor, SQL, or a generic writer. The batch result
contains typed task mappings and a canonical receipt. Read the returned
project reference before a same-key retry and preserve the original target
reference for exact replay. A binding that reports `work.pending.list` as
unavailable must record that public-surface gap; do not substitute a private
reader or infer a list from implementation state.

For a manager decision, call `admit` with a complete non-blank decision frame.
The frame is part of the canonical request and must include all four fields:

```python
decision = portfolio.admit(
    project_ref,
    choice="investigate",
    frame={
        "outcome": "Investigate the dependency before any admission or execution step",
        "recipient": actor,
        "route": "manual-review",
        "authority": authority,
    },
    actor=actor,
    request_id="admit-investigate-1",
)
```

`outcome`, `recipient`, `route`, and `authority` must each be non-blank text.
An admission records the typed manager decision only; it must not launch a
manager, reserve budget, dispatch work, or create an execution session.

To reopen the same pending project after closing the owner Store, use the
returned reference and a fresh request key:

```python
reopened = portfolio.reopen(
    project_ref,
    actor=actor,
    request_id="reopen-1",
)
```

`reopen` requires exactly the durable `project_ref`, `actor`, and non-blank
`request_id`; it returns the existing project identity and a typed receipt.
Retrying the same request with the same reference is an exact replay. A
different reference or changed logical request under that key must be rejected
without a durable delta.

Every result carries typed references and receipts. Readiness, attention,
import, and handoff do not launch a manager, reserve budget, dispatch work, or
create an execution session. Transfer deliberately adopts task and observation
payloads into a new pending project and remaps dependencies between transferred
tasks to the destination task identities. Export also carries the public
document revision and link records for an independent content comparison;
import creates new target-owned document/link identities with the same revision
content and records the source-to-target map in the adoption result. Unknown
source fields remain in adoption metadata. Assignment,
session, dispatch, execution, manager-launch, and budget identities remain
provenance-only and are not cloned, as required by the pending-seed boundary.
A host owns the Store and writer lease; the consumer never receives a database
path, Store, DomainHandler, callback, or generic writer. For a real authoring
close, the owner supplies the managed writer-state callback and the public idle
service returns `closed_cleaned`, `cleanup_pending`, or another explicit
recovery state.
