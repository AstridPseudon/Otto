"""Operating readiness over adopted documents and existing role occurrences.

Preparation is inert. A setup document selects existing handles; it creates
neither roles nor conversations. Execution rechecks the same decision before
the gateway admits a new effect. Retained attempts keep their original pins.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from .owner_readers import json_value, owner_ref


class OperatingSetupError(ValueError):
    """The selected operating setup cannot admit execution."""


def setup_reference(project_ref: Mapping[str, Any]) -> ResourceRef:
    project = owner_ref(project_ref, "project_ref")
    if project["kind"] != "work.project":
        raise OperatingSetupError("operating setup requires a work.project")
    identity = ":".join(project[key] for key in ("authority", "kind", "id"))
    return ResourceRef(project["authority"], "dat.content.document",
                       "operating-setup-" + hashlib.sha256(identity.encode()).hexdigest()[:28])


def read_setup(operations: Any, project_ref: Mapping[str, Any]) -> Mapping[str, Any] | None:
    observed = json_value(operations.content_port.read(setup_reference(project_ref)))
    if not observed:
        return None
    document, revision = observed.get("document"), observed.get("revision")
    if not isinstance(document, Mapping) or not isinstance(revision, Mapping):
        raise OperatingSetupError("operating setup document is unreadable")
    scope = document.get("authoring_scope")
    if (document.get("role") != "operating_setup" or not isinstance(scope, Mapping)
            or any(scope.get(key) != project_ref.get(key) for key in ("authority", "kind", "id"))):
        raise OperatingSetupError("operating setup document is outside the project")
    return normalize_setup(revision.get("content"))


def normalize_setup(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema") != "otto.operating-setup.v1":
        raise OperatingSetupError("operating setup requires schema otto.operating-setup.v1")
    result = json_value(value)
    if set(result) != {"schema", "mode", "roles", "advisor_policy", "acceptance_tasks"}:
        raise OperatingSetupError("operating setup requires mode, roles, advisor_policy and acceptance_tasks")
    if result["mode"] not in {"autonomous", "manual"}:
        raise OperatingSetupError("operating setup mode must be autonomous or manual")
    roles = result["roles"]
    if (not isinstance(roles, Mapping) or "manager" not in roles
            or set(roles) - {"manager", "orchestrator", "project_advisor"}
            or any(not isinstance(v, str) or not v.strip() for v in roles.values())
            or len(set(roles.values())) != len(roles)):
        raise OperatingSetupError("operating setup roles must select distinct existing schedules including manager")
    advisor = result["advisor_policy"]
    if not isinstance(advisor, Mapping) or advisor.get("mode") not in {"enabled", "disabled"}:
        raise OperatingSetupError("advisor policy must be explicitly enabled or disabled")
    if advisor["mode"] == "disabled":
        if (set(advisor) != {"mode", "reason"} or not isinstance(advisor.get("reason"), str)
                or not advisor["reason"].strip() or "project_advisor" in roles):
            raise OperatingSetupError("disabled advisor requires a reason and no advisor schedule")
    elif set(advisor) != {"mode"} or "project_advisor" not in roles:
        raise OperatingSetupError("enabled advisor requires its existing role schedule")
    tasks = result["acceptance_tasks"]
    if not isinstance(tasks, list) or len(tasks) > 256:
        raise OperatingSetupError("acceptance_tasks must be a bounded list of exact task refs")
    result["acceptance_tasks"] = [owner_ref(t, "acceptance task") for t in tasks]
    if any(t["kind"] != "work.task" for t in result["acceptance_tasks"]):
        raise OperatingSetupError("acceptance_tasks must select work.task refs")
    if len({(t["authority"], t["id"]) for t in tasks}) != len(tasks):
        raise OperatingSetupError("acceptance_tasks cannot repeat a task")
    if result["mode"] == "autonomous" and ("orchestrator" not in roles or not tasks):
        raise OperatingSetupError("autonomous setup requires orchestrator and acceptance tasks")
    return result


def validate_execution_contract(prepared: Mapping[str, Any], profile: str, *, execution_manager: bool = False) -> None:
    """Check role/profile agreement using the exact already-resolved contract."""
    from otto.agents.orchestrator_route import _canonical_operation_evidence
    canonical = prepared["canonical_evidence"]
    snapshot = canonical["render"]["snapshot"]
    principal = snapshot["principal"]
    principal = principal if isinstance(principal, str) else principal["id"]
    evidence = _canonical_operation_evidence(prepared, owner=principal, task_ref=snapshot["task_ref"])
    contract = evidence["brief"]["instruction_contract"]
    effect = contract["authority"].get("effect_profile")
    role = canonical["role"]
    if execution_manager and (role != "manager" or effect != "workspace-write-manager"
                              or "mandate_instruction_contract" not in canonical):
        raise OperatingSetupError("execution manager requires an exact active workspace-write-manager mandate")
    if profile not in {"read-only", "workspace-write"}:
        raise OperatingSetupError("execution profile must be read-only or workspace-write")
    if (profile == "workspace-write") != (effect in {"workspace-write-worker", "workspace-write-manager"}):
        raise OperatingSetupError("requested profile conflicts with adopted execution contract")
    if (role == "worker" and effect == "workspace-write-manager"
            and ("canonical_manager_commands" not in contract["allowed_operations"]
                 or "mandate_instruction_contract" not in canonical)):
        raise OperatingSetupError("cold manager operation requires explicit adopted manager command authority")
    if role in {"orchestrator", "project_advisor"} and effect is not None:
        raise OperatingSetupError(role + " cannot use a workspace-write execution contract")


def verify_role_conversation(*, due: Any, assignment: Mapping[str, Any], project_ref: Mapping[str, Any],
                             due_port: Any, actor: str | None, binding_due: Any = None) -> tuple[str, dict[str, Any]]:
    """Read the same exact current/adopted admission proof used by readiness.

    The optional retained pin is one hop, digest checked and owner authenticated;
    a request-provided native ID or pin field alone never establishes authority.
    """
    from otto.attention import DueRecord, native_target_identity
    role = due.role
    native = native_target_identity(due.target)
    principal = assignment["principal"]
    principal_id = principal if isinstance(principal, str) else principal["id"]
    if (not native or (actor is not None and (due.lifecycle_owner != actor or due.manager_ref != actor))
            or due.assignment_ref != assignment["ref"]
            or due.generation != assignment["generation"] or role != assignment["role"]
            or due.recipient != principal_id
            or any(due.target["project_ref"].get(k) != project_ref.get(k) for k in ("authority", "kind", "id"))):
        raise OperatingSetupError("role conversation current assignment/project differs")
    session = assignment.get("payload", {}).get("session")
    bound = session if isinstance(session, str) else native_target_identity(session) if isinstance(session, Mapping) else None
    # A newly prepared continuation has not acquired admission evidence
    # yet. Its current resources/model are checked above; the adopted
    # occurrence retains proof of this same generation's conversation.
    conversation_due = binding_due or due
    proof_pin = due.target.get("native_binding")
    current_attempt = ((binding_due or due).host_evidence or {}).get("gateway_attempt") or {}
    current_admission = current_attempt.get("delivery_admission") or {}
    current_authorization = current_attempt.get("delivery_authorization") or {}
    admitted_current = current_admission.get("native_turn_started") is True
    if admitted_current and (current_authorization.get("status") != "authorized"
            or current_authorization.get("lifecycle_owner") != (binding_due or due).lifecycle_owner):
        raise OperatingSetupError("current native admission is not owner authenticated")
    # Once this exact occurrence has actual admission, its own full
    # authorization below proves the conversation. The prior pin is
    # provenance for preparation, including fresh targets without IDs.
    if bound is None and proof_pin is not None and not admitted_current:
        if not actor:
            raise OperatingSetupError("retained native binding requires authenticated owner read grant")
        import hashlib
        import json
        if not isinstance(proof_pin, Mapping) or set(proof_pin) != {"schedule_id", "due_sha256"}:
            raise OperatingSetupError("native binding requires one exact owner occurrence pin")
        proof = due_port.read_due(proof_pin["schedule_id"])
        proof_digest = hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode()).hexdigest()
        if not isinstance(proof, Mapping) or proof_digest != proof_pin["due_sha256"]:
            raise OperatingSetupError("retained native binding occurrence changed")
        conversation_due = DueRecord.from_dict(proof)
        prior_ref = conversation_due.assignment_ref
        current_ref = due.assignment_ref
        if (any(prior_ref.get(k) != current_ref.get(k) for k in ("authority", "kind", "id"))
                or (prior_ref != current_ref and assignment.get("payload", {}).get("resource_adoption_base_ref") != prior_ref)
                or conversation_due.generation != due.generation or conversation_due.recipient != due.recipient
                or conversation_due.role != role or conversation_due.lifecycle_owner != actor
                or conversation_due.manager_ref != actor
                or native_target_identity(conversation_due.target) != native
                or any(conversation_due.target["project_ref"].get(k) != project_ref.get(k)
                       for k in ("authority", "kind", "id"))):
            raise OperatingSetupError("retained native binding is outside the current adoption/generation")
        proof_attempt = (conversation_due.host_evidence or {}).get("gateway_attempt") or {}
        if ((proof_attempt.get("delivery_admission") or {}).get("native_turn_started") is not True
                or (proof_attempt.get("delivery_authorization") or {}).get("status") != "authorized"):
            raise OperatingSetupError("retained native binding lacks actual authenticated admission")
    attempt = (conversation_due.host_evidence or {}).get("gateway_attempt") or {}
    admission = attempt.get("delivery_admission") or {}
    authorization = attempt.get("delivery_authorization") or {}
    if bound is not None and bound != native:
        raise OperatingSetupError("role conversation differs from current assignment binding")
    if bound is None and (admission.get("native_turn_started") is not True
            or authorization.get("status") != "authorized"
            or authorization.get("lifecycle_owner") != conversation_due.lifecycle_owner
            or conversation_due.recipient != principal_id
            or conversation_due.target.get("principal") != principal
            or admission.get("physical_session_id") != native
            or authorization.get("physical_session_id") != native
            or authorization.get("assignment_ref") != conversation_due.assignment_ref
            or authorization.get("generation") != conversation_due.generation
            or authorization.get("project_ref") != conversation_due.target["project_ref"]
            or authorization.get("task_ref") != conversation_due.target["task_ref"]
            or authorization.get("role") != role or authorization.get("principal") != principal):
        raise OperatingSetupError("role conversation is not backed by assignment or admitted delivery")
    return native, (proof_pin if bound is None and proof_pin is not None else
        {"source": "assignment" if bound is not None else "admitted_role", "schedule_id": conversation_due.schedule_id})


def evaluate_setup(runtime: Any, project_ref: Mapping[str, Any], setup: Mapping[str, Any], *, current_due: Any = None,
                   due_overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Read a connected setup without changing due state, allowances or roles."""
    from otto.attention import DueRecord, native_target_identity
    config = normalize_setup(setup)
    from .role_context import role_introduction
    blockers, roles, dues, introductions = [], {}, {}, {}
    if (getattr(runtime.adapter, "require_host_context", False) is not True
            or not callable(getattr(runtime.adapter, "bind_owner_authorization", None))):
        blockers.append({"role": "host", "code": "host_authorization_unavailable",
                         "message": "operating setup requires the verified owner host adapter"})
    for role, schedule in config["roles"].items():
        try:
            raw = (due_overrides or {}).get(schedule) or runtime.due_port.read_due(schedule)
            if not isinstance(raw, Mapping):
                raise OperatingSetupError("selected role schedule is unavailable")
            binding_due = DueRecord.from_dict(raw)
            due = binding_due
            if current_due is not None and current_due.role == role:
                if (any(current_due.assignment_ref.get(k) != due.assignment_ref.get(k)
                        for k in ("authority", "kind", "id")) or current_due.generation != due.generation
                        or native_target_identity(current_due.target) != native_target_identity(due.target)):
                    raise OperatingSetupError("execution differs from adopted role binding; refresh operating setup")
                due = current_due
            for scoped in (binding_due, due):
                if (scoped.role != role or scoped.project_ref != project_ref["id"]
                        or scoped.lifecycle_owner != runtime.actor or scoped.manager_ref != runtime.actor
                        or any(scoped.target["project_ref"].get(k) != project_ref.get(k)
                               for k in ("authority", "kind", "id"))):
                    raise OperatingSetupError("selected role occurrence is foreign")
            prepared = runtime.prepare_execution_readiness(due=due)
            if "mandate_instruction_contract" not in prepared["canonical_evidence"]:
                raise OperatingSetupError("configured role requires an exact active execution mandate contract")
            validate_execution_contract(prepared, due.profile, execution_manager=role == "manager")
            native = native_target_identity(due.target)
            if native is None:
                raise OperatingSetupError("selected role requires an actual bound conversation")
            assignment = prepared["assignment"]
            principal = assignment["principal"]
            principal_id = principal if isinstance(principal, str) else principal["id"]
            if due.recipient != principal_id or due.target.get("principal") != principal:
                raise OperatingSetupError("selected role recipient differs from canonical principal")
            native, conversation_source = verify_role_conversation(due=due, assignment=assignment,
                project_ref=project_ref, due_port=runtime.due_port, actor=runtime.actor, binding_due=binding_due)
            canonical = prepared["canonical_evidence"]
            introduction = role_introduction(canonical)
            roles[role] = {"schedule_id": schedule, "principal": assignment["principal"],
                           "assignment_ref": due.assignment_ref, "generation": due.generation,
                           "conversation_id": native,
                           "conversation_ref": {"host": due.target["host"], "native_id": native},
                           "conversation_binding_source": conversation_source,
                           "base_resource": canonical["base_resource"]["ref"],
                           "mandate_ref": canonical["source_refs"]["mandate"],
                           "task_ref": canonical["source_refs"]["task"],
                           "execution": {"model": due.requested_model, "reasoning": due.requested_reasoning,
                                         "profile": due.profile,
                                         "selection": due.target.get("execution_selection", {"source": "explicit role occurrence"})}}
            introductions[role] = {**introduction, "conversation_id": native,
                                   "conversation_ref": roles[role]["conversation_ref"],
                                   "execution": roles[role]["execution"]}
            dues[role] = due
            if role == "project_advisor" and due.allowance_ref is None:
                raise OperatingSetupError("enabled advisor requires an adopted allowance")
            if role == "project_advisor":
                check = getattr(runtime, "allowance_readiness", None)
                if not callable(check):
                    raise OperatingSetupError("owner advisor allowance read port is unavailable")
                check(due.allowance_ref)
        except Exception as exc:
            blockers.append({"role": role, "code": type(exc).__name__, "message": str(exc)})
    help_ready = False
    pairing = None
    if "manager" in roles:
        try:
            loop = runtime.portfolio._issue_loop()
            if loop is None:
                raise OperatingSetupError("current manager assignment read port is unavailable")
            manager = loop.ports.current_manager(project_ref)
            if manager is None or json_value(manager.ref) != roles["manager"]["assignment_ref"]:
                raise OperatingSetupError("setup differs from current canonical manager assignment")
        except Exception as exc:
            blockers.append({"role": "manager", "code": type(exc).__name__, "message": str(exc)})
    if "project_advisor" in roles and "manager" in roles:
        try:
            from .advisor_pairing import establish_pairing
            view = runtime.operations.sheet_port.export(ResourceRef.from_dict(project_ref))
            current_assignments = [json_value(item) for item in view["project"]["observed"].get("assignments", ())]
            # The public assignment projection carries exact refs and persisted
            # manager linkage; selection is checked against all current roles.
            pairing = establish_pairing(project_ref, current_assignments,
                manager_conversation_ref=roles["manager"]["conversation_ref"],
                advisor_conversation_ref=roles["project_advisor"]["conversation_ref"]).to_dict()
            if (pairing["manager_ref"] != roles["manager"]["assignment_ref"]
                    or pairing["advisor_ref"] != roles["project_advisor"]["assignment_ref"]):
                raise OperatingSetupError("advisor pairing differs from selected canonical roles")
        except Exception as exc:
            blockers.append({"role": "project_advisor", "code": type(exc).__name__, "message": str(exc)})
    if config["mode"] == "autonomous" and "orchestrator" in roles and "manager" in roles:
        try:
            loop = runtime.portfolio._issue_loop()
            if (loop is None or not callable(getattr(loop.ports.delivery, "send", None))
                    or getattr(loop.ports.delivery, "automatic", True) is False):
                raise OperatingSetupError("autonomous setup requires a supported operational-help delivery port")
            manager = loop.ports.current_manager(project_ref)
            supervisor = loop.ports.current_supervisor(project_ref)
            for role, assignment in (("manager", manager), ("orchestrator", supervisor)):
                if assignment is None or json_value(assignment.ref) != roles[role]["assignment_ref"]:
                    raise OperatingSetupError("help route differs from current " + role + " assignment")
            help_ready = True
        except Exception as exc:
            blockers.append({"role": "orchestrator", "code": type(exc).__name__, "message": str(exc)})
    acceptance = None
    if config["acceptance_tasks"] and "manager" in roles:
        try:
            check = getattr(runtime, "acceptance_readiness", None)
            if not callable(check):
                raise OperatingSetupError("owner acceptance readiness port is unavailable")
            acceptance = check(project_ref, roles["manager"], config["acceptance_tasks"])
        except Exception as exc:
            blockers.append({"role": "manager", "code": type(exc).__name__, "message": str(exc)})
    ready = not blockers
    manual_help = None
    if config["mode"] == "manual":
        loop = runtime.portfolio._issue_loop()
        describe = getattr(loop.ports.delivery, "describe", None) if loop else None
        if callable(describe):
            try:
                manual_help = describe(project_ref)
            except Exception as exc:
                blockers.append({"role": "orchestrator", "code": type(exc).__name__, "message": str(exc)})
                ready = False
    # An active lifecycle alone says nothing about a delivered manager turn.
    attempt = (dues["manager"].host_evidence or {}).get("gateway_attempt") if "manager" in dues else None
    admission = attempt.get("delivery_admission") if isinstance(attempt, Mapping) else None
    observed = (isinstance(admission, Mapping) and isinstance(admission.get("physical_session_id"), str)
                and admission["physical_session_id"] == roles.get("manager", {}).get("conversation_id"))
    advice_enabled = config["advisor_policy"]["mode"] == "enabled"
    if advice_enabled and not ready:
        advice_state = "blocked"
    elif advice_enabled:
        advice_state = "ready"
    else:
        advice_state = "disabled"
    if help_ready:
        operational_help_state = "ready"
    elif config["mode"] == "manual" and (manual_help or roles.get("orchestrator")):
        operational_help_state = "host_only"
    elif config["mode"] == "manual":
        operational_help_state = "missing_destination"
    else:
        operational_help_state = "unavailable"
    help_context = {
        "advice": {"state": advice_state, "recipient": roles.get("project_advisor"),
                   "requires": "an explicitly enabled advisor policy and its current paired role"},
        "operational": {"state": operational_help_state,
                         "recipient": manual_help or roles.get("orchestrator"),
                         "requires": "a current orchestrator destination and supported host delivery"},
        "continuation": "Read the retained delivery, apply the response, then use resolve-help; do not resend an unknown effect.",
        "replacement": "After a role replacement, refresh assignment, generation and conversation before a future turn.",
        "host_only": "Installation, transport and manual receipt inspection remain host actions; setup activation does not dispatch.",
    }
    return {"schema": "otto.operating-readiness.v1", "mode": config["mode"],
            "state": "blocked" if blockers else "active" if observed else "held" if attempt else "ready",
            "ready": ready, "autonomous_ready": ready and config["mode"] == "autonomous",
            "execution_observed": observed, "dispatch": False,
            "capabilities": {"operational_help_delivery": help_ready,
                             "advisor": advice_enabled and ready,
                             "advice": advice_enabled and ready,
                             "manual_supervision": config["mode"] == "manual"},
            "roles": roles, "introductions": introductions, "advisor_policy": config["advisor_policy"],
            "advisor_pairing": pairing,
            "help": help_context,
            "help_destination": manual_help or roles.get("orchestrator"),
            "acceptance": acceptance, "blockers": blockers}


