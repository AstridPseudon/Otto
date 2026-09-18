from otto.agents import InMemoryAttemptCapture, OttoGateway, Responsibility


PROJECT = {"authority": "work", "kind": "project", "id": "project-1", "revision": "rev-4"}
TASK = {"authority": "work", "kind": "task", "id": "task-1", "revision": "rev-3"}
ASSIGNMENT = {"authority": "work", "kind": "wrk.assignment", "id": "assignment-1", "revision": "rev-1"}


def responsibility(*, key="request-1", project=PROJECT, task=TASK,
                    assignment=ASSIGNMENT, generation=1, operation="invoke"):
    return Responsibility(
        "owner-1", "logical-1", operation, "packet-digest",
        requested_model="gpt-5.6-luna", requested_reasoning="high",
        requested_profile="worker-normal", logical_request_key=key,
        project_ref=project, task_ref=task, assignment_ref=assignment,
        generation=generation,
    )


class Adapter:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def invoke(self, request):
        self.calls.append(request)
        return self.result


def test_missing_owner_project_task_or_assignment_is_rejected_before_adapter():
    for field in ("owner", "project_ref", "task_ref", "assignment_ref"):
        values = dict(owner="owner-1", project_ref=PROJECT, task_ref=TASK,
                      assignment_ref=ASSIGNMENT)
        values[field] = "" if field == "owner" else None
        item = Responsibility(
            values["owner"], "logical-1", "invoke", "packet",
            logical_request_key="request-1", project_ref=values["project_ref"],
            task_ref=values["task_ref"], assignment_ref=values["assignment_ref"],
            generation=1,
        )
        adapter = Adapter({"outcome": "succeeded"})
        result = OttoGateway(adapter, require_owner_binding=True).invoke(item, "payload")
        assert result["error"]["code"] == "missing_" + field
        assert adapter.calls == []


def test_bound_success_captures_actual_native_identity_and_owner_refs():
    capture = InMemoryAttemptCapture()
    capture.bind_generation(ASSIGNMENT, 1)
    adapter = Adapter({
        "outcome": "succeeded",
        "identity": {"logical_agent_id": "logical-1", "physical_session_id": "native-42"},
        "observed_model": "gpt-5.6-luna",
        "observed_reasoning": "high",
        "delivery_state": "done",
    })
    result = OttoGateway(adapter, attempt_capture=capture).invoke(
        responsibility(), {"prompt": "hello"}
    )
    attempt = result["attempt"]
    assert attempt["logical_request_key"] == "request-1"
    assert attempt["project_ref"] == PROJECT
    assert attempt["task_ref"] == TASK
    assert attempt["assignment_ref"] == ASSIGNMENT
    assert attempt["generation"] == 1
    assert attempt["native_session_id"] == "native-42"
    assert attempt["observed_model"] == "gpt-5.6-luna"
    assert attempt["observed_reasoning"] == "high"
    assert adapter.calls == [{"prompt": "hello"}]


def test_unknown_attempt_is_recorded_and_distinct_key_cannot_retry_same_generation():
    capture = InMemoryAttemptCapture()
    capture.bind_generation(ASSIGNMENT, 1)
    adapter = Adapter({"outcome": "unknown", "reconciliation": "session unresolved",
                       "delivery_state": "unknown", "timeout": True})
    gateway = OttoGateway(adapter, attempt_capture=capture)
    first = gateway.invoke(responsibility(), "first prose")
    assert first["attempt"]["outcome"] == "unknown"
    assert first["attempt"]["timeout"] is True
    second = gateway.invoke(responsibility(key="request-2"), "changed prose")
    assert second["error"]["code"] == "unknown_attempt_requires_reconciliation"
    assert len(adapter.calls) == 1


def test_same_key_replays_without_adapter_and_new_key_uses_generation_fence():
    capture = InMemoryAttemptCapture()
    capture.bind_generation(ASSIGNMENT, 1)
    adapter = Adapter({"outcome": "succeeded", "physical_session_id": "native-1"})
    gateway = OttoGateway(adapter, attempt_capture=capture)
    first = gateway.invoke(responsibility(), "same")
    replay = gateway.invoke(responsibility(), "same")
    assert first["attempt"]["physical_session_id"] == "native-1"
    assert replay["outcome"] == "replayed"
    assert replay["adapter_called"] is False
    assert len(adapter.calls) == 1

    second = gateway.invoke(responsibility(key="request-2"), "different logical request")
    assert second["attempt"]["logical_request_key"] == "request-2"
    assert len(adapter.calls) == 2


def test_stale_generation_is_rejected_before_adapter_invocation():
    capture = InMemoryAttemptCapture()
    capture.bind_generation(ASSIGNMENT, 2)
    adapter = Adapter({"outcome": "succeeded"})
    result = OttoGateway(adapter, attempt_capture=capture).invoke(
        responsibility(generation=1), "payload"
    )
    assert result["error"]["code"] == "stale_generation"
    assert adapter.calls == []
