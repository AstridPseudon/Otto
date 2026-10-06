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


def evaluate_setup(runtime: Any, project_ref: Mapping[str, Any], setup: Mapping[str, Any], *, current_due: Any = None) -> dict[str, Any]:
    """Read a connected setup without changing due state, allowances or roles."""
    from otto.attention import DueRecord, native_target_identity
    config = normalize_setup(setup)
    blockers, roles, dues = [], {}, {}
    if (getattr(runtime.adapter, "require_host_context", False) is not True
            or not callable(getattr(runtime.adapter, "bind_owner_authorization", None))):
        blockers.append({"role": "host", "code": "host_authorization_unavailable",
                         "message": "operating setup requires the verified owner host adapter"})
    for role, schedule in config["roles"].items():
        try:
            raw = runtime.due_port.read_due(schedule)
            if not isinstance(raw, Mapping):
                raise OperatingSetupError("selected role schedule is unavailable")
            due = DueRecord.from_dict(raw)
            if current_due is not None and current_due.role == role:
                if (any(current_due.assignment_ref.get(k) != due.assignment_ref.get(k)
                        for k in ("authority", "kind", "id")) or current_due.generation != due.generation
                        or native_target_identity(current_due.target) != native_target_identity(due.target)):
                    raise OperatingSetupError("execution differs from adopted role binding; refresh operating setup")
                due = current_due
            if (due.role != role or due.project_ref != project_ref["id"]
                    or due.lifecycle_owner != runtime.actor or due.manager_ref != runtime.actor
                    or any(due.target["project_ref"].get(k) != project_ref.get(k)
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
            session = assignment.get("payload", {}).get("session")
            bound = session if isinstance(session, str) else native_target_identity(session) if isinstance(session, Mapping) else None
            admission = ((due.host_evidence or {}).get("gateway_attempt") or {}).get("delivery_admission") or {}
            if bound != native and admission.get("physical_session_id") != native:
                raise OperatingSetupError("role conversation is not backed by assignment or admitted delivery")
            roles[role] = {"schedule_id": schedule, "principal": assignment["principal"],
                           "assignment_ref": due.assignment_ref, "generation": due.generation,
                           "conversation_id": native,
                           "base_resource": prepared["canonical_evidence"]["base_resource"]["ref"]}
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
    if config["mode"] == "autonomous" and "orchestrator" in roles and "manager" in roles:
        try:
            loop = runtime.portfolio._issue_loop()
            if loop is None or not callable(getattr(loop.ports.delivery, "send", None)):
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
    # An active lifecycle alone says nothing about a delivered manager turn.
    attempt = (dues["manager"].host_evidence or {}).get("gateway_attempt") if "manager" in dues else None
    admission = attempt.get("delivery_admission") if isinstance(attempt, Mapping) else None
    observed = (isinstance(admission, Mapping) and isinstance(admission.get("physical_session_id"), str)
                and admission["physical_session_id"] == roles.get("manager", {}).get("conversation_id"))
    return {"schema": "otto.operating-readiness.v1", "mode": config["mode"],
            "state": "blocked" if blockers else "active" if observed else "held" if attempt else "ready",
            "ready": ready, "autonomous_ready": ready and config["mode"] == "autonomous",
            "execution_observed": observed, "dispatch": False,
            "capabilities": {"operational_help_delivery": help_ready,
                             "advisor": config["advisor_policy"]["mode"] == "enabled" and ready,
                             "manual_supervision": config["mode"] == "manual"},
            "roles": roles, "advisor_policy": config["advisor_policy"],
            "acceptance": acceptance, "blockers": blockers}
