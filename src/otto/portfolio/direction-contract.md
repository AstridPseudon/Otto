# Durable direction scope, identity, authority and exact resolution (D01-D02)

Direction expresses enduring priorities and constraints. It supplies no Store,
dispatch, execution, publication or revision-adoption authority. That authority
continues to come from the existing owner-issued operations and exact contracts.

| Subject | Existing canonical identity / source | Lifetime and authority |
| --- | --- | --- |
| Owner | FND Store authority and `PortfolioOwnerBootstrap.owner_actor` (`AuthenticatedActor`) | Authority identifies the owning Store; the injected authenticated operator authorizes this capability. Operator/principal text in a request is not caller authentication. |
| Overall direction | `owner_direction_subject(authority)`, exactly `fnd.owner/<authority>` | One authority-qualified association locator. No new owner row, fake project, registry, hierarchy or shadow state. The locator survives owner operator and orchestrator replacement. It is retained in the association and event effects; unlike existing WRK subjects it is not an FND identity foreign key. |
| Enduring responsibility | Existing `wrk.responsibility` row created by `ResponsibilityAssignments.assign` | The row names its assignment and role. Direction uses this unversioned subject; it is independent of the current principal, native session, assignment revision and generation. Reads validate the reverse reference from the current assignment. |
| Assignment | Existing `wrk.assignment`, with `responsibility_ref`, scope, principal, role, session, generation, status, pins and history | Existing reassign/resume/replacement changes custody and generation while retaining responsibility identity. Assignment refs accepted as locators resolve to their existing responsibility. This read does not admit execution or waive stale-generation fences. |
| Project/task | Existing `work.project` / `work.task` records | Concrete outcomes, acceptance and membership stay in Work. Optional direct direction bindings use stable subject identity, not project title or task revision. Multiple responsibilities may share a scope and role. |
| Role guide/configuration | Ordinary DAT BASE instruction resources and selected supporting configuration | Reusable role behavior and model/default policy; their generic selection/adoption semantics remain unchanged. They are not a responsibility's fixed primary direction. |
| Mandate/instruction contract | Existing project-scoped DAT mandate plus exact task/assignment/generation contract | Bounded operational authority and effect fences. Replacement can require new pins or a new mandate while retaining direction identity. Binding a direction neither revises nor grants a mandate. |
| Direction document | Existing owned, writable `dat.content.document`, descriptive role `direction` | Stable document identity; content changes use ordinary immutable DAT revisions. Imported/pinned sources remain read-only supporting evidence. A document role alone grants no authority. |
| Primary membership | Existing `document-association`, namespace `direction.primary.v1`, key `primary` | Initial owner binding fixes the document identity for the subject's lifetime. The association has current identity binding for navigation only; it is not scope adoption of the latest revision. |
| Native occurrence | Existing Due, gateway authorization, principal/assignment/generation/session/turn evidence | Execution and delivery identities, never new direction subjects. Existing admission, recovery and uncertain-effect fences remain authoritative. |

The trusted bootstrap explicitly issues `direction_bindings()`. This late-registers
one `dat.direction.bind` operation over ordinary DAT association identities and
FND transaction/receipt/event machinery; predecessor descriptors are unchanged.
Neither the usual manager/worker consumer facade nor assignment resource adoption
grants it. The operation compares the complete authenticated actor with the
currently injected owner actor, including authority and credential reference.
This comparison consumes the owner's trust assertion; it does not authenticate
an arbitrary IPC/native caller. D03 must implement that separate ingress boundary.

Initial binding requires an existing local owned writable direction document,
scoped to the exact subject or its existing project/task scope (including a task's
existing containing project, with authoring revision ignored for identity). Overall direction
requires the owner-wide scope. Bindings use one normalized unversioned subject,
so revision-qualified aliases cannot create another primary. A same-document retry
returns the retained binding without another event; a changed-document retry
fails, including reused logical request keys. FND serialization makes competing
initial bindings commit once. Historical binding operator and the original receipt
remain retained when a new authorized owner operator takes over.

There is no ordinary replace, supersedes, unbind, retire, recreate or transfer
operation on this capability. Generic DAT link/unlink/document writes reject the
reserved primary association, and WRK sheet links/document changes cannot write
around it. Retirement/withdrawal does not remove membership; reading and resuming
the existing canonical subject retains it. Reusing a creation key cannot rewrite
the responsibility. Names, roles, sessions and `(project, role)` pairs cannot
resolve, recreate or inherit another responsibility. A new canonical responsibility
is independent, not a replacement for an existing one: callers continuing existing
work must retain the existing subject and use reassignment. Genuine split/merge,
exceptional mistaken-binding repair and migration require a separately specified
owner operation; this capability supplies no bypass.

