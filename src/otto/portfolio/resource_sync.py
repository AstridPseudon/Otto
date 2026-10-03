"""Role-scoped instructional-resource resolution and brief evidence.

This module is deliberately small and side-effect free.  The canonical work
owner stores the resource reference on a responsibility assignment (through
its explicit ``resource_adoptions`` field); this module validates the richer resource
descriptor and makes the exact pins/digests portable to a host brief.  It is
the common seam used before creation, child launch, dispatch, replacement,
resume, and callback.  It does not select a workflow or grant authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence


class ResourceSyncError(ValueError):
    """A resource descriptor, attachment, or brief is not admissible."""


ROLES = frozenset({"orchestrator", "manager", "worker"})
LIFECYCLES = frozenset({"create", "child", "launch", "replace", "resume", "callback"})
DELIVERY_STATES = frozenset({"prepared", "submitted", "observed_delivered", "running", "completed", "attributed", "accepted"})


def _copy(value: Any, field: str = "value") -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ResourceSyncError(f"{field} must be JSON-compatible") from exc


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ResourceSyncError(f"{field} must be non-blank text")
    return value.strip()


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ref(value: Any, field: str) -> dict[str, Any]:
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
    if not isinstance(value, Mapping):
        raise ResourceSyncError(f"{field} must be a reference object")
    result = _copy(dict(value), field)
    _text(result.get("id"), f"{field}.id")
    if "revision" in result and result["revision"] is not None:
        _text(result["revision"], f"{field}.revision")
    return result


def _identity(ref: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(ref.get("authority", "")), str(ref.get("kind", "")), str(ref["id"]))


def _revision(ref: Mapping[str, Any], field: str) -> str:
    return _text(ref.get("revision"), f"{field}.revision")


def normalize_instruction_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the substantive, owner-scoped instructions in a host brief.

    A resource digest identifies bytes; it is not an instruction.  The contract
    is deliberately narrow so a host receives the task objective, one bounded
    operation, and the authority/effect fences that apply to that operation.
    """

    if not isinstance(value, Mapping):
        raise ResourceSyncError("instruction_contract must be an object")
    result = _copy(dict(value), "instruction_contract")
    task_ref = result.get("task_ref")
    if not isinstance(task_ref, Mapping):
        raise ResourceSyncError("instruction_contract.task_ref must be a reference object")
    _text(task_ref.get("id"), "instruction_contract.task_ref.id")
    _text(task_ref.get("kind"), "instruction_contract.task_ref.kind")
    _text(task_ref.get("authority"), "instruction_contract.task_ref.authority")
    objective = _text(result.get("objective"), "instruction_contract.objective")
    bounded_operation = _text(result.get("bounded_operation"), "instruction_contract.bounded_operation")
    allowed = result.get("allowed_operations")
    if isinstance(allowed, (str, bytes)) or not isinstance(allowed, Sequence) or not allowed:
        raise ResourceSyncError("instruction_contract.allowed_operations must be a non-empty list")
    allowed_values = [_text(item, "instruction_contract.allowed_operations[]") for item in allowed]
    acceptance = result.get("acceptance_criteria")
    if isinstance(acceptance, (str, bytes)) or not isinstance(acceptance, Sequence) or not acceptance:
        raise ResourceSyncError("instruction_contract.acceptance_criteria must be a non-empty list")
    acceptance_values = [_text(item, "instruction_contract.acceptance_criteria[]") for item in acceptance]
    authority = result.get("authority")
    if not isinstance(authority, Mapping):
        raise ResourceSyncError("instruction_contract.authority must be an object")
    authority_value = _copy(dict(authority), "instruction_contract.authority")
    _text(authority_value.get("source"), "instruction_contract.authority.source")
    _text(authority_value.get("owner_actor"), "instruction_contract.authority.owner_actor")
    if authority_value.get("gateway_claim_required") is not True:
        raise ResourceSyncError("instruction_contract authority must require a gateway claim")
    if authority_value.get("owner_write") is not False or authority_value.get("dispatch") is not False:
        raise ResourceSyncError("instruction_contract authority cannot grant owner write or dispatch")
    permitted = authority_value.get("permitted_effects")
    forbidden = authority_value.get("forbidden_effects")
    if isinstance(permitted, (str, bytes)) or not isinstance(permitted, Sequence) or not permitted:
        raise ResourceSyncError("instruction_contract.authority.permitted_effects must be a non-empty list")
    if isinstance(forbidden, (str, bytes)) or not isinstance(forbidden, Sequence):
        raise ResourceSyncError("instruction_contract.authority.forbidden_effects must be a list")
    forbidden_values = {_text(item, "instruction_contract.authority.forbidden_effects[]") for item in forbidden}
    required_forbidden = {"file_write", "owner_write", "publication", "package_adoption"}
    if not required_forbidden.issubset(forbidden_values):
        raise ResourceSyncError("instruction_contract authority does not fence all forbidden effects")
    result["task_ref"] = _copy(dict(task_ref), "instruction_contract.task_ref")
    result["objective"] = objective
    result["bounded_operation"] = bounded_operation
    result["allowed_operations"] = allowed_values
    result["acceptance_criteria"] = acceptance_values
    result["authority"] = authority_value
    if "source_inspection" in result:
        from otto.agents.source_verification import inspection_contract, SourceVerificationError
        try:
            result["source_inspection"] = inspection_contract(result["source_inspection"], task_ref=result.get("task_ref"))
        except SourceVerificationError as exc:
            raise ResourceSyncError(str(exc)) from exc
    return result


