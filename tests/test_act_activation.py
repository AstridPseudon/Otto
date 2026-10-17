"""ACT regressions: activation respects project custody and attaches a view."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import threading
from unittest.mock import patch

from otto.hostctl import lanes
from otto.hostctl.project_service import ProjectOwnerService


class PollHarness(ProjectOwnerService):
    """Exercise the real lane poller with only its shared-host boundary stubbed."""
    def __init__(self, host):
        self.shared_host = host
        self.in_flight = {}
        self.relays = {}
        self.served = 0
        self.last_completed = None
        self._dispatch_context = __import__('threading').local()
        self.config = {'hosts': {}}
        self.home = Path('/tmp')
        self.handled = []

    def _defer_request(self, lane, who, token, request):
        return ProjectOwnerService._defer_request(self, lane, who, token, request)

    def _publish(self, **kwargs):
        pass


def activation_request():
    return {'schema': lanes.REQUEST_SCHEMA, 'command': 'portfolio-operation',
            'args': {'command': 'project', 'sub': 'activate',
                     'args': {'project': 'project-b', 'portfolio': 'portfolio'}}}


def test_busy_queues_once(tmp_path):
    lane = tmp_path / 'lane'
    lanes.private_dir(lane)
    token = lanes.submit(lane, activation_request())
    request = lane / ('request-' + token + '.json')
    request_bytes = request.read_bytes()
    host = SimpleNamespace(_executions={'a': {'running': True, 'scope': {'project': 'project-b'}}},
                           _capacity_holds={})
    service = PollHarness(host)
    with patch('otto.hostctl.project_service.lanes.mark_pending', wraps=lanes.mark_pending) as mark:
        service._poll(lane, 'owner', lambda *args: service.handled.append(args))
        receipt = lane / ('pending-' + token + '.json')
        first_receipt = receipt.read_bytes()
        service._poll(lane, 'owner', lambda *args: service.handled.append(args))
        assert mark.call_count == 1
        assert receipt.read_bytes() == first_receipt
    assert not service.handled
    assert token not in service.in_flight
    assert request.exists()
    assert request.read_bytes() == request_bytes
    assert lanes.read_private_json(lane / ('pending-' + token + '.json'))['state'] == 'queued'


def test_unknown_custody_and_installed_run_alias():
    host = SimpleNamespace(_executions={'a': {'running': False, 'scope': {'project': 'project-a'}}},
                           _capacity_holds={})
    service = PollHarness(host)
    service.router = SimpleNamespace(services={'B': SimpleNamespace(server=SimpleNamespace(
        run_id='run-b', state={'project_ref': {'id': 'project-b'}}))})
    assert not service._project_has_custody('run-b')
    assert service._project_has_custody('project-a')
    assert service._project_has_custody(None)
    host._executions['a'].pop('scope')
    assert service._project_has_custody('project-b')


def test_real_owner_installs_b_during_live_and_queued_a_and_routes_a_result():
    from otto.hostctl.service import owner_lane
    from otto.portfolio.execution_host import CapacityPolicy
    from tests.test_bounded_project_host import BoundedProjectHostTests

    f = BoundedProjectHostTests()
    f.initial_view_letters = "A"
    f.capacity_policy = CapacityPolicy(
        turn_units=1, manager_reserve=1, heavy_headroom=1, worker_floor=0)
    f.setUp()

    def receipt(path):
        f.wait(path.exists, str(path))
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
        f.wait(first_manager.is_set, "first A manager")
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
        f.wait(worker_started.is_set, "A worker")

        seed = host._owner_request(lambda: next(
            row for row in f.f.port.list_due(
                {"project_ref": a_id, "role": "worker"})
            if row["recipient"] == "seed-A"))
        queued_path = f.send("A", {
            "command": "fixture-start", "schedule_id": seed["schedule_id"]})
        f.wait(lambda: host._owner_request(
            lambda: seed["schedule_id"] in host._executions), "queued A execution")
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
        f.wait(second_manager.is_set, "A callback manager")
        f.native.release("manager-A", 2)
        assert receipt(Path(notice["response_path"]))["outcome"] == "succeeded"
        assert f.states["B"] == original_b_state
        assert router.services["A"] is original_a
    finally:
        f.doCleanups()


def test_view_attached_on_activation():
    """The successful activation callback installs the new view on the existing router."""
    from otto.portfolio.project_services import ProjectServices
    host, due, store = SimpleNamespace(_threads=[], bounded_transports=True, _executions={}, _capacity_holds={}), object(), object()
    owner = SimpleNamespace(owner_actor='owner')
    def make_view(project, assignment):
        state = {'project_ref': {'authority': 'a', 'kind': 'project', 'id': project},
                 'assignment_ref': {'authority': 'a', 'kind': 'assignment', 'id': assignment},
                 'manager': project + '-manager', 'manager_generation': 1}
        server = SimpleNamespace(state=state, due_port=due, store=store, owner=owner)
        return SimpleNamespace(host=host, server=server, workspace=Path('/tmp'), run_path=Path('/tmp/' + project))
    first = make_view('project-a', 'assignment-a')
    router = ProjectServices({'project-a': first}, host=host, due_port=due, store=store)
    original_a = router.services['project-a']
    service = ProjectOwnerService.__new__(ProjectOwnerService)
    service.router = router
    view = make_view('project-b', 'assignment-b')
    service._build_activated_view = lambda project: router.add_view(project, view)
    host._executions['a'] = {'running': True, 'scope': {'project': 'project-b'}}
    import pytest
    with pytest.raises(RuntimeError, match='execution custody clears'):
        router.add_view('project-b', view)
    assert list(router.services) == ['project-a']
    host._executions['a'].pop('scope')
    with pytest.raises(RuntimeError, match='execution custody clears'):
        router.add_view('project-b', view)
    host._executions.clear()
    blocked = service._run_operation(lambda args: {'outcome': 'blocked'},
                                    SimpleNamespace(project='project-b'), ('project', 'activate'))
    assert blocked['outcome'] == 'blocked'
    assert 'project-b' not in router.services
    result = service._run_operation(lambda args: {'outcome': 'prepared'},
                                    SimpleNamespace(project='project-b'), ('project', 'activate'))
    assert result['outcome'] == 'prepared'
    assert router.services['project-a'] is original_a
    assert router.services['project-b'] is view
    assert router._project(view.server.state['project_ref']) is view
    assert router.host is host and router.due_port is due and router.store is store
