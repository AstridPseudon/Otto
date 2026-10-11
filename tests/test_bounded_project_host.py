"""Five disposable project views; real owner/gateway/adapter, fake transport.

No provider, installed owner or operational database is opened by this fixture.
"""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import patch

from herzchen.contracts import HostIdentity, ResourceRef
from herzchen.content.instructions import validate_instruction_content
from herzchen.domains.work import WorkGraph
from otto.agents.herzchen_adapter import HerzchenCodexAdapter
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.herzchen_binding import ProjectReadGrant
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.project_services import ProjectServices
from tests import test_execution_application as fixture


class NativeFixture(fixture.Provider):
    def __init__(self):
        super().__init__()
        self.started, self.releases, self.counts = {}, {}, {}
        self.threads = []
        self.release_all = False
        self.unknown_principals = set()
        self.forced_sessions = {}
        self.active = {}
        self.peaks = {"total": 0, "manager": 0, "worker": 0}
        self.lock = threading.Lock()

    def binding(self, **options):
        outer = self

        class Binding(fixture.ProviderBinding):
            def execute(self, request):
                principal = request.identity.logical_agent_id
                if request.identity.physical_session_id is None:
                    request = replace(request, identity=HostIdentity(principal,
                        outer.forced_sessions.get(principal, "native-" + principal)))
                observed = super().execute(request)
                if not self.options.get("delivered_brief"):
                    return observed
                outer.threads.append(threading.get_ident())
                count = outer.counts.get(principal, 0) + 1
                outer.counts[principal] = count
                key = (principal, count)
                with outer.lock:
                    outer.active[key] = "manager" if principal.startswith("manager-") else "worker"
                    outer.peaks["total"] = max(outer.peaks["total"], len(outer.active))
                    for role in ("manager", "worker"):
                        outer.peaks[role] = max(outer.peaks[role], list(outer.active.values()).count(role))
                outer.started.setdefault(key, threading.Event()).set()
                release = outer.releases.setdefault(key, threading.Event())
                try:
                    if not outer.release_all and not release.wait(12):
                        raise RuntimeError("fixture transport was not released")
                    if principal in outer.unknown_principals:
                        receipt, _ = observed
                        return replace(receipt, outcome=fixture.HostOutcome.UNKNOWN), {"delivery_state": "unknown"}
                    return observed
                finally:
                    with outer.lock:
                        outer.active.pop(key)

        return Binding(self, options)

    def release(self, principal, turn=1):
        self.releases.setdefault((principal, turn), threading.Event()).set()

    def has_started(self, principal, turn=1):
        return self.started.get((principal, turn), threading.Event()).is_set()