@dataclass(frozen=True)
class ResourceAttachment:
    """One exact adopted resource revision for one durable responsibility."""

    role: str
    responsibility_ref: Mapping[str, Any]
    resource_ref: Mapping[str, Any]
    resource_name: str
    adopted_revision: str
    entrypoint: str
    bundle_digest: str
    export_manifest_digest: str
    supporting_refs: tuple[Mapping[str, Any], ...] = ()
    required: bool = True
    content: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "responsibility_ref": _copy(dict(self.responsibility_ref)),
            "resource_ref": _copy(dict(self.resource_ref)),
            "resource_name": self.resource_name,
            "adopted_revision": self.adopted_revision,
            "entrypoint": self.entrypoint,
            "bundle_digest": self.bundle_digest,
            "export_manifest_digest": self.export_manifest_digest,
            "supporting_refs": [_copy(dict(ref)) for ref in self.supporting_refs],
            "required": self.required,
            **({"content": _copy(self.content, "resource.content")} if self.content is not None else {}),
        }


def normalize_attachment(value: Mapping[str, Any], *, role: str | None = None) -> ResourceAttachment:
    """Validate one owner-adopted resource descriptor."""

    if not isinstance(value, Mapping):
        raise ResourceSyncError("resource attachment must be an object")
    selected_role = _text(value.get("role", role), "resource.role").lower()
    if selected_role not in ROLES:
        raise ResourceSyncError("resource.role must be orchestrator, manager, or worker")
    if role is not None and selected_role != role:
        raise ResourceSyncError("resource role does not match its responsibility slot")
    responsibility = _ref(value.get("responsibility_ref"), "resource.responsibility_ref")
    resource = _ref(value.get("resource_ref"), "resource.resource_ref")
    adopted = _text(value.get("adopted_revision"), "resource.adopted_revision")
    resource_revision = _revision(resource, "resource.resource_ref")
    if resource_revision != adopted:
        raise ResourceSyncError("resource.adopted_revision does not match resource_ref.revision")
    entrypoint = _text(value.get("entrypoint"), "resource.entrypoint")
    bundle = _text(value.get("bundle_digest"), "resource.bundle_digest")
    manifest = _text(value.get("export_manifest_digest"), "resource.export_manifest_digest")
    required = value.get("required", True)
    if not isinstance(required, bool):
        raise ResourceSyncError("resource.required must be boolean")
    supporting_raw = value.get("supporting_refs", ())
    if isinstance(supporting_raw, (str, bytes)) or not isinstance(supporting_raw, Sequence):
        raise ResourceSyncError("resource.supporting_refs must be a list")
    supporting = tuple(_ref(item, "resource.supporting_ref") for item in supporting_raw)
    return ResourceAttachment(selected_role, responsibility, resource, _text(value.get("resource_name"), "resource.resource_name"), adopted, entrypoint, bundle, manifest, supporting, required, _copy(value.get("content"), "resource.content") if value.get("content") is not None else None)


