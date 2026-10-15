"""Clean-close: reclaim a finished project's host transcripts, as an owner operation.

Once a ``work.project`` is ``completed`` or ``withdrawn`` nothing reads the
host transcripts of its callbacks. ``CleanClose.run`` reclaims them:

1. file-backed retained bodies are purged with ``RetainedNativeBodies.purge_project``
   (marker, rename, delete; later reads see the key as absent);
2. legacy INLINE transcript keys (``raw_result``, ``task_bound_evidence`` under
   ``host_evidence.gateway_attempt.result`` and the two correction/reconciliation
   copies) are removed from the project's ``otto.due-record`` identities and from
   those records' events (``effects_json.record...``). These are the same paths
   as ``otto-clean-close.py``. SL10 ``same_as`` references live inside the
   stripped ``raw_result``, so they go with it.

Rows are rewritten, never deleted: Store admission needs ``count(events) ==
max(append_position)``, a gapless ``source_next_append`` and intact foreign
keys, and ``version``/``current_revision``/``updated_at`` stay as they are. The
rewrite is one exclusive transaction on the owner's own connection, restricted
to the one project's rows, and it is verified inside the transaction (row counts
and append boundary unchanged, no stripped key left) before it commits.

``dry_run=True`` (the default) lists every row and body that would change and
writes nothing. Running twice changes nothing the second time.

Space: stripped rows free SQLite pages that later writes reuse, so the store
stops growing. The file shrinks only by an offline VACUUM (``otto-clean-close.py
apply``, or ``VACUUM INTO`` plus a swap with the owner stopped); auto_vacuum and
the header are deliberately left alone because admission checks them.

Out of scope, by design: Evidence-backed bodies (their reclaim is an explicit,
preview-and-approve workflow that completion does not authorise, and the Otto
host service has no Evidence handler) and inline ``wrk.result`` bodies (read by
usage, history projection and result verification, so not provably unread).
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

SCHEMA = "otto.clean-close.v1"
FINISHED = ("completed", "withdrawn")
LOG = logging.getLogger("otto.clean_close")

STRIP_PATHS = (
    "$.host_evidence.gateway_attempt.result.raw_result",
    "$.host_evidence.gateway_attempt.result.task_bound_evidence",
    "$.host_evidence.gateway_attempt.publication_projection_correction.source_result.raw_result",
    "$.host_evidence.gateway_attempt.publication_projection_correction.source_result.task_bound_evidence",
    "$.host_evidence.gateway_attempt.delivery_admission_reconciliation.source_unknown.raw_result",
    "$.host_evidence.gateway_attempt.delivery_admission_reconciliation.source_unknown.task_bound_evidence",
)
EVENT_STRIP_PATHS = tuple("$.record" + path[1:] for path in STRIP_PATHS)


def _remove(column: str, paths: tuple) -> str:
    return "json_remove(" + column + ", " + ", ".join("'" + p + "'" for p in paths) + ")"


def _has(column: str, paths: tuple) -> str:
    return "(" + " OR ".join("json_type(" + column + ",'" + p + "') IS NOT NULL" for p in paths) + ")"


IDENTITY_AFTER = _remove("payload_json", STRIP_PATHS)
EVENT_AFTER = _remove("effects_json", EVENT_STRIP_PATHS)
IDENTITY_HAS = _has("payload_json", STRIP_PATHS)
EVENT_HAS = _has("effects_json", EVENT_STRIP_PATHS)
_BYTES = "length(CAST({} AS BLOB))"


def _project(project_ref: Any) -> tuple:
    """``(authority or None, id)`` from a ResourceRef, a mapping, or a bare project id."""
    if isinstance(project_ref, str):
        return None, project_ref
    if isinstance(project_ref, Mapping):
        return project_ref.get("authority"), project_ref["id"]
    return project_ref.authority, project_ref.id


class CleanClose:
    """The owner operation. ``store`` is the owner's Store; ``native_bodies`` its body capability."""

    def __init__(self, store: Any, native_bodies: Any = None) -> None:
        self.store, self.native_bodies = store, native_bodies

    # -- the operation -----------------------------------------------------------
    def run(self, project_ref: Any, *, dry_run: bool = True) -> dict[str, Any]:
        authority, project_id = _project(project_ref)
        authority = authority or self.store.authority
        ref = {"authority": authority, "kind": "work.project", "id": project_id}
        report: dict[str, Any] = {"schema": SCHEMA, "project_ref": ref, "dry_run": bool(dry_run), "rows": [],
                                  "bodies": [], "evidence_backend": self._evidence_backend()}
        if authority != self.store.authority:
            return {**report, "outcome": "refused", "reason": "project belongs to another authority"}
        lifecycle = self._lifecycle(authority, project_id)
        report["lifecycle"] = lifecycle
        if lifecycle not in FINISHED:
            return {**report, "outcome": "refused",
                    "reason": "project is not completed or withdrawn (lifecycle: %s)" % lifecycle}
        if dry_run:
            with self.store.read_transaction():
                self._strip(self.store.connection, authority, project_id, report, apply=False)
        else:
            # One exclusive transaction on the owner's own connection; a failed
            # verification raises and rolls the whole rewrite back.
            with self.store.transaction() as tx:
                self._strip(tx, authority, project_id, report, apply=True)
        self._bodies(ref, report, apply=not dry_run)
        report["totals"] = self._totals(report)
        changed = report["totals"]["rows"] or report["totals"]["bodies"] or report["totals"]["marker_to_write"]
        report["outcome"] = ("planned" if changed else "nothing-to-do") if dry_run else (
            "cleaned" if changed else "nothing-to-do")
        report["space"] = ("Freed pages are reused by later writes, so the store stops growing. The file shrinks "
                           "only with an offline VACUUM: `otto-clean-close.py apply`, or VACUUM INTO + swap with "
                           "the owner stopped.")
        return report

    def on_finished(self, project_ref: Any) -> Optional[dict[str, Any]]:
        """Lifecycle hook: clean-close the project; a failure is logged and never raised."""
        try:
            result = self.run(project_ref, dry_run=False)
            if result["outcome"] == "cleaned":
                LOG.info("clean-close %s: %d rows, %d bodies, %d bytes reclaimed", result["project_ref"]["id"],
                         result["totals"]["rows"], result["totals"]["bodies"], result["totals"]["bytes_freed"])
            return result
        except Exception as exc:  # never block or undo the lifecycle transition
            LOG.warning("clean-close of project %r failed (%s: %s); run it by hand", project_ref,
                        type(exc).__name__, exc)
            return None

    # -- parts ------------------------------------------------------------------
    def _lifecycle(self, authority: str, project_id: str) -> Optional[str]:
        with self.store.read_transaction():
            row = self.store.connection.execute(
                "SELECT json_extract(payload_json,'$.lifecycle') FROM identities "
                "WHERE authority=? AND kind='work.project' AND id=?", (authority, project_id)).fetchone()
        return None if row is None else row[0]

    def _evidence_backend(self) -> dict[str, Any]:
        bodies = self.native_bodies
        if bodies is not None and getattr(bodies, "evidence", None) is not None:
            return {"status": "out_of_scope",
                    "reason": "Evidence-backed bodies are reclaimed by Herzchen's explicit reclaim_preview/"
                              "reclaim_apply workflow (an approved preview, dependency state, request keys); "
                              "completion is not purge authority and the owner has no Evidence handler here"}
        return {"status": "not-applicable", "reason": "no Evidence-backed native bodies are composed"}

    def _strip(self, db: Any, authority: str, project_id: str, report: dict, *, apply: bool) -> None:
        select = "SELECT id FROM identities WHERE authority=? AND kind='otto.due-record' " \
                 "AND json_extract(payload_json,'$.project_ref')=?"
        due_ids = [row[0] for row in db.execute(select, (authority, project_id)).fetchall()]
        db.execute("CREATE TEMP TABLE IF NOT EXISTS clean_close_due(id TEXT PRIMARY KEY)")
        db.execute("DELETE FROM temp.clean_close_due")
        try:
            db.executemany("INSERT INTO temp.clean_close_due VALUES (?)", [(i,) for i in due_ids])
            sel = "(SELECT id FROM temp.clean_close_due)"
            before = db.execute("SELECT (SELECT count(*) FROM identities), (SELECT count(*) FROM events), "
                                "(SELECT max(append_position) FROM events)").fetchone()
            identities = db.execute(
                "SELECT kind || '/' || id, " + _BYTES.format("payload_json") + ", " +
                _BYTES.format(IDENTITY_AFTER) + " FROM identities WHERE authority=? AND kind='otto.due-record' "
                "AND id IN " + sel + " AND " + IDENTITY_HAS + " ORDER BY id", (authority,)).fetchall()
            events = db.execute(
                "SELECT event_id, " + _BYTES.format("effects_json") + ", " + _BYTES.format(EVENT_AFTER) +
                " FROM events WHERE subject_authority=? AND subject_kind='otto.due-record' AND subject_id IN " + sel +
                " AND " + EVENT_HAS + " ORDER BY append_position", (authority,)).fetchall()
            for key, was, now in identities:
                report["rows"].append({"table": "identities", "key": key, "field": "payload_json",
                                       "bytes_before": was, "bytes_after": now})
            for key, was, now in events:
                report["rows"].append({"table": "events", "key": key, "field": "effects_json",
                                       "bytes_before": was, "bytes_after": now})
            if apply and (identities or events):
                n_id = db.execute(
                    "UPDATE identities SET payload_json=" + IDENTITY_AFTER + " WHERE authority=? AND "
                    "kind='otto.due-record' AND id IN " + sel + " AND " + IDENTITY_HAS, (authority,)).rowcount
                n_ev = db.execute(
                    "UPDATE events SET effects_json=" + EVENT_AFTER + " WHERE subject_authority=? AND "
                    "subject_kind='otto.due-record' AND subject_id IN " + sel + " AND " + EVENT_HAS,
                    (authority,)).rowcount
                after = db.execute("SELECT (SELECT count(*) FROM identities), (SELECT count(*) FROM events), "
                                   "(SELECT max(append_position) FROM events)").fetchone()
                left = db.execute(
                    "SELECT (SELECT count(*) FROM identities WHERE authority=? AND kind='otto.due-record' AND id IN "
                    + sel + " AND " + IDENTITY_HAS + ") + (SELECT count(*) FROM events WHERE subject_authority=? "
                    "AND subject_kind='otto.due-record' AND subject_id IN " + sel + " AND " + EVENT_HAS + ")",
                    (authority, authority)).fetchone()[0]
                if (tuple(before) != tuple(after) or n_id != len(identities) or n_ev != len(events) or left
                        or after[1] != after[2]):
                    raise RuntimeError("clean-close verification failed; rewrite rolled back")
        finally:
            db.execute("DROP TABLE IF EXISTS temp.clean_close_due")

    def _bodies(self, ref: dict, report: dict, *, apply: bool) -> None:
        bodies = self.native_bodies
        files = getattr(bodies, "files", None)
        if files is None:
            report["file_bodies"] = {"status": "not-applicable", "reason": "no file-backed body store is composed"}
            return
        for entry in files.entries(ref):
            report["bodies"].append({"table": "native-bodies", "key": entry["key"],
                                     "bytes_before": entry["bytes"], "bytes_after": 0})
        marker_missing = not files.purged(ref)
        report["file_bodies"] = {"status": "purged" if apply else "planned", "marker_missing_before": marker_missing}
        if apply:
            bodies.purge_project(ref)

    @staticmethod
    def _totals(report: dict) -> dict[str, Any]:
        rows, bodies = report["rows"], report["bodies"]
        freed = sum(r["bytes_before"] - r["bytes_after"] for r in rows + bodies)
        marker = bool(report.get("file_bodies", {}).get("marker_missing_before"))
        return {"rows": len(rows), "bodies": len(bodies), "bytes_freed": freed, "marker_to_write": marker}
