"""Resource-aware bridge to Herzchen's concrete Codex host adapter."""

from __future__ import annotations

import json
import shlex
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from otto.portfolio.resource_sync import ResourceSyncError, normalize_instruction_contract
import time


class HerzchenAdapterError(ValueError):
    """The owner request cannot be converted into a typed host request."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HerzchenAdapterError(f"{field} must be non-blank text")
    return value.strip()


def _json(value: Any) -> Any:
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) != 64:
        raise HerzchenAdapterError(f"{field} must be a SHA-256 hex digest")
    digest = value.strip().lower()
    if any(char not in "0123456789abcdef" for char in digest):
        raise HerzchenAdapterError(f"{field} must be a SHA-256 hex digest")
    return digest


def _without_digest(value: Mapping[str, Any], *fields: str) -> dict[str, Any]:
    result = dict(_json(value))
    for field in fields:
        result.pop(field, None)
    return result


def _context_digest(*, session_id: str, turn_id: str, provenance: str,
                    model: str, reasoning: str, worker_content: list[Any],
                    task_bound_evidence: Mapping[str, Any], effective_profile: str | None = None) -> str:
    evidence = _without_digest(task_bound_evidence, "context_digest", "evidence_digest")
    body = {
        "session_id": session_id,
        "turn_id": turn_id,
        "provenance": provenance,
        "model": model,
        "reasoning": reasoning,
        "worker_content": worker_content,
        "task_bound_evidence": evidence,
    }
    if effective_profile is not None:
        body["effective_profile"] = effective_profile
    return _digest(body)


class JsonlHostTurnContextReader:
    """Read one host-owned context record from the native JSONL capture.

    The reader is deliberately concrete and fail-closed: a successful process
    line or a nonblank marker is not context evidence.  The host must emit one
    ``otto_host_turn_context`` record carrying the exact session/turn, model,
    read result, and digested task-bound evidence.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def __call__(self, session_id: str, turn_id: str) -> Mapping[str, Any]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise HerzchenAdapterError("native host context capture is unreadable") from exc
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, Mapping):
                continue
            value = record.get("otto_host_turn_context")
            if not isinstance(value, Mapping) and record.get("type") == "otto_host_turn_context":
                value = record
            if not isinstance(value, Mapping):
                continue
            if value.get("session_id") == session_id and value.get("turn_id") == turn_id:
                return dict(value)
        raise HerzchenAdapterError("native host capture has no exact otto_host_turn_context record")


