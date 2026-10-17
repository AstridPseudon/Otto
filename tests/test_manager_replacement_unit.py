"""Socket-free regressions for the native replacement admission boundaries."""

from types import SimpleNamespace

import pytest

from otto.portfolio.execution_operations import recheck_execution_admission
from otto.portfolio.manager_replacement import OwnerManagerReplacement


def test_queued_manager_generation_is_rechecked_at_final_admission():
    calls = []
    due = SimpleNamespace(role="manager", schedule_id="queued-old",
                          assignment_ref={"id": "manager"}, generation=1)

    def current(ref, generation):
        calls.append((ref, generation))
        raise ValueError("generation was replaced")

    with pytest.raises(ValueError, match="generation was replaced"):
        recheck_execution_admission(SimpleNamespace(_current=current), due)
    assert calls == [(due.assignment_ref, 1)]


def _failed_acquisition_fixture():
    assignment_ref = {"authority": "owner", "kind": "wrk.assignment", "id": "manager"}
    project_ref = {"authority": "owner", "kind": "work.project", "id": "project"}
    task_ref = {"authority": "owner", "kind": "work.task", "id": "task"}
    prior = SimpleNamespace(assignment_ref=assignment_ref, generation=1, role="manager",
                            target={"native_id": "old", "project_ref": project_ref,
                                    "task_ref": task_ref}, last_result=None,
                            stop_state="completed", completion_state="succeeded",
                            in_flight_request=None,
                            host_evidence={"gateway_attempt": {"result": {"outcome": "succeeded"}}})
    prior.to_dict = lambda: {"schedule_id": "old"}
    assignment = SimpleNamespace(ref=SimpleNamespace(authority="owner", id="manager",
        to_dict=lambda: assignment_ref), id="manager", role="manager", principal="manager",
        generation=1, session="old")
    reports = {}

    def append_report(_ref, value, *, expected_generation, logical_request_key, actor):
        from hashlib import sha256
        report_id = "report-" + sha256(("manager:" + logical_request_key).encode()).hexdigest()[:28]
        reports.setdefault(report_id, SimpleNamespace(payload={"assignment": assignment_ref,
            "generation": expected_generation, "value": value}))

    app = SimpleNamespace(manager_actor="manager", _read=lambda _: prior,
                          _verify_native_binding=lambda *_: None,
                          assignments=SimpleNamespace(get=lambda _: assignment,
                              append_report=append_report),
                          binding=SimpleNamespace(authenticated_actor=lambda _: "manager"))
    acquisitions = []
    replacement = OwnerManagerReplacement(application=app,
        report_reader=lambda ref: reports.get(ref.id),
        acquire_session=lambda _: acquisitions.append(1) or {"outcome": "error"},
        context_builder=lambda *_: {}, readiness=lambda *_: {})
    return replacement, reports, acquisitions, prior


def _assert_held_guidance(result):
    assert result["outcome"] == "held"
    assert result["retry"] is False
    action = result["next_action"].lower()
    assert "owner" in action and "reconcile" in action
    assert "new accepted schedule" in action
    assert "do not retry acquisition" in action


def test_failed_acquisition_cannot_restart_under_another_request_key():
    replacement, _, acquisitions, _ = _failed_acquisition_fixture()
    _assert_held_guidance(replacement.replace(schedule_id="old", request_key="first"))
    _assert_held_guidance(replacement.replace(schedule_id="old", request_key="first"))
    _assert_held_guidance(replacement.replace(schedule_id="old", request_key="second"))
    assert acquisitions == [1]
    with pytest.raises(PermissionError, match="intent differs"):
        replacement.replace(schedule_id="another-completed-due", request_key="third")
    assert acquisitions == [1]


@pytest.mark.parametrize("rival_key", ["same", "rival"])
def test_concurrent_intents_cannot_acquire_twice(rival_key):
    replacement, _, acquisitions, _ = _failed_acquisition_fixture()
    # Both calls can read an absent intent before either append completes.
    # The later caller must not acquire even when it replays the same key.
    original_reader = replacement.report_reader
    entered = False

    def concurrent_reader(ref):
        nonlocal entered
        if not entered:
            entered = True
            _assert_held_guidance(replacement.replace(schedule_id="old", request_key=rival_key))
            return None  # outer call had already observed the absent intent
        return original_reader(ref)

    replacement.report_reader = concurrent_reader
    _assert_held_guidance(replacement.replace(schedule_id="old", request_key="same"))
    assert acquisitions == [1]


def test_unavailable_intent_readback_and_prior_custody_give_safe_guidance():
    replacement, _, acquisitions, prior = _failed_acquisition_fixture()
    prior.completion_state = "unknown"
    _assert_held_guidance(replacement.replace(schedule_id="old", request_key="pending"))
    prior.completion_state = "succeeded"
    replacement.report_reader = lambda _: None
    _assert_held_guidance(replacement.replace(schedule_id="old", request_key="unavailable"))
    assert acquisitions == []