def delivery_context(runtime: Any, project_ref: Mapping[str, Any], *, current_due: Any) -> dict[str, Any] | None:
    """Project the current adopted setup into future packets; never send it."""
    execution = {"role": current_due.role, "model": current_due.requested_model,
                 "reasoning": current_due.requested_reasoning, "profile": current_due.profile,
                 "selection": current_due.target.get("execution_selection", {"source": "explicit role occurrence"})}
    setup = read_setup(runtime.operations, project_ref)
    if setup is None:
        return {"schema": "otto.operating-role-context.v1", "setup_state": "absent",
                "current_execution": execution, "dispatch": False}
    decision = evaluate_setup(runtime, project_ref, setup, current_due=current_due)
    if not decision["ready"]:
        raise OperatingSetupError("operating setup blocked: " + str(decision["blockers"]))
    return {"schema": "otto.operating-role-context.v1", "setup_state": "adopted",
            "current_execution": execution, "mode": decision["mode"],
            "roles": decision["roles"], "introductions": decision["introductions"],
            "advisor_policy": decision["advisor_policy"], "advisor_pairing": decision["advisor_pairing"],
            "operational_help": {"ready": decision["capabilities"]["operational_help_delivery"],
                                 "recipient": decision["help_destination"],
                                 "mode": "automatic" if decision["capabilities"]["operational_help_delivery"] else "manual",
                                 "state": decision["help"]["operational"]["state"]},
            "help": decision["help"],
            "source": "current adopted operating setup and canonical role occurrences", "dispatch": False}
