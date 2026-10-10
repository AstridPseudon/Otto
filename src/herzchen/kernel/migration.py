"""Explicit, offline, resumable legacy FND -> Events composition migration.

Host composition calls this under Recovery closed-owner custody. A migration
step copies/backfills at most one bounded batch and never executes a domain or
provider command. Source rows, receipts and payloads are copied verbatim.
The old installation remains in place until verified atomic switch; afterward
there is deliberately no snapshot rollback operation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import shutil
from typing import Any, Mapping

from herzchen.contracts import canonical_json
from .schema import (LEGACY_COMPOSITION, LEGACY_SCHEMA_REVISION, COMPOSITION,
                     SCHEMA_REVISION, SCHEMA_FINGERPRINT)
from .store import Store, StoreError
from .recovery import (ClosedOwnerCustody, backup_closed_owner, _regular_file_stat,
                       _file_digest, _ensure_unused, _directory_identity,
                       _assert_directory_identity, _stable_file_state, _same_file_state,
                       clone_closed_owner, FilesystemCloneQualification)
from .history import PROJECTION_INSERT, projection_rows

MIGRATION_SCHEMA = "fnd.events-migration.v1"
COPY_TABLES = tuple(t for t in LEGACY_COMPOSITION if t != "store_metadata")


class MigrationError(StoreError):
    pass


def _metadata(connection):
    return dict(connection.execute("SELECT key, value FROM store_metadata"))


def _columns(connection, table):
    return tuple(row[1] for row in connection.execute("PRAGMA table_info(" + table + ")"))


def _inventory(connection, *, legacy_columns, progress=None):
    """One offline streaming equality proof; includes every authoritative byte.

    Logical row equality is independent of page/rowid layout. Decision/debit
    records are ordinary identities, so they participate without interpretation.
    """
    result = {}
    for table in LEGACY_COMPOSITION:
        columns = legacy_columns[table]
        projection = ",".join(columns)
        if table == "store_metadata":
            # Successor-specific admission/projection metadata is intentional.
            rows = connection.execute("SELECT key,value FROM store_metadata WHERE key NOT IN "
                "('schema_revision','schema_fingerprint','composition') ORDER BY key")
            rows = (row for row in rows if row[0] not in {
                "source_next_append", "history_generation", "history_checkpoint", "legacy_append_boundary",
                "migration_id", "migration_progress", "migration_switch_receipt"})
        else:
            pk = sorted((row[5], row[1]) for row in connection.execute("PRAGMA table_info("+table+")") if row[5])
            order = ",".join(name for _, name in pk) or "rowid"
            rows = connection.execute("SELECT " + projection + " FROM " + table + " ORDER BY " + order)
        count, digest = 0, hashlib.sha256()
        for row in rows:
            digest.update(canonical_json(list(row)).encode() + b"\n")
            count += 1
        result[table] = {"count": count, "sha256": digest.hexdigest()}
        if progress:
            progress("inventory:" + table + ":" + str(count))
    return result


def _fsync_dir(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_journal(path, data):
    payload = dict(data)
    payload["journal_digest"] = hashlib.sha256(canonical_json(data).encode()).hexdigest()
    temp = path.with_name(path.name + ".next")
    # The journal's one known temporary file is replaceable derived state.
    if temp.is_symlink():
        raise MigrationError("journal temporary path is a symlink")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(canonical_json(payload) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    _fsync_dir(path.parent)


def _read_journal(path):
    _regular_file_stat(path)
    data = json.loads(path.read_text())
    digest = data.pop("journal_digest")
    if hashlib.sha256(canonical_json(data).encode()).hexdigest() != digest:
        raise MigrationError("migration journal digest mismatch")
    return data


class EventsMigration:
    """Finite owner maintenance over an exact journal and Recovery custody.

    ``switch`` replaces the admitted source path atomically while holding its
    original durable writer lock. The backup and switch receipt are retained.
    A lost reply is reconciled from the installed database's migration ID;
    a changed request/path or modified source is an actionable conflict.
    """
    def __init__(self, custody: ClosedOwnerCustody, journal_path, *, phase_hook=None, clone_qualification=None):
        if not isinstance(custody, ClosedOwnerCustody):
            raise TypeError("migration requires actual Recovery closed-owner custody")
        custody.require_active()
        self.custody = custody
        self.journal_path = Path(journal_path).absolute()
        self.journal = _read_journal(self.journal_path)
        if (self.journal["schema"] != MIGRATION_SCHEMA or
            self.journal["source"] != str(custody.path) or
            self.journal["authority"] != custody.authority):
            raise MigrationError("journal does not match closed-owner custody")
        if self.journal["phase"] == "preparing":
            self._finish_preparation(custody, self.journal_path, self.journal, phase_hook=phase_hook,
                                     clone_qualification=clone_qualification)
            self.journal = _read_journal(self.journal_path)
        self.candidate = Path(self.journal["candidate"])
        self.backup = Path(self.journal["backup"])
        _regular_file_stat(self.backup)
        if _file_digest(self.backup) != self.journal["backup_digest"]:
            raise MigrationError("retained backup digest mismatch")
        self.legacy = sqlite3.connect("file:" + str(self.backup) + "?mode=ro", uri=True)
        self.legacy.row_factory = sqlite3.Row
        self.columns = {t: _columns(self.legacy, t) for t in LEGACY_COMPOSITION}
        try:
            Store._verify(self.legacy, custody.authority, custody.domains,
                          schema_revision=LEGACY_SCHEMA_REVISION)
            self.source_inventory = _inventory(self.legacy, legacy_columns=self.columns, progress=phase_hook)
            if self.source_inventory != self.journal["source_inventory"]:
                raise MigrationError("backup source equality proof mismatch")
            if custody.schema_revision == SCHEMA_REVISION:
                metadata = _metadata(custody.connection)
                if metadata.get("migration_id") != self.journal["migration_id"]:
                    raise MigrationError("installed successor belongs to another migration")
                # Even after subsequent source writes, a lost switch reply is
                # only reconciled, never rolled back or recopied.
                if metadata.get("migration_switch_receipt") is None:
                    raise MigrationError("installed successor lacks switch intent")
                custody.connection.execute("BEGIN IMMEDIATE")
                try:
                    custody.connection.execute("UPDATE store_metadata SET value=? WHERE key='migration_progress'",
                                               (canonical_json({"phase":"installed"}),))
                    custody.connection.execute("COMMIT")
                except BaseException:
                    custody.connection.execute("ROLLBACK")
                    raise
                self.journal["phase"] = "switched"
                _write_journal(self.journal_path, self.journal)
            elif (custody.schema_revision != LEGACY_SCHEMA_REVISION or
                  _inventory(custody.connection, legacy_columns=self.columns, progress=phase_hook) != self.source_inventory):
                raise MigrationError("source changed since consistent backup")
        except BaseException:
            self.legacy.close()
            raise
        self.owner = None
        if self.journal["phase"] != "switched":
            try:
                self.owner = Store._open(self.candidate, authority=custody.authority,
                                        expected_domains=self._candidate_domains(),
                                        _migration_id=self.journal["migration_id"])
                if _metadata(self.owner.connection).get("migration_id") != self.journal["migration_id"]:
                    self.owner.close()
                    self.owner = None
                    raise MigrationError("candidate migration identity mismatch")
            except BaseException:
                self.legacy.close()
                raise

    def _candidate_domains(self):
        # During bounded copy the descriptor set becomes complete before its
        # metadata digest is adopted. Open admission must remain exact.
        conn = sqlite3.connect("file:" + str(self.candidate) + "?mode=ro", uri=True)
        try:
            from herzchen.contracts import DomainContribution
            from .store import DOMAIN_KIND
            return tuple(DomainContribution.from_dict(json.loads(row[0])) for row in conn.execute(
                "SELECT payload_json FROM identities WHERE kind=? ORDER BY id", (DOMAIN_KIND,)))
        finally:
            conn.close()

    @staticmethod
    def _finish_preparation(custody, journal_path, journal, *, phase_hook=None, clone_qualification=None):
        custody.require_active()
        columns = {t: _columns(custody.connection, t) for t in LEGACY_COMPOSITION}
        if custody.schema_revision != LEGACY_SCHEMA_REVISION or _inventory(custody.connection, legacy_columns=columns, progress=phase_hook) != journal["source_inventory"]:
            raise MigrationError("source changed during interrupted preparation")
        if journal.get("capacity_policy"):
            EventsMigration._check_space(journal)
        backup = Path(journal["backup"])
        partial = backup.with_name(backup.name + ".partial")
        if not backup.exists():
            if partial.exists():
                _regular_file_stat(partial)
                # Retain the exact incomplete local copy for diagnosis. No
                # unknown external effect is resent and no source is deleted.
                number = 1
                while partial.with_name(partial.name + ".interrupted-" + str(number)).exists():
                    number += 1
                os.rename(partial, partial.with_name(partial.name + ".interrupted-" + str(number)))
            def progress(*_):
                if phase_hook:
                    phase_hook("backup-copy")
            if journal.get("backup_method", "sqlite-backup") == "clonefile":
                journal["backup_method_evidence"] = clone_closed_owner(custody, partial, qualification=clone_qualification)
                if phase_hook:
                    phase_hook("backup-clone")
            else:
                backup_closed_owner(custody, partial, progress=progress)
            os.replace(partial, backup)
            _fsync_dir(backup.parent)
        _regular_file_stat(backup)
        check = sqlite3.connect("file:" + str(backup) + "?mode=ro", uri=True)
        try:
            Store._verify(check, custody.authority, custody.domains, schema_revision=LEGACY_SCHEMA_REVISION)
            if _inventory(check, legacy_columns=columns) != journal["source_inventory"]:
                raise MigrationError("consistent backup source equality failed")
        finally:
            check.close()
        journal["backup_digest"] = _file_digest(backup)
        _write_journal(journal_path, journal)
        candidate = Path(journal["candidate"])
        if candidate.exists():
            _regular_file_stat(candidate)
            check = sqlite3.connect("file:" + str(candidate) + "?mode=ro", uri=True)
            try:
                candidate_meta = _metadata(check)
            finally:
                check.close()
            if candidate_meta.get("migration_id") == journal["migration_id"]:
                candidate_owner = Store._open(candidate,authority=custody.authority,
                                             _migration_id=journal["migration_id"])
            else:
                candidate_owner = Store.open(candidate,authority=custody.authority)
                if any(candidate_owner.connection.execute("SELECT 1 FROM " + t + " LIMIT 1").fetchone() for t in COPY_TABLES):
                    candidate_owner.close()
                    raise MigrationError("preparation candidate contains foreign source rows")
        else:
            candidate_owner = Store.create(candidate,authority=custody.authority)
        try:
            with candidate_owner.transaction() as tx:
                tx.execute("INSERT OR IGNORE INTO store_metadata VALUES ('migration_id',?)", (journal["migration_id"],))
                tx.execute("INSERT OR IGNORE INTO store_metadata VALUES ('migration_progress',?)",
                           (canonical_json({"phase":"copy", "table":0, "rowid":0}),))
                from .store import DOMAIN_DESCRIPTOR_DIGEST_KEY
                for key, value in custody.connection.execute("SELECT key,value FROM store_metadata"):
                    if key not in {"schema_revision", "schema_fingerprint", "composition", DOMAIN_DESCRIPTOR_DIGEST_KEY}:
                        tx.execute("INSERT OR REPLACE INTO store_metadata VALUES (?,?)", (key,value))
        finally:
            candidate_owner.close()
        if phase_hook:
            phase_hook("after-candidate-create")
        journal["phase"] = "copy"
        _write_journal(journal_path, journal)

    @classmethod
    def begin(cls, custody, *, candidate_path, backup_path, journal_path, migration_id, phase_hook=None,
              backup_method="sqlite-backup", clone_qualification=None, capacity_policy=None):
        if not isinstance(custody, ClosedOwnerCustody):
            raise TypeError("migration requires Recovery closed-owner custody")
        custody.require_active()
        if backup_method not in {"sqlite-backup", "clonefile"}:
            raise MigrationError("unsupported backup method; no implicit fallback")
        candidate, backup, journal = [Path(p).absolute() for p in (candidate_path, backup_path, journal_path)]
        if len({str(custody.path), str(candidate), str(backup), str(journal)}) != 4:
            raise MigrationError("source, backup, candidate and journal paths must be distinct")
        if not isinstance(migration_id, str) or not migration_id.strip():
            raise MigrationError("migration requires one stable nonblank identity")
        if journal.exists():
            retained = _read_journal(journal)
            if any(retained.get(key) != value for key,value in {
                "source":str(custody.path), "candidate":str(candidate), "backup":str(backup),
                "migration_id":migration_id,"authority":custody.authority,
                "backup_method":backup_method}.items()):
                raise MigrationError("same journal cannot be reused with changed migration input")
            return cls(custody,journal,phase_hook=phase_hook,clone_qualification=clone_qualification)
        if custody.schema_revision != LEGACY_SCHEMA_REVISION:
            raise MigrationError("begin requires the exact admitted legacy composition")
        reserved = {"source_next_append","history_generation","history_checkpoint","legacy_append_boundary",
                    "migration_id","migration_progress","migration_switch_receipt"}
        if reserved.intersection(_metadata(custody.connection)):
            raise MigrationError("legacy metadata conflicts with successor reserved keys")
        for path in (candidate, backup, journal, backup.with_name(backup.name+".partial")):
            _ensure_unused(path)
        columns = {t: _columns(custody.connection, t) for t in LEGACY_COMPOSITION}
        inventory = _inventory(custody.connection, legacy_columns=columns, progress=phase_hook)
        _write_journal(journal, {"schema":MIGRATION_SCHEMA, "phase":"preparing", "migration_id":migration_id,
            "source":str(custody.path), "candidate":str(candidate), "backup":str(backup),
            "source_inventory":inventory, "authority":custody.authority,
            "backup_method":backup_method, "capacity_policy":capacity_policy,
            "legacy_order":"stream-lexical-then-sequence;cross-stream-chronology-unknown"})
        return cls(custody,journal,phase_hook=phase_hook,clone_qualification=clone_qualification)

    @staticmethod
    def plan(*, source_path, candidate_path, backup_path, journal_path, migration_id,
             backup_method="sqlite-backup", headroom_bytes=2147483648,
             candidate_growth_reserve_bytes=268435456, clone_qualification=None):
        """Filesystem-only preparation; no Store, clone, backup or provider work.

        A clone plan requires a maintained independent-clone qualification for
        the actual source directory. File allocation is not unique CoW usage.
        Growth is an explicit reserve; free space is rechecked on apply, each
        bounded step and switch. Exhaustion leaves resumable retained effects.
        """
        source, candidate, backup, journal = [Path(p).absolute() for p in
            (source_path, candidate_path, backup_path, journal_path)]
        if len({source,candidate,backup,journal}) != 4 or not migration_id:
            raise MigrationError("distinct migration paths and stable identity required")
        state = _regular_file_stat(source)
        for path in (candidate,backup,journal):
            _directory_identity(path.parent)
            if path.is_symlink():
                raise MigrationError("migration path is a symlink")
            if path.exists():
                info = _regular_file_stat(path)
                if info.st_dev == state.st_dev and info.st_ino == state.st_ino:
                    raise MigrationError("migration path aliases source inode")
        if candidate.parent != source.parent or backup.parent != source.parent:
            raise MigrationError("migration copy plan must use the qualified source directory")
        if backup_method not in {"sqlite-backup", "clonefile"}:
            raise MigrationError("unsupported backup method")
        if any(type(v) is not int or v < 0 for v in (headroom_bytes,candidate_growth_reserve_bytes)):
            raise MigrationError("capacity reserves must be nonnegative integers")
        if backup_method == "clonefile" and not backup.exists():
            if not isinstance(clone_qualification, FilesystemCloneQualification):
                raise MigrationError("clone plan requires maintained filesystem qualification")
            clone_qualification.require_directory(source.parent)
        candidate_allocated = _regular_file_stat(candidate).st_blocks*512 if candidate.exists() else 0
        candidate_remaining = max(0, state.st_size+candidate_growth_reserve_bytes-candidate_allocated)
        backup_remaining = (16777216 if backup_method == "clonefile" else state.st_size) if not backup.exists() else 0
        free = shutil.disk_usage(source.parent).free
        required = candidate_remaining + backup_remaining + headroom_bytes
        return {"schema":"fnd.events-migration-plan.v1", "source":str(source),
                "candidate":str(candidate), "backup":str(backup), "journal":str(journal),
                "migration_id":migration_id, "backup_method":backup_method,
                "source_bytes":state.st_size, "source_device":state.st_dev, "source_inode":state.st_ino,
                "source_mtime_ns":state.st_mtime_ns, "available_bytes":free,
                "candidate_growth_reserve_bytes":candidate_growth_reserve_bytes,
                "headroom_bytes":headroom_bytes, "remaining_candidate_bytes":candidate_remaining,
                "remaining_backup_bytes":backup_remaining, "required_available_bytes":required,
                "fit":free>=required, "Store_opened":False,
                "allocation_uncertainty":"CoW metadata/growth and other writers; guards recheck available space"}

    @staticmethod
    def _check_space(journal):
        policy = journal.get("capacity_policy")
        if not policy or journal.get("phase") == "switched":
            return
        source, candidate, backup = [Path(journal[name]) for name in ("source","candidate","backup")]
        size = _regular_file_stat(source).st_size
        allocated = _regular_file_stat(candidate).st_blocks*512 if candidate.exists() else 0
        remaining = max(0,size+policy["candidate_growth_reserve_bytes"]-allocated)
        remaining += (16777216 if journal.get("backup_method") == "clonefile" else size) if not backup.exists() else 0
        if shutil.disk_usage(source.parent).free < remaining + policy["headroom_bytes"]:
            raise MigrationError("migration capacity held; retain original journal and resume after sufficient space")

    @classmethod
    def apply(cls, custody, plan, *, clone_qualification=None, phase_hook=None):
        """Fresh apply of one prepared migration; existing journal uses resume."""
        if not isinstance(custody, ClosedOwnerCustody):
            raise TypeError("apply requires actual closed-owner custody")
        custody.require_active()
        if Path(plan["journal"]).exists():
            raise MigrationError("original journal exists; use resume, not another apply")
        state = _regular_file_stat(custody.path)
        if (plan.get("schema") != "fnd.events-migration-plan.v1" or plan["source"] != str(custody.path)
            or (state.st_dev,state.st_ino,state.st_size,state.st_mtime_ns) !=
               (plan["source_device"],plan["source_inode"],plan["source_bytes"],plan["source_mtime_ns"])):
            raise MigrationError("migration plan source changed; prepare a fresh same-identity plan")
        fresh = cls.plan(source_path=custody.path,candidate_path=plan["candidate"],backup_path=plan["backup"],
            journal_path=plan["journal"],migration_id=plan["migration_id"],backup_method=plan["backup_method"],
            headroom_bytes=plan["headroom_bytes"],candidate_growth_reserve_bytes=plan["candidate_growth_reserve_bytes"],
            clone_qualification=clone_qualification)
        if not fresh["fit"]:
            raise MigrationError("migration capacity held before apply")
        return cls.begin(custody,candidate_path=fresh["candidate"],backup_path=fresh["backup"],
            journal_path=fresh["journal"],migration_id=fresh["migration_id"],backup_method=fresh["backup_method"],
            clone_qualification=clone_qualification,phase_hook=phase_hook,
            capacity_policy={k:fresh[k] for k in ("headroom_bytes","candidate_growth_reserve_bytes")})

    @classmethod
    def resume(cls, custody, journal_path, *, clone_qualification=None, phase_hook=None, expected_input=None):
        """Resume only the original durable journal; never allocate a replacement."""
        if not isinstance(custody, ClosedOwnerCustody):
            raise TypeError("resume requires actual closed-owner custody")
        custody.require_active()
        if expected_input is not None:
            retained = _read_journal(Path(journal_path))
            if any(retained.get(key) != value for key,value in expected_input.items()):
                raise MigrationError("original resume input differs; no replacement or rebinding")
        return cls(custody,journal_path,clone_qualification=clone_qualification,phase_hook=phase_hook)

    def installed_receipt(self):
        """Read the actual original switch receipt after lost-reply reconciliation."""
        self.custody.require_active()
        if self.journal["phase"] != "switched":
            raise MigrationError("migration has not actually switched")
        receipt = json.loads(_metadata(self.custody.connection)["migration_switch_receipt"])
        if receipt["migration_id"] != self.journal["migration_id"]:
            raise MigrationError("installed switch receipt identity differs")
        return receipt

    def close(self):
        if self.owner is not None:
            self.owner.close()
            self.owner = None
        self.legacy.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _require(self):
        self.custody.require_active()
        if self.owner is None:
            raise MigrationError("migration handle is not active; reconcile the same journal")

    def step(self, *, limit=100, phase_hook=None):
        """One atomic copy/order/backfill batch. Reads never call this."""
        self._require()
        self._check_space(self.journal)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("migration batch limit must be 1..1000")
        metadata = _metadata(self.owner.connection)
        progress = json.loads(metadata["migration_progress"])
        if progress["phase"] == "verified":
            return progress
        with self.owner.transaction() as tx:
            if progress["phase"] == "copy":
                table = COPY_TABLES[progress["table"]]
                columns = self.columns[table]
                rows = self.legacy.execute("SELECT rowid AS source_rowid," + ",".join(columns) +
                    " FROM " + table + " WHERE rowid>? ORDER BY rowid LIMIT ?", (progress["rowid"],limit)).fetchall()
                # Source event append positions are assigned in a later causal
                # order pass; temporary distinct positions are never exposed.
                for row in rows:
                    values = [row[c] for c in columns]
                    names = list(columns)
                    if table == "events":
                        names.insert(0,"append_position")
                        values.insert(0,self.owner._next_append(tx))
                    tx.execute("INSERT INTO " + table + "(" + ",".join(names) + ") VALUES (" +
                               ",".join("?" for _ in names) + ")", values)
                if rows:
                    progress["rowid"] = rows[-1]["source_rowid"]
                else:
                    progress["table"] += 1
                    progress["rowid"] = 0
                    if progress["table"] == len(COPY_TABLES):
                        progress = {"phase":"order", "stream":"", "sequence":0, "position":0}
                if table == "identities":
                    from herzchen.contracts import DomainContribution
                    from .store import DOMAIN_KIND, DOMAIN_DESCRIPTOR_DIGEST_KEY, _descriptor_digest
                    descriptors = [DomainContribution.from_dict(json.loads(row[0])) for row in
                        tx.execute("SELECT payload_json FROM identities WHERE kind=?", (DOMAIN_KIND,))]
                    tx.execute("UPDATE store_metadata SET value=? WHERE key=?", (_descriptor_digest(descriptors),DOMAIN_DESCRIPTOR_DIGEST_KEY))
                    tx._domain_working = {d.domain_id:d for d in descriptors}
                    tx._domain_digest = _descriptor_digest(descriptors)
            elif progress["phase"] == "order":
                # Reassign via a disjoint positive band to preserve UNIQUE.
                total = self.source_inventory["events"]["count"]
                rows = tx.execute("SELECT event_id,stream,sequence FROM events WHERE (stream,sequence)>(?,?) "
                    "ORDER BY stream,sequence LIMIT ?", (progress["stream"],progress["sequence"],limit)).fetchall()
                for row in rows:
                    progress["position"] += 1
                    tx.execute("UPDATE events SET append_position=? WHERE event_id=?",
                               (total + progress["position"],row["event_id"]))
                    progress["stream"],progress["sequence"] = row["stream"],row["sequence"]
                if not rows:
                    # One bounded final normalization is deferred to a separate
                    # pass, rather than an unbounded UPDATE.
                    progress = {"phase":"normalize", "position":total, "after":total}
            elif progress["phase"] == "normalize":
                total = progress["position"]
                rows = tx.execute("SELECT event_id,append_position FROM events WHERE append_position>? "
                                  "ORDER BY append_position LIMIT ?", (progress["after"],limit)).fetchall()
                for row in rows:
                    tx.execute("UPDATE events SET append_position=? WHERE event_id=?",
                               (row["append_position"]-total,row["event_id"]))
                    progress["after"] = row["append_position"]
                if not rows:
                    tx.execute("UPDATE store_metadata SET value=? WHERE key='source_next_append'",(str(total+1),))
                    tx.execute("UPDATE store_metadata SET value=? WHERE key='legacy_append_boundary'",(str(total),))
                    progress = {"phase":"backfill", "position":0}
            elif progress["phase"] == "backfill":
                rows = tx.execute("SELECT * FROM events WHERE append_position>? ORDER BY append_position LIMIT ?",
                                  (progress["position"],limit)).fetchall()
                for row in rows:
                    for facet in projection_rows(row):
                        tx.execute(PROJECTION_INSERT,facet)
                    progress["position"] = row["append_position"]
                tx.execute("UPDATE store_metadata SET value=? WHERE key='history_checkpoint'",(str(progress["position"]),))
                if not rows:
                    progress = {"phase":"verify"}
            elif progress["phase"] == "verify":
                self.verify()
                progress = {"phase":"verified"}
            else:
                raise MigrationError("unsupported migration progress")
            tx.execute("UPDATE store_metadata SET value=? WHERE key='migration_progress'",(canonical_json(progress),))
            if phase_hook:
                phase_hook("before-" + progress["phase"] + "-commit")
        self.journal["phase"] = progress["phase"]
        _write_journal(self.journal_path,self.journal)
        if phase_hook:
            phase_hook("after-" + progress["phase"] + "-commit")
        return progress

    def verify(self):
        self._require()
        connection = self.owner.connection
        if _inventory(connection,legacy_columns=self.columns) != self.source_inventory:
            raise MigrationError("source counts/digests/receipts/relations equality failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MigrationError("successor relations failed")
        Store._verify(connection,self.custody.authority,self.custody.domains)
        n = self.source_inventory["events"]["count"]
        actual = connection.execute("SELECT count(*),min(append_position),max(append_position) FROM events").fetchone()
        if actual[0] != n or (n and (actual[1],actual[2]) != (1,n)):
            raise MigrationError("source append ordering is incomplete")
        if connection.execute("SELECT 1 FROM events e JOIN events p ON e.store_authority=p.store_authority "
            "AND e.stream=p.stream AND e.sequence=p.sequence+1 WHERE e.append_position<=p.append_position LIMIT 1").fetchone():
            raise MigrationError("migration violated causal stream sequences")
        # Rebuild equality is a streaming digest, not a second live projection.
        expected = hashlib.sha256()
        count = 0
        for row in connection.execute("SELECT * FROM events ORDER BY append_position"):
            for facet in projection_rows(row):
                expected.update(canonical_json(list(facet)).encode()+b"\n")
                count += 1
        actual = hashlib.sha256()
        seen = 0
        for row in connection.execute("SELECT * FROM project_history ORDER BY source_append_position,facet_index,project_authority,project_id"):
            actual.update(canonical_json(list(row)).encode()+b"\n")
            seen += 1
        if seen != count or actual.digest() != expected.digest():
            raise MigrationError("deterministic rebuild equality failed")
        return {"source_inventory":self.source_inventory,"projection_count":count,
                "projection_digest":actual.hexdigest(),"legacy_chronology":"unknown"}

    def switch(self, *, phase_hook=None):
        self._require()
        self._check_space(self.journal)
        if json.loads(_metadata(self.owner.connection)["migration_progress"])["phase"] != "verified":
            raise MigrationError("successor is not verified for switch")
        proof = self.verify()
        if _inventory(self.custody.connection,legacy_columns=self.columns) != self.source_inventory:
            raise MigrationError("old installation changed before switch")
        receipt = {"schema":MIGRATION_SCHEMA,"migration_id":self.journal["migration_id"],
            "source":str(self.custody.path),"backup":str(self.backup),"backup_digest":self.journal["backup_digest"],
            "successor_revision":SCHEMA_REVISION,"successor_fingerprint":SCHEMA_FINGERPRINT,**proof}
        with self.owner.transaction() as tx:
            tx.execute("INSERT OR REPLACE INTO store_metadata VALUES ('migration_switch_receipt',?)",(canonical_json(receipt),))
        self._check_space(self.journal)
        self.journal["phase"] = "switch-intent"
        _write_journal(self.journal_path,self.journal)
        if phase_hook:
            phase_hook("before-switch")
        if not _same_file_state(_stable_file_state(self.custody.path), self.custody.source_file_state):
            raise MigrationError("closed-owner source file identity changed before switch")
        source_parent = _directory_identity(self.custody.path.parent)
        candidate_state = _regular_file_stat(self.candidate)
        if candidate_state.st_dev != self.custody.source_file_state["device"]:
            raise MigrationError("atomic switch requires source and candidate on the same filesystem")
        _assert_directory_identity(self.custody.path.parent,source_parent)
        self._check_space(self.journal)
        # Keep both durable locks until the atomic replacement has completed.
        self.custody.connection.close()
        try:
            os.replace(self.candidate,self.custody.path)
            _fsync_dir(self.custody.path.parent)
        except BaseException:
            # No stale snapshot restore. If rename failed the original remains;
            # if it succeeded the migration ID reconciles the installed path.
            self.owner.close()
            self.owner = None
            self.custody.connection = Store._connect(str(self.custody.path))
            self.custody.schema_revision = _metadata(self.custody.connection)["schema_revision"]
            raise
        self.owner.close()
        self.owner = None
        self.custody.connection = Store._connect(str(self.custody.path))
        self.custody.schema_revision = SCHEMA_REVISION
        self.custody.source_file_state = _stable_file_state(self.custody.path)
        if phase_hook:
            phase_hook("after-switch")
        self.custody.connection.execute("BEGIN IMMEDIATE")
        try:
            self.custody.connection.execute("UPDATE store_metadata SET value=? WHERE key='migration_progress'",
                                           (canonical_json({"phase":"installed"}),))
            self.custody.connection.execute("COMMIT")
        except BaseException:
            self.custody.connection.execute("ROLLBACK")
            raise
        self.journal["phase"] = "switched"
        _write_journal(self.journal_path,self.journal)
        return receipt
