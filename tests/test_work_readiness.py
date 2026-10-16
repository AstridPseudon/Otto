from types import SimpleNamespace

from herzchen.contracts import ResourceRef
from herzchen.domains.work.admission import authoring_stamp
from herzchen.domains.work.readiness import ready


def _task(*, dependencies=(), admitted=True, revision="rev-2", project_ref=None):
    payload = {
        "kind": "task", "id": "task-a", "title": "Task A", "name": "Task A",
        "project_ref": project_ref, "dependencies": list(dependencies),
    }
    if admitted:
        payload["metadata_namespaces"] = {
            "work.admission": authoring_stamp("rev-1", payload, "author")
        }
    ref = ResourceRef("test", "work.task", "task-a", revision)
    return SimpleNamespace(ref=ref, payload=payload, project_ref=project_ref, lifecycle="pending")


def _record(kind, record_id, lifecycle):
    ref = ResourceRef("test", kind, record_id, "rev-1")
    payload = {"lifecycle": lifecycle}
    return SimpleNamespace(ref=ref, payload=payload, lifecycle=lifecycle)


def test_unadmitted_never_dispatches_any_path():
    task = _task(admitted=False)
    result = ready(task, read_record=lambda ref: None, is_admitted=lambda task: True)
    assert result["ready"] is False
    assert result["blockers"][0]["reason"] == "task_not_admitted"


def test_blocked_dep_waits():
    dep_ref = ResourceRef("test", "work.task", "dep", "rev-1")
    dep = _record("work.task", "dep", "active")
    task = _task(dependencies=[dep_ref])
    result = ready(task, read_record=lambda ref: dep)
    assert result["ready"] is False
    assert result["blockers"][0]["reason"] == "dependency_not_completed"


def test_dependency_is_read_by_current_identity_not_historical_pin():
    old_ref = ResourceRef("test", "work.task", "dep", "rev-1")
    current = _record("work.task", "dep", "active")
    seen = []

    def read_current(ref):
        seen.append(ref)
        return current

    result = ready(_task(dependencies=[old_ref]), read_record=read_current)
    assert seen == [ResourceRef("test", "work.task", "dep")]
    assert result["ready"] is False
    assert result["blockers"][0]["ref"]["revision"] == "rev-1"


def test_gate_dep_waits_at_readiness_level():
    gate_ref = ResourceRef("test", "work.gate", "gate", "rev-1")
    gate = _record("work.gate", "gate", "active")
    task = _task(dependencies=[gate_ref])
    result = ready(task, read_record=lambda ref: gate)
    assert result["ready"] is False
    assert result["blockers"][0]["reason"] == "gate_not_passed"


def test_gate_policy_can_supply_canonical_gate_decision():
    gate_ref = ResourceRef("test", "work.gate", "gate", "rev-1")
    gate = _record("work.gate", "gate", "active")
    task = _task(dependencies=[gate_ref])
    result = ready(task, read_record=lambda ref: gate, gate_satisfied=lambda record: True)
    assert result["ready"] is True


def test_project_readiness_policy_blocks_external_prerequisites():
    task = _task(project_ref=ResourceRef("test", "work.project", "project", "rev-3"))
    result = ready(task, read_record=lambda ref: None,
                   project_readiness=lambda ref: {"ready": False, "blockers": [{"reason": "gate"}]})
    assert result["ready"] is False
    assert result["blockers"][0]["reason"] == "project_dependencies_blocked"


def test_admission_survives_lifecycle_revision():
    task = _task(revision="rev-8")
    result = ready(task, read_record=lambda ref: None)
    assert result["ready"] is True
    assert result["admitted_revision"] == "rev-1"


def test_pinned_admission_read_failure_blocks():
    task = _task()
    result = ready(task, read_record=lambda ref: None,
                   read_revision=lambda ref: (_ for _ in ()).throw(OSError("unavailable")))
    assert result["ready"] is False
    assert result["blockers"][0]["reason"] == "task_not_admitted"


def test_terminal_task_lifecycle_is_not_dispatchable():
    for lifecycle in ("completed", "withdrawn"):
        task = _task()
        task.lifecycle = lifecycle
        result = ready(task, read_record=lambda ref: None)
        assert result["ready"] is False
        assert any(blocker["reason"] == "task_not_dispatchable" for blocker in result["blockers"])