def normalize_role_attachments(value: Any) -> dict[str, list[dict[str, Any]]]:
    """Normalize the role-keyed attachment input accepted by ``assign_roles``."""

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ResourceSyncError("resources must be an object keyed by role")
    result: dict[str, list[dict[str, Any]]] = {}
    for raw_role, raw_items in value.items():
        role = _text(raw_role, "resources.role").lower()
        if role not in ROLES:
            raise ResourceSyncError("resources contains an unsupported role")
        if isinstance(raw_items, Mapping):
            items = [raw_items]
        elif isinstance(raw_items, Sequence) and not isinstance(raw_items, (str, bytes)):
            items = list(raw_items)
        else:
            raise ResourceSyncError(f"resources.{role} must be an attachment or list")
        result[role] = [normalize_attachment(item, role=role).to_dict() for item in items]
    return result


def role_resource_pins(resources: Mapping[str, Any] | None, role: str) -> list[dict[str, Any]]:
    """Return the exact resource refs to pass to the canonical assignment port."""

    normalized = normalize_role_attachments(resources)
    slot = {"orchestrator": "orchestrator", "manager": "manager", "worker": "worker", "parent": None, "executor": "worker"}.get(role)
    if slot is None:
        return []
    return [dict(item["resource_ref"]) for item in normalized.get(slot, ())]


def _read_resource_revision(ref: Mapping[str, Any], reader: Any, resource_name: str) -> tuple[str, dict[str, Any]]:
    """Read one immutable descriptor through the injected finite reader."""

    read_method = getattr(reader, "get_record", None) or getattr(reader, "read", None)
    try:
        raw = read_method(ref)
    except Exception as exc:
        raw = None
        read_error = exc
    else:
        read_error = None
    if raw is None:
        try:
            from herzchen.contracts import ResourceRef

            raw = read_method(ResourceRef.from_dict(dict(ref)))
        except Exception as exc:
            raise ResourceSyncError(f"resource reference could not be read: {resource_name}") from (read_error or exc)
    if raw is None:
        raise ResourceSyncError(f"resource reference could not be read: {resource_name}")
    if hasattr(raw, "to_dict"):
        raw = raw.to_dict()
    if not isinstance(raw, Mapping):
        raise ResourceSyncError(f"resource reference returned no record: {resource_name}")
    revision = raw.get("revision") if isinstance(raw.get("revision"), Mapping) else {}
    content = revision.get("content") if isinstance(revision, Mapping) else None
    if not isinstance(content, Mapping) and isinstance(raw.get("content"), Mapping):
        content = raw.get("content")
    if not isinstance(content, Mapping):
        payload = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else {}
        content = payload.get("content") if isinstance(payload.get("content"), Mapping) else None
    if not isinstance(content, Mapping):
        raise ResourceSyncError(f"resource revision has no descriptor content: {resource_name}")
    current_ref = raw.get("current_revision") if isinstance(raw.get("current_revision"), Mapping) else None
    identity_ref = raw.get("identity") if isinstance(raw.get("identity"), Mapping) else {}
    actual_revision = revision.get("revision") if isinstance(revision, Mapping) else None
    if actual_revision is None and isinstance(raw.get("revision"), str):
        actual_revision = raw.get("revision")
    if actual_revision is None and isinstance(current_ref, Mapping):
        actual_revision = current_ref.get("revision")
    if actual_revision is None and isinstance(identity_ref, Mapping):
        actual_revision = identity_ref.get("revision")
    if not isinstance(actual_revision, str) or not actual_revision:
        raise ResourceSyncError(f"resource revision is stale or unpinned: {resource_name}")
    return actual_revision, dict(content)


