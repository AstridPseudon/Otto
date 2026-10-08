# Owner editor host

`DocumentEditorHost` composes one supplied owner's DAT handler, EDT service,
physical materializer and authenticated writer-lease authority. It uses
`ManagerApplication`'s project grant and document visibility reader. It does
not open a Store or register descriptors. The installed host supplies its
private stable writer secret and the existing owner command lane.

The trusted host input accepts the existing `otto.owner-authoring-grant.v1`
envelope. Its request has `command: document-authoring`, `operation`, and a
nonempty `request_key`. Ordinary caller IPC cannot issue that grant, select
an actor, or use a status response as a capability. `help` returns the exact
finite operation fields at the point of use. Example owner envelope:

```json
{"schema":"otto.owner-authoring-grant.v1","request":{"command":"document-authoring","operation":"help","request_key":"editor-help-1"}}
```

Open requires `project_ref` and an identity-only `document_ref` for an owned,
visible, writable, unpinned document. Retain the exact `handle` returned by
open. Status, resume, save, finish, discard and idle-close use that handle
plus the same project/document references. Save additionally takes the
actual `editor_buffer`, normally `{"content": <current JSON content>}`.
It captures that buffer into the physical `document.json` through managed
writer leases, fsyncs it, and then autosaves it through EDT. Only a changed
buffer advances content-edit time; reads and unchanged saves do not.

The default inactivity threshold is 900 seconds. An owner may explicitly
configure `inactivity_seconds` on open/save. The host's existing wait-loop
callback calls `poll_idle(ingress)`. That method publishes a single finite
idle-close request per captured buffer on the existing IPC lane. It performs
no canonical reads/writes or inline check-in. The normal command lane obtains
exclusive writer retirement, verifies captured bytes, invokes the existing
semantic finish and cleans up only after durable publication. The retained
response contains the notification, immutable DAT revision and receipt. It
never adopts that revision into direction/assignment/resource context.

A restart retains EDT snapshots and sessions but loses live UI buffer state.
Inventory exposes recovery status without tokens. Explicit holder resume
and save of the recovered buffer are required before automatic idle check-in.
A missing handle needs the explicit authenticated owner `recover` or
`discard-lost` operation with its canonical session ID. Neither inventory nor
an inferred timestamp grants takeover or publication. Discard retains draft
history and does not advance the DAT head; physical cleanup status is reported
separately. Rejected finish retains its draft and retired-writer state: inspect
recovery, discard explicitly, then open a new session to correct it.

This buffer adapter is a maintained headless editor/save boundary. Connecting
a graphical editor requires that editor to send its own atomic buffer through
the same authenticated input. A CLI proof is not a claim that an unrelated
GUI's unsaved buffer has been captured.
