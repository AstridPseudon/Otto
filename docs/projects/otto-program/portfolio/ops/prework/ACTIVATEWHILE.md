## 1. Design, in implementation order

1. [tests/test_bounded_project_host.py:213](${TRANSFER_ROOT}/source/otto/tests/test_bounded_project_host.py:213) → Let the fixture install only `getattr(self, "initial_view_letters", "ABCDE")`. Keep all five real project services available so a test can install B later. At [line 62](${TRANSFER_ROOT}/source/otto/tests/test_bounded_project_host.py:62), make the fake model wait for release without a duration failure.
2. [src/otto/hostctl/project_service.py:73](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/project_service.py:73) → Resolve an installed run ID to its project ID *before* checking custody. Check every live **and queued** execution’s `scope["project"]`, then capacity holds, against that target. An unknown target or missing execution scope remains a shared fence. Update the global-wait comment at lines 6–7.
3. [src/otto/portfolio/project_services.py:81](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/project_services.py:81) → Apply the same target-scoped execution check in `add_view`. Keep its hold check and distinct-binding checks. Keep the existing copy-and-publish maps at lines 101–105: they preserve A’s service object, fixed binding, and `host.handler`.
4. [src/otto/hostctl/product_service.py:1358](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:1358) → No functional change. The existing builder attaches B to the same router and rolls back a failed installation. Do not swap the router or rebuild A’s view.

Both checks are needed: the lane must admit B’s request, and direct installation must accept B while A runs. They run on the serialized owner, so the check and view publication do not need a new retry or locking mechanism.

## 2. Failing test to write first

Add this to [tests/test_act_activation.py](${TRANSFER_ROOT}/source/otto/tests/test_act_activation.py), after making the fixture change above. It uses the real Store, owner bootstrap, bounded host, project services, and owner service; only the native model is a fixture.

```python
def test_real_owner_installs_b_during_live_and_queued_a_and_routes_a_result():
    import json
    import threading
    import time
    from copy import deepcopy
    from pathlib import Path

    from otto.hostctl import lanes
    from otto.hostctl.service import owner_lane
    from otto.portfolio.execution_host import CapacityPolicy
    from tests.test_bounded_project_host import BoundedProjectHostTests

    f = BoundedProjectHostTests()
    f.initial_view_letters = "A"
    f.capacity_policy = CapacityPolicy(
        turn_units=1, manager_reserve=1, heavy_headroom=1, worker_floor=0)
    f.setUp()

    def receipt(path):
        while not path.exists():
            time.sleep(.01)
        return json.loads(path.read_text())

    try:
        host, router = f.host, f.router
        a_id = f.states["A"]["project_ref"]["id"]
        b_id = f.states["B"]["project_ref"]["id"]
        original_a = router.services["A"]
        original_b_state = deepcopy(f.states["B"])

        first_manager = threading.Event()
        f.native.started[("manager-A", 1)] = first_manager
        manager_response = f.send("A", {"command": "start-manager"})
        first_manager.wait()
        f.native.release("manager-A")
        assert receipt(manager_response)["outcome"] == "succeeded"

        worker_started = threading.Event()
        f.native.started[("worker-A", 1)] = worker_started
        submission = f.send("A", {
            "command": "run-worker", "task": "T", "route": "normal",
            "principal": "worker-A", "request_key": "activation-worker-A",
            "focus": "Complete A's bounded task"})
        admitted = receipt(submission)
        assert admitted["outcome"] == "admitted"
        worker_started.wait()

        seed = host._owner_request(lambda: next(
            row for row in f.f.port.list_due(
                {"project_ref": a_id, "role": "worker"})
            if row["recipient"] == "seed-A"))
        queued_path = f.send("A", {
            "command": "fixture-start", "schedule_id": seed["schedule_id"]})
        while not host._owner_request(
            lambda: seed["schedule_id"] in host._executions):
            time.sleep(.01)
        running, queued = host._owner_request(lambda: (
            host._executions[admitted["schedule_id"]]["running"],
            host._executions[seed["schedule_id"]]["running"]))
        assert running and not queued
        assert not queued_path.exists()

        service = ProjectOwnerService(
            {"home": str(f.root / "activation-owner"),
             "max_active_manager_turns": 2},
            router=router)
        lane = owner_lane(service.home)

        def request(project):
            return {"schema": lanes.REQUEST_SCHEMA,
                    "command": "portfolio-operation",
                    "args": {"command": "project", "sub": "activate",
                             "args": {"project": project}}}

        assert not host._owner_request(lambda:
            service._defer_request(lane, "owner", "b" * 32, request(b_id)))
        assert host._owner_request(lambda:
            service._defer_request(lane, "owner", "a" * 32, request(a_id)))

        def owner_activation(project, operation):
            def run():
                service._dispatch_context.project_id = project
                try:
                    return service.call(operation, hold_during_turn=True)
                finally:
                    service._dispatch_context.project_id = None
            return host._owner_request(run)

        assert owner_activation(
            a_id, lambda: {"outcome": "unexpected"})["outcome"] == "held"

        def install_b():
            router.add_view("B", f.services["B"])
            return {"outcome": "prepared"}

        assert owner_activation(b_id, install_b)["outcome"] == "prepared"
        assert host.handler is router
        assert router.services["A"] is original_a
        assert router.services["B"] is f.services["B"]
        assert host._owner_request(
            lambda: seed["schedule_id"] in host._executions)

        second_manager = threading.Event()
        f.native.started[("manager-A", 2)] = second_manager
        f.native.release("worker-A")
        worker_result = receipt(Path(admitted["response_path"]))
        assert worker_result["outcome"] == "succeeded"
        notice = worker_result["manager_result_notification"]
        second_manager.wait()
        f.native.release("manager-A", 2)
        assert receipt(Path(notice["response_path"]))["outcome"] == "succeeded"
        assert f.states["B"] == original_b_state
        assert router.services["A"] is original_a
    finally:
        f.doCleanups()
```

