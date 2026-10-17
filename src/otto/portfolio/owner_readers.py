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


_PROJECT_SETUP_FIELDS = (
    "title", "name", "outcome", "scope", "approach", "acceptance",
    "protocol", "resources", "criteria", "custom", "fields", "tasks",
    "metadata", "metadata_namespaces", "documents", "document_links",
)


def _project_setup_content(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Authored project content; task revision pointers are only roster links."""
    content = {key: json_value(payload.get(key)) for key in _PROJECT_SETUP_FIELDS}
    fields = content["fields"]
    if isinstance(fields, Mapping):
        # Reviewed activation writes this owner marker after setup preparation.
        content["fields"] = {key: value for key, value in fields.items()
                             if key != "reviewed_activation"}
    elif fields is None:
        content["fields"] = {}
    tasks = content["tasks"]
    if isinstance(tasks, list):
        identities = [
            {key: task.get(key) for key in ("authority", "kind", "id")}
            if isinstance(task, Mapping) else task for task in tasks
        ]
        content["tasks"] = sorted(identities, key=lambda task: str(task))
    return content


def _pin_content_proof(operations: Any, expected: Mapping[str, Any],
                       current_ref: Mapping[str, Any], current_payload: Mapping[str, Any],
                       *, project: bool = False) -> tuple[bool, list[str]]:
    """Compare an exact retained owner revision with a current owner payload."""
    if current_ref == expected:
        return True, []
    retained = operations.reader.get_revision(_resource_ref(expected))
    if retained is None or json_value(retained.ref) != expected or not isinstance(retained.payload, Mapping):
        return False, ["retained_revision"]
    before = (_project_setup_content(retained.payload) if project else json_value(retained.payload))
    after = (_project_setup_content(current_payload) if project else json_value(current_payload))
    changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    return not changed, changed


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
        observed_ref = json_value(record.ref)
        matches, changed = _pin_content_proof(operations, expected, observed_ref, record.payload, project=True)
        return {
            "ref": observed_ref,
            "lifecycle": json_value(record.payload.get("lifecycle")),
            "payload": json_value(record.payload),
            "project_pin_content_matches": matches,
            "project_pin_changed_fields": changed,
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
        from herzchen.domains.work import admission
        try:
            pin_content_matches = admission.task_content_matches(
                operations.reader, _resource_ref(expected_task), record.payload,
                current_ref=record.ref)
        except (AttributeError, KeyError, LookupError, TypeError, ValueError):
            pin_content_matches = False
        return {
            "ref": json_value(record.ref),
            "project_ref": project["ref"],
            "lifecycle": json_value(record.payload.get("lifecycle")),
            "payload": json_value(record.payload),
            "task_pin_content_matches": pin_content_matches,
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
            or current.payload.get("lifecycle") != "completed"
            or completion.get("assignment_ref") != assignment_ref or completion.get("generation") != due.generation
            or completion.get("manager") != due.recipient
            or receipt is None or receipt.status.value != "committed" or receipt.operation != "work.revise"
            or receipt.result_ref != current.ref
            or result.get("outcome") != "succeeded" or result.get("context_digest_verified") is not True
            or any(result.get(k) != v for k,v in (("assignment_ref",assignment_ref),("generation",due.generation),
                ("task_ref",task.to_dict()),("project_ref",due.target["project_ref"])))
            or admission.get("native_turn_started") is not True
            or admission.get("physical_session_id") != result.get("physical_session_id")
            or admission.get("observed_turn_id") != result.get("observed_turn_id")
            or digest is None or digest != resource.get("brief_sha256") or digest != authorization.get("brief_sha256")):
        raise OwnerRoleRuntimeError("settled readiness lacks exact delivered completion predecessor")
    historical = ((brief.get("context") or {}).get("project_state") or {}).get("task") or {}
    if (historical.get("ref") != task.to_dict()
            or not isinstance(historical.get("payload"), Mapping)):
        raise OwnerRoleRuntimeError("settled readiness completion input is unavailable in delivered snapshot")
    # The committed work.revise receipt names the task revision whose content
    # the manager actually accepted. Resolve that exact retained predecessor,
    # then compare the delivery pin and the delivered snapshot to it. Rehashing
    # a forged brief cannot substitute different authored instructions.
    try:
        predecessor_ref_value = owner_ref(completion.get("task_ref"), "completion predecessor")
    except OwnerRoleRuntimeError as exc:
        raise OwnerRoleRuntimeError("settled readiness completion predecessor is unavailable") from exc
    if any(predecessor_ref_value.get(k) != task.to_dict().get(k) for k in ("authority", "kind", "id")):
        raise OwnerRoleRuntimeError("settled readiness completion predecessor is another task")
    predecessor = reader.get_revision(ResourceRef.from_dict(predecessor_ref_value))
    if (predecessor is None or json_value(predecessor.ref) != predecessor_ref_value
            or receipt.target != predecessor.ref):
        raise OwnerRoleRuntimeError("settled readiness completion predecessor is unavailable")
    from herzchen.domains.work.admission import task_content_matches
    predecessor_ref = ResourceRef.from_dict(json_value(predecessor.ref))
    if (not task_content_matches(reader, task, predecessor.payload, current_ref=predecessor_ref)
            or not task_content_matches(reader, task, historical["payload"])):
        raise OwnerRoleRuntimeError("settled readiness delivered task content differs from completion predecessor")
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
        result = operations._assignment_dict(assignment)
        if result["ref"] == expected:
            matches, changed = True, []
        else:
            # Assignment revisions are not retained as Work snapshots. Its
            # adopted-resource event carries the exact owner result payload.
            event_reader = getattr(operations, "_owner_reader", None)
            events = () if event_reader is None else event_reader.list_events(stream="assignment:" + expected["id"])
            retained = [event.effects.get("result_payload") for event in events
                        if json_value(event.subject) == expected
                        and event.operation == "work.assignment.adopt-resources"
                        and isinstance(event.effects.get("result_payload"), Mapping)]
            if len(retained) != 1:
                matches, changed = False, ["retained_revision"]
            else:
                before, after = json_value(retained[0]), json_value(assignment.payload)
                changed = sorted(key for key in before.keys() | after.keys()
                                 if before.get(key) != after.get(key))
                matches = not changed
        return {**result, "assignment_pin_content_matches": matches,
                "assignment_pin_changed_fields": changed}

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
        if (not isinstance(revision_name, str) or not isinstance(current_revision, Mapping)
                or current_revision.get("revision") != revision_name):
            raise OwnerRoleRuntimeError("adopted mandate current revision is unreadable")
        content = revision.get("content")
        if not isinstance(content, Mapping):
            raise OwnerRoleRuntimeError("adopted mandate content is malformed")
        matches = True
        changed: list[str] = []
        if revision_name != expected["revision"]:
            retained = operations.content_port.read(_resource_ref(expected))
            old_content = json_value(retained.get("content")) if isinstance(retained, Mapping) else None
            if (not isinstance(old_content, Mapping) or retained.get("revision") != expected["revision"]):
                matches, changed = False, ["retained_revision"]
            else:
                changed = sorted(key for key in old_content.keys() | content.keys()
                                 if old_content.get(key) != content.get(key))
                matches = not changed
        return {
            "ref": {**current_identity, "revision": revision_name},
            "role": content.get("role"),
            "document_role": "mandate",
            "scope_ref": authoring_scope,
            "status": content.get("status"),
            "brief": content.get("brief"),
            "payload": dict(content),
            "document_owner": owner,
            "mandate_pin_content_matches": matches,
            "mandate_pin_changed_fields": changed,
        }

    return read


__all__ = [
    "OwnerRoleRuntimeError", "assignment_reader", "json_value", "mandate_reader",
    "owner_ref", "project_reader", "task_reader",
]
