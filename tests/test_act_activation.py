"""ACT regressions: activation waits for shared execution custody and then attaches a view."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
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
    host = SimpleNamespace(_executions={'a': {'running': True}}, _capacity_holds={})
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


def test_activate_while_other_runs(tmp_path):
    from otto.portfolio.project_services import ProjectServices
    lane = tmp_path / 'lane'
    lanes.private_dir(lane)
    token = lanes.submit(lane, activation_request())
    host = SimpleNamespace(_executions={'a': {'running': True}}, _capacity_holds={})
    service = PollHarness(host)
    host_obj = SimpleNamespace(_threads=[], bounded_transports=True, _executions=host._executions,
                               _capacity_holds=host._capacity_holds)
    due, store = object(), object()
    owner = SimpleNamespace(owner_actor='owner')
    def make_view(project, assignment):
        state = {'project_ref': {'authority': 'a', 'kind': 'project', 'id': project},
                 'assignment_ref': {'authority': 'a', 'kind': 'assignment', 'id': assignment},
                 'manager': project + '-manager', 'manager_generation': 1}
        server = SimpleNamespace(state=state, due_port=due, store=store, owner=owner)
        return SimpleNamespace(host=host_obj, server=server, workspace=Path('/tmp'), run_path=Path('/tmp/' + project))
    first = make_view('project-a', 'assignment-a')
    router = ProjectServices({'project-a': first}, host=host_obj, due_port=due, store=store)
    original_a = router.services['project-a']
    original_execution = deepcopy(host._executions['a'])
    request_path = lane / ('request-' + token + '.json')
    request_bytes = request_path.read_bytes()
    owner_service = ProjectOwnerService.__new__(ProjectOwnerService)
    owner_service.router = router
    new_view = make_view('project-b', 'assignment-b')
    owner_service._build_activated_view = lambda project: router.add_view(project, new_view)
    service._poll(lane, 'owner', lambda *args: service.handled.append(args))
    service._poll(lane, 'owner', lambda *args: service.handled.append(args))
    assert not service.handled
    assert not (lane / ('response-' + token + '.json')).exists()
    assert host._executions['a'] == original_execution
    assert router.services['project-a'] is original_a
    assert request_path.read_bytes() == request_bytes
    host._executions.clear()
    def activate(who, request, tok, request_lane):
        result = owner_service._run_operation(
            lambda namespace: {'outcome': 'prepared'},
            SimpleNamespace(project='project-b'), ('project', 'activate'))
        service.handled.append(result)
        return result
    service._poll(lane, 'owner', activate)
    assert len(service.handled) == 1
    assert service.handled[0]['outcome'] == 'prepared'
    assert lanes.read_private_json(lane / ('response-' + token + '.json'))['outcome'] == 'prepared'
    assert router.services['project-a'] is original_a
    assert router._project(new_view.server.state['project_ref']) is new_view
    assert router.host is host_obj and router.due_port is due and router.store is store


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
    host._executions['a'] = {'running': True}
    import pytest
    with pytest.raises(RuntimeError, match='execution custody clears'):
        router.add_view('project-b', view)
    assert list(router.services) == ['project-a']
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
