"""Inert setup composition over existing role, DAT and Due operations.

Input selects existing canonical assignments or schedules; it never creates
roles, adopts directions, grants budgets or starts a provider. One immutable
DAT request pins a partial apply. Due receipts retain each prepared role and
the existing setup document remains the sole setup authority.
"""
from __future__ import annotations

from typing import Any, Mapping

from herzchen.contracts import ResourceRef, TransactionContext
from herzchen.content import ContentDocument, ContentRevision
from .execution import _digest, _identity, _text
from .operating_setup import OperatingSetupError, evaluate_setup, normalize_setup, setup_reference
from .owner_readers import json_value, owner_ref, project_reader

SCHEMA = "otto.operating-composition.v1"
DEFAULT_FIELDS = {"model", "reasoning", "timeout_seconds"}
ROLE_FIELDS = {"assignment_ref", "generation", "task_ref", "mandate_ref", "context_refs",
               "instruction", "model", "reasoning", "profile", "native_session_id",
               "binding_schedule_id", "allowance_ref", "timeout_seconds"}


def _normalize(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OperatingSetupError("setup must be an object")
    if value.get("schema") == "otto.operating-setup.v1":
        return normalize_setup(value)
    if value.get("schema") != SCHEMA or set(value) - {
            "schema", "mode", "roles", "advisor_policy", "acceptance_tasks", "defaults"}:
        raise OperatingSetupError("setup requires otto.operating-composition.v1 or otto.operating-setup.v1")
    result = json_value(value)
    defaults = result.get("defaults", {})
    if not isinstance(defaults, Mapping) or set(defaults) - DEFAULT_FIELDS:
        raise OperatingSetupError("defaults select only model, reasoning and timeout_seconds")
    roles = result.get("roles")
    if not isinstance(roles, Mapping):
        raise OperatingSetupError("roles must select existing schedules or assignment bindings")
    for role, spec in roles.items():
        if isinstance(spec, str):
            _text(spec, "schedule_id")
            continue
        if (not isinstance(spec, Mapping) or set(spec) - ROLE_FIELDS
                or not {"assignment_ref", "generation", "task_ref", "mandate_ref"} <= set(spec)):
            raise OperatingSetupError("role binding requires assignment_ref, generation, task_ref and mandate_ref")
        if isinstance(spec["generation"], bool) or not isinstance(spec["generation"], int) or spec["generation"] < 1:
            raise OperatingSetupError("generation must be a positive integer")
        for field, kind in (("assignment_ref", "wrk.assignment"), ("task_ref", "work.task"),
                            ("mandate_ref", "dat.content.document")):
            pin = owner_ref(spec[field], field)
            if pin["kind"] != kind:
                raise OperatingSetupError(field + " has the wrong kind")
    # Share the policy/role/task definition with readiness rather than define
    # another domain validator for composition.
    normalize_setup({"schema": "otto.operating-setup.v1", "mode": result.get("mode"),
        "roles": {role: spec if isinstance(spec, str) else "preview-" + role for role, spec in roles.items()},
        "advisor_policy": result.get("advisor_policy"), "acceptance_tasks": result.get("acceptance_tasks")})
    return result


def _owned_document(app: Any, ref: ResourceRef, project: Mapping[str, Any], role: str) -> dict[str, Any]:
    observed = json_value(app.portfolio.operations.content_port.read(ref))
    if observed:
        # Immutable DAT revision reads carry a document *identity*, while
        # the current head carries its ownership descriptor.
        identity = ResourceRef(ref.authority, ref.kind, ref.id)
        head = observed if ref.revision is None else json_value(app.portfolio.operations.content_port.read(identity))
        doc = head.get("document") or {}
        scope = doc.get("authoring_scope") or {}
        if (doc.get("role") != role or doc.get("maintainer") != app.actor
                or any(scope.get(k) != project[k] for k in ("authority", "kind", "id"))
                or doc.get("import_mode", "owned") != "owned" or doc.get("writable", True) is not True):
            raise PermissionError("setup document is outside current owner custody")
    return observed


def _create(app: Any, ref: ResourceRef, project: Mapping[str, Any], role: str,
            content: Mapping[str, Any], key: str, revision: str) -> Mapping[str, Any]:
    actor = app.binding.authenticated_actor(app.actor)
    document = ContentDocument(ref, role, "private", "append", app.actor, ResourceRef.from_dict(project))
    initial = ContentRevision(ref, revision, content, actor, initial=True)
    context = TransactionContext(actor, key, _digest(content), expected_version=0)
    port = app.portfolio.operations.content_port
    return json_value(port.execute(port.build_create_document(context, document, initial)))


def compose_setup(app: Any, *, project_ref: Mapping[str, Any], operation: str,
                  setup: Mapping[str, Any], request_key: str,
                  expected_setup_ref: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Preview actual records, then apply or CAS-update one selected project.

    Composition input has mode/advisor_policy/acceptance_tasks plus roles, each
    an existing schedule ID or prepare_role's exact assignment/task/mandate
    pins. defaults supplies model/reasoning/timeout; role fields override it.
    Omitted model/session/context values follow prepare_role's adopted sources.
    Return the same request_key/input after a partial effect; never dispatch.
    """
    if operation not in {"preview", "apply", "update"}:
        raise OperatingSetupError("composition operation must be preview, apply or update")
    project = owner_ref(project_ref, "project_ref")
    if project["kind"] != "work.project":
        raise OperatingSetupError("setup requires a project")
    _text(request_key, "request_key")
    value = _normalize(setup)
    current = project_reader(app.portfolio.operations, project)(_identity(project))
    if current["ref"] != project:
        raise OperatingSetupError("operating setup project revision is stale")
    ref = setup_reference(project)
    expected = None if expected_setup_ref is None else owner_ref(expected_setup_ref, "expected_setup_ref")
    if expected is not None and _identity(expected) != _identity(ref.to_dict()):
        raise OperatingSetupError("expected_setup_ref selects another setup")
    if (operation == "update" and expected is None or operation == "apply" and expected is not None):
        raise OperatingSetupError("update requires expected_setup_ref; apply requires an absent setup")
    request = {"project_ref": project, "setup": value, "expected_setup_ref": expected,
               "operation": "update" if expected is not None else "apply"}
    journal_ref = ResourceRef(project["authority"], "dat.content.document",
        "setup-request-" + _digest([project, request_key])[:28])
    journal_pin = ResourceRef(journal_ref.authority, journal_ref.kind, journal_ref.id, "rev-1")
    journal = _owned_document(app, journal_pin, project, "operating_setup_request")
    if journal and journal["content"] != request:
        raise OperatingSetupError("request key was reused with changed setup input")
    revision = "rev-setup-" + _digest([project, request_key])[:28]
    result_ref = ResourceRef(ref.authority, ref.kind, ref.id, revision)
    retained = _owned_document(app, result_ref, project, "operating_setup") if journal else {}
    if retained:
        receipt = app.portfolio.operations.read_document_receipt(project_ref=project, document_ref=ref.to_dict(),
            request_id=request_key + ":setup", actor=app.actor)
        if (not receipt or receipt.get("status") != "committed"
                or receipt.get("result_ref") != result_ref.to_dict()):
            raise OperatingSetupError("retained setup lacks its exact committed receipt")
        head = _owned_document(app, ref, project, "operating_setup")
        return {"outcome": "replayed", "setup_ref": result_ref.to_dict(),
                "current_setup_ref": head["current_revision"], "setup": retained["content"],
                "receipt": receipt, "provider_called": False, "dispatch": False, "retry": False}
    observed = _owned_document(app, ref, project, "operating_setup")
    if expected is None and observed:
        raise OperatingSetupError("setup already exists; update with its exact setup_ref")
    if expected is not None and (not observed or observed["current_revision"] != expected):
        raise OperatingSetupError("operating setup revision is stale")
    candidates, requests, roles = {}, {}, {}
    for role, spec in value["roles"].items():
        if isinstance(spec, str):
            roles[role] = spec
            continue
        role_request = {**value.get("defaults", {}), **spec, "role": role,
                        "project_ref": project, "request_key": request_key + ":role:" + role}
        role_request.setdefault("profile", "workspace-write" if role == "manager" else "read-only")
        prepared = app.prepare_role(**role_request, preview=True)
        roles[role] = prepared["schedule_id"]
        candidates[prepared["schedule_id"]] = prepared["due"]
        requests[role] = role_request
    config = normalize_setup({"schema": "otto.operating-setup.v1", "mode": value["mode"],
        "roles": roles, "advisor_policy": value["advisor_policy"], "acceptance_tasks": value["acceptance_tasks"]})
    decision = evaluate_setup(app.runtime, project, config, due_overrides=candidates)
    # Do not settle, rewrite, or replace an uncertain existing effect in a
    # setup operation. Occurrence reconciliation has its own supported path.
    for role, schedule in roles.items():
        due = app.due_port.read_due(schedule)
        attempt = (due.get("host_evidence") or {}).get("gateway_attempt") if due else None
        unsettled = attempt is not None and (due.get("completion_state") != "succeeded"
            or due.get("in_flight_request") is not None
            or (attempt.get("result") or {}).get("outcome") != "succeeded")
        if due and (unsettled or due.get("completion_state") == "unknown"
                    or due.get("host_state") == "paused" or due.get("stop_state") == "stopped"):
            decision["blockers"].append({"role": role, "code": "retained_effect_held",
                "message": "inspect/reconcile the exact retained occurrence before changing setup"})
            decision["ready"] = False
            decision["autonomous_ready"] = False
            decision["state"] = "blocked"
            decision["capabilities"]["advisor"] = False
            decision["capabilities"]["advice"] = False
            if config["advisor_policy"]["mode"] == "enabled":
                decision["help"]["advice"]["state"] = "blocked"
    base = {"schema": SCHEMA, "project_ref": project, "setup": config, "readiness": decision,
            "expected_setup_ref": expected, "request_key": request_key,
            "provider_called": False, "dispatch": False, "retry": False}
    if not decision["ready"]:
        return {**base, "outcome": "blocked"}
    if operation == "preview":
        return {**base, "outcome": "preview", "records": decision["roles"],
                "next_action": "apply or update with this request_key and unchanged input"}
    handles: dict[str, Any] = {}
    stage = "request"
    try:
        if not journal:
            _create(app, journal_ref, project, "operating_setup_request", request, request_key + ":request", "rev-1")
        handles["request_ref"] = {**journal_ref.to_dict(), "revision": "rev-1"}
        for role, role_request in requests.items():
            stage = "role:" + role
            raw = app.due_port.read_due(roles[role])
            if raw and raw["assignment_ref"] == role_request["assignment_ref"]:
                handles[role] = {"outcome": "replayed", "schedule_id": roles[role], "due_version": raw["version"]}
            else:
                handles[role] = app.prepare_role(**role_request)
            if handles[role]["outcome"] not in {"committed", "prepared", "replayed"}:
                return {**base, "outcome": "partial", "stage": stage, "handles": handles,
                        "next_action": "inspect handles; resume with the same request_key and input"}
        stage = "setup"
        # Recheck actual role records after partial preparation. Preview data
        # is never persisted as substitute evidence for canonical readback.
        decision = evaluate_setup(app.runtime, project, config)
        if not decision["ready"]:
            return {**base, "outcome": "partial", "stage": stage, "handles": handles, "readiness": decision}
        if expected is None:
            receipt = _create(app, ref, project, "operating_setup", config, request_key + ":setup", revision)
        else:
            document = ContentDocument.from_dict(observed["document"])
            actor = app.binding.authenticated_actor(app.actor)
            updated = ContentRevision(ref, revision, config, actor, parent_revision=expected["revision"])
            context = TransactionContext(actor, request_key + ":setup", _digest(request),
                                         expected_revision=expected["revision"])
            port = app.portfolio.operations.content_port
            receipt = json_value(port.execute(port.build_append_revision(context, document, updated)))
        return {**base, "outcome": "applied" if expected is None else "updated", "handles": handles,
                "setup_ref": result_ref.to_dict(), "receipt": receipt, "readiness": decision,
                "next_action": "read operating-setup; activation remains a separate admitted operation"}
    except Exception as exc:
        return {**base, "outcome": "partial", "stage": stage, "handles": handles,
                "error": {"code": type(exc).__name__, "message": str(exc)},
                "next_action": "inspect retained handles; resume only this request_key with unchanged input"}