def resolve_assignment_attachments(assignment: Any, reader: Any, *, role: str | None = None) -> list[dict[str, Any]]:
    """Resolve only explicit adoptions; generic scope/input pins are retained."""

    if hasattr(assignment, "to_dict"):
        assignment = assignment.to_dict()
    if not isinstance(assignment, Mapping):
        raise ResourceSyncError("assignment must be an object")
    assignment = dict(assignment)
    payload = assignment.get("payload")
    if isinstance(payload, Mapping) and "resource_adoptions" in payload:
        nested = payload["resource_adoptions"]
        if not isinstance(nested, list) or not nested:
            raise ResourceSyncError("assignment instruction adoptions must be a non-empty list")
        if payload.get("resource_adoption_digest") != _digest(nested):
            raise ResourceSyncError("assignment instruction adoption digest is inconsistent")
        for field in ("resource_adoptions", "resource_adoption_digest", "resource_adoption_revision"):
            if field in assignment and assignment[field] != payload.get(field):
                raise ResourceSyncError("assignment instruction adoption projections conflict")
            assignment[field] = payload.get(field)
    assignment_ref = assignment.get("assignment_ref", assignment.get("ref"))
    responsibility = _ref(assignment_ref, "assignment_ref")
    selected_role = _text(role or assignment.get("role"), "assignment.role").lower()
    if selected_role == "executor":
        selected_role = "worker"
    if selected_role not in ROLES:
        raise ResourceSyncError("assignment.role must be orchestrator, manager, or worker")
    pins = assignment.get("resource_adoptions", ())
    if isinstance(pins, (str, bytes)) or not isinstance(pins, Sequence):
        raise ResourceSyncError("assignment.resource_adoptions must be a list")
    if reader is None or not callable(getattr(reader, "get_record", None)) and not callable(getattr(reader, "read", None)):
        raise ResourceSyncError("canonical resource reader is unavailable")
    claims: list[dict[str, Any]] = []
    if pins:
        if assignment.get("resource_adoption_digest") != _digest(pins) or not assignment.get("resource_adoption_revision"):
            raise ResourceSyncError("assignment adoption evidence is inconsistent")
    for index, value in enumerate(pins):
        if not isinstance(value, Mapping):
            raise ResourceSyncError("resource adoption must be an object")
        resource_ref = _ref(value.get("resource_ref"), f"assignment.resource_adoptions[{index}]")
        adopted = _revision(resource_ref, f"assignment.resource_adoptions[{index}]")
        actual_revision, content = _read_resource_revision(resource_ref, reader, f"pin-{index}")
        if actual_revision != adopted:
            raise ResourceSyncError("assignment resource pin is stale")
        from herzchen.content.instructions import validate_instruction_content
        try:
            digest = validate_instruction_content(content)
        except (TypeError, ValueError) as exc:
            raise ResourceSyncError(str(exc)) from exc
        if digest != value.get("content_digest") or content["name"] != value.get("resource_name") or content["required"] is not value.get("required"):
            raise ResourceSyncError("adopted instruction evidence does not match immutable content")
        name = content["name"]
        if any(item["resource_name"] == name for item in claims):
            raise ResourceSyncError("duplicate adopted instruction resource name")
        supporting = content.get("supporting_refs", ())
        claims.append({
            "role": selected_role,
            "responsibility_ref": responsibility,
            "resource_ref": resource_ref,
            "resource_name": name,
            "adopted_revision": adopted,
            "entrypoint": content.get("entrypoint"),
            "bundle_digest": content.get("bundle_digest"),
            "export_manifest_digest": content.get("export_manifest_digest"),
            "supporting_refs": supporting,
            "required": content.get("required"),
        })
    return resolve_role_attachments({selected_role: claims}, reader).get(selected_role, [])


def resolve_role_attachments(value: Any, reader: Any) -> dict[str, list[dict[str, Any]]]:
    """Read each pinned document revision and verify its descriptor bytes.

    The reader is the already-injected canonical read port.  A caller cannot
    change the required flag or digest merely by repeating an assignment with
    a new echo: those fields must agree with the immutable descriptor content.
    """

    normalized = normalize_role_attachments(value)
    if reader is None or not callable(getattr(reader, "get_record", None)) and not callable(getattr(reader, "read", None)):
        raise ResourceSyncError("canonical resource reader is unavailable")
    result: dict[str, list[dict[str, Any]]] = {}
    for role, items in normalized.items():
        resolved: list[dict[str, Any]] = []
        for item in items:
            ref = dict(item["resource_ref"])
            actual_revision, content = _read_resource_revision(ref, reader, item["resource_name"])
            if ref.get("revision") != actual_revision:
                raise ResourceSyncError(f"resource revision is stale or unpinned: {item['resource_name']}")
            if item["adopted_revision"] != actual_revision:
                raise ResourceSyncError(f"adopted resource revision does not match the canonical document: {item['resource_name']}")
            if content.get("name", content.get("resource_name")) != item["resource_name"]:
                raise ResourceSyncError(f"resource name does not match canonical descriptor: {item['resource_name']}")
            for field in ("entrypoint", "bundle_digest", "export_manifest_digest", "required"):
                if field not in content:
                    raise ResourceSyncError(f"canonical descriptor is missing {field}: {item['resource_name']}")
                if content[field] != item[field]:
                    raise ResourceSyncError(f"resource {field} does not match canonical descriptor: {item['resource_name']}")
            if "supporting_refs" not in content or not isinstance(content["supporting_refs"], Sequence) or isinstance(content["supporting_refs"], (str, bytes)):
                raise ResourceSyncError(f"canonical descriptor is missing supporting_refs: {item['resource_name']}")
            canonical_supporting = tuple(_ref(ref_value, "resource.supporting_ref") for ref_value in content["supporting_refs"])
            if [dict(ref_value) for ref_value in canonical_supporting] != item["supporting_refs"]:
                raise ResourceSyncError(f"resource supporting_refs do not match canonical descriptor: {item['resource_name']}")
            descriptor = dict(item, resource_ref=ref, resource_name=content.get("name", content.get("resource_name")), entrypoint=content["entrypoint"], bundle_digest=content["bundle_digest"], export_manifest_digest=content["export_manifest_digest"], required=content["required"], supporting_refs=[dict(ref_value) for ref_value in canonical_supporting], content=_copy(dict(content), "resource.content"))
            resolved.append(descriptor)
        result[role] = resolved
    return result


