"""Sealed result store: one HMAC-sealed JSON record per run, written atomically, never overwritten once terminal."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from typing import Any, Iterable, Mapping

RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_TERMINAL = ("settled", "unknown")
_STATES = frozenset(("queued", "running", "settled", "unknown"))


class StoreError(RuntimeError):
    """A record cannot be written, or a stored record cannot be trusted."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ResultStore:
    """The runner's evidence: records under ``runs/``, output under ``output/``, sealed with ``seal.key``.

    A record is trusted only when its seal verifies, its run_id matches its file, and its binding
    matches its argv, cwd and commit. Anything else is invalid and is never overwritten.
    """

    def __init__(self, root: Any, *, forbidden_roots: Iterable[Any] = ()) -> None:
        self._root = os.fspath(root)
        self._forbidden = tuple(os.fspath(path) for path in forbidden_roots)
        self._check_forbidden()
        os.makedirs(self._root, mode=0o700, exist_ok=True)
        os.chmod(self._root, 0o700)
        for sub in ("runs", "output"):
            os.makedirs(os.path.join(self._root, sub), mode=0o700, exist_ok=True)
        self._key = self._load_key()

    def _check_forbidden(self) -> None:
        real = os.path.realpath(self._root)
        for forbidden in self._forbidden:
            limit = os.path.realpath(forbidden)
            if real == limit or os.path.commonpath([real, limit]) == limit:
                raise StoreError("store root is inside a forbidden root")

    def _load_key(self) -> bytes:
        path = os.path.join(self._root, "seal.key")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            with open(path, "rb") as handle:
                key = handle.read()
            if len(key) != 32:
                raise StoreError("seal key is not 32 bytes")
            return key
        key = secrets.token_bytes(32)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
        return key

    def _path(self, run_id: Any) -> str:
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise StoreError("run_id is not a valid run identifier")
        return os.path.join(self._root, "runs", run_id + ".json")

    def _seal(self, body: Mapping[str, Any]) -> str:
        return hmac.new(self._key, _canonical(dict(body)), hashlib.sha256).hexdigest()

    @staticmethod
    def binding(argv: Any, cwd: Any, commit: Any) -> str:
        """The identity of one command: its argv, its directory and the commit it runs at."""
        return hashlib.sha256(_canonical({"argv": list(argv), "cwd": cwd, "commit": commit})).hexdigest()

    def _check(self, run_id: str, record: Any) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise StoreError("record %s is not an object" % run_id)
        body = {key: value for key, value in record.items() if key != "seal"}
        seal = record.get("seal")
        if not isinstance(seal, str) or not hmac.compare_digest(seal.encode(), self._seal(body).encode()):
            raise StoreError("record %s fails its seal" % run_id)
        if record.get("run_id") != run_id:
            raise StoreError("record %s names another run" % run_id)
        try:
            expected = self.binding(record["argv"], record["cwd"], record["commit"])
        except (KeyError, TypeError) as exc:
            raise StoreError("record %s lacks its command identity" % run_id) from exc
        if record.get("binding") != expected:
            raise StoreError("record %s binding does not match its command" % run_id)
        return record

    def _read(self, path: str, run_id: str) -> dict[str, Any]:
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise StoreError("record %s is unreadable" % run_id) from exc
        try:
            record = json.loads(raw)
        except ValueError as exc:
            raise StoreError("record %s is not valid JSON" % run_id) from exc
        return self._check(run_id, record)

    def get(self, run_id: str) -> dict[str, Any] | None:
        """The verified record, or None when the run has no record."""
        path = self._path(run_id)
        try:
            return self._read(path, run_id)
        except FileNotFoundError:
            return None

    def all_records(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Verified records in seq order, and the run_ids that failed verification."""
        runs = os.path.join(self._root, "runs")
        good: list[dict[str, Any]] = []
        bad: list[str] = []
        for name in sorted(os.listdir(runs)):
            if not name.endswith(".json"):
                continue
            run_id = name[:-len(".json")]
            try:
                good.append(self._read(os.path.join(runs, name), run_id))
            except FileNotFoundError:
                continue
            except StoreError:
                bad.append(run_id)
        good.sort(key=lambda record: record["seq"])
        return good, bad

    def next_seq(self) -> int:
        records, _ = self.all_records()
        return 1 + max((record["seq"] for record in records), default=0)

    def output_path(self, run_id: str) -> Path:
        self._path(run_id)
        return Path(self._root, "output", run_id + ".log")

    def put(self, record: dict[str, Any]) -> None:
        """Write a record atomically and set its seal. Refuses invalid, terminal or non-monotonic writes."""
        if not isinstance(record, dict):
            raise StoreError("record must be an object")
        self._check_forbidden()
        path = self._path(record.get("run_id"))
        run_id = record["run_id"]
        try:
            expected = self.binding(record["argv"], record["cwd"], record["commit"])
        except (KeyError, TypeError) as exc:
            raise StoreError("record lacks its command identity") from exc
        if record.get("binding") != expected:
            raise StoreError("record binding does not match its command")
        try:
            previous = self._read(path, run_id)
        except FileNotFoundError:
            previous = None
        except StoreError as exc:
            raise StoreError("refusing to overwrite a record that cannot be verified: %s" % exc) from exc
        old = None
        if previous is not None:
            old = previous["state"]
            if old in _TERMINAL:
                raise StoreError("record %s is already %s and is never overwritten" % (run_id, old))
            if previous["binding"] != record["binding"]:
                raise StoreError("record %s cannot change its binding" % run_id)
        if record.get("state") not in _STATES:
            raise StoreError("record %s has an invalid state" % run_id)
        if old == "running" and record.get("state") == "queued":
            raise StoreError("record %s may not return to queued" % run_id)
        body = {key: value for key, value in record.items() if key != "seal"}
        try:
            data = json.dumps(dict(body, seal=self._seal(body)), sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise StoreError("record %s is not serialisable" % run_id) from exc
        self._atomic_write(path, data)
        record["seal"] = self._seal(body)

    def _atomic_write(self, path: str, data: bytes) -> None:
        directory = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".write-", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