The first B deferral assertion fails on `canon/main`; after that gate is fixed, `add_view` still fails until its global check is fixed. The owner call also proves A remains held.

## 3. Delete

Delete the unconditional `_executions` fences at [project_service.py:74–78](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/project_service.py:74) and [project_services.py:81–86](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/project_services.py:81). Replace their comments with the scoped rule. Delete the duplicate fake `test_activate_while_other_runs` once the real-owner test covers its useful assertions; remove its patched `_build_activated_view` path.

## 4. Plausible mistake

A worker might replace `host.handler` or rebuild the router when installing B. The test checks the handler and A view identities while A is live, then waits for A’s actual retained worker-result callback to succeed and confirms B’s state was untouched. It also catches a partial fix that opens the lane but leaves `add_view` globally fenced.

## 5. Existing expectations and D19 decision

[tests/test_act_activation.py:59–106](${TRANSFER_ROOT}/source/otto/tests/test_act_activation.py:59) asserts that B waits for A; that assertion must be retired. [Lines 127–131](${TRANSFER_ROOT}/source/otto/tests/test_act_activation.py:127) assert direct B installation fails for an unscoped A execution; revise that case to use **B’s own** scoped execution for the refusal. Keep the same-project pending test, with a scoped execution record.

**D19 decision to record:** global activation waiting was the defect. Replace the obsolete cross-project assertions with B activation during A’s live and queued work; retain assertions that same-project and unknown custody defer activation. The project-scoped hold tests do not change.

## 6. Row corrections on `canon/main`

The cited code locations and diagnosis are current. `PLAN.md` is absent from the `canon/main` tree, so its §16 stage-5 reference cannot be checked there. “Only B’s own” needs the existing conservative exception for an unknown target or scope. The router does replace its *mapping snapshots* when B is added; it preserves A’s view and binding. No files were changed and no tests were run.