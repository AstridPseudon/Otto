"""Bounded maintenance and authenticated reads for the Events projection.

The FND ``events`` table remains the only authoritative history.  This module
owns only the rebuildable ``project_history`` projection and its bounded read
protocol.  Readers use projection metadata and never call ``list_events`` or
run maintenance as a side effect of a read.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import hmac
import json
import sqlite3
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from herzchen.contracts import AuthenticatedActor, ResourceRef, canonical_json
from .history import HISTORY_SCHEMA, MAX_SUMMARY_BYTES, project_relations, projection_rows, source_facets


SCHEMA = "fnd.project-history-reader.v1"
CURSOR_FORMAT = "fnd.project-history.cursor.v1"
DEFAULT_BATCH = 100
MAX_BATCH = 1000
MAX_DETAIL_BYTES = 64 * 1024
MAX_METADATA_CANDIDATES = 1000
MAX_PROJECTS = 32
_KEY_COLUMNS = ("recorded_at", "source_append_position", "facet_index", "facet_id")


class ProjectHistoryError(ValueError):
    """Base error for bounded project-history operations."""


class ProjectionMaintenanceError(ProjectHistoryError):
    """The source is valid but the projection cannot currently advance."""


class AuthorizationError(ProjectHistoryError):
    """The supplied authenticated grant does not authorize the request."""


class SnapshotRefreshRequired(ProjectHistoryError):
    """A cursor/snapshot no longer matches the active generation or grant."""


class CursorError(SnapshotRefreshRequired):
    """A cursor is malformed, out of scope, or stale."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _ref_dict(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, ResourceRef):
        return value.to_dict()
    if isinstance(value, Mapping) and all(isinstance(value.get(k), str) for k in ("authority", "kind", "id")):
        return {k: value.get(k) for k in ("authority", "kind", "id", "revision")}
    return None


def _project_key(value: Any, authority: str) -> tuple[str, str]:
    ref = _ref_dict(value)
    if ref is None or ref["kind"] != "work.project" or ref["authority"] != authority:
        raise AuthorizationError("project scope is not an authorized local project")
    return ref["authority"], ref["id"]


