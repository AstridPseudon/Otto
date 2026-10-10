# D02 source history and migration interface

This is the candidate FND owner interface for Events D02. It is not runtime,
resource, or package adoption. D03 owns online projection maintenance and the
bounded project reader; D04 owns presets/guidance; D05 owns installed migration
and adoption. Usage/cost remains a separate pending successor.

`schema.py` retains the exact legacy `fnd-03.v1` declaration and fingerprint and
owns the successor `fnd-03.events.v2` composition. The successor adds an
`events.append_position` column and one rebuildable `project_history` table.
Admission checks the exact physical tables, constraints and indexes, metadata,
foreign-key relations, authority and unchanged domain descriptor expectations.
`Store.open` never migrates. Legacy writable opens raise `MigrationRequiredError`;
`Store.open_readonly` admits either supported composition with a closable reader
and no SQL or mutation surface. Old-ref identity reads still return the current
head: they are not historical-state evidence.

Every accepted `Store.mutate` captures `effects.history_summary` v1 from validated
pre-state and accepted post-state in the same transaction as identity, event and
receipt. It records exact subject revisions, explicit absence on creation,
parent/project membership, lifecycle/status, assignment responsibility,
generation and typed relation changes. Missing fields remain explicitly unknown.
The summaries exclude complete payloads, project sheets, reports, results and
assignment history arrays. Task-scoped assignment project membership is resolved
only at mutation time from the admitted exact task state or a retained summary
of the exact pinned revision. If neither is available, scope membership remains
a disclosed source gap; a stale pin never borrows a changed current head.

Project-sheet child identity/document/link changes and assignment responsibility
creation attach to their actual parent receipt through `history_event_id`; they
receive no extra event or logical request. Nested rollback restores facets and
allocator state. Owner-wide positions are allocated transactionally and survive
restart. Stream sequences remain causal. A mutation's `transaction_id` is an
invocation ID, not a claim that it identifies the enclosing transaction.
`append_event` assigns a new source position and preserves imported facts; it
cannot claim a new writer-validated pre/post summary. Replays allocate nothing.

Inline source summaries are limited to 64 KiB and 128 child facets. Configure
`Store.configure_history_publisher(EvidenceHistoryPublisher(evidence, actor))`
through trusted host composition for larger batches. It publishes typed JSONL
facets with the existing admitted Evidence command port, records an exact pin,
digest, length and facet count, and includes the pin in the source event's
references before the outer commit. Publication and source references commit
atomically. Staging sidecars survive outer rollback; cleanup occurs after the
actual commit. Essential manifests carry a fail-closed Evidence dependency hold
and are not automatically reclaimed. An individually oversized typed state or
large history without the admitted publisher is rejected atomically.

The offline maintenance API is exported from `herzchen.kernel`:

```python
with closed_owner_custody(source_path, authority=authority,
                          expected_domains=adopted_domains) as custody:
    with EventsMigration.begin(custody, candidate_path=candidate_path,
                               backup_path=backup_path,
                               journal_path=journal_path,
                               migration_id=stable_migration_id) as migration:
        while migration.step(limit=100)["phase"] != "verified":
            pass
        receipt = migration.switch()
```

Only a host authorized for owner maintenance may run that operation on an actual
installation. Stop the owning service first. Recovery's sealed custody context
acquires the existing exclusive Store lock, verifies the supported composition,
checks integrity, and settles WAL/journal sidecars. A live owner is refused.
The source, consistent backup, separate successor and journal paths are distinct;
atomic switch requires the source and successor on the same filesystem.

`begin` retains the exact input before backup, so interruption during backup or
candidate creation can resume with the same journal and identity. Partial backup
copies remain inspectable. Reentry refuses changed inputs, source drift or a
changed backup digest. `EventsMigration(custody, journal_path)` resumes the same
prepared operation. `step` copies/orders/backfills one atomic batch of 1–1,000
source rows. The candidate's durable metadata contains its exact continuation;
loss of the journal reply never recopies a committed batch. Pending candidates
cannot be opened as ordinary writable installations.

Legacy order is explicitly deterministic stream-lexical/sequence order; it
preserves each stream's causal sequence and cannot assert historical cross-stream
commit chronology, including equal-time ties. Original event IDs, receipt IDs,
logical keys, payloads, decisions, debit records, timestamps, refs and sequences
are copied verbatim. No provider or domain command is replayed. Backfill reads
only retained event facts and known immutable `result_payload` fields; it never
uses current heads or pinned refs to fill missing historical membership or
active intervals. The projection stores field-level gaps and source positions. Oversized legacy
fields remain in their original authoritative sources and are explicitly listed
as bounded field gaps rather than copied into an unbounded summary.

Verification streams authoritative table counts/digests, checks relationships and
causal sequence order, and compares the migrated projection with a deterministic
fresh extraction. Only then can `switch` atomically replace the admitted source
path. Backup, journal and switch receipt remain retained. An interruption before
rename leaves the old installation unchanged. An interruption after rename is
reconciled from the installed successor's migration ID and receipt, even if new
writes have occurred. There is no rollback/reverse-migration API. Reopen the same
journal after a lost switch reply; do not retry the uncertain switch operation.

`history.py` exports deterministic source facet extraction and projection row
construction for D03 reuse. Migration backfills legacy facts, generation 1 and
its covered append checkpoint. D03 must resolve large manifests with Evidence
range reads and retain facet continuation before marking a source covered; the
extractor deliberately refuses to silently omit a manifest. Projection failure
and read/backfill behavior after activation belong to D03. No online reader,
automatic maintenance hook, automatic pruning, usage parser or cost accounting
is delivered by D02.

Focused qualification lives in `tests/test_events_history.py`. It uses disposable
SQLite/Evidence roots and tests atomic mutations, child facets, replacement,
rollback, concurrent/durable ordering, real Evidence publication/ranges/holds,
residue, supported admission, interrupted backup/copy/order/backfill/switch,
source/projection tampering, receipts/decisions/real debits, and Recovery restore.
Run it with `PYTHONPATH=src:tests /usr/bin/python3 -m unittest discover -s
src/herzchen/kernel/tests -p 'test_events_history.py' -v`.
