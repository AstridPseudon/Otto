# Evidence handling

This maintained workflow uses the trusted Evidence command surface for managed
capture, version, checkin, status and bounded reads. A submission stores a
small immutable manifest in the normal DAT content revision and keeps large
text or binary bytes in owner-managed custody. The manifest records exact
digest, length, format, original bindings and authenticated attribution.

Use the adopted Evidence preset; do not construct a private manifest or infer
authority from a discovered resource. Existing inline content remains readable.
Pinned references preserve captured provenance, while current authorization is
checked before every read. A bounded range is not a full-payload verification.

Replay uses the original logical request key and rejects changed inputs. A
payload, manifest or receipt interruption may leave honest staged or managed
residue; reconcile and retry the same request rather than creating a new one.

For a deliberate export, use the trusted Evidence bundle operation with an
explicit finite selection of exact references. It may produce one bounded
directory or ZIP archive containing copied text/binary bytes plus a manifest
with the immutable pins, original provenance and an included/omitted/
unavailable/purged inventory. The bundle is an authorized copy: the owner
records remain canonical, no identity or authority is transferred, and an
exported copy is not revoked. A missing local materialization is not a
canonical deletion, and bundle export does not provide import or offline sync.

This resource is policy and guidance only. It does not grant actor authority,
register a new storage system, or authorize deletion.
