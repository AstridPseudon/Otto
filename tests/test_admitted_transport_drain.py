"""A drain cannot reject transport belonging to an already admitted job."""
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import json
import socket
import tempfile
import threading
import time
import unittest
from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.domains.work.admission import authoring_stamp
from otto.portfolio.execution_host import CapacityPolicy, ExecutionHost
from otto.portfolio.identity_context import HostCallerBinding
from otto.portfolio.owner_completion import after_owner

@dataclass
class Due:
    schedule_id: str = 'original-worker'
    project_ref: str = 'project'
    role: str = 'worker'
    target: object = None
    host_evidence: object = None
    assignment_ref: object = None
    generation: int = 1
    profile: str = 'workspace-write'
    stop_state: str = 'active'
    completion_state: str = 'none'

class AdmittedDrainTests(unittest.TestCase):
    def test_drain_answers_queued_socket_and_preserves_prepared_due(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_ref = ResourceRef("fixture", "work.project", "project", "p1").to_dict()
            task_ref = ResourceRef("fixture", "work.task", "task", "t1").to_dict()
            payload = {"project_ref": project_ref, "dependencies": []}
            payload["metadata_namespaces"] = {
                "work.admission": authoring_stamp("t0", payload, "fixture")}
            task = SimpleNamespace(ref=ResourceRef.from_dict(task_ref), payload=payload)
            project = SimpleNamespace(
                ref=ResourceRef.from_dict(project_ref), payload={"dependencies": []})

            class Reader:
                def get_record(self, ref):
                    return {"work.task": task, "work.project": project}.get(ref.kind)

            operations = SimpleNamespace(
                _owner_reader=Reader(), port=SimpleNamespace(list=lambda **kw: []),
                dependency_owner_actor=None)
            apps = {}
            for name in ("first", "second"):
                due = Due(
                    schedule_id=name, project_ref="project", role="worker",
                    target={**{"project_ref": project_ref, "task_ref": task_ref},
                            "native_id": "native-" + name},
                    host_evidence={},
                    assignment_ref=ResourceRef(
                        "fixture", "wrk.assignment", name, "r1").to_dict())
                path = root / (name + ".json")
                path.write_text(json.dumps(due.__dict__))
                apps[name] = SimpleNamespace(
                    runtime=SimpleNamespace(adapter=SimpleNamespace(
                        owner_transport_only=True, worktree=str(root / name))),
                    portfolio=SimpleNamespace(operations=operations),
                    binding=SimpleNamespace(authenticated_actor=lambda actor: actor),
                    actor="fixture",
                    _read=lambda schedule, path=path: Due(
                        **json.loads(path.read_text())),
                    _current=lambda ref, generation: SimpleNamespace(
                        ref=ResourceRef.from_dict(ref)))

            binding = HostCallerBinding(
                AuthenticatedActor("fixture", "caller", "credential"),
                ResourceRef("fixture", "wrk.assignment", "caller", "r1"),
                1, "fixture-adapter", "native-caller", "caller-schedule")
            context = {
                "principal": "caller", "generation": 1,
                "assignment_ref": binding.assignment_ref.to_dict(),
                "project_ref": project_ref,
                "native_session": {"id": "native-caller"}}
            first_started = threading.Event()
            queued = threading.Event()
            release = threading.Event()
            calls = {"first": 0, "second": 0}
            socket_path = root / "owner.sock"

            def effect(name):
                calls[name] += 1
                if name == "first":
                    first_started.set()
                    release.wait()
                return {"outcome": "succeeded"}

            def handler(request):
                name = request["schedule_id"]
                result = host.admit_execution(
                    apps[name], apps[name]._read(name),
                    lambda name=name: ExecutionHost.adapter_transport(
                        lambda: effect(name)))
                if name == "second":
                    queued.set()
                return result

            def make_host():
                return ExecutionHost(
                    directory=root / "ipc", socket_path=socket_path,
                    handler=handler, bounded_transports=True,
                    capacity_policy=CapacityPolicy(
                        turn_units=1, manager_reserve=0,
                        heavy_headroom=1, worker_floor=1),
                    caller_binding_reader=lambda ingress: binding,
                    caller_context_resolver=lambda caller: context,
                    caller_authorizer=lambda caller, request: True)

            def call(token, name):
                request = {
                    "command": "owner-execution", "operation": "start-prepared",
                    "schedule_id": name, "transport_request_id": token}
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.connect(str(socket_path))
                    client.sendall(json.dumps(request).encode() + b"\n")
                    client.shutdown(socket.SHUT_WR)
                    data = bytearray()
                    while part := client.recv(65536):
                        data.extend(part)
                return json.loads(data)

            host = make_host()
            host.start()
            replies = {}
            first = threading.Thread(
                target=lambda: replies.setdefault("first", call("1" * 32, "first")))
            first.start()
            first_started.wait()
            second = threading.Thread(
                target=lambda: replies.setdefault("second", call("2" * 32, "second")))
            second.start()
            queued.wait()
            self.assertFalse(host._owner_request(
                lambda: host._executions["second"]["running"]))

            host.begin_drain()
            closing = threading.Thread(target=host.close)
            closing.start()
            release.set()
            closing.join()
            first.join()
            second.join()
            self.assertEqual(replies["first"]["outcome"], "succeeded")
            held = replies["second"]
            self.assertEqual(held["outcome"], "held")
            self.assertIs(held["provider_called"], False)
            self.assertIs(held["effects_started"], False)
            self.assertEqual(calls, {"first": 1, "second": 0})
            self.assertEqual(apps["second"]._read("second").host_evidence, {})
            self.assertEqual(host._executions, {})
            self.assertEqual(host._capacity_holds, {})

            host = make_host()
            host.start()
            self.assertEqual(call("2" * 32, "second")["outcome"], "held")
            self.assertEqual(call("3" * 32, "second")["outcome"], "succeeded")
            self.assertEqual(call("3" * 32, "second")["outcome"], "succeeded")
            self.assertEqual(calls, {"first": 1, "second": 1})
            host.close()

    def test_preparation_crossing_drain_preserves_exact_admitted_transport(self):
        with tempfile.TemporaryDirectory() as root:
            entered, release, done = threading.Event(), threading.Event(), threading.Event()
            assignment_ref={'authority':'fixture','kind':'wrk.assignment','id':'worker'}
            project_ref=ResourceRef('fixture','work.project','project','p1').to_dict()
            task_ref=ResourceRef('fixture','work.task','task','t1').to_dict()
            task_payload={'project_ref':project_ref,'dependencies':[]}
            task_payload['metadata_namespaces']={'work.admission':authoring_stamp('t0',task_payload,'fixture')}
            task=SimpleNamespace(ref=ResourceRef.from_dict(task_ref),payload=task_payload)
            project=SimpleNamespace(ref=ResourceRef.from_dict(project_ref),payload={'dependencies':[]})
            class Reader:
                def get_record(self, ref):
                    if (ref.authority,ref.kind,ref.id)==('fixture','work.task','task'): return task
                    if (ref.authority,ref.kind,ref.id)==('fixture','work.project','project'): return project
                    return None
            class Graph:
                def list(self, **kwargs): return []
            due=Due(target={'project_ref':project_ref,'task_ref':task_ref},assignment_ref=assignment_ref)
            current=SimpleNamespace(ref=SimpleNamespace(to_dict=lambda:assignment_ref))
            operations=SimpleNamespace(_owner_reader=Reader(),port=Graph(),dependency_owner_actor=None)
            app=SimpleNamespace(runtime=SimpleNamespace(adapter=SimpleNamespace(worktree=root,owner_transport_only=True)),
                _read=lambda sid:due,_current=lambda ref,generation:current,
                portfolio=SimpleNamespace(operations=operations),binding=SimpleNamespace(authenticated_actor=lambda actor:actor),actor='fixture')
            calls=[]
            host=ExecutionHost(directory=Path(root)/'ipc',handler=lambda x:None,bounded_transports=True)
            def effect():
                calls.append(threading.get_ident());return 'exact-result'
            def prepare():
                entered.set();self.assertTrue(release.wait(5))
                def capture(value):
                    due.stop_state='completed';due.completion_state='succeeded';return value
                return after_owner(ExecutionHost.adapter_transport(effect),capture)
            host.handler=lambda request:host.admit_execution(app,due,prepare)
            host.start()
            result={}
            def submit():
                value=host._status_read({'command':'fixture'},lambda:host._owned(lambda:host.admit_execution(app,due,prepare)))
                host._status_read({'command':'observe'},lambda:value.then(lambda v:(result.update(value=v),done.set())))
            sender=threading.Thread(target=submit);sender.start()
            try:
                self.assertTrue(entered.wait(5));host.begin_drain()
                with self.assertRaisesRegex(RuntimeError,'draining'):
                    host.retain(name='unadmitted',operation=lambda:calls.append('wrong'))
                release.set();self.assertTrue(done.wait(5));sender.join(5)
                self.assertEqual(result,{'value':'exact-result'});self.assertEqual(len(calls),1)
                self.assertEqual(host._external_waiting,0);self.assertEqual(host._capacity_holds,{})
                with self.assertRaisesRegex(RuntimeError,'draining'):
                    host._status_read({'command':'new'},lambda:host._owned(lambda:host.admit_execution(app,Due(schedule_id='new',target={},assignment_ref={'authority':'f','id':'new'}),effect)))
            finally:
                release.set();host.close();sender.join(5)
    def test_unadmitted_rejection_releases_wait_counter_and_cannot_forge_job(self):
        with tempfile.TemporaryDirectory() as root:
            host=ExecutionHost(directory=root,handler=lambda x:None,bounded_transports=True);host.start();host.begin_drain()
            try:
                with self.assertRaisesRegex(RuntimeError,'draining'):
                    host._status_read({'command':'fixture'},lambda:host._owned(lambda:ExecutionHost.adapter_transport(lambda:None)))
                self.assertEqual(host._external_waiting,0)
                with self.assertRaises(PermissionError):
                    host.retain(name='forged',operation=lambda:None,_admitted_execution=(host,{'scope':{'schedule_id':'fake'},'running':True}))
            finally:host.close()
