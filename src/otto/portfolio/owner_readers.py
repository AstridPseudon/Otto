"""Identity-fenced current-record readers shared by manager and role views.

These functions compose existing finite Herzchen readers. They create no
owner state and accept no Store, writer, adapter, or provider.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping


class OwnerRoleRuntimeError(ValueError):
    """The trusted owner runtime cannot establish a current role operation."""


def json_value(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return json_value(value.to_dict())
    if hasattr(value, "value"):
        return json_value(value.value)
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def owner_ref(value: Any, field: str, *, revision: bool = True) -> dict[str, Any]:
    item = json_value(value)
    if not isinstance(item, Mapping) or not all(
        isinstance(item.get(key), str) and item[key]
        for key in ("authority", "kind", "id")
    ):
        raise OwnerRoleRuntimeError(f"{field} must be a complete owner reference")
    result = {key: item[key] for key in ("authority", "kind", "id")}
    if revision:
        if not isinstance(item.get("revision"), str) or not item["revision"]:
            raise OwnerRoleRuntimeError(f"{field} must be pinned to an owner revision")
        result["revision"] = item["revision"]
    elif item.get("revision") is not None:
        raise OwnerRoleRuntimeError(f"{field} current lookup must be identity-only")
    return result


def _resource_ref(value: Mapping[str, Any]) -> Any:
    from herzchen.contracts import ResourceRef

    return ResourceRef.from_dict(value)


def project_reader(operations: Any, project_pin: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], Any]:
    """Read only the pinned project identity, returning its fresh revision."""
    expected = owner_ref(project_pin, "project_ref")

    def read(identity: Mapping[str, Any]) -> Mapping[str, Any]:
        current = owner_ref(identity, "project lookup", revision=False)
        if current != {key: expected[key] for key in ("authority", "kind", "id")}:
            raise OwnerRoleRuntimeError("project lookup escaped the pinned identity")
        record = operations.reader.get_record(_resource_ref(current))
        if record is None:
            raise OwnerRoleRuntimeError("current project is missing")
        return {
            "ref": json_value(record.ref),
            "lifecycle": json_value(record.payload.get("lifecycle")),
            "payload": json_value(record.payload),
        }

    return read


def task_reader(
    operations: Any,
    project_pin: Mapping[str, Any],
    task_pin: Mapping[str, Any],
) -> Callable[[Mapping[str, Any]], Any]:
    """Read one pinned task and verify its owner-backed project parent."""
    expected_task = owner_ref(task_pin, "task_ref")
    project_read = project_reader(operations, project_pin)

    def read(identity: Mapping[str, Any]) -> Mapping[str, Any]:
        current = owner_ref(identity, "task lookup", revision=False)
        if current != {key: expected_task[key] for key in ("authority", "kind", "id")}:
            raise OwnerRoleRuntimeError("task lookup escaped the pinned identity")
        record = operations.reader.get_record(_resource_ref(current))
        if record is None:
            raise OwnerRoleRuntimeError("current task is missing")
        parent = json_value(record.payload.get("project_ref"))
        parent_ref = owner_ref(
            parent, "task.project_ref",
            revision=isinstance(parent, Mapping) and parent.get("revision") is not None,
        )
        # Stored parent revisions establish membership; current reads use the
        # validated identity and retain project_read's trusted identity fence.
        parent_identity = {key: parent_ref[key] for key in ("authority", "kind", "id")}
        project = project_read(parent_identity)
        return {
            "ref": json_value(record.ref),
            "project_ref": project["ref"],
            "lifecycle": json_value(record.payload.get("lifecycle")),
            "payload": json_value(record.payload),
        }

    return read


def completed_occurrence_task_reader(reader: Any, due: Any, assignment: Any) -> Any:
    """Inspect a settled delivery's exact committed completion input only.

    This reader cannot prepare an effect: callers use it solely for readiness
    of an already succeeded occurrence. Prospective/native invocation readers
    retain current-revision fences.
    """
    import hashlib
    import json
    from herzchen.contracts import ResourceRef
    task = ResourceRef.from_dict(due.target["task_ref"])
    current = reader.get_identity(ResourceRef(task.authority, task.kind, task.id))
    if current is None or current.ref == task:
        return None
    completion = current.payload.get("completion") or {}
    key = completion.get("logical_request_key")
    receipt = reader.get_receipt(key) if isinstance(key, str) else None
    attempt = due.host_evidence.get("gateway_attempt") if isinstance(due.host_evidence, Mapping) else None
    attempt = attempt if isinstance(attempt, Mapping) else {}
    result, authorization, admission = (attempt.get(name) or {} for name in ("result", "delivery_authorization", "delivery_admission"))
    resource = result.get("resource_evidence") or {}
    brief = resource.get("brief")
    digest = None if not isinstance(brief, Mapping) else hashlib.sha256(json.dumps(json_value(brief),
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assignment_ref = json_value(assignment.ref)
    if (due.role != "manager" or due.completion_state != "succeeded" or due.stop_state != "completed"
            or due.in_flight_request is not None or assignment_ref != due.assignment_ref
            or assignment.generation != due.generation or assignment.principal != due.recipient
            or current.payload.get("lifecycle") != "completed" or completion.get("task_ref") != task.to_dict()
            or completion.get("assignment_ref") != assignment_ref or completion.get("generation") != due.generation
            or completion.get("manager") != due.recipient
            or receipt is None or receipt.status.value != "committed" or receipt.operation != "work.revise"
            or receipt.target != task or receipt.result_ref != current.ref
            or result.get("outcome") != "succeeded" or result.get("context_digest_verified") is not True
            or any(result.get(k) != v for k,v in (("assignment_ref",assignment_ref),("generation",due.generation),
                ("task_ref",task.to_dict()),("project_ref",due.target["project_ref"])))
            or admission.get("native_turn_started") is not True
            or admission.get("physical_session_id") != result.get("physical_session_id")
            or admission.get("observed_turn_id") != result.get("observed_turn_id")
            or digest is None or digest != resource.get("brief_sha256") or digest != authorization.get("brief_sha256")):
        raise OwnerRoleRuntimeError("settled readiness lacks exact delivered completion predecessor")
    historical = ((brief.get("context") or {}).get("project_state") or {}).get("task") or {}
    if historical.get("ref") != task.to_dict() or not isinstance(historical.get("payload"), Mapping):
        raise OwnerRoleRuntimeError("settled readiness completion input is unavailable in delivered snapshot")
    parent = historical["payload"].get("project_ref") or {}
    if any(parent.get(k) != due.target["project_ref"].get(k) for k in ("authority","kind","id")):
        raise OwnerRoleRuntimeError("settled readiness task belongs to another project")
    def read(identity):
        if owner_ref(identity, "historical task lookup", revision=False) != {
                k:task.to_dict()[k] for k in ("authority","kind","id")}:
            raise OwnerRoleRuntimeError("settled readiness escaped its completion input")
        return {"ref":task.to_dict(),"project_ref":due.target["project_ref"],
            "lifecycle":historical["payload"].get("lifecycle"),"payload":json_value(historical["payload"])}
    read.completion_readback = {"scope":"settled_delivery_completion_input", "effect_admission":False,
        "delivered_task_ref":task.to_dict(),"current_completed_task_ref":json_value(current.ref),
        "completion_request_key":key}
    return read


def assignment_reader(operations: Any, assignment_pin: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], Any]:
    """Read the exact assignment through its existing finite owner port."""
    expected = owner_ref(assignment_pin, "assignment_ref")

    def read(identity: Mapping[str, Any]) -> Mapping[str, Any]:
        current = owner_ref(identity, "assignment lookup", revision=False)
        if current != {key: expected[key] for key in ("authority", "kind", "id")}:
            raise OwnerRoleRuntimeError("assignment lookup escaped the pinned identity")
        assignment = operations.assignments_port.get(_resource_ref(current))
        return operations._assignment_dict(assignment)

    return read


def mandate_reader(
    operations: Any,
    project_pin: Mapping[str, Any],
    mandate_pin: Mapping[str, Any],
) -> Callable[[Mapping[str, Any]], Any]:
    """Read one exact current adopted mandate document under its project."""
    expected = owner_ref(mandate_pin, "mandate_ref")

    def read(identity: Mapping[str, Any]) -> Mapping[str, Any]:
        current_identity = owner_ref(identity, "mandate lookup", revision=False)
        if current_identity != {key: expected[key] for key in ("authority", "kind", "id")}:
            raise OwnerRoleRuntimeError("mandate lookup escaped the adopted document identity")
        observed = operations.content_port.read(_resource_ref(current_identity))
        document = json_value(observed.get("document")) if isinstance(observed, Mapping) else None
        revision = json_value(observed.get("revision")) if isinstance(observed, Mapping) else None
        if not isinstance(document, Mapping) or not isinstance(revision, Mapping):
            raise OwnerRoleRuntimeError("adopted mandate document/revision is unavailable")
        owner = document.get("maintainer")
        authoring_scope = json_value(document.get("authoring_scope"))
        scope = owner_ref(authoring_scope, "mandate.authoring_scope")
        project = owner_ref(project_pin, "project_ref")
        if document.get("role") != "mandate" or any(
            scope[key] != project[key] for key in ("authority", "kind", "id")
        ):
            raise OwnerRoleRuntimeError("adopted document is not a project-scoped mandate")
        if not isinstance(owner, str) or not owner.strip():
            raise OwnerRoleRuntimeError("mandate document has no owner custody")
        revision_name = revision.get("revision")
        current_revision = json_value(observed.get("current_revision")) if isinstance(observed, Mapping) else None
        if (
            revision_name != expected["revision"]
            or not isinstance(current_revision, Mapping)
            or current_revision.get("revision") != expected["revision"]
        ):
            raise OwnerRoleRuntimeError("adopted mandate revision is stale")
        content = revision.get("content")
        if not isinstance(content, Mapping):
            raise OwnerRoleRuntimeError("adopted mandate content is malformed")
        return {
            "ref": {**current_identity, "revision": revision_name},
            "role": content.get("role"),
            "document_role": "mandate",
            "scope_ref": authoring_scope,
            "status": content.get("status"),
            "brief": content.get("brief"),
            "payload": dict(content),
            "document_owner": owner,
        }

    return read


__all__ = [
    "OwnerRoleRuntimeError", "assignment_reader", "json_value", "mandate_reader",
    "owner_ref", "project_reader", "task_reader",
]