class BoundedProjectHostTests(unittest.TestCase):
    manager_turn_limit = 2
    def setUp(self):
        self.f = f = fixture.ExecutionApplicationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.root = Path(f.temporary.name).resolve()
        graph = WorkGraph(f.store, actor=f.actor)
        projects = [graph.create_project(title="Project " + letter, logical_request_key="project-" + letter)
                    for letter in "ABCDE"]
        self.owner = PortfolioOwnerBootstrap(f.store, binding=f.binding, owner_actor="manager",
            project_read_grant=ProjectReadGrant(f.actor, tuple(project.id for project in projects), "fixture", "v1"))
        self.native = NativeFixture()
        self.directory = self.root / "ipc"
        self.host = ExecutionHost(directory=self.directory, handler=lambda request: None, bounded_transports=True,
            manager_turn_limit=self.manager_turn_limit)
        self.services, self.apps, self.states = {}, {}, {}
        self.saves, self.owner_threads = [], []
        self.owner_targets = {}
        for letter, project in zip("ABCDE", projects):
            task = graph.create_task(project.ref, title="Task " + letter, logical_request_key="task-" + letter)
            workspace = self.root / letter
            workspace.mkdir()
            (workspace / "run.yaml").write_text(json.dumps({"roles": {
                "worker_normal": {"model": "gpt-test", "reasoning": "high"},
                "worker_xhard": {"model": "gpt-test", "reasoning": "high"}}}))
            manager = "manager-" + letter

            def execution(*, principal, model, reasoning, evidence_id, workspace=workspace, manager=manager):
                adapter = HerzchenCodexAdapter(owner=principal, source=str(workspace), worktree=str(workspace),
                    launcher="fixture-only", requested_model=model, requested_reasoning=reasoning,
                    require_host_context=True, binding_factory=self.native.binding,
                    turn_context_reader=lambda session, turn: self.native.contexts.get((session, turn)))
                return self.owner.execution_application(due_port=f.port, adapter=adapter,
                    clock=lambda: fixture.NOW, manager_actor=manager)

            app = execution(principal=manager, model="gpt-test", reasoning="high", evidence_id="prepare")
            contract = f.request()["instruction_contract"]
            contract["task_ref"] = task.ref.to_dict()
            contract["authority"]["owner_actor"] = "seed-" + letter
            contract["authority"]["workspace_roots"] = [str(workspace)]
            seed = app.assign_worker(project_ref=project.ref.to_dict(), task_ref=task.ref.to_dict(),
                principal="seed-" + letter, request_key="seed-" + letter,
                instructions="Prepare fixture context", instruction_contract=contract,
                brief={"role": "worker", "mandate": "Fixture", "links": []}, model="gpt-test", reasoning="high")
            self.assertEqual(seed["outcome"], "committed", seed)
            guide = ResourceRef.from_dict(seed["guide_ref"])
            content = self.owner.content.read(guide)["content"]
            assignments = self.owner.assignments.command_port
            base = assignments.assign(project.ref, role="manager", principal=manager,
                manager=manager, session="native-" + manager, pins=[guide],
                logical_request_key="manager-assign-" + letter, actor=f.binding.authenticated_actor(manager))
            assigned = assignments.adopt_resources(base.ref,
                resources=[{"resource_ref": guide.to_dict(), "resource_name": content["name"],
                    "content_digest": validate_instruction_content(content), "required": True}],
                expected_revision=base.revision, expected_generation=base.generation,
                logical_request_key="manager-adopt-" + letter, actor=f.binding.authenticated_actor(manager))
            contract["authority"].update(owner_actor=manager, effect_profile="workspace-write-manager")
            contract["allowed_operations"].append("canonical_manager_commands")
            contract["authority"]["permitted_effects"].append("canonical_manager_commands")
            mandate = app.portfolio.create_document(project.ref.to_dict(), actor="manager",
                request_id="mandate-" + letter, document_id="mandate-" + letter, role="mandate",
                content={"role": "manager", "scope_ref": project.ref.to_dict(), "status": "active",
                    "dispatch_enabled": True, "task_ref": task.ref.to_dict(),
                    "assignment_ref": assigned.ref.to_dict(), "generation": assigned.generation,
                    "brief": {"role": "manager", "mandate": "Delegate and return"}, "instruction_contract": contract})
            mandate_ref = mandate["record"]["payload"]["current_revision"]
            prepared = app.prepare_role(role="manager", project_ref=project.ref.to_dict(), task_ref=task.ref.to_dict(),
                assignment_ref=assigned.ref.to_dict(), generation=1, mandate_ref=mandate_ref,
                context_refs=(guide.to_dict(), mandate_ref), request_key="manager-start-" + letter,
                instruction="Delegate bounded work and return", model="gpt-test", reasoning="high",
                profile="workspace-write", native_session_id="native-" + manager)
            state = {"authority": f.actor.authority, "owner": "manager", "manager": manager,
                "project_ref": project.ref.to_dict(), "task_refs": {"T": task.ref.to_dict()}, "criterion_refs": {},
                "assignment_ref": assigned.ref.to_dict(), "manager_generation": 1,
                "schedule_id": prepared["schedule_id"], "requested_model": "gpt-test", "requested_reasoning": "high"}
            server = SimpleNamespace(owner=self.owner, portfolio=app.portfolio, state=state,
                binding=f.binding, store=f.store, due_port=f.port, _execution=execution,
                _save_state=lambda letter=letter: self.saves.append(letter))

            def handle(request, state=state, execution=execution):
                self.owner_threads.append(threading.get_ident())
                if request["command"] == "start-manager":
                    return execution(principal=state["manager"], model="gpt-test", reasoning="high",
                        evidence_id=state["schedule_id"]).start(schedule_id=state["schedule_id"])
                if request["command"] == "fixture-read":
                    return {"outcome": "read", "project_ref": state["project_ref"],
                            "due": f.port.read_due(request["schedule_id"])}
                if request["command"] == "fixture-start":
                    due = f.port.read_due(request["schedule_id"])
                    if due["project_ref"] != state["project_ref"]["id"]:
                        raise PermissionError("foreign fixture occurrence")
                    return execution(principal=due["recipient"], model="gpt-test", reasoning="high",
                        evidence_id=due["schedule_id"]).start(schedule_id=due["schedule_id"])
                raise ValueError("unsupported fixture request")
            server.handle = handle
            self.services[letter] = ManagerJourneyService(server=server, host=self.host,
                run_path=workspace, workspace=workspace)
            self.apps[letter], self.states[letter] = app, state
        def owner_route(request):
            return self.owner_targets.get(request.pop("owner_ticket", None))
        self.router = ProjectServices(self.services, owner_route=owner_route)
        self.router.install()
        original = type(f.port).save_due
        def save(port, *args, **kwargs):
            self.owner_threads.append(threading.get_ident())
            return original(port, *args, **kwargs)
        self.save_patch = patch.object(type(f.port), "save_due", new=save)
        self.save_patch.start()
        self.addCleanup(self.save_patch.stop)
        self.host.start()
        self.addCleanup(self.close)
        self.serial = 0

    def close(self):
        self.native.release_all = True
        for event in list(self.native.releases.values()):
            event.set()
        self.host.close()

    def wait(self, predicate, detail="fixture condition"):
        deadline = time.monotonic() + 10
        while not predicate() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(predicate(), detail + ": " + repr(self.host.failures) + "; replies=" + repr([
            {k: value.get(k) for k in ("outcome", "error", "message", "stage", "reason")}
            for path in self.directory.glob("response-*.json") for value in [json.loads(path.read_text())]]))

    def send(self, letter, request):
        self.serial += 1
        token = f"{self.serial:032x}"
        ticket = "owner-ticket-" + token
        self.owner_targets[ticket] = letter
        if request["command"] not in ProjectServices._retained:
            request = {**request, "owner_ticket": ticket}
        path = self.directory / ("request-" + token + ".json")
        path.write_text(json.dumps(request))
        return self.directory / ("response-" + token + ".json")

    def response(self, path):
        self.wait(path.exists, str(path))
        return json.loads(path.read_text())

    def read(self, letter, schedule):
        return self.response(self.send(letter, {"command": "fixture-read", "schedule_id": schedule}))["due"]

    def delegate(self, letter):
        return self.response(self.send(letter, {"command": "run-worker", "task": "T", "route": "normal",
            "principal": "worker-" + letter, "request_key": "work-" + letter, "focus": "Implement only this project's bounded task"}))

    def test_five_projects_share_slots_and_A_settles_while_B_waits(self):
        starts = {letter: self.send(letter, {"command": "start-manager"}) for letter in "AB"}
        self.wait(lambda: all(self.native.has_started("manager-" + letter) for letter in "AB"))
        workers = {letter: self.delegate(letter) for letter in "AB"}
        self.assertTrue(all(value["outcome"] == "admitted" for value in workers.values()), workers)
        self.wait(lambda: self.native.has_started("worker-A"))
        active = self.host._owner_request(lambda: [value["scope"] for value in self.host._executions.values() if value["running"]])
        self.assertEqual(len(active), 3)
        self.assertEqual([row["role"] for row in active].count("manager"), 2)
        self.assertFalse(self.native.has_started("worker-B"))
        self.assertIsNone(self.read("B", workers["B"]["schedule_id"]).get("host_evidence", {}).get("gateway_attempt"))
        # Manager A returns, then its canonical result settles while B is live.
        self.native.release("manager-A")
        self.assertEqual(self.response(starts["A"])["outcome"], "succeeded")
        self.assertFalse(starts["B"].exists())
        self.wait(lambda: self.native.has_started("worker-B"))
        self.assertEqual(self.read("A", self.states["A"]["schedule_id"])["completion_state"], "succeeded")
        # A worker's captured result and owner callback also progress with B live.
        self.native.release("worker-A")
        settled = self.response(Path(workers["A"]["response_path"]))
        self.assertEqual(settled["outcome"], "succeeded", settled)
        self.assertIn("manager_result_notification", settled)
        self.assertFalse(starts["B"].exists())
        self.wait(lambda: self.native.has_started("manager-A", 2))
        self.native.release("manager-A", 2)
        for letter in "CDE":
            starts[letter] = self.send(letter, {"command": "start-manager"})
        self.native.release("manager-B")
        self.native.release("worker-B")
        for letter in "CDE":
            self.wait(lambda letter=letter: self.native.has_started("manager-" + letter))
            self.native.release("manager-" + letter)
            self.assertEqual(self.response(starts[letter])["outcome"], "succeeded")
        self.assertEqual(len(set(self.owner_threads)), 1)
        self.assertTrue(set(self.native.threads).isdisjoint(self.owner_threads))
        self.assertEqual(self.native.peaks, {"total": 3, "manager": 2, "worker": 2})
        for letter in "ABCDE":
            due = self.read(letter, self.states[letter]["schedule_id"])
            self.assertEqual(due["target"]["project_ref"]["id"], self.states[letter]["project_ref"]["id"])
            self.assertIn(str(self.services[letter].workspace), json.dumps(due["host_evidence"]["gateway_attempt"]))

    def test_unknown_cancel_restart_hold_original_capacity_without_replay(self):
        self.native.unknown_principals.add("manager-A")
        first = self.send("A", {"command": "start-manager"})
        self.wait(lambda: self.native.has_started("manager-A"))
        app = self.apps["A"]

        def prepare_second():
            due = app._read(self.states["A"]["schedule_id"])
            second = app.prepare_role(role="manager", project_ref=due.target["project_ref"],
                task_ref=due.target["task_ref"], assignment_ref=due.assignment_ref, generation=due.generation,
                mandate_ref=due.target["mandate_ref"], context_refs=due.context_refs, request_key="second-A",
                instruction="Second exact intent", model="gpt-test", reasoning="high", profile="workspace-write",
                native_session_id=due.target["native_id"])
            self.states["A"]["manager_continuation"] = {"schedule_id": second["schedule_id"]}
            return second
        second = self.host._owner_request(prepare_second)
        pending = self.send("A", {"command": "fixture-start", "schedule_id": second["schedule_id"]})
        self.wait(lambda: pending.with_name("pending-" + pending.name.removeprefix("response-")).exists())
        self.assertFalse(self.native.has_started("manager-A", 2))
        self.native.release("manager-A")
        self.assertEqual(self.response(first)["outcome"], "unknown")
        before = self.read("A", self.states["A"]["schedule_id"])
        self.assertIn(before["schedule_id"], self.host._capacity_holds)
        duplicate = self.response(self.send("A", {"command": "start-manager"}))
        self.assertEqual(duplicate["outcome"], "unknown")
        stopped = self.response(self.send("A", {"command": "execution-control", "operation": "stop",
            "schedule_id": before["schedule_id"], "request_key": "cancel-original", "expected_version": before["version"]}))
        self.assertEqual(stopped["record"]["stop_state"], "stopped", stopped)
        self.assertIn(before["schedule_id"], self.host._capacity_holds)
        self.host.close()
        self.assertFalse(pending.exists())
        self.host = ExecutionHost(directory=self.directory, handler=lambda request: None, bounded_transports=True)
        for service in self.services.values():
            service.host = self.host
        router = ProjectServices(self.services, owner_route=self.router.owner_route)
        recovered = router.install()
        self.router = router
        self.assertEqual(recovered["capacity_holds"], [before["schedule_id"]])
        self.host.start()
        for letter in "BCDE":
            started = self.send(letter, {"command": "start-manager"})
            self.wait(lambda letter=letter: self.native.has_started("manager-" + letter))
            self.native.release("manager-" + letter)
            self.assertEqual(self.response(started)["outcome"], "succeeded")
        after = self.read("A", before["schedule_id"])
        self.assertEqual(after["host_evidence"]["gateway_attempt"], before["host_evidence"]["gateway_attempt"])
        self.assertEqual(self.native.counts["manager-A"], 1)
        self.assertFalse(pending.exists())
        self.assertIsNone(self.read("A", second["schedule_id"]).get("host_evidence", {}).get("gateway_attempt"))

    def test_authenticated_projects_and_adapters_cannot_cross_views(self):
        from otto.portfolio.identity_context import HostIngress
        starts = {letter: self.send(letter, {"command": "start-manager"}) for letter in "AB"}
        self.wait(lambda: all(self.native.has_started("manager-" + letter) for letter in "AB"))
        def bindings():
            return {letter: self.router.managed_caller_binding(self.f.port.read_due(self.states[letter]["schedule_id"])
                ["host_evidence"]["gateway_attempt"]["delivery_authorization"]) for letter in "AB"}
        bindings = self.host._owner_request(bindings)
        self.host.caller_binding_reader = lambda ingress: bindings[ingress.handle]
        self.host.owner_file_compatibility = True
        self.host.caller_context_resolver = self.router.caller_context
        def native(letter, request):
            return self.host._dispatch(request, ingress=HostIngress("fixture-authenticated-native", letter))
        for letter in "AB":
            identity = native(letter, {"command": "whoami"})
            self.assertEqual(identity["caller_context"]["project_ref"], self.states[letter]["project_ref"])
            self.assertEqual(identity["caller_context"]["principal"], "manager-" + letter)
        denied = native("A", {"command": "whoami", "caller_assignment_ref": self.states["B"]["assignment_ref"]})
        self.assertFalse(denied["effects_started"])
        stale = bindings["A"]
        bindings["A"] = replace(stale, generation=2)
        self.assertEqual(native("A", {"command": "whoami"})["outcome"], "error")
        bindings["A"] = stale
        denied = native("A", {"command": "manager-continue", "operation": "dispatch", "report_key": "self"})
        self.assertFalse(denied["effects_started"], denied)
        self.assertIn("prepare work and return", denied["message"])
        service = self.services["A"]
        factory = service._host_execution
        service._host_execution = self.services["B"]._host_execution
        try:
            denied = self.response(self.send("A", {"command": "execution-control", "operation": "read",
                "schedule_id": self.states["A"]["schedule_id"]}))
            self.assertIn("fixed project view", denied["message"])
        finally:
            service._host_execution = factory
        self.assertEqual(len(self.native.calls), 2)

    def test_provider_cannot_reuse_another_projects_live_native_session(self):
        first = self.send("A", {"command": "start-manager"})
        self.wait(lambda: self.native.has_started("manager-A"))
        self.native.forced_sessions["seed-B"] = "native-manager-A"
        seed = self.host._owner_request(lambda: next(row for row in self.f.port.list_due(
            {"project_ref": self.states["B"]["project_ref"]["id"], "role": "worker"})))
        blocked = self.response(self.send("B", {"command": "fixture-start", "schedule_id": seed["schedule_id"]}))
        self.assertNotEqual(blocked["outcome"], "succeeded", blocked)
        due = self.read("B", seed["schedule_id"])
        self.assertNotIn("delivery_authorization", due["host_evidence"]["gateway_attempt"])
        self.assertFalse(self.native.has_started("seed-B"))
        self.assertEqual(len(self.native.calls), 1)
        self.assertFalse(first.exists())

    def test_pending_child_survives_restart_and_returns_to_exact_parent_with_B_live(self):
        from otto.portfolio.identity_context import HostIngress

        def prepare_parent():
            contract = self.f.request()["instruction_contract"]
            contract["task_ref"] = self.states["A"]["task_refs"]["T"]
            contract["authority"].update(owner_actor="coordinator-A",
                workspace_roots=[str(self.services["A"].workspace)])
            contract["delegation"] = {"max_depth": 1, "result_consumption": "yield"}
            contract["allowed_operations"].append("canonical_child_commands")
            contract["authority"]["permitted_effects"].append("canonical_child_commands")
            parent = self.apps["A"].assign_worker(project_ref=self.states["A"]["project_ref"],
                task_ref=contract["task_ref"], principal="coordinator-A", request_key="coordinator-A",
                instructions="Delegate one finite child, yield and consume its result", instruction_contract=contract,
                brief={"role": "worker", "mandate": "Coordinate one child", "links": []}, model="gpt-test", reasoning="high")
            self.states["A"]["workers"] = {"T": {**parent, "principal": "coordinator-A", "model": "gpt-test", "reasoning": "high"}}
            self.services["A"].delegation_policy = {"coordinators": [{"assignment_ref": parent["assignment_ref"],
                "generation": parent["generation"], "native_adapter": self.apps["A"].native_adapter_identity()}],
                "max_depth": 1, "capacity_units": 1, "cumulative_allowance_units": 8}
            return parent

        parent = self.host._owner_request(prepare_parent)
        self.assertEqual(parent["outcome"], "committed", parent)
        outer = self
        class Ingress:
            def __call__(self, ingress):
                due = outer.f.port.read_due(ingress.handle)
                return outer.router.managed_caller_binding(due["host_evidence"]["gateway_attempt"]["delivery_authorization"])

            def live_occurrence(self, schedule):
                return bool(outer.host._executions.get(schedule, {}).get("running"))

        self.host.caller_binding_reader = Ingress()
        self.host.owner_file_compatibility = True
        started = self.send("A", {"command": "fixture-start", "schedule_id": parent["schedule_id"]})
        self.wait(lambda: self.native.has_started("coordinator-A"))
        child = self.host._dispatch({"command": "run-worker", "task": "T", "route": "normal", "principal": "leaf-A",
            "request_key": "child-A", "focus": "Inspect one bounded seam and return the result"},
            ingress=HostIngress("fixture-authenticated-native", parent["schedule_id"]))
        self.assertEqual(child["outcome"], "prepared", child)
        pending = self.directory / ("pending-" + child["start"] + ".json")
        self.wait(pending.exists)
        self.assertFalse(self.native.has_started("leaf-A"))
        closing = threading.Thread(target=self.host.close)
        closing.start()
        self.wait(lambda: self.host.draining)
        self.native.release("coordinator-A")
        closing.join(10)
        self.assertFalse(closing.is_alive())
        self.assertEqual(self.response(started)["outcome"], "succeeded")
        self.assertTrue((self.directory / ("request-" + child["start"] + ".json")).exists())
        self.host = ExecutionHost(directory=self.directory, handler=lambda request: None,
            bounded_transports=True, caller_binding_reader=Ingress(),
            caller_context_resolver=self.router.caller_context, owner_file_compatibility=True)
        for service in self.services.values():
            service.host = self.host
        self.router = ProjectServices(self.services, owner_route=self.router.owner_route)
        self.assertEqual(self.router.install()["capacity_holds"], [])
        self.host.start()
        b = self.send("B", {"command": "start-manager"})
        self.wait(lambda: self.native.has_started("leaf-A") and self.native.has_started("manager-B"))
        self.assertEqual(self.native.counts["coordinator-A"], 1)
        self.native.release("leaf-A")
        returned = self.response(Path(child["response_path"]))
        self.assertEqual(returned["outcome"], "succeeded", returned)
        self.wait(lambda: self.native.has_started("coordinator-A", 2))
        callback_schedule = self.host._owner_request(lambda: next(key for key, job in self.host._executions.items()
            if job["running"] and key.startswith("parent-consume-")))
        consume = {"command": "consume-result", "occurrence": child["occurrence"]}
        foreign = self.host._dispatch(consume, ingress=HostIngress("fixture-authenticated-native", self.states["B"]["schedule_id"]))
        self.assertEqual(foreign["outcome"], "error", foreign)
        consumed = self.host._dispatch(consume, ingress=HostIngress("fixture-authenticated-native", callback_schedule))
        self.assertEqual(consumed["parent_delivery"]["state"], "consumed", consumed)
        evidence = self.host._owner_request(lambda: self.f.port.read_due(child["schedule_id"])
            ["host_evidence"]["parent_consumption"]["evidence"])
        self.assertEqual(evidence["caller_assignment_ref"], parent["assignment_ref"])
        self.assertFalse(b.exists())
        self.native.release("coordinator-A", 2)
        callback = self.response(Path(returned["parent_return"]["response_path"]))
        self.assertEqual(callback["outcome"], "succeeded", callback)
        self.assertEqual(self.native.counts["leaf-A"], 1)
        self.assertEqual(self.states["A"]["workers"]["T"]["schedule_id"], parent["schedule_id"])
        self.assertEqual(len(set(self.owner_threads[-10:])), 1)

    def test_drain_finishes_capture_and_fences_conflicting_source_writers(self):
        # Two worker views intentionally share a checkout; the second must
        # remain unattempted even though the global pool has free capacity.
        first = self.delegate("A")
        self.wait(lambda: self.native.has_started("worker-A"))
        def second_app():
            app = self.apps["B"]
            app.runtime.adapter.worktree = str(self.services["A"].workspace)
            return app
        app = self.host._owner_request(second_app)
        seed = self.host._owner_request(lambda: next(row for row in self.f.port.list_due(
            {"project_ref": self.states["B"]["project_ref"]["id"], "role": "worker"})))
        # Same immutable prepared seed, with host-selected writer scope. Its
        # mismatching contract must still fail if ever admitted after release.
        held = self.host._owner_request(lambda: app.start(schedule_id=seed["schedule_id"]))
        self.wait(lambda: seed["schedule_id"] in self.host._executions)
        self.assertFalse(self.host._executions[seed["schedule_id"]]["running"])
        self.assertFalse(held.done)
        closing = threading.Thread(target=self.host.close)
        closing.start()
        self.wait(lambda: self.host.draining)
        self.assertTrue(closing.is_alive())
        self.native.release("worker-A")
        closing.join(10)
        self.assertFalse(closing.is_alive())
        captured = self.response(Path(first["response_path"]))
        self.assertEqual(captured["outcome"], "succeeded")
        notice = captured["manager_result_notification"]
        self.assertEqual(notice["outcome"], "admitted")
        self.assertTrue((self.directory / ("request-" + notice["retained_handle"] + ".json")).exists())
        self.assertFalse(Path(notice["response_path"]).exists())
        with self.assertRaisesRegex(RuntimeError, "lane is closed"):
            self.host._owner_request(lambda: None)
        self.assertFalse(self.native.has_started("seed-B"))
        self.assertIsNone(self.f.port.read_due(seed["schedule_id"]).get("host_evidence", {}).get("gateway_attempt"))


class ExistingCustodyReleaseTests(unittest.TestCase):
    def test_only_verified_existing_disposition_releases_a_failed_turn(self):
        from tests.test_worker_custody import WorkerCustodyTests
        fixture = WorkerCustodyTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        host = ExecutionHost(directory=Path(fixture.f.temporary.name) / "bounded-ipc",
            handler=lambda request: None, bounded_transports=True)
        app = fixture.f.app
        host.restore_execution(app, app._read(fixture.schedule))
        self.assertIn(fixture.schedule, host._capacity_holds)
        fixture.release()
        host.restore_execution(app, app._read(fixture.schedule))
        self.assertNotIn(fixture.schedule, host._capacity_holds)
        fixture.trace.write_text(fixture.trace.read_text() + fixture.trace.read_text())
        host.restore_execution(app, app._read(fixture.schedule))
        self.assertIn(fixture.schedule, host._capacity_holds)
        self.assertEqual(fixture.f.provider.calls, [])
