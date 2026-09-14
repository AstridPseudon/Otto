# OTT-06 public manager journey

This profile is the shipped handoff for a fresh manager using the installed
Otto package. The manager starts with a disposable Herzchen owner bootstrap;
the consumer receives only the finite serialized operation port and reader.
The manager may create or reopen a pending project, export its typed public
records, and pass the resulting `otto.project-transfer.v1` snapshot to a
second owner with `work.project.import`. Import is passive adoption: it keeps
the source reference and snapshot digest, creates a new pending destination
identity, and never copies a session, assignment, dispatch, budget, or writer.

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

Every result carries typed references and receipts. Readiness, attention,
import, and handoff do not launch a manager, reserve budget, dispatch work, or
create an execution session. Transfer deliberately adopts task and observation
payloads into a new pending project; assignment, session, dispatch, execution,
manager-launch, and budget identities remain provenance-only and are not cloned.
A host owns the Store and writer lease; the consumer never receives a database
path, Store, DomainHandler, callback, or generic writer. For a real authoring
close, the owner supplies the managed writer-state callback and the public idle
service returns `closed_cleaned`, `cleanup_pending`, or another explicit
recovery state.
