# OTT-04 EX-HOST lineage supplement — 2026-09-14

This supplement records the relationship between the accepted Herzchen timer
and the OTT-04 durable attention record. It is evidence metadata; it does not
change the accepted Herzchen source.

The accepted Herzchen implementation is `src/herzchen/kernel/recovery.py` at
commit `b68d8f59712275229c24757664ca30d807d39e4a`, class
`IntervalController`. Its persisted `IntervalState` deliberately contains
`interval_seconds`, `anchor`, `last_slot`, and one `in_flight` request. The
accepted recovery test `tests/kernel/test_recovery.py` verifies restart,
coalesced missed intervals, and completion of the same in-flight request.

OTT-04 keeps those semantics: one persisted anchor, logical covered slot,
single in-flight request, coalesced missed intervals, stale-write protection,
and same-request completion after reopen. The new Otto `DurableAttention`
state machine owns the larger `DueRecord` because the catalog requires the
recipient, instruction, profile, invocation identity, owner, stop state,
outstanding decision, return condition, and final result to survive restart.
The accepted `IntervalController` schema cannot represent those fields.

Using both controllers for one schedule would create two timer records and
two in-flight authorities. OTT-04 therefore does not instantiate a second
Herzchen interval controller. It retains the accepted interval behavior in
the single Otto record and persists that record through the shipped
owner-side `StoreDueRecordPort` and `due_record_contribution()` in
`src/otto/attention.py`. The consumer receives only the finite
`DueRecordPort`; Store, SQLite paths, and the domain handler remain trusted
host state. The fresh source and installed observations prove the resulting
single record's event/receipt, replay, CAS rejection, reopen, and in-flight
continuity.

The public amendment composition similarly reuses accepted Herzchen
`ProjectSheet.apply`, `ProjectSheet.pin_assignment_route`,
`ResponsibilityAssignments.get`, and `ContextPacketService` operations. It
does not add a scheduler, automatic dispatch, second attention engine, or
private inbox. `ImprovementPropagation` reports attention/readiness first;
only the manager decision invokes those finite public operations, preserving
owner, usage/budget, running input pins, and `dispatch: false`.

The historical 53/53 campaign remains in
`work/ott-04-result-20260914.md`; the fresh continuation proof is in
`work/ott-04-continuation-20260914/real-observation-installed.json` and
`real-observation-source.json`.