def _iso_datetime(value: Any, *, field: str, timezone_name: Optional[str] = None) -> datetime:
    """Parse an exact instant; date-only values require an IANA timezone."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date) and not isinstance(value, datetime):
        value = value.isoformat()
        parsed = None
    elif isinstance(value, str):
        parsed = None
    else:
        raise ProjectHistoryError(f"{field} must be an ISO timestamp or date")
    if parsed is None:
        text = str(value)
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            if not timezone_name:
                raise ProjectHistoryError(f"{field} date-only range requires an IANA timezone")
            try:
                zone = ZoneInfo(timezone_name)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ProjectHistoryError(f"{field} timezone must be an IANA zone") from exc
            try:
                local_date = date.fromisoformat(text)
            except ValueError as exc:
                raise ProjectHistoryError(f"{field} is not a valid date") from exc
            parsed = datetime.combine(local_date, time.min, zone)
            # A local midnight can be ambiguous/nonexistent in a few IANA
            # zones.  Round-trip both folds and reject anything that changes.
            for fold in (0, 1):
                candidate = parsed.replace(fold=fold)
                if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != candidate.replace(tzinfo=None):
                    raise ProjectHistoryError(f"{field} local time is nonexistent or ambiguous")
            if parsed.replace(fold=0).utcoffset() != parsed.replace(fold=1).utcoffset():
                raise ProjectHistoryError(f"{field} local time is nonexistent or ambiguous")
        else:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ProjectHistoryError(f"{field} must be an ISO-8601 timestamp") from exc
            if parsed.tzinfo is None:
                if not timezone_name:
                    raise ProjectHistoryError(f"{field} must include a timezone or an IANA timezone")
                try:
                    zone = ZoneInfo(timezone_name)
                except (ZoneInfoNotFoundError, ValueError) as exc:
                    raise ProjectHistoryError(f"{field} timezone must be an IANA zone") from exc
                for fold in (0, 1):
                    candidate = parsed.replace(tzinfo=zone, fold=fold)
                    if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != parsed:
                        raise ProjectHistoryError(f"{field} local time is nonexistent or ambiguous")
                if parsed.replace(tzinfo=zone, fold=0).utcoffset() != parsed.replace(tzinfo=zone, fold=1).utcoffset():
                    raise ProjectHistoryError(f"{field} local time is nonexistent or ambiguous")
                parsed = parsed.replace(tzinfo=zone)
    if parsed.tzinfo is None:
        raise ProjectHistoryError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _range(from_value: Any, to_value: Any, timezone_name: Optional[str]) -> tuple[str, str]:
    start = _iso_datetime(from_value, field="from", timezone_name=timezone_name)
    end = _iso_datetime(to_value, field="to", timezone_name=timezone_name)
    if end <= start:
        raise ProjectHistoryError("recorded-time range must be non-empty and use [from,to)")
    return start.isoformat(timespec="microseconds").replace("+00:00", "Z"), end.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _grant_parts(grant: Any, authority: str) -> tuple[Any, tuple[str, ...], str]:
    if grant is None:
        raise AuthorizationError("an authenticated project-read grant is required")
    principal = getattr(grant, "principal", None)
    ids = getattr(grant, "project_ids", None)
    revision = getattr(grant, "policy_revision", None)
    if revision is None:
        revision = getattr(grant, "grant_revision", None)
    if principal is None and isinstance(grant, Mapping):
        principal, ids, revision = grant.get("principal"), grant.get("project_ids"), grant.get("revision", grant.get("grant_revision"))
    if not isinstance(principal, AuthenticatedActor):
        raise AuthorizationError("grant principal is not authenticated")
    if principal.authority != authority or not isinstance(ids, (tuple, list)) or not ids or len(ids) > MAX_PROJECTS:
        raise AuthorizationError("grant has an invalid project scope")
    if not all(isinstance(item, str) and item.strip() and "/" not in item for item in ids):
        raise AuthorizationError("grant has an invalid project scope")
    if not isinstance(revision, str) or not revision.strip():
        raise AuthorizationError("grant revision is required")
    return principal, tuple(dict.fromkeys(ids)), revision


def _same_actor(left: Any, right: Any) -> bool:
    return isinstance(left, AuthenticatedActor) and isinstance(right, AuthenticatedActor) and left == right


@dataclass(frozen=True)
class ProjectHistoryGrant:
    """Small framework-neutral grant accepted by the authenticated reader."""

    principal: AuthenticatedActor
    project_ids: tuple[str, ...]
    policy_source: str = "owner"
    policy_revision: str = "1"

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedActor):
            raise TypeError("principal must be an AuthenticatedActor")
        if not isinstance(self.project_ids, tuple) or not 1 <= len(self.project_ids) <= MAX_PROJECTS:
            raise ValueError("project_ids must contain 1..32 projects")
        if len(set(self.project_ids)) != len(self.project_ids) or not all(isinstance(x, str) and x.strip() for x in self.project_ids):
            raise ValueError("project_ids must be distinct non-empty strings")
        if not all(isinstance(x, str) and x.strip() for x in (self.policy_source, self.policy_revision)):
            raise ValueError("grant policy identity is required")

    @property
    def grant_revision(self) -> str:
        return self.policy_revision


def _token_encode(value: Mapping[str, Any]) -> str:
    body = _json(dict(value)).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest().encode("ascii")
    return base64.urlsafe_b64encode(body + b"." + digest).decode("ascii").rstrip("=")


def _token_decode(token: str) -> dict[str, Any]:
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise CursorError("cursor is malformed")
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        body, supplied = raw.rsplit(b".", 1)
        expected = hashlib.sha256(body).hexdigest().encode("ascii")
        if not hmac.compare_digest(supplied, expected):
            raise CursorError("cursor integrity check failed")
        value = json.loads(body)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise CursorError("cursor is malformed") from exc
    if not isinstance(value, dict):
        raise CursorError("cursor is malformed")
    return value


class ProjectHistoryProjection:
    """Owner-side bounded projector over the admitted successor composition."""

    def __init__(self, store: Any, *, manifest_reader: Any = None, default_batch: int = DEFAULT_BATCH) -> None:
        if not hasattr(store, "connection") or not hasattr(store, "transaction"):
            raise TypeError("project history maintenance requires an admitted writable Store")
        if type(default_batch) is not int or not 1 <= default_batch <= MAX_BATCH:
            raise ValueError("default_batch must be between 1 and 1000")
        self.store = store
        self.manifest_reader = manifest_reader
        self.default_batch = default_batch

    @property
    def connection(self) -> sqlite3.Connection:
        return self.store.connection

    def _metadata(self) -> dict[str, str]:
        return dict(self.connection.execute("SELECT key,value FROM store_metadata"))

    def status(self) -> dict[str, Any]:
        metadata = self._metadata()
        checkpoint = int(metadata.get("history_checkpoint", "0"))
        maximum = int(self.connection.execute("SELECT COALESCE(MAX(append_position),0) FROM events").fetchone()[0])
        return {
            "schema": SCHEMA, "generation": int(metadata.get("history_generation", "1")),
            "checkpoint": checkpoint, "source_append_boundary": maximum,
            "lag": max(0, maximum - checkpoint), "covered": checkpoint >= maximum,
            "facet_continuation": {k:v for k,v in json.loads(metadata["history_manifest_continuation:" + str(metadata.get("history_generation", "1"))]).items() if k != "pending_hex"} if metadata.get("history_manifest_continuation:" + str(metadata.get("history_generation", "1"))) else None,
            "last_error": json.loads(metadata["history_lag_error"]) if metadata.get("history_lag_error") else None,
        }

    def _manifest_page(self, manifest, offset):
        ref = _ref_dict(manifest.get("ref"))
        if ref is None or self.manifest_reader is None:
            raise ProjectionMaintenanceError("history manifest requires an exact admitted Evidence reader")
        if hasattr(self.manifest_reader, "read_evidence"):
            page = self.manifest_reader.read_evidence(ResourceRef.from_dict(ref), offset=offset, max_bytes=4096)
        else:
            page = self.manifest_reader(ref, offset, 4096)
        if not isinstance(page, Mapping) or not isinstance(page.get("bytes"), (bytes, bytearray)):
            raise ProjectionMaintenanceError("Evidence manifest range reader returned no bounded bytes")
        data = bytes(page["bytes"])
        nxt = page.get("next_offset")
        if len(data) > 4096 or (nxt is not None and (not data or type(nxt) is not int or nxt != offset + len(data))):
            raise ProjectionMaintenanceError("Evidence manifest continuation did not advance by its exact bounded bytes")
        if offset + len(data) > MAX_SUMMARY_BYTES * 128:
            raise ProjectionMaintenanceError("Evidence manifest exceeds bounded maintenance fan-out")
        return data, nxt

    def _manifest_facets(self, row, history):
        """Stream JSONL across arbitrary byte boundaries; never retain the body."""
        manifest = history["manifest"]
        offset, count, pending = 0, 0, b""
        digest = hashlib.sha256()
        while True:
            data, nxt = self._manifest_page(manifest, offset)
            digest.update(data); pending += data
            lines = pending.split(b"\n"); pending = lines.pop()
            if nxt is None and pending:
                lines.append(pending); pending = b""
            for line in lines:
                if line.strip():
                    if len(line) > MAX_SUMMARY_BYTES:
                        raise ProjectionMaintenanceError("Evidence manifest facet exceeds its summary bound")
                    item = json.loads(line)
                    if not isinstance(item, Mapping):
                        raise ProjectionMaintenanceError("Evidence manifest facet is not an object")
                    count += 1
                    yield item
            if len(pending) > MAX_SUMMARY_BYTES:
                raise ProjectionMaintenanceError("Evidence manifest facet exceeds its summary bound")
            if nxt is None:
                break
            offset = nxt
        if manifest.get("facet_count") is not None and count != manifest["facet_count"]:
            raise ProjectionMaintenanceError("Evidence manifest facet count changed")
        if manifest.get("byte_digest") is not None and digest.hexdigest() != manifest["byte_digest"]:
            raise ProjectionMaintenanceError("Evidence manifest digest changed")

    def _facet_rows(self, row, facets, generation, start_index=0):
        synthetic = {key: row[key] for key in row.keys()} if hasattr(row, "keys") else dict(row)
        synthetic["effects_json"] = _json({"history_summary": {"schema": HISTORY_SCHEMA, "primary": facets[0], "facets": facets[1:]}})
        try:
            refs = [ref for ref in json.loads(row["after_refs_json"])
                    if isinstance(ref, Mapping) and str(ref.get("kind", "")).startswith("dat.content.")]
        except (TypeError, ValueError, json.JSONDecodeError):
            refs = []
        for value in projection_rows(synthetic, generation=generation, start_index=start_index):
            locator = json.loads(value[-1]); locator["evidence_refs"] = refs
            yield tuple(list(value[:-1]) + [_json(locator)])

    def _rows_for_event(self, row, generation):
        history = json.loads(row["effects_json"]).get("history_summary")
        if isinstance(history, Mapping) and history.get("schema") == HISTORY_SCHEMA and history.get("manifest"):
            yield from self._facet_rows(row, [history["primary"]], generation)
            for index, facet in enumerate(self._manifest_facets(row, history), start=1):
                yield from self._facet_rows(row, [facet], generation, start_index=index)
        else:
            yield from self._facet_rows(row, list(source_facets(row)), generation)

    def _manifest_batch(self, tx, row, history, generation, budget):
        """Persist byte/facet continuation atomically with the projected rows.

        Only complete verified source positions become visible. The final
        digest pass streams at most the declared 8 MiB manifest cap; it never
        accumulates facets or body bytes. Its I/O is explicitly reported.
        """
        key = "history_manifest_continuation:" + str(generation)
        saved = tx.execute("SELECT value FROM store_metadata WHERE key=?", (key,)).fetchone()
        manifest = history["manifest"]
        binding = {"event_id": row["event_id"], "position": row["append_position"], "manifest": manifest}
        progress = json.loads(saved[0]) if saved else {"binding": binding, "offset": 0, "next_index": 1, "pending_hex": "", "eof": False, "primary_done": False}
        if progress["binding"] != binding:
            raise ProjectionMaintenanceError("retained manifest continuation belongs to different source work")
        count = 0
        def insert(facet, index):
            nonlocal count
            for value in self._facet_rows(row, [facet], generation, start_index=index):
                tx.execute("INSERT OR IGNORE INTO project_history VALUES (" + ",".join("?" for _ in value) + ")", value)
                count += 1
        if not progress["primary_done"]:
            insert(history["primary"], 0); progress["primary_done"] = True
        pending = bytes.fromhex(progress["pending_hex"])
        units, read_bytes = 0, 0
        while units < budget:
            newline = pending.find(b"\n")
            if newline >= 0 or (progress["eof"] and pending):
                stop = newline if newline >= 0 else len(pending)
                line, pending = pending[:stop], pending[stop + (newline >= 0):]
                if line.strip():
                    if len(line) > MAX_SUMMARY_BYTES:
                        raise ProjectionMaintenanceError("Evidence manifest facet exceeds its summary bound")
                    item = json.loads(line)
                    if not isinstance(item, Mapping):
                        raise ProjectionMaintenanceError("Evidence manifest facet is not an object")
                    insert(item, progress["next_index"]); progress["next_index"] += 1; units += 1
                continue
            if progress["eof"] or read_bytes >= 4096 * budget:
                break
            data, nxt = self._manifest_page(manifest, progress["offset"])
            pending += data; read_bytes += len(data); progress["offset"] += len(data); progress["eof"] = nxt is None
            if b"\n" not in pending and len(pending) > MAX_SUMMARY_BYTES:
                raise ProjectionMaintenanceError("Evidence manifest facet exceeds its summary bound")
        progress["pending_hex"] = pending.hex()
        done = progress["eof"] and not pending
        verify_bytes = 0
        if done:
            # Validate all immutable byte ranges without materializing them.
            offset = 0; digest = hashlib.sha256()
            while True:
                data, nxt = self._manifest_page(manifest, offset); digest.update(data); verify_bytes += len(data)
                if nxt is None:break
                offset = nxt
            if manifest.get("facet_count") != progress["next_index"] - 1 or manifest.get("byte_digest") != digest.hexdigest():
                raise ProjectionMaintenanceError("Evidence manifest final count or digest changed")
            tx.execute("DELETE FROM store_metadata WHERE key=?", (key,))
        else:
            tx.execute("INSERT OR REPLACE INTO store_metadata(key,value) VALUES (?,?)", (key, _json(progress)))
        self._last_manifest_io = {"range_bytes_read": read_bytes, "verification_bytes_read": verify_bytes,
                                  "verification_max_bytes": MAX_SUMMARY_BYTES * 128, "continuation": not done}
        return count, done

    def _apply(self, tx, rows, generation, facet_budget=None):
        projected, last = 0, 0
        for row in rows:
            history = json.loads(row["effects_json"]).get("history_summary")
            if isinstance(history, Mapping) and history.get("schema") == HISTORY_SCHEMA and history.get("manifest"):
                count, done = self._manifest_batch(tx, row, history, generation, facet_budget or self.default_batch)
                projected += count
                if not done:break
            else:
                for value in self._rows_for_event(row, generation):
                    tx.execute("INSERT OR IGNORE INTO project_history VALUES (" + ",".join("?" for _ in value) + ")", value)
                    projected += 1
            last = int(row["append_position"])
        return projected, last

    def maintain(self, *, limit: Optional[int] = None, raise_on_error: bool = False) -> dict[str, Any]:
        limit = self.default_batch if limit is None else limit
        if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
            raise ValueError("maintenance limit must be between 1 and 1000")
        metadata = self._metadata()
        generation = int(metadata.get("history_generation", "1"))
        checkpoint = int(metadata.get("history_checkpoint", "0"))
        self._last_manifest_io = None
        try:
            with self.store.transaction() as tx:
                rows = tx.execute("SELECT * FROM events WHERE append_position > ? ORDER BY append_position LIMIT ?", (checkpoint, limit)).fetchall()
                projected, last = self._apply(tx, rows, generation, facet_budget=limit)
                if last:
                    tx.execute("UPDATE store_metadata SET value=? WHERE key='history_checkpoint'", (str(last),))
                tx.execute("DELETE FROM store_metadata WHERE key='history_lag_error'")
            result = self.status()
            result.update({"outcome": "advanced" if rows else "caught_up", "events_examined": len(rows), "rows_projected": projected, "manifest_io": getattr(self, "_last_manifest_io", None)})
            return result
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc), "checkpoint": checkpoint, "generation": generation}
            try:
                with self.store.transaction() as tx:
                    tx.execute("INSERT OR REPLACE INTO store_metadata(key,value) VALUES ('history_lag_error',?)", (_json(error),))
            except Exception:
                pass
            if raise_on_error:
                raise
            result = self.status()
            result.update({"outcome": "lagged", "events_examined": 0, "rows_projected": 0, "error": error})
            return result

    def rebuild(self, *, batch_size: Optional[int] = None) -> dict[str, Any]:
        batch_size = self.default_batch if batch_size is None else batch_size
        if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH:
            raise ValueError("rebuild batch_size must be between 1 and 1000")
        current = self.status()
        new_generation = int(current["generation"]) + 1
        try:
            with self.store.transaction() as tx:
                tx.execute("DELETE FROM project_history WHERE generation=?", (new_generation,))
                tx.execute("DELETE FROM store_metadata WHERE key=?", ("history_manifest_continuation:" + str(new_generation),))
            checkpoint = 0
            total_rows = 0
            while True:
                with self.store.transaction() as tx:
                    rows = tx.execute("SELECT * FROM events WHERE append_position > ? ORDER BY append_position LIMIT ?", (checkpoint, batch_size)).fetchall()
                    projected, last = self._apply(tx, rows, new_generation, facet_budget=batch_size)
                if not rows:
                    break
                total_rows += projected
                if last:checkpoint = last
            # Verify the new generation against the deterministic source walk
            # before changing the active generation or invalidating cursors.
            expected = hashlib.sha256(); expected_count = 0
            for row in self.connection.execute("SELECT * FROM events ORDER BY append_position"):
                for value in self._rows_for_event(row, new_generation):
                    expected.update(canonical_json(list(value)).encode() + b"\n"); expected_count += 1
            actual = hashlib.sha256(); actual_count = 0
            for row in self.connection.execute("SELECT * FROM project_history WHERE generation=? ORDER BY source_append_position,facet_index,project_authority,project_id,facet_id", (new_generation,)):
                actual.update(canonical_json(list(row)).encode() + b"\n"); actual_count += 1
            if expected_count != actual_count or expected.digest() != actual.digest():
                raise ProjectionMaintenanceError("deterministic rebuild equality failed")
            with self.store.transaction() as tx:
                tx.execute("UPDATE store_metadata SET value=? WHERE key='history_generation'", (str(new_generation),))
                tx.execute("UPDATE store_metadata SET value=? WHERE key='history_checkpoint'", (str(checkpoint),))
                tx.execute("DELETE FROM store_metadata WHERE key='history_lag_error'")
            result = self.status()
            result.update({"outcome": "switched", "previous_generation": current["generation"], "rows_projected": total_rows, "rebuild_rows": actual_count})
            return result
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc), "generation": new_generation}
            try:
                with self.store.transaction() as tx:
                    tx.execute("INSERT OR REPLACE INTO store_metadata(key,value) VALUES ('history_rebuild_error',?)", (_json(error),))
            except Exception:
                pass
            raise

    def post_commit_hook(self, *, limit: Optional[int] = None) -> Callable[[], dict[str, Any]]:
        return lambda: self.maintain(limit=limit)


class ProjectHistoryReader:
    """One authenticated, bounded owner reader over ``project_history``."""

    def __init__(self, store: Any, *, grant: Any = None, grant_reader: Optional[Callable[[], Any]] = None, evidence_reader: Any = None) -> None:
        if not hasattr(store, "connection") and callable(getattr(store, "_project_history_owner", None)):
            store = store._project_history_owner()
        if not hasattr(store, "connection"):
            raise TypeError("project history reader requires an owner-backed reader")
        self.store = store
        self.grant = grant
        self.grant_reader = grant_reader
        self.evidence_reader = evidence_reader

    @property
    def connection(self) -> sqlite3.Connection:
        return self.store.connection

    def _current_grant(self, supplied: Any) -> Any:
        # A grant reader is the reauthorization boundary.  A caller-supplied
        # page token/grant is useful as a transport value, but it must not
        # bypass the current owner policy when a live reader is available.
        return self.grant_reader() if self.grant_reader else (supplied if supplied is not None else self.grant)

    def _scope(self, projects: Optional[Sequence[Any]], grant: Any) -> tuple[AuthenticatedActor, tuple[tuple[str, str], ...], str]:
        principal, allowed, revision = _grant_parts(grant, self.store.authority)
        if projects is None:
            projects = tuple(ResourceRef(self.store.authority, "work.project", item) for item in allowed)
        if isinstance(projects, (str, bytes)) or not 1 <= len(projects) <= MAX_PROJECTS:
            raise ProjectHistoryError("project scope must contain 1..32 explicit projects")
        selected = tuple(_project_key(item, self.store.authority) for item in projects)
        if any(project_id not in allowed for _authority, project_id in selected):
            raise AuthorizationError("project scope is not authorized")
        return principal, tuple(dict.fromkeys(selected)), revision

    def _snapshot(self, *, grant_revision: str, projects: tuple[tuple[str, str], ...], from_at: Optional[str], to_at: Optional[str], active: Any, filters: Mapping[str, Any], generation: int, boundary: int) -> dict[str, Any]:
        # Keep the persisted/token form JSON-shaped so a snapshot survives a
        # round trip through the owner reader without changing its normalized
        # scope identity.
        scope = {"projects": [list(project) for project in projects], "from": from_at, "to": to_at, "active_during": active, "filters": dict(filters)}
        shape = {"authority": self.store.authority, "owner_incarnation": self.store.authority, "grant_revision": grant_revision, "generation": generation, "boundary": boundary, "scope": scope}
        return {**shape, "snapshot_digest": _digest(shape)}

    def _snapshot_projects(self, snapshot: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
        scope = snapshot.get("scope")
        projects = scope.get("projects") if isinstance(scope, Mapping) else None
        if isinstance(projects, (str, bytes)) or not isinstance(projects, (tuple, list)) or not 1 <= len(projects) <= MAX_PROJECTS:
            raise SnapshotRefreshRequired("snapshot project scope is malformed")
        normalized = []
        for project in projects:
            if not isinstance(project, (tuple, list)) or len(project) != 2 or not all(isinstance(item, str) and item.strip() for item in project):
                raise SnapshotRefreshRequired("snapshot project scope is malformed")
            authority, project_id = project
            if authority != self.store.authority or "/" in project_id:
                raise SnapshotRefreshRequired("snapshot project scope is malformed")
            normalized.append((authority, project_id))
        if len(set(normalized)) != len(normalized):
            raise SnapshotRefreshRequired("snapshot project scope is malformed")
        return tuple(normalized)

    def _validate_snapshot(self, token: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
        if not isinstance(token, Mapping) or token.get("schema") not in (None, SCHEMA):
            raise SnapshotRefreshRequired("snapshot is malformed")
        supplied = token.get("snapshot_digest")
        body = {key: token.get(key) for key in ("authority", "owner_incarnation", "grant_revision", "generation", "boundary", "scope")}
        if supplied != _digest(body):
            raise SnapshotRefreshRequired("snapshot integrity check failed")
        stable = ("authority", "owner_incarnation", "grant_revision", "generation", "scope")
        # A fixed snapshot remains readable after later source facts are
        # projected.  Its covered boundary is immutable and may be older than
        # the current checkpoint; a generation switch is the invalidation
        # boundary.
        boundary = body.get("boundary")
        current_boundary = expected.get("boundary")
        if (any(body.get(key) != expected.get(key) for key in stable)
                or type(boundary) is not int or type(current_boundary) is not int
                or boundary < 0 or boundary > current_boundary):
            raise SnapshotRefreshRequired("snapshot scope, generation, grant, or owner boundary changed")

    def _decode_cursor(self, cursor: str) -> dict[str, Any]:
        value = _token_decode(cursor)
        if value.get("format") != CURSOR_FORMAT or not isinstance(value.get("snapshot"), str) or not value.get("snapshot"):
            raise CursorError("cursor format is unsupported")
        return value

    def _encode_cursor(self, snapshot: Mapping[str, Any], key: Sequence[Any]) -> str:
        return _token_encode({"format": CURSOR_FORMAT, "snapshot": snapshot["snapshot_digest"], "key": list(key)})

    def _inventory_active(self, projects: Sequence[tuple[str, str]]) -> tuple[set[tuple[str, str]], int]:
        if not projects:
            return set(), 0
        placeholders = ",".join("?" for _ in projects)
        rows = self.connection.execute("SELECT id,payload_json FROM identities WHERE authority=? AND kind='work.project' AND id IN (" + placeholders + ")", (self.store.authority, *(item[1] for item in projects))).fetchall()
        active: set[tuple[str, str]] = set()
        for row in rows:
            payload = json.loads(row[1])
            if payload.get("lifecycle") in {"active", "running", "open"} or payload.get("status") in {"active", "running", "open"}:
                active.add((self.store.authority, row[0]))
        return active, len(rows)

    def _historical_active_result(self, projects, start, end, *, generation, boundary,
                                  progress=None, return_progress=False):
        """Inspect at most 1,000 captured summaries, with explicit continuation.

        Metadata keyset seeks precede Python lifecycle inspection. No JSON
        predicate can hide a scan behind LIMIT. Missing state and unfinished
        discovery are separate, explicit coverage gaps; current heads are unused.
        """
        projects = tuple(projects)
        state = dict(progress or {"index": 0, "after": None, "known": False,
                                 "active": [], "unknown": []})
        if (set(state) != {"index", "after", "known", "active", "unknown"}
                or type(state["index"]) is not int or not 0 <= state["index"] <= len(projects)
                or type(state["known"]) is not bool):
            raise CursorError("active discovery progress is malformed")
        after = state["after"]
        if after is not None and (not isinstance(after, list) or len(after) != 4
                or not isinstance(after[0], str) or type(after[1]) is not int
                or type(after[2]) is not int or not isinstance(after[3], str)):
            raise CursorError("active discovery key is malformed")
        for name in ("active", "unknown"):
            values = state[name]
            if not isinstance(values, list) or any(not isinstance(x,list) or tuple(x) not in projects for x in values):
                raise CursorError("active discovery projects are out of scope")
        active = {tuple(x) for x in state["active"]}
        unknown = {tuple(x) for x in state["unknown"]}
        examined = hydrated = 0
        while state["index"] < len(projects) and examined < MAX_METADATA_CANDIDATES:
            authority, project = projects[state["index"]]
            where = ("generation=? AND project_authority=? AND project_id=? "
                     "AND subject_authority=? AND subject_kind='work.project' "
                     "AND subject_id=? AND source_append_position<=?")
            args = (generation, authority, project, authority, project, boundary)
            if state["after"] is None:
                prior = self.connection.execute(
                    "SELECT summary_json FROM project_history WHERE " + where +
                    " AND recorded_at<? ORDER BY recorded_at DESC,source_append_position DESC,facet_index DESC,facet_id DESC LIMIT 1",
                    (*args, start)).fetchone()
                fields = {}
                if prior is not None:
                    examined += 1; hydrated += len(prior[0].encode())
                    fields = json.loads(prior[0]).get("after",{}).get("fields",{})
                value = fields.get("lifecycle", fields.get("status"))
                state["known"] = value in {"active","running","open","pending","completed","closed","stopped","withdrawn","failed"}
                if value in {"active","running","open"}:
                    active.add((authority,project)); state["index"] += 1
                    state["known"] = False
                    continue
            remaining = MAX_METADATA_CANDIDATES - examined
            if not remaining: break
            clause = " AND recorded_at>=? AND recorded_at<?"
            tail = [start,end]
            if state["after"] is not None:
                clause += " AND (recorded_at,source_append_position,facet_index,facet_id)>(?,?,?,?)"
                tail.extend(state["after"])
            rows = self.connection.execute(
                "SELECT recorded_at,source_append_position,facet_index,facet_id,summary_json FROM project_history WHERE " + where + clause +
                " ORDER BY recorded_at,source_append_position,facet_index,facet_id LIMIT ?",
                (*args,*tail,remaining)).fetchall()
            examined += len(rows); hydrated += sum(len(row[4].encode()) for row in rows)
            found = False
            for n,row in enumerate(rows):
                summary = json.loads(row[4])
                if n == 0 and state["after"] is None and not state["known"]:
                    before = summary.get("before",{})
                    fields = before.get("fields",{})
                    value = fields.get("lifecycle",fields.get("status"))
                    state["known"] = before.get("exists") is False or value in {"active","running","open","pending","completed","closed","stopped","withdrawn","failed"}
                    found = value in {"active","running","open"}
                fields = summary.get("after",{}).get("fields",{})
                found = found or fields.get("lifecycle",fields.get("status")) in {"active","running","open"}
                if found: break
            if found or len(rows) < remaining:
                if found: active.add((authority,project))
                elif not state["known"]: unknown.add((authority,project))
                state["index"] += 1; state["after"] = None; state["known"] = False
            else:
                state["after"] = list(rows[-1][:4])
                break
        state["active"] = [list(x) for x in sorted(active)]
        state["unknown"] = [list(x) for x in sorted(unknown)]
        incomplete = state["index"] < len(projects)
        unresolved = set(projects[state["index"]:]) if incomplete else set()
        if return_progress:
            return active, unknown | unresolved, examined, hydrated, state, not incomplete
        return active, unknown | unresolved, examined

    def _historical_active(self, projects, start, end, *, generation, boundary):
        active, unknown, _ = self._historical_active_result(
            projects, start, end, generation=generation, boundary=boundary)
        return active | unknown

    def _query_rows(self, *, snapshot: Mapping[str, Any], projects: Sequence[tuple[str, str]], limit: int, after: Optional[Sequence[Any]], from_at: Optional[str], to_at: Optional[str], filters: Mapping[str, Any], max_candidates: int = MAX_METADATA_CANDIDATES) -> tuple[list[sqlite3.Row], int]:
        where = ["generation=?", "source_append_position<=?"]
        args: list[Any] = [snapshot["generation"], snapshot["boundary"]]
        if projects:
            where.append("(" + " OR ".join("(project_authority=? AND project_id=?)" for _ in projects) + ")")
            for project in projects: args.extend(project)
        if from_at is not None:
            where.append("recorded_at>=?"); args.append(from_at)
        if to_at is not None:
            where.append("recorded_at<?"); args.append(to_at)
        if after is not None:
            where.append("(recorded_at,source_append_position,facet_index,facet_id)>(?,?,?,?)"); args.extend(after)
        rows = self.connection.execute("SELECT generation,facet_id,source_event_id,facet_index,source_append_position,stream,stream_sequence,project_authority,project_id,subject_authority,subject_kind,subject_id,subject_revision,recorded_at,occurred_at,facet_type,role,outcome FROM project_history WHERE " + " AND ".join(where) + " ORDER BY recorded_at,source_append_position,facet_index,facet_id LIMIT ?", (*args, max_candidates)).fetchall()
        return rows, len(rows)

    def read(self, *, projects: Optional[Sequence[Any]] = None, from_at: Any = None, to_at: Any = None, timezone_name: Optional[str] = None, active_during: Optional[Sequence[Any]] = None, limit: int = 50, cursor: Optional[str] = None, snapshot: Optional[Mapping[str, Any]] = None, grant: Any = None, actor: Any = None, filters: Optional[Mapping[str, Any]] = None, _state_validation: bool = False) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ProjectHistoryError("limit must be between 1 and 200")
        grant = self._current_grant(grant)
        principal, scope, grant_revision = self._scope(projects, grant)
        if actor is not None and not _same_actor(actor, principal):
            raise AuthorizationError("authenticated actor does not match the grant")
        filters = dict(filters or {})
        if set(filters) - {"role", "outcome", "facet_type"}:
            raise ProjectHistoryError("unsupported project-history filter")
        normalized_range = None
        if (from_at is None) != (to_at is None):
            raise ProjectHistoryError("from and to must be supplied together")
        if from_at is not None:
            normalized_range = _range(from_at, to_at, timezone_name)
        normalized_active = None
        if active_during is not None:
            if not isinstance(active_during, (tuple, list)) or len(active_during) != 2:
                raise ProjectHistoryError("active_during must be a [from,to) pair")
            normalized_active = _range(active_during[0], active_during[1], timezone_name)
        if cursor is not None:
            decoded = self._decode_cursor(cursor)
            if snapshot is None or decoded["snapshot"] != snapshot.get("snapshot_digest"):
                raise CursorError("cursor requires its original snapshot")
            if decoded.get("mode", "facts") not in ("facts", "active-discovery"):
                raise CursorError("state cursor cannot page event facts")
            after = decoded.get("key")
            if after is not None and (not isinstance(after, list) or len(after) != 4):
                raise CursorError("cursor key is malformed")
        else:
            after = None
        metadata = dict(self.connection.execute("SELECT key,value FROM store_metadata"))
        generation = int(metadata.get("history_generation", "1"))
        boundary = int(metadata.get("history_checkpoint", "0"))
        expected = self._snapshot(grant_revision=grant_revision, projects=scope, from_at=None if normalized_range is None else normalized_range[0], to_at=None if normalized_range is None else normalized_range[1], active=normalized_active, filters=filters, generation=generation, boundary=boundary)
        expected["schema"] = SCHEMA
        if snapshot is not None:
            self._validate_snapshot(snapshot, expected)
            expected = dict(snapshot)
        active_set, unknown_active, inventory_examined = set(), set(), 0
        discovery, discovery_complete, discovery_bytes = None, True, 0
        if normalized_active is not None:
            known_active, unknown_active, inventory_examined, discovery_bytes, discovery, discovery_complete = self._historical_active_result(
                scope, normalized_active[0], normalized_active[1],
                generation=int(expected["generation"]), boundary=int(expected["boundary"]),
                progress=None if cursor is None else decoded.get("discovery"), return_progress=True)
            active_set = known_active | unknown_active
        query_from = None if normalized_range is None and normalized_active is None else (normalized_range or normalized_active)[0]
        query_to = None if normalized_range is None and normalized_active is None else (normalized_range or normalized_active)[1]
        metadata_budget = MAX_METADATA_CANDIDATES - inventory_examined
        if _state_validation: metadata_budget = min(metadata_budget,1)
        rows, examined = self._query_rows(snapshot=expected, projects=scope, limit=limit, after=after, from_at=query_from, to_at=query_to, filters=filters,max_candidates=metadata_budget) if discovery_complete and metadata_budget else ([], 0)
        def matches(row: sqlite3.Row) -> bool:
            return ((normalized_active is None or (row[7], row[8]) in active_set)
                    and (filters.get("role") is None or row[16] == filters["role"])
                    and (filters.get("outcome") is None or row[17] == filters["outcome"])
                    and (filters.get("facet_type") is None or row[15] == filters["facet_type"]))
        matching = [row for row in rows if matches(row)]
        selected = matching[:limit]
        result_rows = []
        hydrated = 0
        detail_hydrated = 0
        candidate_bytes = 0
        for row in selected:
            summary_raw, detail_raw = self.connection.execute("SELECT summary_json,detail_json FROM project_history WHERE generation=? AND facet_id=?", (row[0], row[1])).fetchone()
            summary = json.loads(summary_raw); detail = json.loads(detail_raw)
            hydrated += len(summary_raw.encode())
            detail_hydrated += len(detail_raw.encode())
            candidate_bytes += sum(len(str(row[index]).encode()) for index in (1, 2, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17) if row[index] is not None)
            result_rows.append({"generation": row[0], "facet_id": row[1], "source_event_id": row[2], "facet_index": row[3], "source_append_position": row[4], "stream": row[5], "stream_sequence": row[6], "project_ref": None if row[7] is None else {"authority": row[7], "kind": "work.project", "id": row[8]}, "subject_ref": {"authority": row[9], "kind": row[10], "id": row[11], "revision": row[12]}, "recorded_at": row[13], "occurred_at": row[14], "facet_type": row[15], "role": row[16], "outcome": row[17], "summary": summary, "detail": detail})
        has_more = len(matching) > limit or len(rows) == metadata_budget
        cursor_row = selected[-1] if len(matching) > limit else (rows[-1] if rows else None)
        next_cursor = self._encode_cursor(expected, [cursor_row[13], cursor_row[4], cursor_row[3], cursor_row[1]]) if cursor_row is not None and has_more else None
        if not discovery_complete:
            next_cursor = _token_encode({"format":CURSOR_FORMAT,"mode":"active-discovery","snapshot":expected["snapshot_digest"],"key":None,"discovery":discovery})
            has_more = True
        elif discovery is not None and not metadata_budget:
            next_cursor = _token_encode({"format":CURSOR_FORMAT,"mode":"facts","snapshot":expected["snapshot_digest"],"key":after,"discovery":discovery})
        elif next_cursor and discovery is not None:
            value = self._decode_cursor(next_cursor); value["discovery"] = discovery; next_cursor = _token_encode(value)
        matched = set(active_set)
        if normalized_active is None:
            matched.update((row[7], row[8]) for row in rows if row[7] is not None)
        return {"schema": SCHEMA, "rows": result_rows, "projects": [{"authority": a, "kind": "work.project", "id": p} for a, p in scope], "matched_projects": [{"authority": a, "kind": "work.project", "id": p} for a, p in sorted(matched)], "snapshot": expected, "snapshot_digest": expected["snapshot_digest"], "next_cursor": next_cursor, "partial": bool(not selected and has_more), "coverage": {"projection_generation": generation, "covered_append_position": boundary, "lag": max(0, int(self.connection.execute("SELECT COALESCE(MAX(append_position),0) FROM events").fetchone()[0]) - boundary), "active_inventory": "bounded-historical-project-batches" if normalized_active is not None else "not-requested", "active_unknown_projects": [{"authority": a, "kind": "work.project", "id": p} for a,p in sorted(unknown_active)], "active_discovery_complete": discovery_complete, "active_candidates_examined": inventory_examined, "active_summary_bytes_hydrated": discovery_bytes}, "io_work": {"metadata_candidates_examined": examined + inventory_examined, "active_candidates_examined": inventory_examined, "candidate_metadata_bytes": candidate_bytes, "rows_returned": len(result_rows), "summary_bytes_hydrated": hydrated + discovery_bytes, "detail_bytes_hydrated": detail_hydrated}}

    def read_state(self, *, projects=None, from_at=None, to_at=None, timezone_name=None,
                   active_during=None, limit=50, cursor=None, snapshot=None,
                   grant=None, actor=None, filters=None):
        """Bounded subject pages with the latest captured state before exclusive to.

        The same authenticated fixed snapshot governs period facts and state.
        This never consults current heads or source events, and a missing field
        in a captured state remains unknown. Subject and fact cursors differ.
        """
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ProjectHistoryError("limit must be between 1 and 200")
        decoded = self._decode_cursor(cursor) if cursor is not None else None
        after = None
        validation_cursor = None
        if decoded is not None:
            if snapshot is None or decoded["snapshot"] != snapshot.get("snapshot_digest"):
                raise CursorError("subject cursor requires its original state snapshot")
            if decoded.get("mode") == "active-discovery":
                validation_cursor = cursor
            elif decoded.get("mode") == "state":
                after = decoded.get("key")
                if not isinstance(after,list) or len(after)!=4 or not all(isinstance(x,str) for x in after):
                    raise CursorError("subject cursor key is malformed")
                if decoded.get("discovery") is not None:
                    validation_cursor = _token_encode({**decoded,"mode":"facts","key":None})
            else:
                raise CursorError("facts cursor cannot page historical state")
        # Reuse the single authorization/range/snapshot boundary. Discovery
        # must finish before either facts or captured state are presented.
        checked = self.read(projects=projects, from_at=from_at, to_at=to_at,
            timezone_name=timezone_name, active_during=active_during, limit=1,
            cursor=validation_cursor,snapshot=snapshot,grant=grant,actor=actor,filters=filters,_state_validation=True)
        fixed = checked["snapshot"]; scope = self._snapshot_projects(fixed)
        if not checked["coverage"]["active_discovery_complete"]:
            return {**checked,"rows":[],"partial":True}
        discovery = None
        if checked["next_cursor"]:
            discovery = self._decode_cursor(checked["next_cursor"]).get("discovery")
        if discovery is None and decoded is not None:
            discovery = decoded.get("discovery")
        # A completed discovery without a facts continuation still needs its
        # exact membership on subsequent subject pages.
        if active_during is not None and discovery is None:
            discovery = {"index":len(scope),"after":None,"known":False,
                "active":[[x["authority"],x["id"]] for x in checked["matched_projects"] if x not in checked["coverage"]["active_unknown_projects"]],
                "unknown":[[x["authority"],x["id"]] for x in checked["coverage"]["active_unknown_projects"]]}
        start, end = fixed["scope"].get("from"), fixed["scope"].get("to")
        subject_limit = min(limit,(MAX_METADATA_CANDIDATES - checked["io_work"]["metadata_candidates_examined"] - 1) // 2)
        if not subject_limit:
            return {**checked,"rows":[],"partial":True,"next_cursor":_token_encode({"format":CURSOR_FORMAT,"mode":"active-discovery","snapshot":fixed["snapshot_digest"],"key":None,"discovery":discovery})}
        candidates = []
        for authority, project in sorted(scope):
            if after is not None and (authority, project) < tuple(after[:2]):continue
            clause = "generation=? AND project_authority=? AND project_id=? AND source_append_position<=?"
            args = [fixed["generation"], authority, project, fixed["boundary"]]
            if end is not None:clause += " AND recorded_at<?";args.append(end)
            if after is not None and (authority, project) == tuple(after[:2]):
                clause += " AND (subject_kind,subject_id)>(?,?)";args.extend(after[2:])
            remaining = subject_limit + 1 - len(candidates)
            keys = self.connection.execute("SELECT DISTINCT subject_kind,subject_id FROM project_history WHERE " + clause +
                " ORDER BY subject_kind,subject_id LIMIT ?", (*args, remaining)).fetchall()
            candidates.extend((authority,project,k[0],k[1]) for k in keys)
            if len(candidates) > subject_limit:break
        chosen = candidates[:subject_limit]; rows = []; hydrated = 0; detail_hydrated = 0
        allowed_active = {(x["authority"],x["id"]) for x in checked["matched_projects"]}
        for authority, project, kind, subject in chosen:
            if active_during is not None and (authority,project) not in allowed_active:continue
            clause = "generation=? AND project_authority=? AND project_id=? AND subject_kind=? AND subject_id=? AND source_append_position<=?"
            args = [fixed["generation"],authority,project,kind,subject,fixed["boundary"]]
            if end is not None:clause += " AND recorded_at<?";args.append(end)
            row = self.connection.execute(
                "SELECT generation,facet_id,source_event_id,facet_index,source_append_position,stream,stream_sequence,project_authority,project_id,subject_authority,subject_kind,subject_id,subject_revision,recorded_at,occurred_at,facet_type,role,outcome,summary_json,detail_json FROM project_history WHERE " + clause +
                " ORDER BY recorded_at DESC,source_append_position DESC,facet_index DESC,facet_id DESC LIMIT 1", args).fetchone()
            if row is None:continue
            summary = json.loads(row[18]);detail = json.loads(row[19]);hydrated += len(row[18].encode());detail_hydrated += len(row[19].encode())
            fields = summary.get("after",{}).get("fields",{})
            lifecycle = fields.get("lifecycle",fields.get("status"))
            if start is not None and row[13] < start and lifecycle in {"completed","closed","resolved","withdrawn","failed","stopped"}:continue
            memberships = [v for v in fields.values() if isinstance(v,Mapping) and v.get("kind")=="work.project"]
            if memberships and not any(v.get("authority")==authority and v.get("id")==project for v in memberships):continue
            if any((filters or {}).get(name) is not None and (filters or {})[name]!=row[index] for name,index in (("role",16),("outcome",17),("facet_type",15))):continue
            rows.append({"generation":row[0],"facet_id":row[1],"source_event_id":row[2],"facet_index":row[3],"source_append_position":row[4],"stream":row[5],"stream_sequence":row[6],"project_ref":{"authority":authority,"kind":"work.project","id":project},"subject_ref":{"authority":row[9],"kind":kind,"id":subject,"revision":row[12]},"recorded_at":row[13],"occurred_at":row[14],"facet_type":row[15],"role":row[16],"outcome":row[17],"summary":summary,"detail":detail,"state_as_of_before":end,"state_coverage":summary.get("coverage","unknown"),"period_overlap":"unknown" if lifecycle is None else "captured"})
        more = len(candidates)>subject_limit
        next_cursor = _token_encode({"format":CURSOR_FORMAT,"mode":"state","snapshot":fixed["snapshot_digest"],"key":list(chosen[-1]),"discovery":discovery}) if more and chosen else None
        return {**checked,"rows":rows,"next_cursor":next_cursor,"partial":bool(not rows and more),"coverage":{**checked["coverage"],"historical_state":"captured-state-before-exclusive-to","subject_continuation":True,"unknown_fields_preserved":True},"io_work":{"metadata_candidates_examined":len(candidates)+len(chosen)+checked["io_work"]["metadata_candidates_examined"],"summary_bytes_hydrated":hydrated+checked["io_work"]["summary_bytes_hydrated"],"detail_bytes_hydrated":detail_hydrated+checked["io_work"]["detail_bytes_hydrated"],"validation_io":checked["io_work"],"rows_returned":len(rows)}}

    page = read
    query = read

    def detail(self, facet_id: str, *, snapshot: Mapping[str, Any], grant: Any = None, actor: Any = None, max_bytes: int = MAX_DETAIL_BYTES) -> dict[str, Any]:
        if not isinstance(facet_id, str) or not facet_id or type(max_bytes) is not int or not 0 <= max_bytes <= MAX_DETAIL_BYTES:
            raise ProjectHistoryError("invalid bounded detail request")
        grant = self._current_grant(grant)
        principal, allowed, revision = _grant_parts(grant, self.store.authority)
        if actor is not None and not _same_actor(actor, principal):
            raise AuthorizationError("authenticated actor does not match the grant")
        snapshot_projects = self._snapshot_projects(snapshot)
        if any(project_id not in allowed for _authority, project_id in snapshot_projects):
            raise AuthorizationError("snapshot project scope is not authorized")
        metadata = dict(self.connection.execute("SELECT key,value FROM store_metadata"))
        expected = {"authority": self.store.authority, "owner_incarnation": self.store.authority, "grant_revision": revision, "generation": int(metadata.get("history_generation", "1")), "boundary": int(metadata.get("history_checkpoint", "0")), "scope": snapshot.get("scope")}
        self._validate_snapshot(snapshot, expected)
        row = self.connection.execute(
            "SELECT project_authority,project_id,recorded_at,facet_type,role,outcome,source_append_position,summary_json,detail_json "
            "FROM project_history WHERE generation=? AND facet_id=?",
            (snapshot["generation"], facet_id),
        ).fetchone()
        if row is None or (row[0], row[1]) not in snapshot_projects:
            raise AuthorizationError("selected history detail is unavailable")
        scope = snapshot.get("scope")
        if not isinstance(scope, Mapping):
            raise SnapshotRefreshRequired("snapshot scope is malformed")
        from_at, to_at = scope.get("from"), scope.get("to")
        if (from_at is None) != (to_at is None) or (to_at is not None and row[2] >= to_at):
            raise AuthorizationError("selected history detail is outside the snapshot range")
        if from_at is not None and row[2] < from_at:
            subject = self.connection.execute("SELECT subject_authority,subject_kind,subject_id FROM project_history WHERE generation=? AND facet_id=?", (snapshot["generation"],facet_id)).fetchone()
            latest = self.connection.execute(
                "SELECT facet_id FROM project_history WHERE generation=? AND project_authority=? AND project_id=? AND subject_authority=? AND subject_kind=? AND subject_id=? AND source_append_position<=? AND recorded_at<? ORDER BY recorded_at DESC,source_append_position DESC,facet_index DESC,facet_id DESC LIMIT 1",
                (snapshot["generation"],row[0],row[1],*subject,snapshot["boundary"],to_at)).fetchone()
            fields = json.loads(row[7]).get("after",{}).get("fields",{})
            lifecycle = fields.get("lifecycle",fields.get("status"))
            memberships = [x for x in fields.values() if isinstance(x,Mapping) and x.get("kind")=="work.project"]
            if (latest is None or latest[0] != facet_id
                    or lifecycle in {"completed","closed","resolved","withdrawn","failed","stopped"}
                    or (memberships and not any(x.get("authority")==row[0] and x.get("id")==row[1] for x in memberships))):
                raise AuthorizationError("selected history detail is not a captured carry-in state")
        filters = scope.get("filters", {})
        if not isinstance(filters, Mapping) or set(filters) - {"role", "outcome", "facet_type"}:
            raise SnapshotRefreshRequired("snapshot filters are malformed")
        if any(filters.get(name) is not None and filters.get(name) != row[index]
               for name, index in (("facet_type", 3), ("role", 4), ("outcome", 5))):
            raise AuthorizationError("selected history detail is outside the snapshot filters")
        active = scope.get("active_during")
        if active is not None:
            if not isinstance(active, (tuple, list)) or len(active) != 2:
                raise SnapshotRefreshRequired("snapshot active_during range is malformed")
            active_projects = self._historical_active(
                ((row[0], row[1]),), active[0], active[1],
                generation=int(snapshot["generation"]), boundary=int(snapshot["boundary"]),
            )
            if (row[0], row[1]) not in active_projects:
                raise AuthorizationError("selected history detail is outside the active snapshot scope")
        if row[6] > int(snapshot["boundary"]):
            raise AuthorizationError("selected history detail is outside the snapshot boundary")
        locator = json.loads(row[8])
        raw = row[8].encode("utf-8")
        evidence = None
        refs = locator.get("evidence_refs", ()) if isinstance(locator, Mapping) else ()
        if self.evidence_reader and refs:
            selected = next((ref for ref in refs if isinstance(ref, Mapping) and ref.get("kind") == "dat.content.revision"), None)
            if selected is not None:
                ref = ResourceRef.from_dict(selected)
                try:
                    evidence = self.evidence_reader.read_evidence(ref, actor=principal, offset=0, max_bytes=max_bytes)
                except TypeError:
                    evidence = self.evidence_reader.read_evidence(ref, offset=0, max_bytes=max_bytes)
        return {"schema": SCHEMA, "facet_id": facet_id, "project_ref": {"authority": row[0], "kind": "work.project", "id": row[1]}, "summary": json.loads(row[7]), "detail_locator": locator, "evidence": evidence, "bytes": raw[:max_bytes], "truncated": len(raw) > max_bytes, "io_work": {"detail_bytes_read": min(len(raw), max_bytes), "evidence_bytes_read": 0 if evidence is None else len(evidence.get("bytes", b""))}}


ProjectHistoryMaintainer = ProjectHistoryProjection
BoundedProjectHistoryReader = ProjectHistoryReader
AuthenticatedProjectHistoryReader = ProjectHistoryReader

__all__ = ["AuthenticatedProjectHistoryReader", "AuthorizationError", "BoundedProjectHistoryReader", "CURSOR_FORMAT", "CursorError", "ProjectHistoryError", "ProjectHistoryGrant", "ProjectHistoryMaintainer", "ProjectHistoryProjection", "ProjectHistoryReader", "ProjectionMaintenanceError", "SCHEMA", "SnapshotRefreshRequired"]
