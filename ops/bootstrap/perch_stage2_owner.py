"""Stage-2 staging owner entrypoint for fake-run worker stand-ins."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import sys


def complete_landed_canary(context, landing):
    """Close A/B through the owner's ordinary guarded manager completion.

    A passing ``done`` lands and accepts work, but it does not itself complete
    the work task. The next canary task has a real dependency on that lifecycle
    transition. Completion reuses managed evidence recorded by the landing's
    accepted assessment result.
    """
    from herzchen.contracts import ResourceRef
    from herzchen.domains.assessment import AssessmentModule

    server = context["view"].server
    task = context["task"]
    alias = task.payload.get("alias")
    if server.run_id != "perch-stage2" or alias not in {"A", "B", "C"}:
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
    accepted_decisions = tuple(assessment.get_decision(ResourceRef.from_dict(ref)) for ref in decisions)
    evidence_refs = tuple(dict.fromkeys(ref for decision in accepted_decisions
                                        for ref in decision.evidence_refs))
    evidence_hashes = {}
    for evidence_ref in evidence_refs:
        pin = next((row for decision in accepted_decisions
                    for row in decision.payload.get("evidence_digests", ())
                    if isinstance(row, Mapping) and row.get("ref") == evidence_ref.to_dict()), None)
        # Pass the digest recorded by acceptance through to the product check.
        # Missing pins remain missing and are refused by WorkAssignments.complete.
        if pin is not None and "digest" in pin:
            evidence_hashes["%s:%s:%s" % (evidence_ref.kind, evidence_ref.id,
                                          evidence_ref.revision)] = pin["digest"]
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
        disposition="accepted", evidence_refs=[ref.to_dict() for ref in evidence_refs],
        evidence_hashes=evidence_hashes, gate_refs=decisions,
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
    if os.environ.get("OTTO_STAGING_FAKE_PRESENCE") == "1":
        install_fake_completion()
        from perch_fake_presence import main as fake_main
        return fake_main(argv)
    from otto.hostctl.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