def resolve_role_resources(*, role: str, responsibility_ref: Mapping[str, Any], generation: int, lifecycle: str, attachments: Sequence[Mapping[str, Any]], required_resource_names: Sequence[str] = ()) -> dict[str, Any]:
    """Resolve one deterministic resource set at a lifecycle decision point."""

    role = _text(role, "role").lower()
    if role not in ROLES:
        raise ResourceSyncError("role is unsupported")
    lifecycle = _text(lifecycle, "lifecycle").lower()
    if lifecycle not in LIFECYCLES:
        raise ResourceSyncError("lifecycle is unsupported")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise ResourceSyncError("generation must be a positive integer")
    responsibility = _ref(responsibility_ref, "responsibility_ref")
    values = [normalize_attachment(item, role=role) for item in attachments]
    if isinstance(required_resource_names, (str, bytes)) or not isinstance(required_resource_names, Sequence):
        raise ResourceSyncError("required_resource_names must be a list")
    required_names = {_text(item, "required_resource_name") for item in required_resource_names}
    for item in values:
        if _identity(item.responsibility_ref) != _identity(responsibility):
            raise ResourceSyncError("resource responsibility does not match the outgoing responsibility")
        if not item.resource_ref.get("revision"):
            raise ResourceSyncError("resource_ref must pin an adopted revision")
    seen: dict[tuple[str, str, str], str] = {}
    unique_values: list[ResourceAttachment] = []
    for item in values:
        key = _identity(item.resource_ref)
        descriptor_digest = _digest(item.to_dict())
        prior = seen.get(key)
        if prior is not None and prior != descriptor_digest:
            raise ResourceSyncError("one resource identity is attached with conflicting revision or digest claims")
        if prior is None:
            seen[key] = descriptor_digest
            unique_values.append(item)
    ordered = sorted((item.to_dict() for item in unique_values), key=lambda item: (item["resource_name"], item["adopted_revision"], _identity(item["resource_ref"])))
    missing = sorted(required_names - {item["resource_name"] for item in ordered})
    if missing:
        raise ResourceSyncError("required resource is not attached: " + ", ".join(missing))
    required = [item for item in ordered if item["required"]]
    return {
        "role": role,
        "responsibility_ref": responsibility,
        "generation": generation,
        "lifecycle": lifecycle,
        "resources": ordered,
        "required_count": len(required),
        "resource_set_digest": _digest(ordered),
        "export_manifest_digest": _digest([item["export_manifest_digest"] for item in ordered]),
    }