Content revision append leaves membership unchanged. Guides, mandates and work
outcomes remain independent inputs; support documents do not become another
primary merely by being linked or labeled direction. Generic read/authoring,
history, import/export, assignment replacement and gateway mechanics are reused.

## Exact scope adoption and resolution (D02/B02)

The same owner-issued `direction_bindings()` capability adds `adopt` and `resolve`.
The D01 domain descriptor stays byte-equivalent; one additional finite adoption
descriptor registers `dat.direction.adopt`, writing the existing primary DAT
association. No direction state, content table or history ledger is added.

`adopt(subject, revision_ref, actor=owner, expected_binding_ref=exact_binding,
logical_request_key=key)` authorizes one exact local revision of the fixed primary
document. FND serializes reads/writes and CASes the binding. Its event and receipt
retain the authenticated operator, scope, primary and supporting refs/digests.
The primary revision declares optional `supporting_refs` (at most 32 exact local
DAT pins); duplicates collapse, conflicting revisions and self references fail.
Imported/read-only local documents can supply evidence without becoming primary.
Foreign pins are unavailable to this local composition, never guessed or fetched.
Same-key adoption replays the exact prior outcome, even after later adoption;
changed requests conflict. Stale binding revisions require read/reconciliation.
Save/append does not call adoption or revise the fixed association.

`resolve(subject, actor=owner)` consumes the exact scope-adopted primary and its
declared supporting inputs. It returns content/digests, latest, scope-adopted and
effective refs separately. Latest is read only as a head locator, never followed
as effective content. Current DAT visibility applies even to old immutable
revisions; immutable identity and digest evidence must match. Missing, unbound,
unadopted, inaccessible, conflicting and invalid inputs produce named actionable
errors. Structural verification does not judge semantic strategy agreement.

`resolve(..., assignment_ref=exact_assignment, expected_generation=current)`
also fences current assignment revision/generation and applicable scope. It
reuses `resolve_assignment_attachments` over existing Work adoptions and requires
exactly one required BASE. That BASE must pin this primary in `supporting_refs`.
The pin must have a retained authorized adoption event for this exact scope;
assignment managers cannot authorize wider direction by adopting a resource.
Overlapping BASE supporting refs cannot override the direction's declared pins.
An older assignment pin remains effective after a newer scope adoption or draft,
subject to current access to its consumed inputs. New pending supporting inputs
do not invalidate the old assignment. Results expose pending scope adoption and
pending assignment application separately. Assignment refresh remains the
existing Work `adopt_resources` operation with its queued/reassigned, generation,
revision and unconsumed-admission guards; this capability does not bypass them.

Ordinary DAT writes validate the envelope's document target and prevent create
from resetting an existing direction document or append from changing its scope,
role or ownership mode. Work sheet document changes cannot replace direction
heads through their lower-level generic write path: use DAT revision authoring.
The D01 namespace/link/unlink/import fences remain intact; generic guides and
other document memberships keep existing semantics.

## Follow-on responsibilities and proof limits

The owner-only `read` retains identity inspection and reports scope adoption when
present; it does not select a head implicitly. A malformed retained binding fails
closed and needs explicit owner repair, never unlink/rebind. D02 does not add
worker caller authorization: the injected authenticated owner capability remains
the trusted boundary until D03 supplies the independently trusted caller ingress.

D03-D06 still own caller authentication, prompt composition, overrides, adoption
at eligible future boundaries, installed command/UX/history and connected delivery
proof. `resolve` reports `delivered_ref: null`, `delivery_status: not_inspected`:
scope/assignment adoption is not retained native delivery. D03-D06 must join
occurrence evidence and install the resolver in actual invocation/read surfaces.
D01-D02 tests use disposable canonical Stores, no live owner Store, installed
service or provider. They exercise withdrawal and resume through existing Work
operations; they do not claim a new responsibility/native-retirement API or live
retirement transport. Model/route/native attestation remains the receiving owner's
responsibility. No package/runtime adoption, task acceptance or deployment occurs
as a consequence of this source change.
