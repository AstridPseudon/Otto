"""Stage-2 staging owner entrypoint: seed the canary's declared assessment scopes.

The registered tasklist supplies task aliases and the portfolio save supplies
typed checks. The file-mode activation route has no command to declare the
criteria named by run.json, so seed those records inside the staging owner's
serialized activation call. Each admitted task gets its required scope at its
new current revision, before the owner dispatch pump runs.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import hashlib
import json
import copy
from collections.abc import Mapping


def _seed_scopes(service, task_refs):
    from herzchen.contracts import ResourceRef
    from herzchen.domains.assessment import AssessmentModule
    from otto.hostctl.owner import HostSession, service_store

    if set(task_refs) != {"A", "B", "C"}:
        raise RuntimeError("stage-2 activation must materialize exactly A, B and C")
    config = service.config
    host = (config.get("hosts") or {}).get("claude-code")
    if host is None:
        raise RuntimeError("stage-2 canary host was not admitted")
    with service_store(service.store), HostSession(config, host=host) as session:
        assessment = AssessmentModule(session.store, actor=session.owner.owner_actor,
                                      payload_resolver=session.owner.evidence_payload_resolver)
        for alias in ("A", "B", "C"):
            task = ResourceRef.from_dict(task_refs[alias])
            if task.kind != "work.task" or task.revision is None:
                raise RuntimeError("stage-2 task " + alias + " has no exact revision")
        first_task = session.owner.graph.current(ResourceRef.from_dict(
            {k: task_refs["A"][k] for k in ("authority", "kind", "id")}))
        project_ref = first_task.payload.get("project_ref")
        if not isinstance(project_ref, dict):
            raise RuntimeError("stage-2 task has no registered project")
        project_identity = ResourceRef.from_dict(project_ref)
        current_project = session.owner.graph.current(ResourceRef(project_identity.authority,
                                                                  project_identity.kind, project_identity.id))
        scope = assessment.declare_scope(
            "perch-stage2-policy-criteria", parent_obligation=current_project.ref,
            protocol="perch-stage2-policy", criteria=[
                {"id": "perch-stage2-criterion-" + alias, "source_alias": "C-" + alias,
                 "expected_behavior": "The canary's typed check passes."}
                for alias in ("A", "B", "C")],
            review_required=False, allow_no_review=True,
            policy={"required_for_completion": False},
            logical_request_key="perch-stage2-policy-criteria", actor=session.owner.owner_actor)
        created = {alias: ref.to_dict() for alias, ref in zip(("A", "B", "C"), scope.criterion_refs)}
    return {"policy_scope_ref": scope.ref.to_dict(), "criterion_refs": created}


def _seed_admitted_scope(service, task_ref):
    from herzchen.contracts import ResourceRef
    from herzchen.domains.assessment import AssessmentModule
    from otto.hostctl.owner import HostSession, service_store

    config = service.config
    host = (config.get("hosts") or {}).get("claude-code")
    if host is None:
        raise RuntimeError("stage-2 canary host was not admitted")
    with service_store(service.store), HostSession(config, host=host) as session:
        admitted = ResourceRef.from_dict(task_ref)
        task = session.owner.graph.current(ResourceRef(admitted.authority, admitted.kind, admitted.id))
        alias = task.payload.get("alias")
        if alias not in {"A", "B", "C"}:
            return None
        project_ref = task.payload.get("project_ref")
        project_identity = ResourceRef.from_dict(project_ref)
        project = session.owner.graph.current(ResourceRef(project_identity.authority,
                                                          project_identity.kind, project_identity.id))
        run_id = ((project.payload.get("custom") or {}).get("otto_host_registration") or {}).get("run_id")
        if run_id != "perch-stage2":
            return None
        assessment = AssessmentModule(session.store, actor=session.owner.owner_actor,
                                      payload_resolver=session.owner.evidence_payload_resolver)
        policy_scope = assessment.get_scope(ResourceRef(task.ref.authority, "assessment.scope",
                                                        "perch-stage2-policy-criteria"))
        criterion = policy_scope.criterion_refs[("A", "B", "C").index(alias)]
        scope = assessment.declare_scope(
            "perch-stage2-check-" + alias, parent_obligation=task.ref,
            protocol="check-accepted", criteria=[criterion],
            review_required=False, allow_no_review=True,
            designated_approver="perch-stage2-manager",
            authority=session.owner.owner_actor.authority,
            policy={"required_for_completion": True, "acceptance_mode": "check-accepted"},
            logical_request_key="perch-stage2-check-" + alias,
            actor=session.owner.owner_actor)
        return {"task_ref": task.ref.to_dict(), "scope_ref": scope.ref.to_dict(),
                "criterion_ref": criterion.to_dict()}


def _status_with_dispatch(service, result):
    """Expose the composed canary's retained worker records on its host read.

    The normal manager status command requires a native manager caller. The
    canary harness reads project status as its admitted host; this staging-only
    projection copies the same owner state that automatic dispatch persists.
    """
    project = result.get("project_ref") if isinstance(result, Mapping) else None
    if not isinstance(result, Mapping) or result.get("outcome") != "read" or not isinstance(project, Mapping):
        return result
    views = getattr(getattr(service, "router", None), "services", {})
    view = views.get(project.get("id")) if isinstance(views, Mapping) else None
    server = getattr(view, "server", None)
    if (server is None or getattr(server, "run_id", None) != "perch-stage2"
            or server.state.get("project_ref", {}).get("id") != project.get("id")):
        return result
    return {**result,
            "workers": copy.deepcopy(server.state.get("workers") or {}),
            "automatic_dispatch_failures": copy.deepcopy(
                server.state.get("automatic_dispatch_failures") or {})}


def install_scope_setup():
    from otto.hostctl.project_service import ProjectOwnerService
    from otto.hostctl.service import OwnerService

    original = ProjectOwnerService._run_operation
    original_admit = ProjectOwnerService._admit_revision

    def activation_with_scopes(self, handler, namespace, operation):
        if operation == ("project", "status") and getattr(namespace, "project", None) == "perch-stage2":
            return _status_with_dispatch(self, original(self, handler, namespace, operation))
        if operation != ("project", "activate") or getattr(namespace, "project", None) != "perch-stage2":
            return original(self, handler, namespace, operation)
        result = OwnerService._run_operation(self, handler, namespace, operation)
        if result.get("outcome") != "prepared":
            return result
        task_refs = result["activation"]["steps"]["tasks"]["task_refs"]
        scopes = _seed_scopes(self, task_refs)
        builder = getattr(self, "_build_activated_view", None)
        if not callable(builder):
            raise RuntimeError("prepared stage-2 activation has no composed owner view builder")
        builder("perch-stage2")
        return {**result, "bootstrap_assessment": scopes}

    ProjectOwnerService._run_operation = activation_with_scopes

    def admission_with_scope(self, args):
        answer = original_admit(self, args)
        if answer.get("outcome") not in {"admitted", "replayed", "already-admitted"}:
            return answer
        scope = _seed_admitted_scope(self, answer["task_ref"])
        return {**answer, **({"bootstrap_assessment": scope} if scope is not None else {})}

    ProjectOwnerService._admit_revision = admission_with_scope


def defer_fake_lab_cleanup(root):
    """Keep fake worker artifacts readable until native result capture finishes.

    The real landing/check/assessment still runs. Landing reports
    ``cleanup_pending`` when this fixture defers its final lab unlink; the
    harness removes those disposable labs after the staging owner closes.
    """
    from herzchen.fleet.labs import LabFleet, LabRefused

    original = LabFleet.remove
    canary = (Path(root) / "perch-canary").resolve()

    def defer(self, name, merged_into=None, before_unlink=None):
        repo = Path(self.repo).resolve()
        if (merged_into is not None and canary in repo.parents and repo.name == "canon"):
            raise LabRefused("PERCH fake worker lab retained for native artifact capture")
        return original(self, name, merged_into=merged_into, before_unlink=before_unlink)

    LabFleet.remove = defer


def complete_landed_canary(context, landing):
    """Close A/B through the owner's ordinary guarded manager completion.

    A passing ``done`` lands and accepts work, but it does not itself complete
    the work task. The next canary task has a real dependency on that lifecycle
    transition. The fake manager consumes only owner-retained landing records.
    """
    from herzchen.contracts import ResourceRef
    from herzchen.domains.assessment import AssessmentModule

    server = context["view"].server
    task = context["task"]
    alias = task.payload.get("alias")
    if server.run_id != "perch-stage2" or alias not in {"A", "B"}:
        return None
    if landing.get("landed") is not True:
        raise RuntimeError("stage-2 manager cannot complete work that did not land")
    results = landing.get("assessment_results")
    decisions = landing.get("acceptances")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(decisions, list) or len(decisions) != 1:
        raise RuntimeError("stage-2 landing has no single owner assessment and acceptance")
    owner = server.owner
    assessment = AssessmentModule(server.store, actor=owner.owner_actor,
                                  payload_resolver=owner.evidence_payload_resolver)
    assessed = assessment.get_result(ResourceRef.from_dict(results[0]))
    candidate = assessed.candidate_ref
    candidate_identity = owner.graph.reader.get_identity(candidate)
    if candidate_identity is None or candidate_identity.ref != candidate:
        raise RuntimeError("stage-2 landing candidate is no longer an exact stored revision")
    candidate_value = candidate_identity.payload.get("value")
    if not isinstance(candidate_value, dict):
        raise RuntimeError("stage-2 landing candidate has no stored value")
    digest = hashlib.sha256(json.dumps(candidate_value, sort_keys=True,
                                       separators=(",", ":")).encode()).hexdigest()
    task_ref = owner.graph.current(ResourceRef(task.ref.authority, "work.task", task.ref.id)).ref
    project_pin = context["project_ref"]
    project_ref = owner.graph.current(ResourceRef(project_pin["authority"], "work.project",
                                                  project_pin["id"])).ref
    manager_pin = server.state["assignment_ref"]
    manager_ref = owner.assignments.get(ResourceRef(manager_pin["authority"], "wrk.assignment",
                                                    manager_pin["id"])).ref
    completion = server.portfolio.complete_task(
        project_ref.to_dict(), task_ref.to_dict(), manager_ref.to_dict(),
        actor=server.state["manager"], request_id="perch-stage2-complete-" + alias,
        expected_generation=server.state["manager_generation"],
        expected_project_revision=project_ref.revision, expected_task_revision=task_ref.revision,
        disposition="accepted", evidence_refs=[candidate.to_dict()],
        evidence_hashes={"candidate": digest}, gate_refs=decisions,
        candidate_ref=candidate.to_dict())
    if completion.get("outcome") != "completed":
        raise RuntimeError("stage-2 manager completion refused: " + repr(completion))
    context["view"]._refresh_refs()
    return completion


def install_fake_completion():
    """Give the fake manager a real completion after the owner lands A/B."""
    from otto.hostctl.product_service import _OwnerExecutorPort

    original = _OwnerExecutorPort.call

    def finish_after_landing(self, operation, assignment, args, *, feedback):
        context = None
        if operation == "worker-done":
            context = self.inner._assignment_context(assignment)
        landing = original(self, operation, assignment, args, feedback=feedback)
        if context is None or landing.get("landed") is not True:
            return landing
        complete = self.executor()(lambda: complete_landed_canary(context, landing))
        return {**landing, **({"bootstrap_completion": complete} if complete is not None else {})}

    _OwnerExecutorPort.call = finish_after_landing


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = os.environ.get("OTTO_STAGING_ROOT")
    if (os.environ.get("OTTO_STAGING_STAGE2_SETUP") != "1" or not root
            or len(argv) != 4 or argv[0] != "--home" or argv[2:] != ["service", "run"]
            or Path(argv[1]).resolve() != (Path(root) / "home").resolve()):
        raise SystemExit("stage-2 owner launcher requires the staging owner's service run")
    install_scope_setup()
    if os.environ.get("OTTO_STAGING_FAKE_PRESENCE") == "1":
        defer_fake_lab_cleanup(root)
        install_fake_completion()
        from perch_fake_presence import main as fake_main
        return fake_main(argv)
    from otto.hostctl.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
