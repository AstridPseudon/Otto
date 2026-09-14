# OTT-04 implementation brief — durable attention and continuity

This is the single executable brief for OTT-04. Work directly in the isolated
OTT-04 checkout named in the input manifest. The manager has already verified
the immutable package inputs and the accepted OTT-03/Herzchen source pins.

## Route and objective

- Task: `OTT-04`, Implement durable attention and continuity.
- Objective: ready events reach the same responsible agent without duplicate
  sessions or repeated idle work.
- Route: `gpt-5.6-luna` with `model_reasoning_effort=high` (normal worker).
  Do not substitute a model or silently lower reasoning. Do not invoke a
  review/oracle or AST work.
- Prerequisite: accepted OTT-03 source in the manifest. The root manager owns
  the ledger, gates and shared source; this worker owns only the Otto files and
  evidence paths listed below.

## Immutable inputs and custody

- Otto source base: commit
  `0806be099eecdc9b861677ef7e71f7b54d2789a6`, tree
  `3527a4dd83f32f23bd36fabce591f81fd12e50ec`.
- Product source represented by that custody: commit
  `aea1ac6471784256a408daaef324dab9f5cba571`, tree
  `0f2246eefb5e5996355a8c31d3cc7a8f76655875`.
- Accepted Herzchen source: commit
  `98430201ff196313df0ac69a701851225c8c31a7`, tree
  `ddd9eaab56df1b8321443021db8283e4a75910cd`; accepted wheel SHA-256
  `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.
- P01 profile must remain byte-identical at
  `profiles/otto/operating.md`, commit
  `5482198b004375310d4fec33204e8fb71763a369`, tree
  `a3515b8ba1ae45293a74e451be2061f1a7a00827`, SHA-256
  `9d277b810adcbeac445d5aff2fc31a8052cfa99b844696e11412a90d11744726`.
- Full immutable input list and document hashes are in
  `work/ott-04-input-manifest-20260914.json`. Verify it before editing; record
  any mismatch as a hard stop and notify the manager.

## Ownership and allowed paths

Implement only:

- `src/otto/attention.py`
- `tests/otto/test_continuity.py`
- versioned evidence under `work/ott-04-*`

Do not edit Herzchen, `src/otto/portfolio/`, profiles, package/control files,
or another manager's tests. Use accepted public Herzchen APIs. If an accepted
shared API is genuinely insufficient, record the exact endpoint, request and
observable gap and stop that bounded row for manager routing; do not add a
private SQL writer, private inbox/event engine, scheduler, callback transport,
or side ledger.

## Required first milestone (before broad propagation)

Build one representative end-to-end path against an installed accepted
Herzchen wheel and a disposable real Store/portfolio: create a real attention
or responsibility notification with the shared public packet/attention API,
read it through the shared `ContextPacketService` and/or `EventCursorReader`,
return a real event/receipt, and reopen it from persisted state. The consumer
must receive only finite serialized commands and no Store/DB descriptor or
generic writer. A fixture-only fake port does not satisfy this milestone.

Only after this representative path is green, propagate the narrow adapter to
the rest of the tests. Use a deterministic injected clock for interval tests;
never sleep, poll a model, create cron/distributed scheduling, or launch an
agent as a side effect of a due report.

## Behavior and proof obligations

Implement and test all of the original OTT-04 catalog scope:

1. **Durable attention and timers.** Persist a small due record containing
   recipient, instruction, profile, anchor, last-covered slot, invocation
   identity and stop state. Support one-off and interval checks through the
   same code for three hours and another interval. Preserve anchors and
   outstanding decisions across close/reopen/restart; coalesce missed slots;
   keep at most one in-flight request; complete the same request exactly once.
2. **Shared event cursor and continuity.** Read returned results, relevant
   dependency changes and adopted due check-ins through shared event/attention
   mechanisms. Preserve cursor, stream/filter, authority and event identity;
   duplicate, lost, out-of-order, expired or mismatched cursors must be
   explicit and recoverable. Reading a cursor is not acknowledgment.
3. **Owner and delivery identity.** Show responsible owner, missing handoff,
   exact return condition and availability/unknown-host state. A crash or
   unknown launch must reconcile the original invocation/receipt without
   relaunching duplicate work or inventing success/session IDs. Interruption
   lets the current owner resume without creating another session.
4. **No automatic action.** Due/ready/seen produces attention/readiness only.
   Acting on it requires a recorded manager decision and must not create a
   manager, task, budget reservation, dispatch, or automatic replanning.
   Waiting is a valid state; unavailable hosts are reported honestly.
5. **Improvement propagation.** Keep a handled review notification distinct
   from an implemented improvement. A manager-selected amendment must change
   the intended plan/next dispatch and current attention/assignment views,
   preserve current owner/usage/running input pins, and expose incomplete
   propagation. Use shared packet/amendment APIs; do not copy state into an
   Otto-private inbox.
6. **Observable mutations.** For every new public mutation, capture
   before/action/fresh-after state, expected persisted delta, event/receipt
   linkage, exact replay (same request returns the original result with no
   second delta), changed-input rejection/rollback and read-only/no-op cases.
   Keep malformed or unavailable host/launch paths truthful.

The installed campaign must use a fresh Otto wheel plus the accepted Herzchen
wheel, unset `PYTHONPATH`/`PYTHONHOME`, and report module origins from that same
invocation. Preserve source and installed evidence separately. Tests prove
implementation; the real Store/packet/event observations prove product use.

## Deliverables and handoff

Commit the coherent owned source/test increment and write a versioned result
under `work/ott-04-*` containing: exact input/source/tree/wheel hashes; model,
reasoning, process/session and command receipts; the representative real
shared-attention observation; restart/duplicate/unknown/coalescing/interval
observations; amendment/no-auto-action evidence; source and installed test
counts, origins and return codes; and every unresolved gap. Distinguish
fixture-only results, product proof and later OTT-06 rehearsal. Do not claim
OTT-04 complete if any required surface remains only a fixture or if a shared
capability gap is unresolved.

