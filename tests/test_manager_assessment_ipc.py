"""Real owner assessment commands through nested file IPC; native transport is fake."""
from tests.execution_helpers import start_worker
import hashlib
import json
import threading
import time
import unittest

from herzchen.contracts import ResourceRef
from herzchen.domains.assessment import AssessmentModule
from herzchen.domains.work import WorkGraph
from herzchen.kernel.limits import LimitService
from otto.portfolio.completion_gate import completion_gate_from_command
from otto.portfolio.execution_operations import complete_task_from_command
from otto.portfolio.manager_assessment_command import (
    manager_assessment_from_command, manager_assessment_pool_from_command,
)
from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
from tests import test_manager_reentrant_ipc as reentrant


class ManagerAssessmentIPCTests(unittest.TestCase):
    reports, cleanup_host, wait_file, send, dispatch = (reentrant.ManagerReentrantIPCTests.reports, reentrant.ManagerReentrantIPCTests.cleanup_host,
                                                       reentrant.ManagerReentrantIPCTests.wait_file, reentrant.ManagerReentrantIPCTests.send, reentrant.ManagerReentrantIPCTests.dispatch)

    def setUp(self):
        reentrant.ManagerReentrantIPCTests.setUp(self)
        f = self.fixture
        self.assignment = ResourceRef.from_dict(f.app._read(self.anchor).assignment_ref)
        worker = start_worker(f.app, f.request())
        self.assertEqual(worker["outcome"], "succeeded", worker)
        self.candidate = f.app.assignments.list_observations(ResourceRef.from_dict(worker["assignment_ref"]), kind="result")[0]
        self.source = WorkGraph(f.store, actor=f.actor).create_task(f.project.ref,
            title="Pinned source", logical_request_key="assessment-source")
        self.tasks["PA05"] = self.source.ref.to_dict()
        owner = AssessmentModule(f.store, actor=f.actor)
        criteria = owner.declare_scope("original-project-criteria", parent_obligation=f.project.ref,
            protocol="original-criteria", criteria=[{"id": "original-C09", "definition": "observable correction"}],
            logical_request_key="original-criteria")
        self.criterion = criteria.criterion_refs[0]
        self.config = {"kind": "owner_local_bookkeeping", "purpose": "local test inspection", "local_only": True,
            "pool_ref": ResourceRef(f.actor.authority, "limit", "configured-local-inspection").to_dict(),
            "capacity_units": 1, "cumulative_allowance_units": 1,
            "scope_project_ref": f.project.ref.to_dict(),
            "task_criterion_pairs": [{"task": "PA02", "criterion": "quality"}]}
        self.policy = LocalAssessmentPolicy.from_config(self.config,
            task_refs=self.tasks, criterion_refs={"quality": self.criterion.to_dict()})
        pool_record = f.owner.create_manager_assessment_pool(
            project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            manager_assignment_ref=self.assignment.to_dict(), manager_actor="manager",
            manager_generation=1, logical_request_key="local-assessment-pool-v1", assessment_policy=self.policy,
        )
        self.pool = LimitService(f.store).get_pool(ResourceRef.from_dict(pool_record["pool"]))
        self.plan = self.directory.parent / "assessment-plan.json"
        self.native_child.write_text('''import importlib.util,json,sys,time
from pathlib import Path
paths=sys.argv[:]
spec=importlib.util.spec_from_file_location("owner_manager_ctl",paths[1]);c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
c.IPC=Path(paths[2]);c.STATUS_OWNER=c.IPC/"owner.json";c.SERVICE=c.IPC/"unused.sock"
Path(paths[5]).write_text(json.dumps({"ready":True}))
p=json.loads((Path(paths[2]).parent/"assessment-plan.json").read_text());results=[];refs={}
for entry in p["commands"]:
    request=json.loads(json.dumps(entry))
    if request.get("command")=="manager-assessment":
        for field,value in list(request["arguments"].items()):
            if isinstance(value,str) and value.startswith("$"):request["arguments"][field]=refs[value[1:]]
    # Parse the maintained CLI, then traverse its actual file IPC client.
    argv=["manager_ctl.py",request["command"]]
    for name,value in request.items():
        if name=="command":continue
        if isinstance(value,list):
            for item in value:argv += ["--"+name[:-1].replace("_","-"),str(item)]
        else:argv += ["--"+name.replace("_","-"),json.dumps(value) if isinstance(value,dict) else str(value)]
    original=c.call
    def capture(payload):
        response=original(payload);results.append(response);return response
    c.call=capture;sys.argv=argv
    try:c.main()
    except SystemExit as exc:
        if exc.code not in (0,1,None):raise
    c.call=original
    response=results[-1]
    if response.get("ref") and request.get("operation"):refs[request["operation"]]=response["ref"]
Path(paths[3]).write_text(json.dumps({"results":results,"refs":refs}))
deadline=time.monotonic()+10
while not Path(paths[4]).exists() and time.monotonic()<deadline:time.sleep(.01)
if not Path(paths[4]).exists():raise RuntimeError("manager release expired")
''')

    def request(self, operation, arguments, key=None):
        f = self.fixture
        return {"command": "manager-assessment", "task": "PA02", "operation": operation,
                "arguments": arguments, "request_key": key or "inspect-" + operation,
                "expected_task_ref": f.task.ref.to_dict(), "expected_assignment_ref": self.assignment.to_dict(),
                "expected_generation": 1}

    def commands(self, verdict="PASS"):
        scope = {"authority": self.fixture.actor.authority, "kind": "assessment.scope", "id": "task-inspection"}
        candidate, criterion = self.candidate.ref.to_dict(), self.criterion.to_dict()
        return [
            self.request("declare-scope", {"scope_ref": scope, "criterion_refs": [criterion], "protocol": "manager-retained-inspection"}),
            self.request("freeze-input", {"scope_ref": "$declare-scope", "candidate_ref": candidate,
                "criterion_refs": [criterion], "source_refs": [self.source.ref.to_dict()],
                "evidence_refs": [candidate], "packet": {"inspection": "Retained result and source inspected"}}),
            self.request("select-candidate", {"scope_ref": "$declare-scope", "candidate_ref": candidate,
                "criterion_ref": criterion, "rationale": "Exact owner result"}),
            self.request("assess", {"scope_ref": "$declare-scope", "candidate_ref": candidate,
                "criterion_ref": criterion, "input_ref": "$freeze-input", "verdict": verdict,
                "limit_pool_ref": self.pool.ref.to_dict(), "protocol_result": {"inspected": True}}),
            self.request("accept", {"result_ref": "$assess", "candidate_ref": candidate, "criterion_ref": criterion,
                "evidence_refs": [candidate], "rationale": "Observable retained correction inspected"}),
            self.request("coverage", {}),
        ]

    def handle(self, request):
        f = self.fixture
        if request["command"] == "manager-assessment":
            self.handler_threads.append(threading.get_ident())
            return manager_assessment_from_command(f.owner, request=request, policy=self.policy,
                state={"project_ref": f.project.ref.to_dict(), "task_refs": self.tasks,
                       "assignment_ref": self.assignment.to_dict(), "manager": "manager", "manager_generation": 1})
        if request["command"] == "manager-assessment-pool":
            self.handler_threads.append(threading.get_ident())
            return manager_assessment_pool_from_command(f.owner, request=request, policy=self.policy,
                state={"project_ref": f.project.ref.to_dict(), "task_refs": self.tasks,
                       "assignment_ref": self.assignment.to_dict(), "manager": "manager", "manager_generation": 1})
        if request["command"] == "completion-gate":
            self.handler_threads.append(threading.get_ident())
            return completion_gate_from_command(f.owner.assignments.command_port, request=request,
                task_ref=self.tasks[request["task"]], actor=f.actor)
        if request["command"] == "complete-task":
            self.handler_threads.append(threading.get_ident())
            return complete_task_from_command(f.app.portfolio, request=request,
                project_ref=f.project.ref.to_dict(), task_ref=self.tasks[request["task"]],
                manager_assignment_ref=self.assignment.to_dict(), manager_actor="manager", manager_generation=1)
        if request["command"] == "advisor-decision-state":
            self.handler_threads.append(threading.get_ident())
            return self.advisor.loop.read_decision(pairing=self.pairing, decision_id=request["decision_id"])
        return reentrant.ManagerReentrantIPCTests.handle(self, request)

    def run_commands(self, commands):
        self.plan.write_text(json.dumps({"commands": commands}))
        response = self.dispatch()
        deadline = time.monotonic() + 8
        while not self.child_receipt.exists() and not response.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(response.exists(), response.read_text() if response.exists() else "")
        child = self.wait_file(self.child_receipt)
        self.assertFalse(response.exists(), "native manager must still be waiting")
        self.assertEqual(len(set(self.handler_threads + self.mutation_threads)), 1)
        self.assertNotEqual(self.transport_threads[0], self.handler_threads[0])
        self.assertEqual(len(self.fixture.provider.calls), 3, "only fake manager/worker/continued native invocations")
        return response, child

    def finish(self, response):
        self.release.touch()
        self.assertEqual(self.wait_file(response)["outcome"], "succeeded")

    def gate(self, token, refs):
        digest = hashlib.sha256(json.dumps(self.candidate.value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        response = self.send(hashlib.sha256(token.encode()).hexdigest(), {"command": "completion-gate", "task": "PA02",
            "candidate_ref": json.dumps(self.candidate.ref.to_dict()),
            "gate_refs": [json.dumps(refs["accept"]) ] if "accept" in refs else [],
            "evidence_refs": [json.dumps(self.candidate.ref.to_dict())], "evidence_hashes": [digest]})
        return self.wait_file(response)

    def test_native_child_records_acceptance_before_return_then_normal_completion_succeeds(self):
        response, child = self.run_commands(self.commands())
        self.assertEqual([r["outcome"] for r in child["results"]], ["committed"] * 5 + ["read"])
        coverage = child["results"][-1]["coverage"]
        self.assertEqual(coverage["decisions"][0]["ref"], child["refs"]["accept"])
        self.assertEqual(coverage["decisions"][0]["author"], "manager")
        gate = self.gate("gate-clear", child["refs"])
        # The read-only predicate cannot verify native result evidence. The
        # existing completion owner verifies its sealed result/attempt chain.
        self.assertEqual(gate["eligibility"], "unknown", gate)
        self.assertEqual(gate["owner_gate_state"]["blockers"], [])
        self.assertEqual(gate["owner_gate_state"]["accepted_decision_refs"], [child["refs"]["accept"]])
        self.assertFalse(gate["acceptance_recorded"])
        self.assertFalse(response.exists())
        self.finish(response)
        digest = hashlib.sha256(json.dumps(self.candidate.value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        complete = self.send("abcdef123", {"command": "complete-task", "task": "PA02",
            "request_key": "complete-inspected-task", "disposition": "accepted",
            "evidence_refs": [json.dumps(self.candidate.ref.to_dict())], "evidence_hashes": ["native-result=" + digest],
            "gate_refs": [json.dumps(child["refs"]["accept"])], "candidate_ref": json.dumps(self.candidate.ref.to_dict())})
        completed = self.wait_file(complete)
        self.assertEqual(completed["outcome"], "completed", completed)
        self.assertEqual(completed["completion"]["assessment_gate_check"]["blockers"], [])
        self.assertEqual(LimitService(self.fixture.store).get_pool(self.pool.ref).cumulative_used_units, 1)

    def test_required_scope_survives_metadata_revision_but_rejects_task_content_edit(self):
        f = self.fixture
        task_pin = f.task.ref
        AssessmentModule(f.store, actor=f.actor).declare_scope(
            "content-bound-scope", parent_obligation=task_pin, protocol="manager-inspection",
            criteria=[self.criterion], designated_approver="manager", authority=f.actor.authority,
            policy={"required_for_completion": True}, logical_request_key="content-bound-scope")
        commands = f.owner.manager_assessment(
            project_ref=f.project.ref.to_dict(), task_ref=task_pin.to_dict(),
            manager_assignment_ref=self.assignment.to_dict(), manager_actor="manager",
            manager_generation=1, assessment_policy=self.policy)
        metadata_revision = WorkGraph(f.store, actor=f.actor).revise(
            task_pin, lifecycle="active", logical_request_key="assessment-metadata-revision", actor=f.actor)
        self.assertNotEqual(metadata_revision.ref, task_pin)
        self.assertIsNotNone(commands.required_scope())
        edited = WorkGraph(f.store, actor=f.actor).revise(
            metadata_revision.ref, title="Edited after activation",
            logical_request_key="assessment-authored-edit", actor=f.actor)
        self.assertNotEqual(edited.ref, metadata_revision.ref)
        with self.assertRaises(PermissionError):
            commands.required_scope()

    def test_local_pool_owner_setup_is_bounded_and_replay_safe(self):
        f = self.fixture
        created = f.owner.create_manager_assessment_pool(
            project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            manager_assignment_ref=self.assignment.to_dict(), manager_actor="manager",
            manager_generation=1, logical_request_key="local-assessment-pool-v1", assessment_policy=self.policy,
        )
        self.assertEqual(created["pool"], self.policy.pool_ref.to_dict())
        self.assertEqual(created["outcome"], "committed")
        self.assertEqual(created["capacity_units"], 1)
        self.assertEqual(created["cumulative_allowance_units"], 1)
        self.assertTrue(created["local_only"])
        self.assertEqual(created["remaining_allowance_units"], 1)

    def test_close_finding_is_owner_guarded_before_acceptance(self):
        f = self.fixture
        scope = {"authority": f.actor.authority, "kind": "assessment.scope", "id": "task-close-finding"}
        candidate, criterion = self.candidate.ref.to_dict(), self.criterion.to_dict()
        finding_ref = {"authority": f.actor.authority, "kind": "assessment.finding",
                       "id": "assess-close-finding-finding-0", "revision": None}
        commands = [
            self.request("declare-scope", {"scope_ref": scope, "criterion_refs": [criterion],
                "protocol": "manager-close-finding"}, key="declare-close-finding"),
            self.request("freeze-input", {"scope_ref": {"authority": f.actor.authority,
                "kind": "assessment.scope", "id": "task-close-finding", "revision": "rev-1"},
                "candidate_ref": candidate, "criterion_refs": [criterion],
                "source_refs": [self.source.ref.to_dict()], "evidence_refs": [candidate],
                "packet": {"inspection": "retained result with one explicitly closed finding"}},
                key="freeze-close-finding"),
            self.request("select-candidate", {"scope_ref": {"authority": f.actor.authority,
                "kind": "assessment.scope", "id": "task-close-finding", "revision": "rev-1"},
                "candidate_ref": candidate, "criterion_ref": criterion,
                "rationale": "select-close-finding"}, key="select-close-finding"),
            self.request("assess", {"scope_ref": {"authority": f.actor.authority,
                "kind": "assessment.scope", "id": "task-close-finding", "revision": "rev-1"},
                "candidate_ref": candidate, "criterion_ref": criterion,
                "input_ref": {"authority": f.actor.authority, "kind": "assessment.input",
                               "id": "freeze-close-finding", "revision": "rev-1"},
                "verdict": "PASS", "limit_pool_ref": self.pool.ref.to_dict(),
                "protocol_result": {"inspected": True},
                "findings": [{"summary": "bounded finding requiring explicit owner closure"}]},
                key="assess-close-finding"),
            self.request("close-finding", {"finding_ref": finding_ref,
                "evidence_refs": [candidate], "test_only": False,
                "rationale": "closed-by-retained-owner-evidence"}, key="close-finding"),
            self.request("accept", {"result_ref": {"authority": f.actor.authority,
                "kind": "assessment.result", "id": "assess-close-finding", "revision": "rev-1"},
                "candidate_ref": candidate, "criterion_ref": criterion,
                "evidence_refs": [candidate], "rationale": "accept-after-finding-close"},
                key="accept-close-finding"),
        ]
        response, child = self.run_commands(commands)
        self.assertEqual([r["outcome"] for r in child["results"]], ["committed"] * len(commands))
        self.assertEqual(child["results"][4]["operation"], "close-finding")
        self.assertEqual(child["results"][5]["operation"], "accept")
        self.finish(response)

    def test_read_only_advisor_decision_state_responds_during_native_wait(self):
        f = self.fixture
        from types import SimpleNamespace
        from otto.attention import DurableAttention
        from otto.portfolio.advisor_delivery import AdvisorDeliveryLoop, AdvisorDeliveryPorts
        from otto.portfolio.advisor_pairing import establish_pairing
        advisor = f.app.assignments.assign(f.project.ref, role="project_advisor", principal="advisor",
            manager="manager", session="advisor-session", pins=[], logical_request_key="read-only-advisor", actor=f.actor)
        def pairing(_project):
            values = [f.app.assignments.get(ref) for ref in (self.assignment, advisor.ref)]
            return establish_pairing(f.project.ref.to_dict(),
                [{**dict(value.payload), "ref": value.ref.to_dict()} for value in values],
                manager_conversation_ref={"host": "local", "native_id": "manager-session"},
                advisor_conversation_ref={"host": "local", "native_id": "advisor-session"})
        self.pairing = pairing(None)
        def forbidden(_delivery):
            raise AssertionError("read-only decision query must never deliver")
        self.advisor = SimpleNamespace(loop=AdvisorDeliveryLoop(AdvisorDeliveryPorts(
            assignments=f.app.assignments,
            attention=DurableAttention(f.owner.shared_attention_port(due_port=f.port), due_port=f.port),
            authenticate=f.binding.authenticated_actor, current_pairing=pairing,
            reports_for_project=lambda _project: self.reports(), role_delivery=forbidden)))
        limits, pool = LimitService(f.store), self.pool
        before = limits.get_pool(pool.ref)
        response, child = self.run_commands([{"command": "advisor-decision-state", "decision_id": "unobserved-decision"}])
        self.assertEqual(child["results"], [{"outcome": "unknown", "decision_id": "unobserved-decision"}])
        after = limits.get_pool(pool.ref)
        self.assertEqual((after.cumulative_used_units, after.held_units),
                         (before.cumulative_used_units, before.held_units))
        self.finish(response)

    def test_changed_consumed_input_cannot_be_accepted(self):
        commands = self.commands()
        commands.insert(4, {"command": "task-state", "task": "PA05", "lifecycle": "active", "request_key": "source-changed"})
        response, child = self.run_commands(commands)
        self.assertEqual(child["results"][5]["outcome"], "error")
        self.assertIn("stale", str(child["results"][5]))
        self.assertEqual(child["results"][-1]["coverage"]["decisions"], [])
        self.assertEqual(self.gate("gate-stale", child["refs"])["eligibility"], "blocked")
        self.finish(response)

    def test_unknown_is_not_accepted_and_replay_cannot_change_assessment_input(self):
        commands = self.commands("UNKNOWN")
        commands.insert(4, commands[3])  # exact logical-key replay
        changed = json.loads(json.dumps(commands[3]))
        changed["arguments"]["verdict"] = "PASS"
        commands.insert(5, changed)
        response, child = self.run_commands(commands)
        self.assertEqual(child["results"][3]["ref"], child["results"][4]["ref"])
        self.assertEqual(child["results"][5]["outcome"], "error")
        self.assertEqual(child["results"][6]["outcome"], "error")
        self.assertEqual(child["results"][-1]["coverage"]["decisions"], [])
        self.assertEqual(LimitService(self.fixture.store).get_pool(self.pool.ref).cumulative_used_units, 1)
        self.assertEqual(self.gate("gate-unknown", child["refs"])["eligibility"], "blocked")
        self.finish(response)

    def test_assignment_and_task_pins_and_actor_override_fail_before_mutation(self):
        original = self.commands()[0]
        commands = []
        for field,value in (("expected_task_ref", {**self.fixture.task.ref.to_dict(), "revision": "rev-999"}),
                            ("expected_assignment_ref", {**self.assignment.to_dict(), "revision": "rev-999"}),
                            ("expected_generation", 2)):
            commands.append({**original, field: value})
        commands.append({**original, "arguments": {**original["arguments"], "actor": "another-manager"}})
        commands.append(self.request("coverage", {}))
        response, child = self.run_commands(commands)
        self.assertEqual([r["outcome"] for r in child["results"]], ["error"] * 4 + ["read"])
        self.assertEqual(child["results"][-1]["coverage"]["scope_count"], 0)
        self.finish(response)

    def test_existing_designated_approver_is_enforced_by_the_owner(self):
        f = self.fixture
        scope = AssessmentModule(f.store, actor=f.actor).declare_scope("other-approver-scope",
            parent_obligation=f.task.ref, protocol="manager-retained-inspection", criteria=[self.criterion],
            designated_approver="another-approver", authority=f.actor.authority,
            policy={"required_for_completion": True}, logical_request_key="other-approver-scope")
        commands = self.commands()[1:]
        for command in commands:
            for field,value in list(command["arguments"].items()):
                if value == "$declare-scope":
                    command["arguments"][field] = scope.ref.to_dict()
        response, child = self.run_commands(commands)
        self.assertEqual(child["results"][3]["outcome"], "error")
        self.assertIn("designated approver", str(child["results"][3]))
        self.assertEqual(child["results"][-1]["coverage"]["decisions"], [])
        self.finish(response)