def compose_role_brief(*, role: str, responsibility_ref: Mapping[str, Any], generation: int, lifecycle: str, operating_core: Mapping[str, Any], context: Mapping[str, Any], attachments: Sequence[Mapping[str, Any]], required_resource_names: Sequence[str] = (), reader: Any = None, resource_adoption: Mapping[str, Any] | None = None, instruction_contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Compose the exact outgoing brief and its evidence pins."""

    if not isinstance(operating_core, Mapping) or not operating_core:
        raise ResourceSyncError("operating_core must be a non-empty object")
    if not isinstance(context, Mapping) or not context:
        raise ResourceSyncError("context must be a non-empty object")
    if reader is not None:
        attachments = resolve_role_attachments({role: list(attachments)}, reader).get(role, [])
    resolved = resolve_role_resources(role=role, responsibility_ref=responsibility_ref, generation=generation, lifecycle=lifecycle, attachments=attachments, required_resource_names=required_resource_names)
    body = {
        "schema": "otto.orchestrator.role_brief.v1",
        "operating_core": _copy(dict(operating_core), "operating_core"),
        "context": _copy(dict(context), "context"),
        "resource_resolution": resolved,
        "authority": {"execution": False, "owner_write": False, "dispatch": False},
    }
    if reader is not None:
        body["instruction_content"] = [
            _copy(item["content"], "resource.content")
            for item in resolved["resources"]
            if isinstance(item, Mapping) and item.get("content") is not None
        ]
    if resource_adoption is not None:
        body["resource_adoption"] = _copy(resource_adoption)
    if instruction_contract is not None:
        body["instruction_contract"] = normalize_instruction_contract(instruction_contract)
    body["brief_sha256"] = _digest(body)
    body["idempotency_key"] = "otto-role-brief-" + body["brief_sha256"]
    return body


def brief_resource_evidence(brief: Mapping[str, Any], *, delivery_state: str = "prepared", native_identity: str | None = None) -> dict[str, Any]:
    """Project brief pins into existing attempt/custody evidence."""

    if not isinstance(brief, Mapping) or brief.get("schema") != "otto.orchestrator.role_brief.v1":
        raise ResourceSyncError("brief is not a role brief")
    observed = _text(brief.get("brief_sha256"), "brief_sha256")
    body = _copy(dict(brief), "brief")
    body.pop("brief_sha256", None)
    body.pop("idempotency_key", None)
    if observed != _digest(body):
        raise ResourceSyncError("brief digest is internally inconsistent")
    resolution = brief.get("resource_resolution")
    if not isinstance(resolution, Mapping):
        raise ResourceSyncError("brief has no resource resolution")
    state = _text(delivery_state, "delivery_state").lower()
    if state not in DELIVERY_STATES:
        raise ResourceSyncError("delivery_state is unsupported")
    native = None if native_identity is None else _text(native_identity, "native_identity")
    return {
        "schema": "otto.orchestrator.resource_evidence.v1",
        "brief_sha256": observed,
        "brief": body,
        "resource_set_digest": _text(resolution.get("resource_set_digest"), "resource_set_digest"),
        "export_manifest_digest": _text(resolution.get("export_manifest_digest"), "export_manifest_digest"),
        "resource_revisions": [
            {"name": item["resource_name"], "resource_ref": _copy(item["resource_ref"]), "adopted_revision": item["adopted_revision"], "required": item["required"], "bundle_digest": item["bundle_digest"]}
            for item in resolution.get("resources", ()) if isinstance(item, Mapping)
        ],
        "resources": [_copy(item) for item in resolution.get("resources", ()) if isinstance(item, Mapping)],
        "role": _text(resolution.get("role"), "resource.role"),
        "responsibility_ref": _ref(resolution.get("responsibility_ref"), "resource.responsibility_ref"),
        "generation": resolution.get("generation"),
        "lifecycle": _text(resolution.get("lifecycle"), "resource.lifecycle"),
        "delivery_state": state,
        "native_identity": native,
    }


def validate_resource_evidence(value: Mapping[str, Any], *, role: str | None = None, responsibility_ref: Mapping[str, Any] | None = None, generation: int | None = None) -> dict[str, Any]:
    """Validate evidence already recorded by an outgoing attempt."""

    if not isinstance(value, Mapping) or value.get("schema") != "otto.orchestrator.resource_evidence.v1":
        raise ResourceSyncError("resource evidence has an unsupported schema")
    result = _copy(dict(value), "resource_evidence")
    _text(result.get("brief_sha256"), "resource_evidence.brief_sha256")
    _text(result.get("resource_set_digest"), "resource_evidence.resource_set_digest")
    _text(result.get("export_manifest_digest"), "resource_evidence.export_manifest_digest")
    resources = result.get("resources")
    if isinstance(resources, (str, bytes)) or not isinstance(resources, Sequence):
        raise ResourceSyncError("resource evidence has no resource inventory")
    resources_value = [_copy(item, "resource_evidence.resource") for item in resources]
    if _digest(resources_value) != result["resource_set_digest"]:
        raise ResourceSyncError("resource evidence resource digest is inconsistent")
    if _digest([item.get("export_manifest_digest") for item in resources_value]) != result["export_manifest_digest"]:
        raise ResourceSyncError("resource evidence export digest is inconsistent")
    brief = result.get("brief")
    if not isinstance(brief, Mapping):
        raise ResourceSyncError("resource evidence has no immutable brief")
    brief_body = _copy(dict(brief), "resource_evidence.brief")
    brief_resolution = brief_body.get("resource_resolution")
    if not isinstance(brief_resolution, Mapping):
        raise ResourceSyncError("resource evidence brief has no resource resolution")
    if brief_resolution.get("resources") != resources_value:
        raise ResourceSyncError("resource evidence inventory does not match the immutable brief")
    if brief_resolution.get("resource_set_digest") != result["resource_set_digest"] or brief_resolution.get("export_manifest_digest") != result["export_manifest_digest"]:
        raise ResourceSyncError("resource evidence digests do not match the immutable brief")
    if _digest(brief_body) != result["brief_sha256"]:
        raise ResourceSyncError("resource evidence brief digest is inconsistent")
    observed_role = _text(result.get("role"), "resource_evidence.role").lower()
    if observed_role not in ROLES:
        raise ResourceSyncError("resource evidence role is unsupported")
    if role is not None and observed_role != role:
        raise ResourceSyncError("resource evidence role does not match the attempt")
    observed_ref = _ref(result.get("responsibility_ref"), "resource_evidence.responsibility_ref")
    if responsibility_ref is not None and observed_ref != _ref(responsibility_ref, "expected_responsibility_ref"):
        raise ResourceSyncError("resource evidence responsibility does not match the attempt")
    observed_generation = result.get("generation")
    if not isinstance(observed_generation, int) or isinstance(observed_generation, bool) or observed_generation < 1:
        raise ResourceSyncError("resource evidence generation is invalid")
    if generation is not None and observed_generation != generation:
        raise ResourceSyncError("resource evidence generation does not match the attempt")
    lifecycle = _text(result.get("lifecycle"), "resource_evidence.lifecycle").lower()
    if lifecycle not in LIFECYCLES:
        raise ResourceSyncError("resource evidence lifecycle is unsupported")
    delivery = _text(result.get("delivery_state"), "resource_evidence.delivery_state").lower()
    if delivery not in DELIVERY_STATES:
        raise ResourceSyncError("resource evidence delivery state is unsupported")
    brief_role = _text(brief_resolution.get("role"), "resource_evidence.brief.role").lower()
    brief_ref = _ref(brief_resolution.get("responsibility_ref"), "resource_evidence.brief.responsibility_ref")
    if brief_role != observed_role or _identity(brief_ref) != _identity(observed_ref) or brief_resolution.get("generation") != observed_generation or brief_resolution.get("lifecycle") != lifecycle:
        raise ResourceSyncError("resource evidence outer identity does not match the immutable brief")
    summaries = result.get("resource_revisions")
    expected_summaries = [
        {"name": item["resource_name"], "resource_ref": _copy(item["resource_ref"]), "adopted_revision": item["adopted_revision"], "required": item["required"], "bundle_digest": item["bundle_digest"]}
        for item in resources_value
    ]
    if summaries != expected_summaries:
        raise ResourceSyncError("resource evidence revision summary is inconsistent")
    for item in resources_value:
        attachment = normalize_attachment(item, role=observed_role)
        if _identity(attachment.responsibility_ref) != _identity(observed_ref) or attachment.resource_ref.get("revision") != attachment.adopted_revision:
            raise ResourceSyncError("resource evidence attachment identity is not pinned")
        _text(item.get("entrypoint"), "resource_evidence.entrypoint")
        _text(item.get("bundle_digest"), "resource_evidence.bundle_digest")
        _text(item.get("export_manifest_digest"), "resource_evidence.export_manifest_digest")
    return result


__all__ = [
    "DELIVERY_STATES", "LIFECYCLES", "ROLES", "ResourceAttachment", "ResourceSyncError",
    "brief_resource_evidence", "compose_role_brief", "normalize_attachment", "normalize_role_attachments", "normalize_instruction_contract",
    "resolve_role_attachments", "resolve_role_resources", "role_resource_pins", "validate_resource_evidence",
    "resolve_assignment_attachments",
]
