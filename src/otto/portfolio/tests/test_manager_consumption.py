"""Exact ordinary-manager delivery consumption; disposable synthetic provider only."""
from dataclasses import replace
import copy
from types import SimpleNamespace
import unittest

from otto.portfolio.identity_context import HostIngress
from otto.portfolio.occurrence_reads import digest, handle
from otto.portfolio.worker_occurrences import manager_consumption_parent
from otto.portfolio.tests.test_worker_occurrences import WorkerOccurrenceTests


class ManagerConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = WorkerOccurrenceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.x, self.f = self.fixture, self.fixture.f
        request = dict(self.f.request(), request_key="ordinary-manager-child", principal="ordinary-leaf")
        request["instruction_contract"]["authority"]["owner_actor"] = "ordinary-leaf"
        request["instruction_contract"]["authority"]["workspace_roots"] = [str(self.x.root / "worker-lab")]
        started = self.f.app.assign_and_start(**request)
        self.assertEqual(started["outcome"], "succeeded", started)
        self.child = self.f.app._read(started["schedule_id"])
        self.assertIsNone(self.child.target.get("parent"))
        # The callback resumes the original manager launch, whose contract is
        # bound to the fixture root; the separately launched child uses worker-lab.
        self.f.app.runtime.adapter.worktree = str(self.x.root)
        self.f.app.runtime.adapter.source = str(self.x.root)
        self.f.app.runtime.adapter.writable_roots = (str(self.x.root),)
        delivered = self.f.app.continue_manager_from_worker(manager_schedule_id=self.x.server.state["schedule_id"],
            worker_schedule_id=self.child.schedule_id, execute=True)
        self.assertEqual(delivered["outcome"], "succeeded", delivered)
        self.callback = self.f.app._read(delivered["schedule_id"])
        self.context = {"role":"manager", "assignment_ref":self.callback.assignment_ref,
            "generation":self.callback.generation, "native_session":{"id":self.callback.target["native_id"]},
            "occurrence_ref":{"schedule_id":self.callback.schedule_id}}

    def test_actual_owner_report_and_repeat_preserve_launch_and_provider(self):
        live = replace(self.callback, stop_state="active", completion_state="none", delivery_state="ready")
        self.f.port.save_due(live.schedule_id, live.to_dict(), request_id="synthetic-live-manager",
            expected_version=self.callback.version)
        self.x.bindings["manager"] = self.x.binding(live)
        request = {"command":"consume-result", "occurrence":handle(self.child.to_dict())}
        calls = len(self.f.provider.calls)
        response = self.x.host._dispatch(request, ingress=HostIngress("synthetic-owner-caller", "manager"))
        self.assertEqual(response["parent_delivery"]["state"], "consumed", response)
        count = self.f.store.consumer().snapshot_counts()
        self.assertEqual(self.x.host._dispatch(request, ingress=HostIngress("synthetic-owner-caller", "manager")), response)
        self.assertEqual(self.f.store.consumer().snapshot_counts(), count)
        self.assertEqual(len(self.f.provider.calls), calls)
        retained = self.f.port.read_due(self.child.schedule_id)
        self.assertIsNone(retained["target"].get("parent"), "never rewrite the original null-parent launch")
        self.assertEqual(retained["target"], self.child.target)
        self.assertEqual(len(self.f.app.assignments.list_observations(self.x.manager.ref, kind="report")),1)
        denied = self.x.host._dispatch(request, ingress=HostIngress("file-ipc", self.x.host.directory/"owner"))
        self.assertEqual(denied["outcome"],"error")
        self.assertEqual(self.f.store.consumer().snapshot_counts(), count)
        self.assertEqual(len(self.f.provider.calls), calls)

    def test_exact_callback_anchor_allows_recovery_but_not_changed_or_missing_anchor(self):
        callback = self.callback.to_dict()
        caller = copy.deepcopy(callback)
        caller["schedule_id"] = "synthetic-recovery"
        caller["host_evidence"].pop("worker_result_continuation")
        caller["target"]["native_binding"] = {"schedule_id":callback["schedule_id"], "due_sha256":digest(callback)}
        context = {**self.context,"occurrence_ref":{"schedule_id":caller["schedule_id"]}}
        records = {caller["schedule_id"]:caller,callback["schedule_id"]:callback}
        service = SimpleNamespace(server=SimpleNamespace(state=self.x.server.state,owner=self.f.owner,
            due_port=SimpleNamespace(read_due=records.get), portfolio=self.f.app.portfolio))
        parent = manager_consumption_parent(service,context,self.child.to_dict())
        self.assertEqual(parent["callback_schedule_id"],callback["schedule_id"])
        callback["message"] = "changed exact record"
        with self.assertRaises(PermissionError):manager_consumption_parent(service,context,self.child.to_dict())
        records.pop(callback["schedule_id"])
        with self.assertRaises(PermissionError):manager_consumption_parent(service,context,self.child.to_dict())

    def test_foreign_identity_task_generation_native_or_join_rejected_without_effects(self):
        callback = self.callback.to_dict();child = self.child.to_dict()
        records = {callback["schedule_id"]:callback}
        service = SimpleNamespace(server=SimpleNamespace(state=self.x.server.state,owner=self.f.owner,
            due_port=SimpleNamespace(read_due=records.get), portfolio=self.f.app.portfolio))
        count = self.f.store.consumer().snapshot_counts()
        cases=[]
        for field,value in (("role","worker"),("generation",2),("assignment_ref",{**self.context["assignment_ref"],"id":"foreign"}),
                            ("native_session",{"id":"foreign"})):
            cases.append(({**self.context,field:value},copy.deepcopy(child),copy.deepcopy(callback)))
        for field,value in (("generation",2),("assignment_ref",{**callback["assignment_ref"],"id":"foreign"})):
            a=copy.deepcopy(callback);a[field]=value;cases.append((self.context,copy.deepcopy(child),a))
        for field in ("project_ref","reported_task_ref"):
            a=copy.deepcopy(callback);a["target"][field]={**a["target"][field],"id":"foreign"};cases.append((self.context,copy.deepcopy(child),a))
        for field in ("worker_result_sha256","physical_session_id","worker_schedule_id"):
            a=copy.deepcopy(callback);a["host_evidence"]["worker_result_continuation"][field]="foreign";cases.append((self.context,copy.deepcopy(child),a))
        a=copy.deepcopy(callback);a["host_evidence"].pop("worker_result_continuation");cases.append((self.context,copy.deepcopy(child),a))
        a=copy.deepcopy(child);a["target"]["parent"]={"unrelated":"coordinator"};cases.append((self.context,a,callback))
        a=copy.deepcopy(child);a["target"]["launch_request"]={"external_parent":{"id":"root"}};cases.append((self.context,a,callback))
        for context,due,anchor in cases:
            records[callback["schedule_id"]]=anchor
            with self.subTest(context=context,due=due["schedule_id"],anchor=anchor["target"].get("reported_task_ref")):
                with self.assertRaises(PermissionError):manager_consumption_parent(service,context,due)
        self.assertEqual(self.f.store.consumer().snapshot_counts(),count)

    def test_unverified_capture_held_without_report(self):
        live=replace(self.callback,stop_state="active",completion_state="none",delivery_state="ready")
        self.f.port.save_due(live.schedule_id,live.to_dict(),request_id="synthetic-live-held",expected_version=self.callback.version)
        self.x.bindings["manager"]=self.x.binding(live)
        raw=self.child.to_dict();raw["host_evidence"]["gateway_attempt"]["result"]["context_digest_verified"]=False
        self.f.port.save_due(self.child.schedule_id,raw,request_id="synthetic-uncaptured",expected_version=self.child.version)
        count=self.f.store.consumer().snapshot_counts();calls=len(self.f.provider.calls)
        response=self.x.host._dispatch({"command":"consume-result","occurrence":handle(raw)},ingress=HostIngress("synthetic-owner-caller","manager"))
        self.assertEqual(response["outcome"],"held",response)
        self.assertEqual(self.f.store.consumer().snapshot_counts(),count);self.assertEqual(len(self.f.provider.calls),calls)