class HerzchenCodexAdapter:
    """Create a fresh Codex binding for each verified owner operation.

    The bridge keeps the neutral Otto gateway contract on the outside and the
    typed Herzchen ``HostRequest`` contract on the inside.  A fresh binding is
    intentional: the verified brief must never be left in shared mutable
    adapter state across operations.
    """

    owner_bound = True

    def __init__(
        self,
        *,
        owner: str,
        source: str,
        worktree: str,
        launcher: str,
        requested_model: str = "gpt-5.6-luna",
        requested_reasoning: str = "high",
        binding_factory: Optional[Callable[..., Any]] = None,
        host_adapter_factory: Optional[Callable[..., Any]] = None,
        turn_context_reader: Optional[Callable[[str, str], Mapping[str, Any] | None]] = None,
        host_context_path: Optional[str] = None,
        native_trace_path: Optional[str] = None,
        trusted_thread_reader: Optional[Callable[[str], Mapping[str, Any]]] = None,
        require_host_context: bool = False,
        owner_authorizer: Optional[Callable[[str, str], Mapping[str, Any]]] = None,
        owner_delivery_verifier: Optional[Callable[..., Mapping[str, Any]]] = None,
        source_verifier_factory: Optional[Callable[..., Any]] = None,
        writable_roots: Sequence[str] = (),
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.owner = _text(owner, "owner")
        self.source = _text(source, "source")
        self.worktree = _text(worktree, "worktree")
        self.writable_roots = tuple(_text(value, "writable_roots") for value in writable_roots)
        self.launcher = _text(launcher, "launcher")
        self.requested_model = _text(requested_model, "requested_model")
        self.requested_reasoning = _text(requested_reasoning, "requested_reasoning")
        self.binding_factory = binding_factory
        self.host_adapter_factory = host_adapter_factory
        self.turn_context_reader = turn_context_reader
        self.host_context_path = host_context_path
        self.native_trace_path = native_trace_path
        self.trusted_thread_reader = trusted_thread_reader
        self.require_host_context = bool(require_host_context)
        self._owner_authorizer = owner_authorizer
        self._owner_delivery_verifier = owner_delivery_verifier
        self.source_verifier_factory, self.monotonic_clock = source_verifier_factory, monotonic_clock
        self._source_verifier = None
        self._thread_started_callback: Optional[Callable[[str], None]] = None

    def bind_owner_authorization(self, authorizer: Callable[[str, str], Mapping[str, Any]],
                                 *, verifier: Optional[Callable[..., Mapping[str, Any]]] = None) -> "HerzchenCodexAdapter":
        """Return a fresh adapter for one owner-admitted two-turn delivery."""
        if not callable(authorizer):
            raise HerzchenAdapterError("trusted owner authorizer is required")
        return type(self)(
            owner=self.owner, source=self.source, worktree=self.worktree, launcher=self.launcher,
            requested_model=self.requested_model, requested_reasoning=self.requested_reasoning,
            binding_factory=self.binding_factory, host_adapter_factory=self.host_adapter_factory,
            turn_context_reader=self.turn_context_reader, host_context_path=self.host_context_path,
            native_trace_path=self.native_trace_path, require_host_context=self.require_host_context,
            owner_authorizer=authorizer, owner_delivery_verifier=verifier,
            trusted_thread_reader=self.trusted_thread_reader,
            source_verifier_factory=self.source_verifier_factory, monotonic_clock=self.monotonic_clock,
            writable_roots=self.writable_roots,
        )

    def set_thread_started_callback(self, callback: Optional[Callable[[str], None]]) -> Optional[Callable[[str], None]]:
        prior = self._thread_started_callback
        if callback is not None and not callable(callback):
            raise HerzchenAdapterError("thread-started callback must be callable")
        self._thread_started_callback = callback
        return prior

    @staticmethod
    def _uses_task_projection(brief: Mapping[str, Any]) -> bool:
        task = brief.get("instruction_contract", {}).get("task_ref", {})
        generation = brief.get("context", {}).get("canonical_snapshot", {}).get("generation")
        return (task.get("authority") == "o01-worker-readiness-operational-pending-d7"
                and task.get("id") == "task-02ce5a517090e99c5335f62a3e75"
                and type(generation) is int and generation >= 9)

    @staticmethod
    def build_task_projection(brief: Mapping[str, Any], digest: str,
                              *, recipient: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        """D241's finite T01 view, regenerated only from the supplied owner brief."""
        def need(ok: bool, reason: str) -> None:
            if not ok:
                raise HerzchenAdapterError("T01 projection: " + reason)

        need(_digest(brief) == digest, "canonical digest mismatch")
        try:
            contract = brief["instruction_contract"]
            core = brief["operating_core"]
            state = brief["context"]["project_state"]
            snapshot = brief["context"]["canonical_snapshot"]
            resource = brief["resource_resolution"]
            targets, constraints, links = contract["read_targets"], core["operational_constraints"], core["links"]
            need(len(targets) == len(set(targets)) == 130 and all(Path(p).is_absolute() for p in targets), "read inventory changed")
            need(len(constraints) == 16, "operational constraints changed")
            need(len(constraints[6].splitlines()[1:]) == 14 and len(constraints[7].splitlines()[1:]) == 1,
                 "Git/rg inventory changed")
            cats = "ALLOWED CAT COMMANDS (inner commands only, exact order):\n" + "\n".join("cat -- " + p for p in targets)
            claims = "C01 CLAIM MAP: " + json.dumps(contract["claim_evidence_map"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            need(constraints[12] == cats and constraints[15] == claims, "derived constraints do not reconstruct exactly")
            need(contract == brief["instruction_contract_source"]["instruction_contract"]
                 == brief["context"]["mandate_instruction_contract"]["instruction_contract"], "contract copies differ")
            need(snapshot["task_ref"] == contract["task_ref"] == state["task"]["ref"]
                 and snapshot["assignment_ref"] == resource["responsibility_ref"]
                 and snapshot["generation"] == resource["generation"]
                 and state["assignment"] == snapshot, "current owner identities differ")
            need(hashlib.sha256(core["operating_contract"].encode()).hexdigest()
                 == "4957ee771649d7fd25a345a0e23095beb00b1279e2ab94a80fd898c9ddc0061b", "adopted skill applicability changed")
            run_roots = {m.group(1) for link in links if isinstance(link.get("path"), str)
                         for m in [re.match(r"^(.*?/.otto/runs/[^/]+/)", link["path"])] if m}
            need(len(run_roots) == 1, "run path root is ambiguous")
            roots = {"RUN": next(iter(run_roots)), "CUSTODY": os.path.commonpath(targets).rstrip("/") + "/"}

            def mapped(value: Any, inverse: bool = False) -> Any:
                if isinstance(value, str):
                    for key, prefix in roots.items():
                        old, new = ("@" + key + "/", prefix) if inverse else (prefix, "@" + key + "/")
                        if value.startswith(old):
                            return new + value[len(old):]
                    return value
                if isinstance(value, list):
                    return [mapped(v, inverse) for v in value]
                if isinstance(value, Mapping):
                    return {k: mapped(v, inverse) for k, v in value.items()}
                return value

            packed_contract = mapped(contract)
            packed_links = [{**link, **({"path": mapped(link["path"])} if isinstance(link.get("path"), str) else {})} for link in links]
            need(mapped(packed_contract, True) == contract and mapped(packed_links, True) == links, "path aliases are not invertible")
            packed_constraints = list(constraints)
            packed_constraints[12] = {"derive": "cat_commands_from_ordered_read_targets"}
            packed_constraints[15] = {"derive": "claim_map_from_instruction_contract"}
            owner = {"authority": brief["authority"], "canonical_snapshot": snapshot,
                     "project_ref": state["project"]["ref"], "project_lifecycle": state["project"]["lifecycle"],
                     "task": state["task"], "assignment": state["assignment"], "mandate_ref": snapshot["mandate_ref"],
                     "resource_adoption": brief["resource_adoption"],
                     "resource_resolution_identity": {k: v for k, v in resource.items() if k != "resources"}}
            if recipient is not None:
                need(set(recipient) == {"principal", "model", "reasoning", "profile", "approval_policy", "worker_effects"}
                     and recipient["principal"] == snapshot["principal"] and recipient["profile"] == "read-only"
                     and recipient["approval_policy"] == "never"
                     and recipient["worker_effects"] == contract["authority"]["permitted_effects"]
                     and all(isinstance(recipient[k], str) and recipient[k].strip() for k in ("model", "reasoning")),
                     "recipient binding is not verified")
                owner["recipient_permission_contract"] = dict(recipient)
            projection = {"schema": "otto.o12.d241-t01-task-projection.v1", "canonical_owner_brief_sha256": digest,
                "instruction_contract": packed_contract, "owner_context": owner,
                "operating_core_task_view": {**{k: core[k] for k in ("role", "mandate", "priorities", "user_constraints", "continuation")},
                    "operational_constraints_in_order": packed_constraints, "links_with_path_aliases": packed_links, "link_path_roots": roots},
                "source_record_hashes": {"project_payload_sha256": _digest(state["project"]["payload"]),
                    "full_adopted_operating_contract_sha256": hashlib.sha256(core["operating_contract"].encode()).hexdigest(),
                    "resource_resolution_sha256": _digest(resource), "instruction_content_sha256": _digest(brief["instruction_content"]),
                    "all_links_sha256": _digest(links), "all_operational_constraints_sha256": _digest(constraints)},
                "model_instructions": "Expand @RUN/ and @CUSTODY/ using link_path_roots. Read each ordered absolute target as one separate cat -- <path> call with max_output_tokens=30000. Reconstruct the two derived constraints from ordered read_targets and claim_evidence_map. Then run all listed Git commands separately and the fixed rg once. All acceptance, prohibitions and owner constraints remain binding. Context compaction alone does not prove source-output truncation; apply the exact tool-response completeness rules. Completion is not owner acceptance.",
                "generation_clarification": "The active generation is owner_context.canonical_snapshot.generation. Older generation wording inside the immutable bounded_operation is historical source text; do not change that contract."}
            return _json(projection)
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            if isinstance(exc, HerzchenAdapterError):
                raise
            raise HerzchenAdapterError("T01 projection: malformed canonical input") from exc

    def _request_projection(self, brief: Mapping[str, Any], digest: str, request: Mapping[str, Any]) -> Any:
        if not self._uses_task_projection(brief):
            return None
        return self.build_task_projection(brief, digest, recipient={
            "principal": request.get("logical_agent_id"),
            "model": request.get("requested_model", self.requested_model),
            "reasoning": request.get("requested_reasoning", self.requested_reasoning),
            "profile": request.get("requested_profile", "read-only"), "approval_policy": "never",
            "worker_effects": brief["instruction_contract"]["authority"]["permitted_effects"]})

    @staticmethod
    def render_verified_brief(brief: Mapping[str, Any], digest: str, *, model_projection: Any = None) -> str:
        """Render the immutable brief as the model-visible instruction block."""

        if not isinstance(brief, Mapping) or not brief:
            raise HerzchenAdapterError("resource_brief must be a non-empty object")
        digest = _text(digest, "resource_brief_sha256")
        if model_projection is None and HerzchenCodexAdapter._uses_task_projection(brief):
            model_projection = HerzchenCodexAdapter.build_task_projection(brief, digest)
        if model_projection is not None:
            expected = HerzchenCodexAdapter.build_task_projection(brief, digest,
                recipient=model_projection.get("owner_context", {}).get("recipient_permission_contract"))
            if model_projection != expected:
                raise HerzchenAdapterError("T01 projection differs from verified canonical input")
            encoded = json.dumps(model_projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            return ("Verified T01 task projection.\n"
                    f'<otto-task-projection canonical-brief-sha256="{digest}" projection-sha256="{_digest(model_projection)}">\n'
                    + encoded + "\n</otto-task-projection>\n")
        encoded = json.dumps(_json(dict(brief)), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        guidance = ""
        contract = brief.get("instruction_contract")
        if isinstance(contract, Mapping) and contract.get("source_inspection") is not None:
            targets = contract.get("read_targets")
            if (not isinstance(targets, list) or not targets or
                    any(not isinstance(path, str) or not Path(path).is_absolute()
                        or "\x00" in path or "\n" in path or "\r" in path
                        for path in targets)):
                raise HerzchenAdapterError("bounded brief has no exact absolute read targets")
            reads = "\n".join("cat -- " + shlex.quote(path) for path in targets)
            guidance = (
                "Read each required target with one separate command exactly as listed below. "
                "A multi-file cat does not satisfy this contract. Do not combine commands "
                "with &&, pipes, semicolons, loops, helpers or output truncation. "
                "The owner checks each command, complete output and source state.\n"
                + reads + "\n"
                "For a Git root already admitted by the owner, the only permitted forms are "
                "git --no-optional-locks -c core.fsmonitor=false -C <admitted-root> rev-parse HEAD "
                "and git --no-optional-locks -c core.fsmonitor=false -C <admitted-root> "
                "status --porcelain=v1 --untracked-files=all. Run each separately. "
                "For search, use rg --no-config --color=never --no-heading --with-filename "
                "-n -F --sort path -e <literal> [up to eight -e literals] -- <admitted-in-root-paths>. "
                "Always include --sort path for deterministic output order across native and owner queries. "
                "Use bounded explicit files. Search does not replace any required cat read.\n"
            )
        return (
            "Verified owner context. The bounded contract below is input only; "
            "the canonical gateway claim is the sole execution authority. Do not "
            "infer dispatch or owner-write authority from this brief.\n"
            f"<otto-resource-brief sha256=\"{digest}\">\n{encoded}\n"
            "</otto-resource-brief>\n" + guidance
        )

    @staticmethod
    def build_cursor_queue(brief: Mapping[str, Any], projection: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Derive D256's pinned sequence from the current full canonical input."""
        digest = _digest(brief)
        expected = HerzchenCodexAdapter.build_task_projection(brief, digest,
            recipient=projection.get("owner_context", {}).get("recipient_permission_contract"))
        if expected != projection:
            raise HerzchenAdapterError("cursor projection differs from canonical brief")
        contract = brief["instruction_contract"]
        constraints = brief["operating_core"]["operational_constraints"]
        cats = ["cat -- " + shlex.quote(path) for path in contract["read_targets"]]
        git, rg = constraints[6].splitlines()[1:], constraints[7].splitlines()[1:]
        queue = [{"ordinal": i + 1, "kind": "cat" if i < 130 else "git" if i < 144 else "rg", "cmd": cmd}
                 for i, cmd in enumerate(cats + git + rg)]
        if (len(cats) != 130 or len(git) != 14 or len(rg) != 1
                or contract["source_inspection"]["manifest_sha256"] != "9d72c9b3efa302900a37cd279829285b823f70e57bc7e15d744570d05c7f45fe"
                or _digest(queue) != "ca4efcc3123056554d475a70b481c2992715bba47394c5b5b76816dfafa42d10"):
            raise HerzchenAdapterError("cursor command inventory or source manifest changed")
        return queue

    def _new_host(self, prompt: str, brief: Mapping[str, Any], *, model: str, reasoning: str,
                  model_projection: Any = None,
                  recipient_authorizer: Optional[Callable[..., Mapping[str, Any]]] = None,
                  timeout_seconds: Optional[float] = None, occurrence_deadline: Optional[float] = None,
                  source_verifier: Any = None, timeout_brief: Any = None) -> Any:
        cursor_queue = None
        if model_projection is not None and brief["context"]["canonical_snapshot"]["generation"] >= 11:
            recipient = model_projection["owner_context"].get("recipient_permission_contract", {})
            if (model != "gpt-6-luna" or reasoning != "xhigh" or recipient.get("model") != model
                    or recipient.get("reasoning") != reasoning or recipient.get("profile") != "read-only"
                    or recipient.get("approval_policy") != "never"):
                raise HerzchenAdapterError("cursor requires exact current Luna/xhigh read-only/never recipient")
            cursor_queue = self.build_cursor_queue(brief, model_projection)
        bounded = {} if timeout_seconds is None else {
            "timeout_seconds": timeout_seconds, "occurrence_deadline": occurrence_deadline,
            "source_verifier": source_verifier, "monotonic_clock": self.monotonic_clock,
            **({"timeout_brief": timeout_brief} if timeout_brief is not None else {})}
        if self.binding_factory is None:
            try:
                from herzchen.adapters import CodexCliBinding
            except Exception as exc:  # pragma: no cover - exercised by deployments without Herzchen
                raise HerzchenAdapterError("Herzchen Codex binding is unavailable") from exc
            binding = CodexCliBinding(
                self.worktree,
                launcher=self.launcher,
                model=model,
                reasoning=reasoning,
                prompt=prompt,
                evidence_path=self.host_context_path,
                native_trace_path=self.native_trace_path,
                trusted_thread_reader=self.trusted_thread_reader,
                recipient_authorizer=recipient_authorizer,
                writable_roots=self.writable_roots,
                delivered_brief=brief, model_projection=model_projection, cursor_queue=cursor_queue, **bounded,
            )
        else:
            receiving = {} if recipient_authorizer is None and not bounded else {
                "recipient_authorizer": recipient_authorizer, "delivered_brief": brief,
                "trusted_thread_reader": self.trusted_thread_reader,
            }
            binding = self.binding_factory(
                worktree=self.worktree, launcher=self.launcher, model=model, reasoning=reasoning,
                prompt=prompt, host_context_path=self.host_context_path,
                **({"model_projection": model_projection} if model_projection is not None else {}),
                **({"cursor_queue": cursor_queue} if cursor_queue is not None else {}), **receiving, **bounded,
            )
        if self.host_adapter_factory is None:
            try:
                from herzchen.adapters import HerzchenHostAdapter
            except Exception as exc:  # pragma: no cover - exercised by deployments without Herzchen
                raise HerzchenAdapterError("Herzchen host adapter is unavailable") from exc
            return HerzchenHostAdapter(
                binding,
                owner=self.owner,
                source=self.source,
                worktree=self.worktree,
                launcher=self.launcher,
                requested_model=model,
                requested_reasoning=reasoning,
            )
        return self.host_adapter_factory(
            binding=binding,
            owner=self.owner,
            source=self.source,
            worktree=self.worktree,
            launcher=self.launcher,
            requested_model=model,
            requested_reasoning=reasoning,
            host_context_path=self.host_context_path,
        )

    def _typed_request(self, operation: str, request: Mapping[str, Any]) -> tuple[Any, str, Mapping[str, Any]]:
        if not isinstance(request, Mapping):
            raise HerzchenAdapterError("host request must be an object")
        from herzchen.contracts import HostIdentity, HostOperation, HostRequest, ResourceRef

        brief = request.get("resource_brief")
        digest = _text(request.get("resource_brief_sha256"), "resource_brief_sha256")
        if not isinstance(brief, Mapping):
            raise HerzchenAdapterError("resource-aware host request has no verified brief")
        if _digest(dict(brief)) != digest:
            raise HerzchenAdapterError("resource brief digest is inconsistent")
        try:
            contract = normalize_instruction_contract(brief.get("instruction_contract"))
        except ResourceSyncError as exc:
            raise HerzchenAdapterError(f"resource brief has no substantive instruction contract: {exc}") from exc
        logical_agent_id = _text(request.get("logical_agent_id"), "logical_agent_id")
        target = request.get("target_ref")
        if not isinstance(target, Mapping):
            raise HerzchenAdapterError("target_ref is required")
        try:
            target_ref = ResourceRef.from_dict(dict(target))
            host_operation = HostOperation(operation)
        except Exception as exc:
            raise HerzchenAdapterError("typed Herzchen host request is malformed") from exc
        if contract["task_ref"] != dict(target):
            raise HerzchenAdapterError("instruction contract task does not match target_ref")
        requested_profile = request.get("requested_profile", "read-only")
        expected_read_targets = contract.get("read_targets")
        if self.require_host_context and requested_profile == "read-only" and (
            not isinstance(expected_read_targets, list)
            or not expected_read_targets
            or any(not isinstance(item, (str, Mapping)) or (isinstance(item, str) and not item.strip()) for item in expected_read_targets)
        ):
            raise HerzchenAdapterError("host-context resource contract must declare exact read targets")
        identity = HostIdentity(logical_agent_id, request.get("physical_session_id"))
        typed = HostRequest(host_operation, identity, target_ref, requested_profile)
        return typed, digest, brief

    @staticmethod
    def _observed_context(
        value: Mapping[str, Any] | None,
        *,
        expected_session_id: str,
        expected_turn_id: str,
        expected_read_targets: list[Any] | None = None,
        expected_profile: str = "read-only",
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise HerzchenAdapterError("host-owned turn context is not an object")
        turn = value.get("turn_context") if isinstance(value.get("turn_context"), Mapping) else value
        collaboration = turn.get("collaboration_mode") if isinstance(turn.get("collaboration_mode"), Mapping) else {}
        settings = collaboration.get("settings") if isinstance(collaboration.get("settings"), Mapping) else {}
        session_id = value.get("session_id") or value.get("physical_session_id") or turn.get("session_id") or turn.get("physical_session_id")
        turn_id = value.get("turn_id") or turn.get("turn_id")
        provenance = value.get("provenance") or value.get("context_provenance") or turn.get("provenance")
        context_digest = value.get("context_digest") or turn.get("context_digest")
        if session_id != expected_session_id:
            raise HerzchenAdapterError("host-owned turn context session does not match the observed host session")
        if turn_id != expected_turn_id:
            raise HerzchenAdapterError("host-owned turn context turn does not match the observed host turn")
        if provenance != "host_owned_turn_context":
            raise HerzchenAdapterError("host-owned turn context provenance is not exact")
        if not isinstance(context_digest, str) or not context_digest.strip():
            raise HerzchenAdapterError("host-owned turn context digest is required")
        model = turn.get("model") or turn.get("model_name")
        reasoning = turn.get("reasoning_effort") or turn.get("reasoning") or turn.get("effort") or settings.get("reasoning_effort")
        worker_content = value.get("worker_content", turn.get("worker_content", []))
        if isinstance(worker_content, (str, bytes)):
            worker_content = [worker_content]
        if not isinstance(worker_content, list):
            worker_content = []
        effective_profile = value.get("effective_profile")
        if effective_profile is not None and (not isinstance(effective_profile, str) or not effective_profile.strip() or effective_profile != effective_profile.strip() or "\x00" in effective_profile):
            raise HerzchenAdapterError("host effective_profile is malformed")
        task_evidence = value.get("task_bound_evidence") or turn.get("task_bound_evidence")
        if not isinstance(task_evidence, Mapping):
            raise HerzchenAdapterError("host-owned turn context lacks positive task-bound operation evidence")
        task_evidence = _json(task_evidence)
        if task_evidence.get("session_id") != expected_session_id:
            raise HerzchenAdapterError("task-bound evidence session does not match the observed host session")
        if task_evidence.get("turn_id") != expected_turn_id:
            raise HerzchenAdapterError("task-bound evidence turn does not match the observed host turn")
        if task_evidence.get("provenance") != "host_command_execution/item_completed":
            raise HerzchenAdapterError("task-bound evidence provenance is not exact")
        context_digest = _sha256_text(context_digest, "context_digest")
        if task_evidence.get("context_digest") != context_digest:
            raise HerzchenAdapterError("task-bound evidence context digest does not match host context")
        evidence_digest = _sha256_text(task_evidence.get("evidence_digest"), "task_bound_evidence.evidence_digest")
        if evidence_digest != _digest(_without_digest(task_evidence, "evidence_digest")):
            raise HerzchenAdapterError("task-bound evidence digest does not match attested bytes")
        assignment_ref = task_evidence.get("assignment_ref")
        if not isinstance(assignment_ref, Mapping) or not assignment_ref:
            raise HerzchenAdapterError("task-bound evidence assignment binding is required")
        generation = task_evidence.get("generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise HerzchenAdapterError("task-bound evidence generation binding is required")
        delivered_contract_digest = _sha256_text(task_evidence.get("delivered_contract_digest"), "delivered_contract_digest")
        result_ref = task_evidence.get("result_ref")
        if not isinstance(result_ref, (str, Mapping)) or not result_ref:
            raise HerzchenAdapterError("task-bound evidence result reference is required")
        result_digest = _sha256_text(task_evidence.get("result_digest"), "result_digest")
        read_targets = task_evidence.get("read_targets")
        if (
            not isinstance(read_targets, list)
            or (expected_profile == "read-only" and not read_targets)
            or any(not isinstance(item, (str, Mapping)) or (isinstance(item, str) and not item.strip()) for item in read_targets)
        ):
            raise HerzchenAdapterError("task-bound evidence exact read targets are required")
        if (expected_profile == "read-only" and expected_read_targets is not None
                and read_targets != [_json(item) for item in expected_read_targets]):
            raise HerzchenAdapterError("observed read targets do not match the exact bounded contract")
        if expected_read_targets is not None:
            # Validate real referenced native records; no named wrapper field is
            # itself an authority primitive. Do not synthesize host_event_ref.
            records = task_evidence.get("host_records", {}).get("commands", [])
            host_event_ref = value.get("host_event_ref")
            if host_event_ref is None and isinstance(records, list) and records:
                host_event_ref = records[-1]
            if (
                not isinstance(host_event_ref, Mapping)
                or host_event_ref not in records
                or host_event_ref.get("session_id") != expected_session_id
                or host_event_ref.get("turn_id") != expected_turn_id
                or host_event_ref.get("event_type") != "item_completed"
                or not isinstance(host_event_ref.get("item_id"), str)
                or host_event_ref.get("item_type") != "CommandExecution"
                or not _sha256_text(host_event_ref.get("raw_line_sha256"), "host_event_ref.raw_line_sha256")
            ):
                raise HerzchenAdapterError("host-owned context lacks the exact native item_completed CommandExecution reference")
        operation_result = task_evidence.get("operation_result")
        if (
            not isinstance(operation_result, Mapping)
            or operation_result.get("status") != "completed"
            or operation_result.get("result_ref") != result_ref
            or operation_result.get("result_digest") != result_digest
            or "output" not in operation_result
            or result_digest != _digest(operation_result.get("output"))
        ):
            raise HerzchenAdapterError("task-bound evidence lacks a completed operation result")
        if _context_digest(
            session_id=expected_session_id,
            turn_id=expected_turn_id,
            provenance=provenance,
            model=str(model or ""),
            reasoning=str(reasoning or ""),
            worker_content=[_json(item) for item in worker_content],
            task_bound_evidence=task_evidence,
            effective_profile=effective_profile,
        ) != context_digest:
            raise HerzchenAdapterError("host context digest does not match attested context bytes")
        task_evidence["delivered_contract_digest"] = delivered_contract_digest
        task_evidence["result_digest"] = result_digest
        return {
            "model": model.strip() if isinstance(model, str) and model.strip() else None,
            "reasoning": reasoning.strip() if isinstance(reasoning, str) and reasoning.strip() else None,
            "worker_content": [_json(item) for item in worker_content],
            "session_id": session_id,
            "turn_id": turn_id,
            "provenance": provenance,
            "context_digest": context_digest.strip(),
            "task_bound_evidence": task_evidence,
            "context_digest_verified": True,
            "observed_profile": effective_profile,
        }

    @staticmethod
    def _observed_turn_id(envelope: Mapping[str, Any]) -> str | None:
        """Extract only a host-owned turn id from the returned envelope."""

        direct = envelope.get("turn_id")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        host = envelope.get("host_evidence")
        if isinstance(host, Mapping):
            direct = host.get("turn_id")
            if isinstance(direct, str) and direct.strip():
                return direct.strip()
            events = host.get("events")
            if isinstance(events, list):
                for event in reversed(events):
                    if isinstance(event, Mapping) and isinstance(event.get("turn_id"), str) and event["turn_id"].strip():
                        return event["turn_id"].strip()
        return None

    def _execute(self, operation: str, request: Mapping[str, Any],
                 *, observed_override: Optional[tuple[Any, Any]] = None) -> Mapping[str, Any]:
        typed, digest, brief = self._typed_request(operation, request)
        context_reader = self.turn_context_reader
        if not callable(context_reader) and self.host_context_path:
            context_reader = JsonlHostTurnContextReader(self.host_context_path)
        if self.require_host_context and not callable(context_reader):
            raise HerzchenAdapterError("host-owned turn context reader is required before launch")
        if observed_override is None:
            if brief.get("instruction_contract", {}).get("source_inspection") is not None:
                raise HerzchenAdapterError("bounded source inspection requires owner-authorized direct invoke")
            projection = self._request_projection(brief, digest, request)
            host = self._new_host(
                self.render_verified_brief(brief, digest, model_projection=projection), brief,
                model_projection=projection,
                model=_text(request.get("requested_model", self.requested_model), "requested_model"),
                reasoning=_text(request.get("requested_reasoning", self.requested_reasoning), "requested_reasoning"),
            )
            method = getattr(host, operation, None)
            if not callable(method):
                raise HerzchenAdapterError(f"Herzchen host adapter does not support {operation}")
            observed = method(typed)
        else:
            observed = observed_override
        if not isinstance(observed, tuple) or len(observed) != 2:
            raise HerzchenAdapterError("Herzchen host adapter returned an invalid receipt")
        receipt, envelope = observed
        receipt_value = _json(receipt)
        envelope_value = _json(envelope)
        identity = getattr(receipt, "identity", None)
        physical = getattr(identity, "physical_session_id", None)
        outcome = getattr(getattr(receipt, "outcome", None), "value", getattr(receipt, "outcome", "unknown"))
        observed_model = envelope_value.get("observed_model") if isinstance(envelope_value, Mapping) else None
        observed_reasoning = envelope_value.get("observed_reasoning") if isinstance(envelope_value, Mapping) else None
        worker_content = envelope_value.get("worker_content", []) if isinstance(envelope_value, Mapping) else []
        context_provenance = None
        observed_turn_id = self._observed_turn_id(envelope_value) if isinstance(envelope_value, Mapping) else None
        observed_context_digest = None
        task_bound_evidence = None
        observed_profile = envelope_value.get("observed_profile") if isinstance(envelope_value, Mapping) else None
        if callable(context_reader) and outcome == "succeeded":
            if not physical:
                raise HerzchenAdapterError("successful host result has no physical session for context attestation")
            if not observed_turn_id:
                raise HerzchenAdapterError("successful host result has no host-owned turn id for context attestation")
            try:
                supplied = envelope_value.get("host_evidence", {}).get("otto_host_turn_context")
                observed_context = supplied if isinstance(supplied, Mapping) else context_reader(str(physical), observed_turn_id)
            except Exception as exc:
                raise HerzchenAdapterError("host-owned turn context reader failed") from exc
            context = self._observed_context(
                observed_context,
                expected_session_id=str(physical),
                expected_turn_id=observed_turn_id,
                expected_profile=typed.requested_profile,
                expected_read_targets=(
                    brief.get("instruction_contract", {}).get("read_targets")
                    if isinstance(brief.get("instruction_contract"), Mapping)
                    else None
                ),
            )
            observed_model = context["model"]
            observed_reasoning = context["reasoning"]
            context_worker_content = context["worker_content"]
            if not observed_model or not observed_reasoning:
                raise HerzchenAdapterError("host-owned turn context lacks model/reasoning")
            worker_content = context_worker_content
            context_provenance = context["provenance"]
            observed_context_digest = context["context_digest"]
            task_bound_evidence = context["task_bound_evidence"]
            observed_profile = context["observed_profile"]
        native_host = envelope_value.get("host_evidence") if isinstance(envelope_value, Mapping) else None
        native_host = native_host if isinstance(native_host, Mapping) else {}
        return {
            "outcome": str(outcome),
            "receipt": receipt_value,
            "envelope": envelope_value,
            "native_candidate": native_host.get("native_candidate"),
            "verification_failures": native_host.get("verification_failures", []),
            "resource_brief_sha256": digest,
            "physical_session_id": physical,
            "observed_turn_id": observed_turn_id,
            "observed_model": observed_model,
            "observed_reasoning": observed_reasoning,
            "observed_profile": observed_profile,
            "observed_context_provenance": context_provenance,
            "observed_context_digest": observed_context_digest,
            "context_digest_verified": bool(observed_context_digest),
            "task_bound_evidence": task_bound_evidence,
            "worker_content": worker_content,
            "delivery_state": envelope_value.get("delivery_state", "unknown") if isinstance(envelope_value, Mapping) else "unknown",
        }

    def invoke(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._owner_authorizer is not None:
            return self._invoke_owner_authorized(request)
        return self._execute("invoke", request)

    def _invoke_owner_authorized(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Initialize inertly, bind owner identity, then deliver by exact resume."""
        from herzchen.contracts import HostIdentity, HostOperation, HostRequest

        if not self.require_host_context or not (callable(self.turn_context_reader) or self.host_context_path):
            raise HerzchenAdapterError("owner-authorized delivery requires host-owned task evidence")
        if not callable(self._owner_delivery_verifier):
            raise HerzchenAdapterError("trusted current owner delivery verifier is required")
        typed, digest, brief = self._typed_request("invoke", request)
        model = _text(request.get("requested_model", self.requested_model), "requested_model")
        reasoning = _text(request.get("requested_reasoning", self.requested_reasoning), "requested_reasoning")
        projection = self._request_projection(brief, digest, request)
        inert_prompt = (
            "Initialize this session only. Do not read files, use tools, execute commands, "
            "or perform task work. Return READY."
        )
        limits = brief.get("instruction_contract", {}).get("source_inspection")
        inert_options, work_options = {}, {}
        if limits is not None:
            from .source_verification import inspection_contract, finite, T01_EXTENDED_TIMEOUTS, t01_timeout_brief
            limits = inspection_contract(limits, task_ref=brief["instruction_contract"].get("task_ref"))
            extended = limits["timeouts"] == T01_EXTENDED_TIMEOUTS
            if extended and (not t01_timeout_brief(brief) or model != "gpt-6-luna" or reasoning != "xhigh" or typed.requested_profile != "read-only"):
                raise HerzchenAdapterError("extended timeout requires exact generation12 T01 recipient")
            total = finite(request.get("owner_timeout_seconds"), 4620 if extended else 1920)
            if total != limits["timeouts"]["total_seconds"] or not callable(self.source_verifier_factory):
                raise HerzchenAdapterError("current owner timeout/admitted source verifier mismatch")
            deadline = request.get("owner_occurrence_deadline")
            if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
                raise HerzchenAdapterError("authentic owner occurrence deadline is required")
            finite(deadline - self.monotonic_clock(), total)
            self._source_verifier = self.source_verifier_factory(brief=brief, deadline=deadline)
            inert_options = {"timeout_seconds": limits["timeouts"]["inert_seconds"], "occurrence_deadline": deadline}
            work_options = {"timeout_seconds": limits["timeouts"]["delivery_seconds"], "occurrence_deadline": deadline,
                            "source_verifier": self._source_verifier}
            if extended:
                inert_options["timeout_brief"] = brief
                work_options["timeout_brief"] = brief
        initializer = self._new_host(inert_prompt, {}, model=model, reasoning=reasoning, **inert_options)
        observed_initial = initializer.invoke(typed)
        if not isinstance(observed_initial, tuple) or len(observed_initial) != 2:
            raise HerzchenAdapterError("inert host initialization returned no receipt")
        initial_receipt, initial_envelope = observed_initial
        initial_identity = getattr(initial_receipt, "identity", None)
        physical = getattr(initial_identity, "physical_session_id", None)
        initial_outcome = getattr(getattr(initial_receipt, "outcome", None), "value", getattr(initial_receipt, "outcome", "unknown"))
        base = {"initialization_receipt": _json(initial_receipt),
                "initialization_envelope": _json(initial_envelope),
                "physical_session_id": physical, "retry_allowed": False}
        if isinstance(physical, str) and physical.strip() and self._thread_started_callback is not None:
            try:
                self._thread_started_callback(physical)
            except Exception as exc:
                return {**base, "outcome": "unknown", "delivery_state": "unknown",
                        "error": {"code": "owner_identity_capture_failed", "message": str(exc)}}
        initial_host = _json(initial_envelope).get("host_evidence", {})
        if (initial_outcome != "succeeded" or not isinstance(physical, str) or not physical.strip()
                or initial_host.get("invocation_turn_verified") is not True):
            return {**base, "outcome": "unknown", "delivery_state": "unknown",
                    "error": {"code": "inert_start_unresolved", "message": "initialization did not prove a completed host session"}}
        if self._thread_started_callback is None:
            return {**base, "outcome": "unknown", "delivery_state": "unknown",
                    "error": {"code": "owner_identity_capture_missing", "message": "provider identity was not bound to the owner"}}
        try:
            authorization = self._owner_authorizer(physical, digest)
        except Exception as exc:
            return {**base, "outcome": "unknown", "delivery_state": "unknown",
                    "error": {"code": "owner_delivery_denied", "message": str(exc)}}
        expected = {"status": "authorized", "physical_session_id": physical, "brief_sha256": digest,
                    "logical_request_key": request.get("logical_request_key"),
                    "project_ref": request.get("expected_project_ref"), "task_ref": typed.target.to_dict(),
                    "assignment_ref": request.get("expected_assignment_ref"),
                    "generation": request.get("expected_generation"), "role": request.get("expected_role"),
                    "principal": request.get("expected_principal"),
                    "lifecycle_owner": request.get("expected_lifecycle_owner")}
        if (not isinstance(authorization, Mapping) or any(value is None for value in expected.values())
                or any(authorization.get(key) != value for key, value in expected.items())
                or not isinstance(authorization.get("owner_version"), int)
                or isinstance(authorization.get("owner_version"), bool)):
            return {**base, "outcome": "unknown", "delivery_state": "unknown",
                    "error": {"code": "owner_delivery_denied", "message": "owner authorization readback was not exact"}}
        resumed = HostRequest(
            HostOperation.RESUME, HostIdentity(typed.identity.logical_agent_id, physical),
            typed.target, typed.requested_profile,
        )
        recipient_admitted = False

        def admit_recipient(host_request: Any) -> Mapping[str, Any]:
            # Closure is injected by the owner composition, never a public
            # request/prompt receipt. The receiving binding calls it at launch.
            nonlocal recipient_admitted
            if (recipient_admitted or host_request != resumed
                    or host_request.requested_profile not in {"read-only", "workspace-write"}
                    or host_request.identity.logical_agent_id != (
                        authorization["principal"] if isinstance(authorization["principal"], str)
                        else authorization["principal"].get("id"))):
                raise HerzchenAdapterError("recipient identity or permission contract changed")
            current = self._owner_delivery_verifier(physical, digest, dict(authorization))
            if not isinstance(current, Mapping) or dict(current) != dict(authorization):
                raise HerzchenAdapterError("current recipient authorization changed")
            recipient_admitted = True
            return dict(current)

        observed_work = None
        try:
            recipient = self._new_host(
                self.render_verified_brief(brief, digest, model_projection=projection), brief,
                model=model, reasoning=reasoning, model_projection=projection,
                recipient_authorizer=admit_recipient, **work_options,
            )
            observed_work = recipient.resume(resumed)
            result = dict(self._execute(
                "resume", {**request, "physical_session_id": physical},
                observed_override=observed_work,
            ))
        except Exception as exc:
            # Unknown task evidence is a durable reconciliation result, not a
            # reason to discard the known provider identity or launch again.
            result = {"outcome": "unknown", "delivery_state": "unknown",
                      "physical_session_id": physical,
                      "receipt": _json(observed_work[0]) if isinstance(observed_work, tuple) and len(observed_work) == 2 else None,
                      "error": {"code": "authorized_result_unverified", "message": str(exc)}}
            retained = _json(observed_work[1]) if isinstance(observed_work, tuple) and len(observed_work) == 2 else {}
            result["envelope"] = retained
            if isinstance(retained, Mapping):
                native_host = retained.get('host_evidence')
                if isinstance(native_host, Mapping):
                    result['native_candidate'] = native_host.get('native_candidate')
                    result['verification_failures'] = native_host.get('verification_failures', [])
        # Keep transport diagnostics even when context attestation cannot run.
        # A completed initializer is not evidence of a completed task resume.
        if (result.get("outcome") != "succeeded" and not result.get("observed_turn_id")
                and "error" not in result):
            result["error"] = {
                "code": "authorized_result_unverified",
                "message": ("initialization succeeded, but host resume returned "
                            + str(result.get("outcome", "unknown"))
                            + " without a verified resumed turn; task delivery remains unverified"),
            }
        owner_still_current = False
        if result.get("outcome") == "succeeded":
            try:
                owner_still_current = self._owner_delivery_verifier(physical, digest, dict(authorization)) == authorization
            except Exception:
                owner_still_current = False
        result.update({"initialization_receipt": base["initialization_receipt"],
                       "initialization_envelope": base["initialization_envelope"],
                       "owner_delivery_authorization": _json(authorization),
                       "transport_operation": "resume", "retry_allowed": False})
        evidence = result.get("task_bound_evidence")
        if projection is not None and (not isinstance(evidence, Mapping) or evidence.get("model_projection") != {
                "canonical_brief_sha256": digest, "projection_sha256": _digest(projection),
                "schema": projection["schema"]}):
            result.update({"outcome": "unknown", "delivery_state": "unknown"})
            result.setdefault("error", {"code": "projection_result_unverified", "message": "exact model projection binding was not proved"})
        if projection is not None and brief["context"]["canonical_snapshot"]["generation"] >= 11:
            expected_cursor = {"canonical_brief_sha256": digest,"projection_sha256":_digest(projection),
                "generation":brief["resource_resolution"]["generation"],"logical_request_key":authorization["logical_request_key"],
                "physical_session_id":physical,"turn_intent":"otto.d256.one-resume.v1"}
            expected_cursor["nonce"] = _digest(expected_cursor)
            joined = evidence.get("command_cursor") if isinstance(evidence, Mapping) else None
            if (not isinstance(joined, Mapping) or any(joined.get(k) != v for k,v in expected_cursor.items())
                    or joined.get("turn_id") != evidence.get("turn_id")
                    or joined.get("queue_sha256") != _digest(self.build_cursor_queue(brief, projection))
                    or len(joined.get("command_receipts", [])) != 145):
                result.update({"outcome":"unknown","delivery_state":"unknown"})
                result.setdefault("error", {"code":"cursor_native_join_unverified","message":"exact same-turn cursor receipt chain was not proved"})
        contract = brief.get("instruction_contract")
        if (not owner_still_current or not recipient_admitted or result.get("outcome") != "succeeded" or result.get("physical_session_id") != physical
                or not result.get("context_digest_verified")
                or not isinstance(evidence, Mapping)
                or evidence.get("operation") != "resume"
                or evidence.get("assignment_ref") != request.get("expected_assignment_ref")
                or evidence.get("generation") != request.get("expected_generation")
                or evidence.get("owner_delivery_authorization") != authorization
                or not isinstance(contract, Mapping)
                or evidence.get("delivered_contract_digest") != _digest(dict(contract))):
            result.update({"outcome": "unknown", "delivery_state": "unknown"})
            result.setdefault("error", {"code":"authorized_result_unverified", "message":"exact resumed session and task evidence were not proved"})
        if limits is not None and result.get("outcome") == "succeeded":
            try:
                self.verify_source_result(result.get("task_bound_evidence"), brief)
            except Exception as exc:
                result.update({"outcome": "unknown", "delivery_state": "unknown",
                               "error": {"code": "source_verification_failed", "message": str(exc)}})
        result["raw_result"] = {
            "initialization_receipt": base["initialization_receipt"],
            "initialization_envelope": base["initialization_envelope"],
            "work_receipt": result.get("receipt"),
            "work_envelope": _json(result.get("envelope")),
            "transport_operation": "resume",
            "owner_delivery_authorization": _json(authorization),
            "task_bound_evidence": _json(evidence),
            "worker_content": _json(result.get("worker_content", [])),
            "native_candidate": _json(result.get("native_candidate")),
            "verification_failures": _json(result.get("verification_failures", [])),
        }
        return result

    def verify_source_result(self, evidence: Any, brief: Mapping[str, Any]) -> bool:
        if brief.get("instruction_contract", {}).get("source_inspection") is None:
            return True
        if self._source_verifier is None or not isinstance(evidence, Mapping):
            raise HerzchenAdapterError("trusted source verifier result is unavailable")
        proof = evidence.get("operation_result", {}).get("output", {}).get("source_verification")
        return self._source_verifier.recheck(proof)

    def resume(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._execute("resume", request)

    def send(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._execute("send", request)


__all__ = ["HerzchenAdapterError", "HerzchenCodexAdapter", "JsonlHostTurnContextReader"]
