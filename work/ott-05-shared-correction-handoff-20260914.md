# OTT-05 shared-integration correction handoff

This is a versioned continuation of logical worker
`01a0a181-e38c-7c01-a655-ca5eb3d191ab`. The original launch receipt and the
prior increment remain immutable. The prior private-ledger result is
incomplete evidence, not an acceptance claim.

## Correction lineage

- Prior source: `5b0607dd83b7723fc19faa6ad5e525b94afe22e7`, tree
  `51edce88eb7a25fd2e36d69c9d2051fa81b1b715`.
- Prior evidence: `aef4ca00483bb42aae2ab598cbe9571bb6692b9f`, tree
  `991d34faf111caac1b9f72293692701307b84103`.
- Finding preserved: `ReleaseLedger` owned private state, counters, receipts,
  events and JSON persistence, recreated Herzchen contracts, and imported no
  Herzchen public command/contribution. It is not used by the corrected tests
  or representative.
- Corrected source: `fcd24c187b9cc45a77f19041f5b211f0713e9f36`, tree
  `65b723091b64ec53d7b82350dcfa0e2e284bc63d`.
- Separate evidence commit: the commit containing this supplement and
  `ott-05-shared-test-receipt-20260914.json` (reported separately with its
  final tree).

## Composition implemented

`otto.engineering.ReleaseOperations.bootstrap()` is the finite Otto consumer
boundary. Its trusted owner-side bootstrap creates the accepted Herzchen
`Store`, registers the accepted work contributions and one narrow Otto release
contribution, and holds the sealed handlers. Otto does not define a ledger,
database, JSON snapshot, receipt class, event class, command envelope, or
parallel candidate/decision model.

Repository metadata is persisted as a Herzchen Store identity. Candidate and
decision creation/read use public Herzchen `DecisionsModule` and real
`wrk.candidate`/`wrk.decision` records. Repository mutations use public
Herzchen `TransactionContext`, `CommandEnvelope`, `DomainHandler.mutate`,
`CommandReceipt`, `ConsumerStore`, and Store events. Close/reopen uses
`Store.close()` and `Store.open()` with the exact registered domain set.

Candidate selection, required checks, manager decision, merge observation,
promotion, publication observation, and deployment observation are separate
operations and rights. Merge does not change publication/deployment state.
Hourly and 12-hour behavior is profile data only; the adapter creates no
scheduler, queue, allowance, duplicate custodian, auto-promotion,
auto-publication, or deployment.

## Fresh proof

The fresh installed representative command was:

```text
env -u PYTHONPATH -u PYTHONHOME work/ott-05-shared-installed-venv-20260914/bin/python work/ott-05-shared-representative-installed-20260914.py
```

Return code was 0. `otto` and `herzchen` both originated from the installed
venv site-packages. The accepted Herzchen wheel hash was
`2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`; the
candidate Otto wheel hash was
`27961fe2a36dc248b5c91b96e5d1356c19de46ff61a313e9688c1b30a77652f0`.
Both `PYTHONPATH` and `PYTHONHOME` were absent.

The path created and read an actual `wrk.candidate` and `wrk.decision`,
recorded required checks and manager decision receipts, closed and reopened
the Store, and read the same typed records and events. The repository stream
had four initial events and four events after reopen. A stale target head was
rejected with `stale_head`. A partial promotion recorded completed `source`,
pending `integration`, and the same owner. An unknown merge remained visible
without changing the target head. Publication and deployment remained
`not_performed`.

Focused source and installed harnesses each ran exactly 3 tests and returned
0. They cover stale head, changed source set, duplicate source-set key,
changed same-key replay conflict, exact same-key replay receipt identity,
wrong-owner partial recovery, unknown runner outcome, separate rights, and
no automatic publication/deployment.

## Rights and gaps

Repository registration and candidate selection belong to
`repository_owner`; checks to `check_authority`; decisions to
`manager_authority`; merge to `merge_authority`; promotion to
`promotion_authority`; publication and deployment observations to their own
separate authorities. The persisted profile names one manager and one
repository owner.

The accepted Herzchen `Store.mutate` path does not update
`IdentityRecord.edit_token`. The corrected adapter therefore enforces the
stable expected edit token from its persisted repository payload and uses
Herzchen expected revision/version checks; it introduces no parallel token or
receipt system. No real Git merge, source promotion, package publication, or
deployment was attempted because those actions are outside OTT-05 scope.
This is implementation evidence for C20/C21/C27/C31, not a catalog gate or
acceptance decision.
