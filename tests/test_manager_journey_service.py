"""Exercise the delivered service handler with only its provider substituted."""
from datetime import timedelta
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from herzchen.domains.work.admission import authoring_stamp
from herzchen.domains.assessment import AssessmentModule
from herzchen.domains.work import WorkGraph
from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
from otto.portfolio.execution_host import ExecutionAdmissionHeld, ExecutionHost
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.hostctl.serve import HostOwnerService
from tests import test_manager_service_continuation as continuation
from tests.test_execution_application import ProviderBinding, NOW


def test_effective_manager_brief_composes_base_project_and_manager_notes():
    from otto.portfolio.role_context import effective_context_projection
    project = {"authority": "owner", "kind": "work.project", "id": "project-current", "revision": "p2"}
    assignment = {"authority": "owner", "kind": "wrk.assignment", "id": "manager-current", "revision": "a4"}
    canonical = {"role": "manager", "base_resource": {}, "supporting_context": [],
        "direction_context": [], "render": {
            "project_state": {"project": {"ref": project, "payload": {"title": "Current Project"}}, "task": None},
            "snapshot": {"assignment_ref": assignment, "mandate_ref": {"id": "brief-1"}, "generation": 4},
            "brief": {"mandate": "Deliver the signed release.", "user_constraints": ["No external publish."],
                "priorities": [{"id": "p1", "text": "Complete review."}],
                "operational_constraints": ["Use the existing worker route."],
                "continuation": {"next_action": "review"}, "links": []}}}
    effective = effective_context_projection(canonical, tool_entrypoint="otto manager")
    brief = effective["effective_manager_brief"]
    assert brief["project_ref"] == project
    assert brief["assignment_ref"] == assignment
    assert brief["generation"] == 4
    assert brief["project_brief"]["mandate"] == "Deliver the signed release."
    assert brief["manager_notes"]["priorities"][0]["id"] == "p1"
    assert brief["manager_notes"]["continuation"]["next_action"] == "review"
    assert brief["base_manager_brief"]["schema"] == "otto.base-manager-brief.v1"
    assert "Wake for judgment events" in brief["base_manager_brief"]["constraints"][-1]


class ManagerJourneyServiceTests(unittest.TestCase):
    reports = continuation.ManagerServiceContinuationTests.reports

    def setUp(self):
        continuation.ManagerServiceContinuationTests.setUp(self)
        root = Path(__file__).resolve().parents[1]
        self.root = Path(self.fixture.temporary.name).resolve()
        self.service = SimpleNamespace(RUN=self.root / "run")
        self.service.RUN.mkdir()
        self.directory = self.root / "projects" / self.fixture.project.id / "manager-ipc"
        application = self.fixture
        scope = AssessmentModule(application.store, actor=application.actor).declare_scope("criteria",
            parent_obligation=application.project.ref, protocol="fixture",
            criteria=[{"id": "C01", "source_alias": "C01"}],
            logical_request_key="journey-criteria")
        run_config = {"run_id": "manager-journey-fixture", "roles": {
            "manager": {"model": "gpt-test", "reasoning": "high"},
            "worker_normal": {"model": "gpt-test", "reasoning": "high"},
            "worker_xhard": {"model": "gpt-test", "reasoning": "high"}},
            "worker_operation_profiles": {}, "assessment_accounting": {
            "kind": "owner_local_bookkeeping", "local_only": True, "purpose": "isolated journey",
            "pool_id": "journey-local", "capacity_units": 1, "cumulative_allowance_units": 1,
            "task_criterion_pairs": ["J01/C01"]}}
        run_doc = application.app.portfolio.create_document(application.project.ref.to_dict(), actor="manager",
            request_id="journey-run-config", document_id="journey-run-config", role="SOURCE",
            visibility="shared", content=run_config)
        application.app.portfolio.link_document(application.project.ref.to_dict(),
            {key: value for key, value in run_doc["document_ref"].items() if key != "revision"}, actor="manager",
            request_id="journey-run-config-link", namespace="project.files", key="run.json")
        (self.service.RUN / "run.json").write_text(json.dumps({
            "run_id": "manager-journey-fixture", "roles": {
                "manager": {"model": "gpt-test", "reasoning": "high"},
                "worker_normal": {"model": "gpt-test", "reasoning": "high"},
                "worker_xhard": {"model": "gpt-test", "reasoning": "high"}},
            "worker_operation_profiles": {}, "assessment_accounting": run_config["assessment_accounting"]}))
        state = {"authority": application.actor.authority, "owner": "manager", "manager": "manager",
                 "project_ref": application.project.ref.to_dict(), "task_refs": {"J01": application.task.ref.to_dict()},
                 "criterion_refs": {}, "assignment_ref": application.app._read(self.anchor).assignment_ref,
                 "manager_generation": 1, "schedule_id": self.anchor,
                 "requested_model": "gpt-test", "requested_reasoning": "high",
                 "manager_continuation": {"schedule_id": self.anchor,
                                          "native_session_id": "manager-session"}}
        state["schema"] = "otto.host-service-state.v1"
        state["run_id"] = "manager-journey-fixture"
        state["mandate_ref"] = application.app._read(self.anchor).target["mandate_ref"]
        state_path = self.root / "projects" / application.project.id / "service-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state))
        record = SimpleNamespace(ref=application.project.ref, payload={"tasks": [], "custom": {}})

        def adapter_factory(*, principal, model, reasoning, service=None, worker_mcp=None,
                            workspace=None, source=None, roles=("worker", "manager")):
            # The real owner chooses the adapter here; the adapter's binding factory is the fake model.
            return application.app.runtime.adapter

        session = SimpleNamespace(
            config={"home": str(self.root), "store": {"authority": application.store.authority}},
            owner=application.owner, due_port=application.port, binding=application.binding,
            store=application.store, native_bodies=None,
            execution_application=lambda adapter, manager_actor=None: application.app)
        self.server = HostOwnerService(session, record, command_lock=threading.RLock(), adapter_factory=adapter_factory,
            worker_mcp_provider=lambda due: {"fixture_grant": due["assignment_ref"]["id"]},
            worker_lab_provider=lambda project, task: {"workspace": str(self.root)},
            worker_context_provider=lambda due: {"workspace": str(self.root)})
        self.fixture.provider.work_started = threading.Event()
        self.fixture.provider.work_release = threading.Event()
        from otto.portfolio.manager_journey_service import install_manager_journey_service
        self.host = self.server.execution_host
        install_manager_journey_service(self.server, run_path=self.service.RUN, workspace=self.root,
            orchestrator_principal="manager", observe_schedules=lambda project: {
                "mode": "no-owned-schedule", "pm_owned_schedule_ids": [],
                "coverage": {"project": project, "fixture": "no schedule automation configured"},
                "shared_records": []})
        self.host.start()
        self.fixture.provider.manager_env = dict(os.environ, PYTHONPATH=str(root / "src"),
            OTTO_MANAGER_IPC=str(self.directory), OTTO_CALLER_SOCKET=str(self.host.socket_path),
            OTTO_PROJECT="manager-journey-fixture")
        manager = '''import json,os,sys
from otto.hostctl.manager_client import run_launched
for line in sys.stdin:
    request=json.loads(line); argv=[request.pop("command")]
    for key,value in request.items():
        if key=="finish":
            if value is False: argv.append("--review-only")
            continue
        if key=="source_refs":
            for item in value: argv.extend(("--source-ref",json.dumps(item)))
            continue
        flag="--"+key.replace("_","-")
        if isinstance(value,bool):
            if value: argv.append(flag)
        else: argv.extend((flag,json.dumps(value) if isinstance(value,(dict,list)) else str(value)))
    try: result=run_launched(argv,os.environ)
    except BaseException as exc: result={"outcome":"error","error":type(exc).__name__,"message":str(exc)}
    print(json.dumps(result),flush=True)
'''
        process = subprocess.Popen([sys.executable, "-u", "-c", manager], env=self.fixture.provider.manager_env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        due = application.port.read_due(self.anchor)
        authorization = (due.get("host_evidence") or {}).get("gateway_attempt", {}).get("delivery_authorization")
        self.assertIsInstance(authorization, dict, "the fixture manager turn must retain owner authorization")
        self.fixture.provider.manager_release = self.server.native_callers.observe(process, authorization)
        self.fixture.provider.manager_process = process
        self.addCleanup(self.close_host)

    def close_host(self):
        self.fixture.provider.work_release.set()
        process = self.fixture.provider.manager_process
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if self.fixture.provider.manager_release is not None:
            self.fixture.provider.manager_release()
        self.host.close()

    def send(self, token, request):
        (self.directory / ("request-" + token + ".json")).write_text(json.dumps(request))
        return self.directory / ("response-" + token + ".json")

    def send_caller(self, token, request):
        """Run an identity-bearing manager command through the maintained caller client."""
        result = self.root / ("caller-" + token + ".json")
        process = self.fixture.provider.manager_process
        self.assertIsNotNone(process, "the fixture manager process must remain registered")
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        result.write_text(process.stdout.readline())
        return result

    def wait_response(self, path):
        deadline = time.monotonic() + 15
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(path.exists(), str(path))
        return json.loads(path.read_text())

    def worker_request(self):
        return {"command": "run-worker", "task": "J01", "route": "xhard", "principal": "worker",
                "request_key": "service-j01", "focus": "Inspect the bounded J01 seam"}

    def seed_historical_instruction_acceptance(self, *, key, pool_id=None):
        """Persist the formerly accepted instruction-only completion as owner history."""
        from herzchen.kernel.limits import LimitService
        from otto.portfolio.manager_journey_command import _digest

        f = self.fixture
        due = f.app._read(self.anchor)
        candidate = ResourceRef.from_dict(due.target["mandate_ref"])
        content = f.owner.content.read(candidate)["content"]
        assessment = AssessmentModule(f.store, actor=f.actor)
        scope = assessment.declare_scope(key + "-scope", parent_obligation=f.task.ref,
            protocol="historical-instruction-only", criteria=[{"id": "C01", "source_alias": "C01"}],
            designated_approver="manager", policy={"required_for_completion": True},
            logical_request_key=key + "-scope")
        packet = assessment.freeze_input(scope.ref, packet={"observed": "historical instruction document accepted"},
            consumed_refs=[candidate], logical_request_key=key + "-input")
        pool = LimitService(f.store).create_pool(
            ResourceRef(f.actor.authority, "limit", pool_id or key + "-allowance"), capacity_units=1,
            cumulative_allowance_units=1, logical_request_key=key + "-allowance", actor=f.actor)
        judged = assessment.assess(scope.ref, candidate=candidate, criterion=scope.criterion_refs[0],
            input_packet=packet.ref, verdict="PASS", limit_pool=pool.ref, logical_request_key=key + "-judgment")
        gate = assessment.accept(judged.ref, rationale="Historical instruction accepted",
            evidence_refs=[candidate], logical_request_key=key + "-acceptance")
        f.app.assignments.complete(f.task.ref, project=f.project.ref, assignment=due.assignment_ref,
            expected_generation=due.generation, expected_project_revision=f.project.ref.revision,
            expected_task_revision=f.task.ref.revision, disposition="accepted", evidence_refs=[candidate.to_dict()],
            evidence_hashes={candidate.kind + ":" + candidate.id + ":" + candidate.revision: _digest(content)},
            gate_refs=[gate.ref.to_dict()], candidate_ref=candidate.to_dict(),
            logical_request_key=key + "-completion", actor=f.actor)
        task = f.owner.graph.current(f.task.ref)
        project_ref = ResourceRef.from_dict(self.server.state["project_ref"])
        self.server.state["project_ref"] = f.owner.graph.current(
            ResourceRef(project_ref.authority, project_ref.kind, project_ref.id)).ref.to_dict()
        self.server.state["task_refs"]["J01"] = task.ref.to_dict()
        self.server._save_state()
        return task, pool.ref

    def test_worker_preparation_rejects_host_principal_before_assignment_write(self):
        self.install_candidate()
        with patch.object(self.fixture.app, "assign_worker", wraps=self.fixture.app.assign_worker) as assign:
            result_path = self.send("reserved-worker", {**self.worker_request(), "principal": "orchestrator"})
            result = self.wait_response(result_path)
        self.assertNotEqual(result.get("outcome"), "admitted", result)
        assign.assert_not_called()
        self.assertNotIn("J01", self.server.state.get("workers", {}))

    def test_manager_actions_are_authenticated_project_scoped_and_save_notes(self):
        self.install_candidate()
        service = self.host.handler
        state = self.server.state
        caller = {"role": "manager", "principal": state["manager"],
            "project_ref": state["project_ref"], "assignment_ref": state["assignment_ref"],
            "generation": state["manager_generation"]}
        saved = service.dispatch_bound(caller, {"command": "save", "request_key": "tool-note-1",
            "task": "J01", "note": "Keep the exact returned worker evidence for review."})
        self.assertEqual(saved["outcome"], "saved", saved)
        reports = self.reports()
        note = next(item["value"] for item in reports if item["value"].get("schema") == "otto.manager-note.v1")
        self.assertEqual(note["project_ref"], state["project_ref"])
        self.assertEqual(note["assignment_ref"], state["assignment_ref"])
        self.assertEqual(note["generation"], state["manager_generation"])
        shown = service.dispatch_bound(caller, {"command": "show"})
        self.assertIn(shown["outcome"], {"read", "listed", "partial"}, shown)
        self.assertFalse(shown["provider_called"])
        self.assertEqual(shown["project_role_identity"]["project_ref"], state["project_ref"])
        self.assertEqual(shown["project_role_identity"]["role"], "manager")
        foreign_caller = {**caller, "project_ref": {**state["project_ref"], "id": "foreign-project"}}
        with self.assertRaises(PermissionError):
            service.dispatch_bound(foreign_caller, {"command": "show"})
        effective_brief = shown["effective_context"].get("effective_manager_brief", {})
        if effective_brief:
            self.assertEqual(effective_brief["project_ref"], state["project_ref"])
            self.assertEqual(effective_brief["base_manager_brief"]["schema"], "otto.base-manager-brief.v1")
            self.assertEqual(effective_brief["manager_notes"]["saved_notes"][0]["note"],
                "Keep the exact returned worker evidence for review.")
        with self.assertRaises(ValueError):
            service.dispatch_bound(caller, {"command": "show", "project_ref": {"id": "foreign"}})
        with self.assertRaises(ValueError):
            service.dispatch_bound(caller, {"command": "save", "request_key": "tool-note-2",
                "task": "FOREIGN", "note": "Must remain scoped."})

    def test_answer_and_route_actions_reuse_existing_owner_paths(self):
        self.install_candidate()
        state = self.server.state
        f = self.fixture
        portfolio = ResourceRef(f.actor.authority, "wrk.portfolio", "journey-portfolio")
        root_actor = f.binding.authenticated_actor("root")
        root = f.owner.assignments.command_port.assign(portfolio, role="orchestrator", principal="root",
            session="journey-root-session", logical_request_key="journey-root", actor=root_actor)
        from herzchen.domains.work import register_orchestration
        from herzchen.domains.work.orchestration import Orchestration
        register_orchestration(f.store)
        orchestration = Orchestration(f.store, actor=root_actor, operator_actor=root_actor,
            portfolio_ref=portfolio, main_assignment_ref=root.ref, expected_main_principal="root")
        f.owner.orchestration_port = orchestration.command_port
        f.owner.orchestration_portfolio = portfolio
        project_ref = ResourceRef.from_dict(state["project_ref"])
        project = f.owner.graph.current(ResourceRef(project_ref.authority, project_ref.kind, project_ref.id))
        enrollment = f.owner.consumer_operations().execute("work.orchestrator.projects.attach", {
            "target_assignment_ref": root.ref.to_dict(), "target_assignment_revision": root.revision,
            "target_assignment_generation": root.generation,
            "projects": [{"project_ref": project.ref.to_dict(), "project_version": project.version,
                "assignment_ref": ResourceRef.from_dict(state["assignment_ref"]).to_dict(),
                "assignment_revision": state["assignment_ref"]["revision"],
                "assignment_generation": state["manager_generation"]}]},
            request_id="journey-project-supervision", actor="root")
        self.assertEqual(enrollment["outcome"], "attached", enrollment)
        updated = f.owner.graph.current(project.ref)
        self.assertEqual(updated.payload["metadata"]["otto_orchestrator"]["assignment_ref"], root.ref.to_dict())
        state["project_ref"] = updated.ref.to_dict()
        self.server._save_state()
        issue = self.wait_response(self.send_caller("tool-help-request", {"command": "request-help", "request_key": "tool-help-1",
            "issue_key": "manager-route-question", "problem": "Choose the next bounded action",
            "evidence": [{"ref": state["project_ref"]}], "impact": "Avoid duplicate work",
            "requested_decision": "Continue the same project", "return_condition": "Return the route decision"}))
        self.server.portfolio._issue_loop().respond_to_issue(project_ref=state["project_ref"],
            issue_id=issue["issue_id"], actor="root", authority_source="owner fixture decision",
            response="Continue the current bounded task", proposed_solution="Use the normal worker route",
            next_action="Continue this project", request_id="tool-help-response-1")
        result = self.wait_response(self.send_caller("tool-answer", {"command": "answer",
            "issue_id": issue["issue_id"], "evidence": [{"ref": state["project_ref"]}],
            "next_action": "Continue the same project."}))
        self.assertEqual(result["outcome"], "recorded", result)
        self.assertEqual(result["issue_id"], issue["issue_id"])
        issues = self.wait_response(self.send_caller("tool-help-read", {"command": "read-help"}))
        self.assertEqual(issues["issues"][0]["state"], "resolved")
        rerouted = self.wait_response(self.send_caller("tool-route-reroute", {"command": "route", "operation": "reroute",
            "task": "J01", "principal": "worker-2",
            "route": "normal", "focus": "Continue the bounded task."}))
        self.assertEqual(rerouted["outcome"], "admitted", rerouted)
        self.assertTrue(self.fixture.provider.work_started.wait(10))
        self.assertIn("Continue the bounded task.", self.fixture.provider.calls[-1])
        self.fixture.provider.work_release.set()
        settled = self.wait_response(Path(rerouted["response_path"]))
        self.assertEqual(settled["outcome"], "succeeded", settled)
        result = self.wait_response(self.send_caller("tool-route-retry", {"command": "route", "operation": "retry",
            "schedule_id": state["schedule_id"]}))
        self.assertIn(result["outcome"], {"succeeded", "replayed"}, result)
        self.assertEqual(result["schedule_id"], state["schedule_id"])

    def test_manager_client_mints_logical_request_keys_and_routes_actions_by_identity(self):
        from otto.hostctl.manager_client import run_launched
        from otto.portfolio.manager_journey_client import requires_native_caller
        from otto.portfolio.execution_host import _nested_capability
        self.assertTrue(all(requires_native_caller(name) for name in ("show", "save", "answer", "route")))
        self.assertEqual([_nested_capability({"command": name}) for name in ("show", "save", "answer", "route")],
                         ["admitted"] * 4)
        with patch("otto.portfolio.caller_client.call", side_effect=lambda _socket, request: request) as call:
            result = run_launched(["save", "--note", "Retain exact evidence."], {
                "OTTO_MANAGER_IPC": "/tmp/manager-ipc", "OTTO_CALLER_SOCKET": "/tmp/caller.sock"})
        self.assertEqual(result["command"], "save")
        self.assertRegex(result["request_key"], r"^manager-tool:[0-9a-f]{32}$")
        call.assert_called_once()

    def test_worker_result_notification_stays_retained_until_manager_settlement(self):
        self.install_candidate()
        f = self.fixture
        prior = f.app._read(self.anchor)
        f.port.save_due(self.anchor, replace(prior, stop_state="active", completion_state="none",
            in_flight_request="fixture-live-manager").to_dict(),
            request_id="fixture-live-manager", expected_version=prior.version)
        admitted = self.wait_response(self.send_caller("1111", self.worker_request()))
        f.provider.work_release.set()
        settled = self.wait_response(Path(admitted["response_path"]))
        self.assertEqual(settled["outcome"], "succeeded", settled)
        notification = settled["manager_result_notification"]
        response = Path(notification["response_path"])
        pending = response.with_name(response.name.replace("response-", "pending-", 1))
        deadline = time.monotonic() + 10
        while not pending.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(pending.exists())
        self.assertFalse(response.exists())
        self.assertEqual(len(f.provider.calls), 2, "no concurrent second manager turn")
        worker_before = f.port.read_due(admitted["schedule_id"])
        live = f.app._read(self.anchor)
        f.port.save_due(self.anchor, prior.to_dict(), request_id="fixture-manager-now-settled", expected_version=live.version)
        resumed = self.wait_response(response)
        self.assertEqual(resumed["outcome"], "succeeded", resumed)
        self.assertFalse(pending.exists())
        self.assertEqual(len(f.provider.calls), 3)
        self.assertEqual(f.port.read_due(admitted["schedule_id"]), worker_before)
        repeat = self.wait_response(self.send("2222", {"command": "manager-worker-result", "task": "J01",
            "principal": "worker", "schedule_id": admitted["schedule_id"]}))
        self.assertEqual(repeat["outcome"], "replayed", repeat)
        self.assertEqual(len(f.provider.calls), 3)

    def test_manager_report_commits_while_worker_provider_is_blocked(self):
        worker = self.send_caller("1111", self.worker_request())
        started = self.fixture.provider.work_started.wait(20)
        self.assertTrue(started, worker.read_text() if worker.exists() else "no response")
        admitted = self.wait_response(worker)
        report = self.send_caller("2222", {"command": "report", "task": "J01", "summary": "nested report",
            "next_action": "inspect evidence", "request_key": "nested-report"})
        self.assertEqual(self.wait_response(report)["outcome"], "committed")
        self.assertFalse(self.fixture.provider.work_release.is_set(),
                         "the report committed before releasing the blocked worker model")
        self.fixture.provider.work_release.set()
        settled = self.wait_response(Path(admitted["response_path"]))
        self.assertEqual(settled["outcome"], "succeeded", settled)

    def install_candidate(self):
        self.assertIn("C01", self.server.state["criterion_refs"])
        self.assertIn("assessment_policy", self.server.state)
        (self.service.RUN / "run.json").write_text(json.dumps({
            "run_id": "manager-journey-fixture", "roles": {
                "manager": {"model": "gpt-test", "reasoning": "high"},
                "worker_normal": {"model": "gpt-test", "reasoning": "high"},
                "worker_xhard": {"model": "gpt-test", "reasoning": "high"}},
            "worker_operation_profiles": {},
            "assessment_accounting": self.server.state["assessment_policy"]}))
        from otto.portfolio.manager_journey_service import install_manager_journey_service
        install_manager_journey_service(self.server, run_path=self.service.RUN, workspace=self.root,
            orchestrator_principal="manager", observe_schedules=lambda project: {
                "mode": "no-owned-schedule", "pm_owned_schedule_ids": [],
                "coverage": {"project": project, "fixture": "no schedule automation configured"},
                "shared_records": []})

    def restart_host(self):
        from otto.portfolio.execution_host import ExecutionHost

        self.host = ExecutionHost(directory=self.directory, handler=self.server.handle,
            owner_path=self.directory / "manager-status-owner.json",
            caller_binding_reader=self.server.native_callers,
            caller_context_resolver=self.server._caller_context,
            caller_authorizer=self.server._authorize_caller, owner_file_compatibility=True)
        self.server.execution_host = self.host
        self.install_candidate()
        self.host.start()

    def status_request(self, admitted):
        return {"command": "worker-status", "task": "J01", "principal": "worker",
                "schedule_id": admitted["schedule_id"]}

    def test_retained_worker_admission_nested_commands_native_review_finish_and_terminal_project(self):
        self.install_candidate()
        application = self.fixture
        admitted = self.wait_response(self.send_caller("1111", self.worker_request()))
        self.assertEqual(admitted["outcome"], "admitted", admitted)
        self.assertTrue(application.provider.work_started.wait(10))
        self.assertFalse(Path(admitted["response_path"]).exists())
        due_while_blocked = application.port.read_due(admitted["schedule_id"])
        nested = [
                ("3333", {"command": "project-lifecycle-read", "task": "J01"}),
                ("4444", self.status_request(admitted)),
                ("5555", {"command": "status"}),
        ]
        report = self.wait_response(self.send_caller("2222", {"command": "report", "task": "J01",
                "summary": "nested progress", "next_action": "review returned evidence", "request_key": "nested-report"}))
        results = [self.wait_response(self.send(token, request)) for token, request in nested]
        self.assertEqual(report["outcome"], "committed", report)
        self.assertEqual([result["outcome"] for result in results], ["read", "pending", "ok"], results)
        self.assertEqual(application.port.read_due(admitted["schedule_id"]), due_while_blocked)
        repeated = self.wait_response(self.send_caller("6666", self.worker_request()))
        self.assertEqual(repeated["outcome"], "retained", repeated)
        self.assertEqual(repeated["handles"]["start"], admitted["retained_handle"], repeated)
        self.assertEqual(len(application.provider.calls), 2)
        application.provider.work_release.set()
        settled_worker = self.wait_response(Path(admitted["response_path"]))
        self.assertEqual(settled_worker["outcome"], "succeeded", settled_worker)
        resumed = self.wait_response(Path(settled_worker["manager_result_notification"]["response_path"]))
        self.assertEqual(resumed["outcome"], "succeeded", resumed)
        self.assertEqual(application.port.read_due(admitted["schedule_id"])["last_result"]["outcome"], "succeeded")
        self.assertTrue(any(row["value"].get("summary") == "nested progress"
            for row in self.reports()))
        candidate = application.app.assignments.list_observations(ResourceRef.from_dict(admitted["assignment_ref"]), kind="result")[0].ref.to_dict()
        reports_before_finish = self.reports()
        reviewed = self.wait_response(self.send("7777", {"command": "review-task", "task": "J01",
            "request_key": "native-review", "candidate_ref": candidate, "source_refs": [candidate],
            "inspection": {"checks": "Failed check followed by repair and successful focused check; native custody inspected"},
            "judgments": {"C01": {"verdict": "PASS", "rationale": "Retained native evidence proves the bounded correction",
                                    "evidence_refs": [candidate]}}}))
        self.assertEqual(reviewed["completion"]["outcome"], "completed", reviewed)
        # The supported installed service continues the same manager after its
        # execution task has completed, then performs normal terminal close.
        anchor_before = application.port.read_due(self.anchor)
        current_task = self.server.state["task_refs"]["J01"]
        notification = reviewed["task_settlement_notification"]
        self.assertEqual(notification["outcome"], "admitted", reviewed)
        continued = self.wait_response(Path(notification["response_path"]))
        self.assertEqual(continued["outcome"], "succeeded", continued)
        callback = application.port.read_due(continued["schedule_id"])
        self.assertIn("task_settlement_continuation", callback["host_evidence"])
        self.assertEqual(callback["target"]["task_ref"], current_task)
        self.assertEqual(callback["target"]["native_id"], "manager-session")
        self.assertNotEqual(callback["target"]["mandate_ref"], anchor_before["target"]["mandate_ref"])
        before_content = application.owner.content.read(ResourceRef.from_dict(anchor_before["target"]["mandate_ref"]))["content"]
        after_content = application.owner.content.read(ResourceRef.from_dict(callback["target"]["mandate_ref"]))["content"]
        self.assertEqual(after_content, {**before_content, "task_ref": current_task,
            "instruction_contract": {**before_content["instruction_contract"], "task_ref": current_task}})
        self.assertEqual(application.port.read_due(self.anchor), anchor_before)
        duplicate = self.wait_response(self.send("a003", {
            "command": "manager-task-settlement", "principal": "manager", "schedule_id": callback["schedule_id"]}))
        self.assertEqual(duplicate["outcome"], "replayed", duplicate)
        self.assertEqual(application.port.read_due(callback["schedule_id"]), callback)
        closed = self.wait_response(self.send("8888", {"command": "finish-project", "request_key": "terminal-project",
            "dispositions": {name: {"status": "qualified", "rationale": "Isolated fixture with no publication, remote or scheduled runtime obligation"}
                             for name in ("acceptance", "publication", "remote", "runtime")}}))
        self.assertEqual(closed["outcome"], "completed", closed)


        self.assertEqual(closed["readback"]["lifecycle"], "completed")
        self.assertEqual(len(application.provider.calls), 4, "anchor, worker, result inspection and terminal continuation")
        progress = lambda rows: [row for row in rows if row["value"].get("schema") == "otto.manager-progress.v1"]
        self.assertEqual(progress(self.reports()), progress(reports_before_finish), "finish wake must not invent a progress report")
        self.assertEqual(application.port.read_due(admitted["schedule_id"])["last_result"]["observed_model"], "gpt-test")

    def test_native_review_pending_own_settlement_automatically_continues_to_close(self):
        self.install_candidate()
        f = self.fixture
        outer = self

        class OrdinaryManager(ProviderBinding):
            def execute(self, request):
                result = super().execute(request)
                if request.identity.logical_agent_id == "manager" and self.options.get("delivered_brief"):
                    phase = "close" if "Observed owner task-settlement context:" in self.options["prompt"] else "review"
                    if phase == "review":
                        inputs = json.loads(outer.send_caller("native-review-input",
                            {"command": "review-input", "task": "J01"}).read_text())
                        reviewed = json.loads(outer.send_caller("native-review", {"command": "review-task",
                            "task": "J01", "request_key": "native-retained-review",
                            "candidate_ref": inputs["candidate_ref"], "source_refs": inputs["source_refs"],
                            "inspection": {"observed": "actual retained failed check, repair and passed check inspected"},
                            "judgments": {"C01": {"verdict": "PASS", "rationale": "retained_native_inspection_pass",
                                "evidence_refs": inputs["evidence_refs"]}}}).read_text())
                        (outer.root / "review.json").write_text(json.dumps(reviewed))
                    else:
                        closed = json.loads(outer.send_caller("native-terminal-close", {"command": "finish-project",
                            "request_key": "native-terminal-close", "dispositions": {
                                name: {"status": "qualified", "rationale": "isolated fixture has no publication remote or owned schedule"}
                                for name in ("acceptance", "publication", "remote", "runtime")}}).read_text())
                        (outer.root / "close.json").write_text(json.dumps(closed))
                return result

        f.app.runtime.adapter.binding_factory = lambda **options: OrdinaryManager(f.provider, options)
        reports_before = self.reports()
        f.provider.work_release.set()
        worker = self.wait_response(self.send_caller("1111", self.worker_request()))
        result = self.wait_response(Path(worker["response_path"]))
        reviewed = self.wait_response(Path(result["manager_result_notification"]["response_path"]))
        self.assertEqual(reviewed["outcome"], "succeeded", reviewed)
        self.assertEqual(json.loads((self.root / "review.json").read_text())["completion"]["outcome"], "pending")
        self.assertEqual(reviewed["completion_intents"][0]["result"]["outcome"], "completed")
        final = self.wait_response(Path(reviewed["task_settlement_notification"]["response_path"]))
        self.assertEqual(final["outcome"], "succeeded", final)
        closed = json.loads((self.root / "close.json").read_text())
        self.assertEqual(closed["outcome"], "completed", closed)
        self.assertEqual(f.owner.graph.current(f.project.ref).lifecycle.value, "completed")
        progress = lambda rows: [row for row in rows if row["value"].get("schema") == "otto.manager-progress.v1"]
        self.assertEqual(progress(self.reports()), progress(reports_before))
        self.assertEqual(len(f.provider.calls), 4)
        duplicate = f.app.continue_manager_after_tasks(manager_schedule_id=final["schedule_id"], execute=True)
        self.assertEqual(duplicate["outcome"], "idle", duplicate)
        self.assertEqual(len(f.provider.calls), 4)

    def test_instruction_candidate_rejection_is_before_any_review_or_budget_effect(self):
        self.install_candidate()
        f = self.fixture
        due = f.app._read(self.anchor)
        candidate = due.target["mandate_ref"]
        review = {"command": "review-task", "task": "J01", "request_key": "instruction-substitution",
            "candidate_ref": candidate, "source_refs": [candidate], "inspection": {"observed": "artifact prose only"},
            "judgments": {"C01": {"verdict": "PASS", "rationale": "inspected", "evidence_refs": [candidate]}}}
        assignment = ResourceRef.from_dict(self.server.state["assignment_ref"])
        reports_before = f.app.assignments.list_observations(assignment, kind="report")
        due_before = f.port.read_due(self.anchor)
        pool_match = {("record_type",): "limit"}
        pools_before = {ref.id for ref in f.store.consumer().find_identity_refs(kind="limit", payload_matches=pool_match)}
        response = self.wait_response(self.send("abcd", review))
        self.assertEqual(response["outcome"], "error", response)
        self.assertIn("GUIDE/MANDATE", response["message"])
        reports_after = f.app.assignments.list_observations(assignment, kind="report")
        self.assertEqual(reports_after, reports_before, "rejected candidate must not create a journey journal report")
        self.assertEqual(f.port.read_due(self.anchor), due_before)
        self.assertEqual({ref.id for ref in f.store.consumer().find_identity_refs(kind="limit", payload_matches=pool_match)}, pools_before,
                         "rejected candidate must not create or consume assessment budget")
        self.assertEqual(f.owner.graph.current(f.task.ref).lifecycle.value, "pending")
        self.assertEqual(len(f.provider.calls), 1)

    def test_review_input_exact_result_and_stale_worker_fence_and_cli_shape(self):
        self.install_candidate()
        f = self.fixture
        f.provider.work_release.set()
        admitted = self.wait_response(self.send_caller("1111", self.worker_request()))
        settled = self.wait_response(Path(admitted["response_path"]))
        self.assertEqual(settled["outcome"], "succeeded", settled.get("error"))
        self.assertIn("manager_result_notification", settled, settled)
        self.wait_response(Path(settled["manager_result_notification"]["response_path"]))
        inputs = self.wait_response(self.send("abcd", {"command": "review-input", "task": "J01"}))
        self.assertEqual(inputs["outcome"], "read", inputs)
        self.assertEqual(inputs["candidate_ref"]["kind"], "wrk.result")
        self.assertEqual(inputs["candidate_ref"], inputs["evidence_refs"][0])
        retained = f.owner.graph.reader.get_identity(ResourceRef.from_dict(inputs["candidate_ref"]))
        self.assertEqual(retained.payload["value"], f.port.read_due(admitted["schedule_id"])["host_evidence"]["gateway_attempt"]["result"])
        self.server.state["workers"]["J01"]["generation"] += 1
        with self.assertRaisesRegex(PermissionError, "binding differs"):
            self.host.handler.commands.review_input("J01")
        import argparse
        from otto.portfolio.manager_journey_client import _review_ref, command_result_summary
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "repeat --source-ref"):
            _review_ref(json.dumps(inputs["source_refs"]))
        self.assertEqual(_review_ref(json.dumps(inputs["candidate_ref"])), inputs["candidate_ref"])
        summary = command_result_summary({"outcome": "succeeded", "review_input": inputs})
        self.assertEqual(summary["review_input"]["candidate_ref"], inputs["candidate_ref"])

    def test_historical_instruction_acceptance_stays_recorded_but_cannot_close_project(self):
        self.install_candidate()
        f = self.fixture
        # Seed the real historical owner records that the old implementation
        # accepted, without invoking the repaired review path or changing it.
        historical, pool = self.seed_historical_instruction_acceptance(key="historical-bad-candidate")
        self.assertEqual(historical.lifecycle.value, "completed")
        before = f.owner.graph.current(f.task.ref).payload
        from herzchen.kernel.limits import LimitService
        usage = LimitService(f.store).get_pool(pool).cumulative_used_units
        closed = self.wait_response(self.send("bbbb", {"command": "finish-project", "request_key": "blocked-close",
            "dispositions": {name: {"status": "qualified", "rationale": "historical completion alone"}
                             for name in ("acceptance", "publication", "remote", "runtime")}}))
        self.assertEqual(closed["outcome"], "held", closed)
        self.assertIn("genuine artifact", closed["reason"])
        self.assertEqual(f.owner.graph.current(f.task.ref).payload, before)
        self.assertEqual(LimitService(f.store).get_pool(pool).cumulative_used_units, usage)
        self.assertEqual(usage, 1)
        self.assertEqual(f.owner.graph.current(f.project.ref).lifecycle.value, "pending")
        before_due = f.port.read_due(self.anchor)
        prepared = f.app.continue_manager_after_tasks(manager_schedule_id=self.anchor, execute=False)
        self.assertEqual(prepared["outcome"], "committed", prepared)
        next_due = f.port.read_due(prepared["schedule_id"])
        self.assertIsNone((next_due.get("host_evidence") or {}).get("gateway_attempt"))
        self.assertEqual(f.app.continue_manager_after_tasks(manager_schedule_id=self.anchor, execute=False)["schedule_id"], prepared["schedule_id"])
        self.assertEqual(f.port.read_due(self.anchor), before_due)
        current = f.app._read(self.anchor)
        f.port.save_due(self.anchor, replace(current, completion_state="unknown").to_dict(),
                       request_id="fixture-unknown-closeout-anchor", expected_version=current.version)
        held = f.app.continue_manager_after_tasks(manager_schedule_id=self.anchor, execute=True)
        self.assertEqual(held["outcome"], "held", held)
        self.assertEqual(f.port.read_due(prepared["schedule_id"]), next_due)
        self.assertEqual(len(f.provider.calls), 1)

    def test_owner_corrective_task_preserves_old_acceptance_and_closes_only_after_genuine_review(self):
        self.install_candidate()
        f = self.fixture
        old, _historical_pool = self.seed_historical_instruction_acceptance(
            key="old-wrong-binding", pool_id="journey-local")
        old_payload = json.loads(json.dumps(old.payload))
        project = f.owner.graph.current(f.project.ref)
        outcome = "Repair the promised artifact path and verify its actual contents under C01"
        batch = f.owner.sheet.apply(project.ref, {"tasks": [{"id": "J02", "title": "Correct preserved artifact obligation",
            "outcome": outcome, "acceptance": ["C01"]}]}, logical_request_key="corrective-task", actor=f.actor)
        corrective = f.owner.graph.current(batch.mappings["J02"])
        task_review = f.app.portfolio.create_document(batch.project.ref.to_dict(), actor="manager",
            request_id="corrective-task-admission-review", document_id="corrective-task-admission-review",
            role="SOURCE", content={"task_ref": corrective.ref.to_dict(),
                "decision": "approved", "observed": "The correction scope and C01 acceptance were reviewed."})
        f.owner.graph.admit(corrective.ref, revision=corrective.ref.revision,
            review_ref=ResourceRef.from_dict(task_review["record"]["payload"]["current_revision"]),
            disposition="approved", logical_request_key="corrective-task-admission", actor=f.actor)
        corrective = f.owner.graph.current(corrective.ref)
        self.assertEqual(f.owner.graph.admission_state(corrective.ref)["admitted_revision"],
            batch.mappings["J02"].revision)
        criterion = self.server.state["criterion_refs"]["C01"]
        from otto.portfolio.manager_journey_command import _digest
        content = {"schema": "otto.completed-task-correction.v1", "owner_actor": "manager",
            "project_ref": batch.project.ref.to_dict(), "corrective_task_ref": corrective.ref.to_dict(),
            "corrective_outcome_sha256": _digest(outcome), "criterion_refs": [criterion],
            "replaces": [{"task_ref": old.ref.to_dict(), "completion_sha256": _digest(old.payload["completion"]),
                "gate_refs": old.payload["completion"]["gate_refs"], "criterion_refs": [criterion]}]}
        document = f.app.portfolio.create_document(batch.project.ref.to_dict(), actor="manager",
            request_id="owner-correction-source", document_id="owner-correction-source", role="SOURCE", content=content)
        source_ref = document["record"]["payload"]["current_revision"]
        linked = f.owner.sheet.apply(batch.project.ref, {"metadata": {"owner_task_corrections": [source_ref]}},
            logical_request_key="owner-correction-link", actor=f.actor)
        self.server.state["project_ref"] = linked.project.ref.to_dict()
        self.server.state["task_refs"]["J02"] = corrective.ref.to_dict()
        policy_config = {"kind": "owner_local_bookkeeping", "local_only": True,
            "purpose": "explicit correction bookkeeping without resetting prior consumption", "pool_id": "corrective-local",
            "capacity_units": 1, "cumulative_allowance_units": 1, "task_criterion_pairs": ["J02/C01"]}
        self.server.state["assessment_policy"] = policy_config
        self.server._save_state()
        config_path = self.service.RUN / "run.json"
        run_config = json.loads(config_path.read_text())
        run_config["assessment_accounting"] = policy_config
        config_path.write_text(json.dumps(run_config))
        policy = LocalAssessmentPolicy.from_run_config(policy_config, state=self.server.state)
        self.host.handler.commands.policy = policy
        project = f.owner.graph.current(f.project.ref)
        self.assertEqual(self.host.handler.commands._completed_task_corrections(project, list(f.owner.graph.list(project=project.ref, kind="task"))), (set(), []))
        tampered_content = {**content, "replaces": [{**content["replaces"][0], "completion_sha256": "0" * 64}]}
        tampered_document = f.app.portfolio.create_document(batch.project.ref.to_dict(), actor="manager",
            request_id="owner-correction-tampered-source", document_id="owner-correction-tampered-source",
            role="SOURCE", content=tampered_content)
        tampered_ref = tampered_document["record"]["payload"]["current_revision"]
        f.owner.sheet.apply(batch.project.ref, {"metadata": {"owner_task_corrections": [tampered_ref]}},
            logical_request_key="owner-correction-tampered-link", actor=f.actor)
        project = f.owner.graph.current(batch.project.ref)
        with self.assertRaisesRegex(ValueError, "pin distinct preserved"):
            self.host.handler.commands._completed_task_corrections(project, list(f.owner.graph.list(project=project.ref, kind="task")))
        self.assertEqual(f.owner.graph.current(old.ref).payload, old_payload)
        f.owner.sheet.apply(batch.project.ref, {"metadata": {"owner_task_corrections": [source_ref]}},
            logical_request_key="owner-correction-restore-link", actor=f.actor)
        current_project_ref = ResourceRef.from_dict(self.server.state["project_ref"])
        self.server.state["project_ref"] = f.owner.graph.current(
            ResourceRef(current_project_ref.authority, current_project_ref.kind, current_project_ref.id)).ref.to_dict()
        self.server._save_state()
        outer = self

        class CorrectiveManager(ProviderBinding):
            def execute(self, request):
                result = super().execute(request)
                if request.identity.logical_agent_id == "manager" and self.options.get("delivered_brief"):
                    inputs = json.loads(outer.send_caller("corrective-review-input",
                        {"command": "review-input", "task": "J02"}).read_text())
                    (outer.root / "corrective-inputs.json").write_text(json.dumps(inputs))
                    reviewed = json.loads(outer.send_caller("corrective-review", {"command": "review-task",
                        "task": "J02", "request_key": "corrective-genuine-review",
                        "candidate_ref": inputs["candidate_ref"], "source_refs": inputs["source_refs"],
                        "inspection": {"observed": "actual promised path and criterion contents inspected"},
                        "judgments": {"C01": {"verdict": "PASS", "rationale": "corrected_artifact_pass",
                            "evidence_refs": inputs["evidence_refs"]}}}).read_text())
                    (outer.root / "corrective-review.json").write_text(json.dumps(reviewed))
                return result

        f.app.runtime.adapter.binding_factory = lambda **options: CorrectiveManager(f.provider, options)
        f.provider.work_release.set()
        admitted = self.wait_response(self.send_caller("1111", {**self.worker_request(), "task": "J02", "route": "normal",
            "principal": "corrective-worker", "request_key": "corrective-artifact-worker", "focus": outcome}))
        self.assertEqual(admitted["outcome"], "admitted", admitted)
        settled = self.wait_response(Path(admitted["response_path"]))
        self.assertEqual(settled.get("outcome"), "succeeded", settled.get("error"))
        self.assertIn("manager_result_notification", settled,
            {key: value for key, value in settled.items() if key in {"outcome", "error", "completion_intents"}})
        manager_result = self.wait_response(Path(settled["manager_result_notification"]["response_path"]))
        self.assertEqual(manager_result["outcome"], "succeeded", manager_result)
        reviewed = json.loads((self.root / "corrective-review.json").read_text())
        self.assertEqual(reviewed["completion"]["outcome"], "completed", reviewed)
        self.assertEqual(manager_result["completion_intents"][0]["result"]["outcome"], "replayed")
        self.assertEqual(manager_result["task_settlement_notification"]["outcome"], "admitted",
            manager_result["task_settlement_notification"])
        self.wait_response(Path(manager_result["task_settlement_notification"]["response_path"]))
        project = f.owner.graph.current(f.project.ref)
        rows = list(f.owner.graph.list(project=project.ref, kind="task"))
        covered, proof = self.host.handler.commands._completed_task_corrections(project, rows)
        self.assertEqual(covered, {old.ref.id})
        inputs = json.loads((self.root / "corrective-inputs.json").read_text())
        self.assertEqual(proof[0]["candidate_ref"], inputs["candidate_ref"])
        from herzchen.kernel.limits import LimitService
        limits = LimitService(f.store)
        self.assertEqual(limits.get_pool(ResourceRef(f.actor.authority, "limit", "journey-local")).cumulative_used_units, 1)
        self.assertEqual(limits.get_pool(policy.pool_ref).cumulative_used_units, 1)
        self.assertEqual(f.owner.graph.current(old.ref).payload, old_payload)
        closed = self.wait_response(self.send("4444", {"command": "finish-project", "request_key": "corrected-terminal-close",
            "dispositions": {name: {"status": "qualified", "rationale": "corrective obligation verified; old acceptance retained as history"}
                             for name in ("acceptance", "publication", "remote", "runtime")}}))
        self.assertEqual(closed["outcome"], "completed", closed)
        self.assertEqual(f.owner.graph.current(old.ref).payload, old_payload)
        project = f.owner.graph.current(f.project.ref)
        self.assertEqual(project.lifecycle.value, "completed")
        control = project.payload["lifecycle_control"]
        self.assertIn("completed_task_corrections", json.dumps(control))

    def test_current_manager_lifecycle_read_uses_the_finite_owner_grant(self):
        f = self.fixture
        f.compose(owner_actor="service-owner", manager_actor="manager")
        self.server.owner, self.server.portfolio = f.owner, f.app.portfolio
        self.server.state["owner"] = "service-owner"
        self.install_candidate()
        request = {"command": "project-lifecycle-read", "task": "J01"}
        current = self.host.handler(request)
        self.assertEqual(current["outcome"], "read", current)
        self.assertEqual(current["project_ref"], self.server.state["project_ref"])
        with self.assertRaisesRegex(ValueError, "bound project/task/manager"):
            self.host.handler({**request, "project_ref": {**self.server.state["project_ref"], "id": "foreign"}})
        with self.assertRaisesRegex(ValueError, "current task alias"):
            self.host.handler({**request, "task": "foreign"})
        self.assertEqual(len(f.provider.calls), 1)

    def test_unsettled_self_continuation_names_the_return_then_owner_settlement_action(self):
        self.install_candidate()
        current = self.fixture.app._read(self.anchor)
        pending = replace(current, completion_state="none", stop_state="active")
        self.fixture.port.save_due(self.anchor, pending.to_dict(), request_id="fixture-unsettled-manager-turn",
            expected_version=current.version)
        pending_due = self.fixture.port.read_due(self.anchor)
        self.assertEqual(pending_due["completion_state"], "none")
        self.assertEqual(pending_due["stop_state"], "active")
        held = self.host.handler({"command": "manager-continue", "report_key": self.key})
        self.assertEqual(held["outcome"], "held", held)
        self.assertIn("return from the current native turn", held["next_action"])
        self.assertEqual(held["current_schedule_id"], self.anchor)
        self.assertEqual(self.fixture.port.read_due(self.anchor), pending_due)
        self.assertEqual(len(self.fixture.provider.calls), 1)

    def test_worker_roots_follow_actual_adapter_and_owner_configured_cold_operation(self):
        self.install_candidate()
        config = json.loads((self.service.RUN / "run.json").read_text())
        config["worker_operation_profiles"] = {"J01": "cold_manager_operation"}
        (self.service.RUN / "run.json").write_text(json.dumps(config))
        self.fixture.app.runtime.adapter.writable_roots = (str(self.root / "controller"),)
        admitted = self.wait_response(self.send_caller("cccc", self.worker_request()))
        self.assertEqual(admitted["outcome"], "admitted", admitted)
        self.assertTrue(self.fixture.provider.work_started.wait(10))
        due = self.fixture.app._read(admitted["schedule_id"])
        from otto.agents.orchestrator_route import prepare_canonical_assignment_role_brief
        # The provider receives the actual canonical brief, not a fabricated
        # contract built only in the assertion.
        prompt = self.fixture.provider.calls[-1]
        self.assertIn("cold manager operation", prompt)
        self.assertNotIn("Implement only J01", prompt)
        self.assertIn("canonical_manager_commands", prompt)
        self.assertIn("Use the prescribed maintained canonical manager commands", prompt)
        self.assertNotIn("Do not modify canonical state", prompt)
        self.assertIn(str(self.root / "controller"), prompt)
        self.fixture.provider.work_release.set()
        self.assertEqual(self.wait_response(Path(admitted["response_path"]))["outcome"], "succeeded")

    def test_unknown_operation_profile_is_rejected_before_any_provider_or_assignment(self):
        self.install_candidate()
        config = json.loads((self.service.RUN / "run.json").read_text())
        config["worker_operation_profiles"] = {"J01": "invented_authority"}
        (self.service.RUN / "run.json").write_text(json.dumps(config))
        calls = len(self.fixture.provider.calls)
        result = self.wait_response(self.send_caller("dddd", self.worker_request()))
        self.assertEqual(result["outcome"], "error")
        self.assertIn("owner must correct run policy", result["message"])
        self.assertEqual(len(self.fixture.provider.calls), calls)
        self.assertNotIn("J01", self.server.state.get("workers", {}))

    def test_unknown_send_keeps_handle_and_restart_cannot_repeat_provider(self):
        self.install_candidate()
        application = self.fixture
        application.provider.unknown = True
        admitted = self.wait_response(self.send_caller("1111", self.worker_request()))
        self.assertTrue(application.provider.work_started.wait(10))
        application.provider.work_release.set()
        unknown = self.wait_response(Path(admitted["response_path"]))
        self.assertEqual(unknown["outcome"], "unknown", unknown)
        before = application.port.read_due(admitted["schedule_id"])
        calls = len(application.provider.calls)
        self.host.close()
        self.restart_host()
        repeated = self.host.handler(self.worker_request())
        self.assertEqual(repeated["handles"]["start"], admitted["retained_handle"], repeated)
        self.assertEqual(len(application.provider.calls), calls)
        self.assertEqual(application.port.read_due(admitted["schedule_id"]), before)
        held = self.host.handler({**self.worker_request(), "request_key": "unknown-new-key"})
        self.assertEqual(held["outcome"], "held")
        self.assertEqual(len(application.provider.calls), calls)

    def test_real_continued_manager_submits_worker_and_nested_review_survives_parent_drain(self):
        self.install_candidate()
        application = self.fixture
        document = application.app.portfolio.create_document(application.project.ref.to_dict(), actor="manager",
            request_id="nested-source", document_id="nested-source", role="SOURCE", visibility="shared",
            content={"check": "source inspection retained"})
        candidate = document["record"]["payload"]["current_revision"]
        review = {"command": "review-task", "task": "J01", "request_key": "nested-review", "finish": True,
            "candidate_ref": candidate, "source_refs": [candidate], "inspection": {"observed": "retained check inspected"},
            "judgments": {"C01": {"verdict": "PASS", "rationale": "source demonstrates the bounded criterion",
                                    "evidence_refs": [candidate]}}}
        plan = self.root / "native-plan.json"
        plan.write_text(json.dumps([self.worker_request(), {"command": "project-lifecycle-read", "task": "J01"},
            {"command": "report", "task": "J01", "summary": "nested manager evidence",
             "next_action": "finish after native settlement", "request_key": "nested-progress"}, review]))
        parent_release = threading.Event()
        receipt = self.root / "native-commands.json"
        self.addCleanup(parent_release.set)
        outer = self

        class NativeManagerBinding(ProviderBinding):
            def execute(self, request):
                if request.identity.logical_agent_id != "manager" or not self.options.get("delivered_brief"):
                    return super().execute(request)
                started, released = application.provider.work_started, application.provider.work_release
                application.provider.work_started = None
                try:
                    observed = super().execute(request)
                finally:
                    application.provider.work_started, application.provider.work_release = started, released
                results = [json.loads(outer.send_caller("nested-%d" % index, command).read_text())
                           for index, command in enumerate(json.loads(plan.read_text()))]
                receipt.write_text(json.dumps(results))
                if not parent_release.wait(25):
                    raise RuntimeError("parent manager release expired")
                return observed

        application.app.runtime.adapter.binding_factory = lambda **options: NativeManagerBinding(application.provider, options)
        key = "current-explicit-intent"
        application.app.assignments.append_report(ResourceRef.from_dict(self.server.state["assignment_ref"]),
            {"schema": "otto.manager-progress.v1", "project_ref": application.project.ref.to_dict(), "task_alias": "J01",
             "task_ref": application.task.ref.to_dict(), "continue_requested": True, "summary": "Old UNKNOWN prose is advice, not new owner authority",
             "next_action": "Submit the bounded current worker; preserve actual unknown-send fences",
             "logical_request_key": key, "recorded_at": NOW.isoformat()}, expected_generation=1,
            logical_request_key=key, actor=application.actor)
        response = self.send("1111", {"command": "manager-continue", "operation": "dispatch", "report_key": key})
        deadline = time.monotonic() + 15
        while not receipt.exists() and not response.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(receipt.exists(), (self.root / "native-error.txt").read_text() if (self.root / "native-error.txt").exists() else
                        str(json.loads(response.read_text()).get("continuation", {}).get("result", {}).get("error")) if response.exists() else
                        json.dumps({path.name: path.read_text() for path in self.directory.glob("request-*.json")}))
        nested = json.loads(receipt.read_text())
        self.assertEqual([value["outcome"] for value in nested], ["admitted", "read", "committed", "accepted"],
                         nested[1])
        self.assertEqual(nested[-1]["completion"]["outcome"], "pending", nested)
        self.assertFalse(response.exists())
        closing = threading.Thread(target=self.host.close)
        closing.start()
        try:
            deadline = time.monotonic() + 5
            while not self.host._closing and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(closing.is_alive())
            progress = self.wait_response(self.send("2222", {"command": "project-lifecycle-read", "task": "J01"}))
            self.assertEqual(progress["outcome"], "read")
            application.provider.work_release.set()
            self.assertEqual(self.wait_response(Path(nested[0]["response_path"]))["outcome"], "succeeded")
            parent_release.set()
            result = self.wait_response(response)
            self.assertEqual(result["outcome"], "succeeded", result)
            self.assertEqual(result["completion_intents"][0]["result"]["outcome"], "completed", result)
        finally:
            application.provider.work_release.set()
            parent_release.set()
            closing.join(15)
        self.assertFalse(closing.is_alive())
        self.assertEqual(len(application.provider.calls), 3)
        callback = result["continuation"]["schedule_id"]
        context = json.loads(application.port.read_due(callback)["message"].split("\n", 1)[1])
        self.assertEqual(context["current_intent"]["reported_next_action"], "Submit the bounded current worker; preserve actual unknown-send fences")
        self.assertEqual(context["current_intent"]["source"], "adopted_manager_contract")
        self.assertIn("not owner prohibitions", context["requirement_provenance"]["agent_suggestions"])
        self.assertEqual(context["execution_task_ref"], application.task.ref.to_dict())
        self.assertEqual(context["reported_task_ref"], application.task.ref.to_dict())
        self.assertEqual(application.owner.graph.current(application.task.ref).lifecycle.value, "completed")
        self.restart_host()
        terminal = self.host.handler({"command": "finish-project", "request_key": "continued-terminal",
            "dispositions": {name: {"status": "qualified", "rationale": "Local connected journey; native occurrences settled, no external publication obligations"}
                             for name in ("acceptance", "publication", "remote", "runtime")}})
        self.assertEqual(terminal["outcome"], "completed", terminal)
        self.assertEqual(terminal["readback"]["lifecycle"], "completed")
        self.assertEqual(len(application.provider.calls), 3)

    def test_deferred_intermediate_finish_wakes_same_manager_to_delegate_next_task(self):
        self.install_candidate()
        f = self.fixture
        next_task = WorkGraph(f.store, actor=f.actor).create_task(f.project.ref,
            title="Next useful delivery", logical_request_key="intermediate-next-task")
        self.server.state["task_refs"]["J02"] = next_task.ref.to_dict()
        policy_config = dict(self.server.state["assessment_policy"])
        policy_config["task_criterion_pairs"] = ["J01/C01", "J02/C01"]
        self.server.state["assessment_policy"] = policy_config
        self.server._save_state()
        policy = LocalAssessmentPolicy.from_run_config(policy_config, state=self.server.state)
        self.host.handler.commands.policy = policy
        run_config = json.loads((self.service.RUN / "run.json").read_text())
        run_config["assessment_accounting"] = policy_config
        (self.service.RUN / "run.json").write_text(json.dumps(run_config))
        next_request = {**self.worker_request(), "task": "J02", "principal": "next-worker",
                        "request_key": "intermediate-next-worker", "focus": "Implement next useful delivery"}
        outer = self
        phases = []
        class OrdinaryManager(ProviderBinding):
            def execute(self, request):
                result = super().execute(request)
                if request.identity.logical_agent_id == "manager" and self.options.get("delivered_brief"):
                    phase = "review" if not phases else "advance" if len(phases) == 1 else "inspect"
                    if phase == "advance":
                        outer.assertIn("Observed owner task-settlement context:", self.options["prompt"])
                        outer.assertIn("Advance only genuinely unfinished tasks through ordinary delegation and review",
                            self.options["prompt"])
                    phases.append(phase)
                    if phase == "review":
                        inputs = json.loads(outer.send_caller("intermediate-review-input",
                            {"command": "review-input", "task": "J01"}).read_text())
                        reviewed = json.loads(outer.send_caller("intermediate-review", {"command": "review-task",
                            "task": "J01", "request_key": "intermediate-review", "candidate_ref": inputs["candidate_ref"],
                            "source_refs": inputs["source_refs"], "finish": False,
                            "inspection": {"observed": "genuine retained worker result inspected"},
                            "judgments": {"C01": {"verdict": "PASS", "rationale": "retained_native_inspection_pass",
                                "evidence_refs": inputs["evidence_refs"]}}}).read_text())
                        (outer.root / "review.json").write_text(json.dumps(reviewed))
                        finished = json.loads(outer.send_caller("intermediate-finish", {"command": "finish-task", "task": "J01",
                            "request_key": "intermediate-finish", "review_key": "intermediate-review"}).read_text())
                        (outer.root / "review.json").write_text(json.dumps(finished))
                    elif phase == "advance":
                        advanced = json.loads(outer.send_caller("intermediate-advance", next_request).read_text())
                        (outer.root / "advance.json").write_text(json.dumps(advanced))
                    else:
                        inspected = json.loads(outer.send_caller("intermediate-inspect",
                            {"command": "project-lifecycle-read", "task": "J02"}).read_text())
                        (outer.root / "inspect.json").write_text(json.dumps(inspected))
                return result
        f.app.runtime.adapter.binding_factory = lambda **options: OrdinaryManager(f.provider, options)
        reports_before = self.reports()
        f.provider.work_release.set()
        first = self.wait_response(self.send_caller("a101", self.worker_request()))
        worker = self.wait_response(Path(first["response_path"]))
        reviewed = self.wait_response(Path(worker["manager_result_notification"]["response_path"]))
        reviewed_finish = json.loads((self.root / "review.json").read_text())
        self.assertEqual(reviewed_finish["outcome"], "pending", reviewed_finish)
        self.assertEqual(reviewed["completion_intents"][0]["result"]["outcome"], "completed")
        notification = reviewed["task_settlement_notification"]
        self.assertEqual(notification["outcome"], "admitted", notification)
        advanced = self.wait_response(Path(notification["response_path"]))
        self.assertEqual(advanced["outcome"], "succeeded", advanced)
        self.assertEqual(advanced["task_settlement_notification"]["outcome"], "replayed")
        self.assertEqual(advanced["task_settlement_notification"]["schedule_id"], advanced["schedule_id"])
        next_worker = json.loads((self.root / "advance.json").read_text())
        self.assertEqual(next_worker["outcome"], "admitted", next_worker)
        settled_next = self.wait_response(Path(next_worker["response_path"]))
        self.assertEqual(settled_next["outcome"], "succeeded", settled_next)
        self.assertEqual(f.owner.graph.current(f.task.ref).lifecycle.value, "completed")
        self.assertEqual(f.owner.graph.current(next_task.ref).lifecycle.value, "pending")
        callback = f.port.read_due(advanced["schedule_id"])
        facts = callback["host_evidence"]["task_settlement_continuation"]
        self.assertEqual(len(facts["completed_tasks"]), 1)
        self.assertEqual(facts["completed_tasks"][0]["task_ref"]["id"], f.task.ref.id)
        calls = len(f.provider.calls)
        self.host.close()
        self.restart_host()
        same = f.app.continue_manager_after_tasks(manager_schedule_id=advanced["schedule_id"], execute=True)
        self.assertEqual(same["outcome"], "replayed", same)
        self.assertEqual(same["schedule_id"], advanced["schedule_id"])
        self.assertEqual(len(f.provider.calls), calls)
        self.assertEqual(f.port.read_due(advanced["schedule_id"]), callback)
        before = f.app._read(advanced["schedule_id"])
        f.port.save_due(before.schedule_id, replace(before, completion_state="unknown").to_dict(),
            request_id="intermediate-unknown-anchor", expected_version=before.version)
        self.assertEqual(f.app.continue_manager_after_tasks(manager_schedule_id=before.schedule_id, execute=True)["outcome"], "held")
        self.assertEqual(len(f.provider.calls), calls)
        progress = lambda rows: [r for r in rows if r["value"].get("schema") == "otto.manager-progress.v1"]
        self.assertEqual(progress(self.reports()), progress(reports_before))

    def test_current_report_intent_preserves_manager_execution_binding_across_tasks(self):
        self.install_candidate()
        application = self.fixture
        next_task = WorkGraph(application.store, actor=application.actor).create_task(application.project.ref, title="Next delivery task",
                                                              logical_request_key="next-delivery-task")
        self.server.state["task_refs"]["J02"] = next_task.ref.to_dict()
        assignment = ResourceRef.from_dict(self.server.state["assignment_ref"])
        current_key = "current-j02-intent"
        for key, minutes, action in ((current_key, 1, "Inspect current J02 evidence; do not resend any uncertain occurrence"),
                                     ("obsolete-suggestion", 2, "UNKNOWN: all useful work must stop until root writes custom pins")):
            application.app.assignments.append_report(assignment,
                {"schema": "otto.manager-progress.v1", "project_ref": application.project.ref.to_dict(), "task_alias": "J02",
                 "task_ref": next_task.ref.to_dict(), "continue_requested": True, "next_action": action,
                 "logical_request_key": key, "recorded_at": (NOW + timedelta(minutes=minutes)).isoformat()},
                expected_generation=1, logical_request_key=key, actor=application.actor)
        prepared = self.wait_response(self.send("1111", {"command": "manager-continue", "operation": "prepare",
                                                         "report_key": current_key}))
        self.assertEqual(prepared["outcome"], "committed", prepared)
        callback = prepared["continuation"]["schedule_id"]
        due = application.port.read_due(callback)
        self.assertEqual(due["target"]["task_ref"], application.task.ref.to_dict())
        self.assertEqual(due["target"]["reported_task_ref"], next_task.ref.to_dict())
        self.assertEqual(application.app.inspect_mandate(schedule_id=callback)["scope_mismatches"], {})
        self.assertIn("Inspect current J02", json.loads(due["message"].split("\n", 1)[1])
                      ["current_intent"]["reported_next_action"])
        self.assertIn("Advance the adopted manager objective", due["instruction"])
        self.assertNotIn("all useful work must stop", due["instruction"])
        application.provider.work_release.set()
        delivered = self.wait_response(self.send("2222", {"command": "manager-continue", "operation": "dispatch",
                                                          "report_key": current_key}))
        self.assertEqual(delivered["outcome"], "succeeded", delivered)
        self.assertIn("uncertain_effects", application.provider.calls[-1])
        self.assertIn("remote_push", application.provider.calls[-1])


class TaskSettlementDrainBoundaryTests(unittest.TestCase):
    def fixture(self, *, closes=True, error=None):
        project_ref = {"authority": "owner", "kind": "work.project", "id": "fixture-project", "revision": "rev-1"}
        assignment_ref = {"authority": "owner", "kind": "wrk.assignment", "id": "fixture-manager", "revision": "rev-1"}
        state = {"manager": "same-manager", "schedule_id": "original-anchor",
                 "project_ref": project_ref, "assignment_ref": assignment_ref, "manager_generation": 1}
        saved, prepared, submitted = [], [], []
        service = object.__new__(ManagerJourneyService)
        due = {"role": "manager", "recipient": state["manager"], "target": {"project_ref": project_ref},
               "assignment_ref": assignment_ref, "generation": state["manager_generation"]}
        service.server = SimpleNamespace(state=state, due_port=SimpleNamespace(read_due=lambda schedule: due),
                                          _save_state=lambda: saved.append(dict(state)))
        host = SimpleNamespace(_closing=False)
        service.host = host

        def prepare(**options):
            prepared.append(options)
            host._closing = closes
            return {"outcome": "prepared", "schedule_id": "exact-prepared-callback"}

        def submit(request):
            submitted.append(request)
            if error is not None:
                raise RuntimeError(error)
            return {"outcome": "admitted", "schedule_id": request["schedule_id"]}

        host.submit = submit
        app = SimpleNamespace(continue_manager_after_tasks=prepare,
            _read=lambda schedule: SimpleNamespace(schedule_id=schedule, in_flight_request="original-key",
                instruction="original-instruction", target={"native_id": "same-native-session"}))
        return service, app, state, saved, prepared, submitted

    def test_finish_pending_return_annotation_requires_exact_current_manager_occurrence(self):
        from otto.portfolio.manager_journey_service import _CALLER
        service, *_ = self.fixture()
        state = service.server.state
        project = {"authority": "owner", "kind": "work.project", "id": "fixture-project", "revision": "rev-1"}
        task = {"authority": "owner", "kind": "work.task", "id": "fixture-task", "revision": "task-rev-1"}
        state.update(project_ref=project, task_refs={"J01": task})
        due = {"role": "manager", "recipient": "same-manager", "target": {"project_ref": project,
                "task_ref": task}, "assignment_ref": state["assignment_ref"], "generation": 1,
               "stop_state": "active", "in_flight_request": "current-turn-key"}
        service.server.due_port.read_due = lambda schedule: due if schedule == "original-anchor" else None
        pending = {"outcome": "pending", "completion_intent": "finish-intent",
                   "settlement_schedule_ids": ["original-anchor"], "provider_called": False}
        caller = {"role": "manager", "principal": "same-manager", "assignment_ref": state["assignment_ref"],
                  "generation": 1, "project_ref": project, "task_ref": task,
                  "occurrence_ref": {"schedule_id": "original-anchor"}}
        token = _CALLER.set(caller)
        try:
            annotated = service._annotate_current_turn_return(pending, {"task": "J01"})
            self.assertEqual(annotated["outcome"], "pending")
            self.assertTrue(annotated["waiting_for_current_turn_return"])
            self.assertIn("Return from this current native manager turn now", annotated["next_action"])
            self.assertNotIn("manager-continue", annotated["next_action"].split("Do not poll", 1)[0])
            self.assertEqual(annotated["completion_intent"], "finish-intent")
            self.assertFalse(annotated["provider_called"])

            for changed, result in (
                ({**caller, "principal": "foreign"}, pending),
                ({**caller, "generation": 2}, pending),
                ({**caller, "task_ref": {**task, "revision": "stale"}}, pending),
            ):
                other = _CALLER.set(changed)
                try:
                    self.assertEqual(service._annotate_current_turn_return(result, {"task": "J01"}), result)
                finally:
                    _CALLER.reset(other)

            for schedule_ids in ([], ["other"], ["original-anchor", "other"]):
                self.assertEqual(service._annotate_current_turn_return(
                    {**pending, "settlement_schedule_ids": schedule_ids}, {"task": "J01"}),
                    {**pending, "settlement_schedule_ids": schedule_ids})
            other = _CALLER.set({**caller, "occurrence_ref": {"schedule_id": "other"}})
            try:
                self.assertEqual(service._annotate_current_turn_return(pending, {"task": "J01"}), pending)
            finally:
                _CALLER.reset(other)
            due["completion_state"] = "unknown"
            self.assertEqual(service._annotate_current_turn_return(pending, {"task": "J01"}), pending)
        finally:
            _CALLER.reset(token)

    def test_drain_after_preparation_preserves_exact_callback_and_completion(self):
        service, app, state, saved, prepared, submitted = self.fixture(
            error="execution host is draining; no new worker may be admitted")
        result = service._retain_task_settlement(app)
        self.assertEqual(result["outcome"], "held")
        self.assertFalse(result["provider_called"])
        self.assertTrue(result["callback_prepared"])
        self.assertEqual(result["schedule_id"], "exact-prepared-callback")
        self.assertEqual(state["manager_continuation"]["requested_continuation"]["settled_schedule_id"], "original-anchor")
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(prepared), 1)
        self.assertEqual(len(submitted), 1)

    def test_other_runtime_error_is_not_disguised_as_drain(self):
        service, app, *_ = self.fixture(error="receipt admission corrupted")
        with self.assertRaisesRegex(RuntimeError, "corrupted"):
            service._retain_task_settlement(app)

    def test_known_error_without_current_drain_is_not_disguised(self):
        service, app, *_ = self.fixture(closes=False,
            error="execution host is draining; no new worker may be admitted")
        with self.assertRaisesRegex(RuntimeError, "draining"):
            service._retain_task_settlement(app)

    def test_already_draining_does_not_prepare_or_submit(self):
        service, app, _, saved, prepared, submitted = self.fixture()
        service.host._closing = True
        self.assertEqual(service._retain_task_settlement(app)["outcome"], "held")
        self.assertEqual((saved, prepared, submitted), ([], [], []))

    def test_live_admission_keeps_original_behavior(self):
        service, app, *_ = self.fixture(closes=False)
        self.assertEqual(service._retain_task_settlement(app),
            {"outcome": "admitted", "schedule_id": "exact-prepared-callback"})

class ManagerJourneyWorkerWorkspaceTests(unittest.TestCase):
    """Small direct checks that do not depend on an installed controller fixture."""

    def _service(self, *, due=None, resolved=None, tracked_worker=False):
        project, lab, run = Path("/owner/project"), Path("/owner/labs/J01"), Path("/owner/run")
        observed = []

        def execution(**options):
            observed.append(options)
            adapter = SimpleNamespace(worktree=options.get("workspace", project), source=run)
            runtime = SimpleNamespace(adapter=adapter, native_result_verifier=object(), acceptance_readiness=None)
            return SimpleNamespace(runtime=runtime)

        due_port = SimpleNamespace(read_due=lambda schedule_id: due if due and due.get("schedule_id") == schedule_id else None)
        owner = SimpleNamespace(owner_actor=SimpleNamespace(actor="owner"),
            role_runtime=lambda **_kwargs: SimpleNamespace(acceptance_readiness="trusted"))
        workers = {"J01": {"schedule_id": "worker-schedule", "principal": "worker"}} if tracked_worker else {}
        server = SimpleNamespace(_execution=execution, state={"manager": "owner-manager", "workers": workers}, due_port=due_port,
            owner=owner, worker_context_provider=lambda exact_due: resolved)
        service = object.__new__(ManagerJourneyService)
        service.server, service._host_execution = server, execution
        service.workspace, service.run_path = project, run
        service.commands, service.adapter_selection = SimpleNamespace(policy=None), None
        return service, observed, lab

    def test_worker_execution_uses_owner_supplied_lab_context(self):
        service, observed, lab = self._service()
        service._execution(principal="worker", model="fixture", reasoning="low", evidence_id="preflight",
            _worker_context={"workspace": str(lab)}, project_ref={"id": "project"}, task_ref={"id": "J01"})
        self.assertEqual(Path(observed[0]["workspace"]), lab)
        self.assertEqual(Path(observed[0]["workspace"]), Path("/owner/labs/J01"))

    def test_retained_worker_execution_resolves_lab_from_exact_due(self):
        due = {"schedule_id": "worker-schedule", "role": "worker", "recipient": "worker",
               "assignment_ref": {"id": "assignment-J01"}}
        service, observed, lab = self._service(due=due, resolved={"workspace": "/owner/labs/J01"})
        service._execution(principal="worker", model="fixture", reasoning="low", evidence_id="worker-schedule")
        self.assertEqual(Path(observed[0]["workspace"]), lab)

    def test_retained_worker_due_for_another_recipient_is_rejected(self):
        due = {"schedule_id": "worker-schedule", "role": "worker", "recipient": "someone-else",
               "assignment_ref": {"id": "assignment-J01"}}
        service, observed, _lab = self._service(due=due, resolved={"workspace": "/owner/labs/J01"})
        with self.assertRaisesRegex(PermissionError, "exact recipient and assignment"):
            service._execution(principal="worker", model="fixture", reasoning="low", evidence_id="worker-schedule")
        self.assertEqual(observed, [])

    def test_tracked_worker_without_exact_due_cannot_fall_back_to_project(self):
        service, observed, _lab = self._service(tracked_worker=True)
        with self.assertRaisesRegex(PermissionError, "no exact worker Due"):
            service._execution(principal="worker", model="fixture", reasoning="low", evidence_id="worker-schedule")
        self.assertEqual(observed, [])

    def test_execution_control_uses_worker_schedule_as_execution_binding(self):
        due = {"schedule_id": "worker-schedule", "role": "worker", "recipient": "worker",
               "project_ref": {"id": "project"}, "requested_model": "fixture", "requested_reasoning": "low",
               "target": {"launch_request": {"selection": {"identity": "pinned"}}}}
        service, _observed, _lab = self._service(due=due, tracked_worker=True)
        service.commands = SimpleNamespace(_authorize=lambda: None)
        service.server.state.update(project_ref={"id": "project"})
        captured = []
        app = SimpleNamespace(_read=lambda _schedule: SimpleNamespace())
        service._execution = lambda **options: (captured.append(options) or app)
        service._execution_control({"command": "execution-control", "operation": "read",
                                    "schedule_id": "worker-schedule"})
        self.assertEqual(captured[0]["evidence_id"], "worker-schedule")

    def test_startup_recovery_routes_worker_due_to_its_own_lab_app(self):
        due = {"schedule_id": "worker-schedule", "role": "worker", "recipient": "worker",
               "requested_model": "fixture", "requested_reasoning": "low",
               "target": {"launch_request": {"selection": {"identity": "pinned"}}}}
        service, _observed, _lab = self._service(due=due, tracked_worker=True)
        service.server.state["reminder_schedule_ids"] = []
        service._reminder_ids = lambda: ()
        captured = []
        worker_app = SimpleNamespace(recovery_status=lambda **_kw: {"state": "prepared"},
                                     recover=lambda **_kw: {"outcome": "prepared"})
        service._execution = lambda **options: (captured.append(options) or worker_app)
        manager_app = SimpleNamespace(recover_startup=lambda **kw: {
            "schema": "otto.owner-startup-recovery.v1", "outcome": "reconciled",
            "occurrences": [], "schedule_ids": kw["schedule_ids"]})
        result = service._startup_recovery(manager_app, ["worker-schedule"], execute=False)
        self.assertEqual(captured[0]["evidence_id"], "worker-schedule")
        self.assertEqual(result["schedule_ids"], [])
        self.assertEqual(result["occurrences"][0]["schedule_id"], "worker-schedule")

    def test_startup_seed_worker_uses_exact_schedule_when_manager_pin_is_absent(self):
        due = {"schedule_id": "worker-schedule", "role": "worker", "recipient": "worker",
               "project_ref": {"id": "project"}, "requested_model": "fixture", "requested_reasoning": "low",
               "target": {"launch_request": {}}}
        service, _observed, _lab = self._service(due=due, tracked_worker=True)
        service.commands = SimpleNamespace(_authorize=lambda: None)
        service.server.state.update(project_ref={"id": "project"})
        service.server.state.pop("manager")
        service.server.state["reminder_schedule_ids"] = []
        service._reminder_ids = lambda: ()
        captured = []
        worker_app = SimpleNamespace(
            recover_startup=lambda **_kw: {"schema": "otto.owner-startup-recovery.v1", "outcome": "reconciled",
                                           "occurrences": []},
            recovery_status=lambda **_kw: {"state": "prepared"},
            recover=lambda **_kw: {"outcome": "prepared"})
        service._execution = lambda **options: (captured.append(options) or worker_app)
        service._execution_control({"command": "execution-control", "operation": "startup"})
        self.assertEqual(captured[0]["evidence_id"], "worker-schedule")

class AutomaticWorkerRetentionTests(unittest.TestCase):
    def test_replayed_automatic_failure_does_not_start_same_generation_again(self):
        service = ManagerJourneyService.__new__(ManagerJourneyService)
        service.commands = SimpleNamespace(_authorize=lambda: None)
        worker = {"automatic": True, "automatic_revision": "revision-4",
            "schedule_id": "worker-auto-j01", "principal": "worker-J01",
            "model": "fixture", "reasoning": "low"}
        state = {"workers": {"J01": worker}, "automatic_dispatch_failures": {"J01": {
            "admitted_revision": "revision-4", "schedule_id": "worker-auto-j01",
            "reason": "paused task cannot be admitted"}}}
        service.server = SimpleNamespace(state=state,
            due_port=SimpleNamespace(read_due=lambda _schedule: {"target": {"launch_request": {}}}))
        service.host = SimpleNamespace(_closing=False,
            settle_automatic_failure=lambda *_args: self.fail("settled replay must not settle twice"))
        service._execution = lambda **_kw: self.fail("settled replay must not construct or start execution")

        for command in ("start-retained-worker", "worker-status"):
            result = service({"command": command, "task": "J01",
                              "principal": "worker-J01", "schedule_id": "worker-auto-j01"})
            self.assertEqual(result["outcome"], "held")
            self.assertEqual(result["reason"], "paused task cannot be admitted")
            self.assertTrue(result["automatic_failure_settled"])

    def test_automatic_admission_held_is_settled_as_known_pre_effect_failure(self):
        service = ManagerJourneyService.__new__(ManagerJourneyService)
        service.commands = SimpleNamespace(_authorize=lambda: None)
        project_ref = {"authority": "fixture", "kind": "work.project", "id": "project-j01"}
        task_ref = {"authority": "fixture", "kind": "work.task", "id": "task-j01"}
        assignment_ref = {"authority": "fixture", "kind": "work.assignment", "id": "assignment-j01"}
        due = {"assignment_ref": assignment_ref, "generation": 4, "host_evidence": {},
               "target": {"project_ref": project_ref, "task_ref": task_ref, "launch_request": {}}}
        settled = []
        service.host = SimpleNamespace(_closing=False, settle_automatic_failure=lambda *args: (
            settled.append(args) or {"outcome": "settled"}))
        service.server = SimpleNamespace(state={"project_ref": project_ref, "task_refs": {"J01": task_ref},
            "workers": {"J01": {"automatic": True, "schedule_id": "worker-auto-j01",
                "principal": "worker-J01", "model": "fixture", "reasoning": "low"}}},
            due_port=SimpleNamespace(read_due=lambda _schedule: due))
        def start(**_kw):
            raise ExecutionAdmissionHeld("paused task cannot be admitted")
        service._execution = lambda **_kw: SimpleNamespace(start=start)

        result = service({"command": "start-retained-worker", "task": "J01",
                          "principal": "worker-J01", "schedule_id": "worker-auto-j01"})

        self.assertEqual(result["outcome"], "held")
        self.assertEqual(result["automatic_failure_settlement"], {"outcome": "settled"})
        self.assertEqual(len(settled), 1)
        self.assertIs(settled[0][3]["provider_called"], False)
        self.assertIs(settled[0][3]["effects_started"], False)

    def test_manual_retained_start_still_requires_current_manager_occurrence(self):
        service = ManagerJourneyService.__new__(ManagerJourneyService)
        service.commands = SimpleNamespace(_authorize=lambda: None)
        service.host = SimpleNamespace(_closing=False)
        service.server = SimpleNamespace(state={"workers": {"J01": {
            "schedule_id": "worker-manual-j01", "principal": "worker-J01",
            "model": "fixture", "reasoning": "low"}}},
            due_port=SimpleNamespace(read_due=lambda _schedule: {"target": {"launch_request": {}}}))
        started = []
        service._execution = lambda **_kw: SimpleNamespace(start=lambda **_args: started.append(True))
        service._current_manager_schedule = lambda: (_ for _ in ()).throw(
            PermissionError("no current owner-issued manager occurrence"))

        with self.assertRaisesRegex(PermissionError, "no current owner-issued manager occurrence"):
            service({"command": "start-retained-worker", "task": "J01",
                     "principal": "worker-J01", "schedule_id": "worker-manual-j01"})

        self.assertEqual(started, [])

    def test_automatic_known_pre_admission_failure_is_settled_with_bounded_reason(self):
        service = ManagerJourneyService.__new__(ManagerJourneyService)
        service.commands = SimpleNamespace(_authorize=lambda: None)
        project_ref = {"authority": "fixture", "kind": "work.project", "id": "project-j01"}
        task_ref = {"authority": "fixture", "kind": "work.task", "id": "task-j01", "revision": 3}
        assignment_ref = {"authority": "fixture", "kind": "work.assignment", "id": "assignment-j01"}
        worker = {"automatic": True, "schedule_id": "worker-auto-j01", "principal": "worker-J01",
                  "model": "fixture", "reasoning": "low"}
        due = {"assignment_ref": assignment_ref, "generation": 4, "host_evidence": {},
               "target": {"project_ref": project_ref, "task_ref": task_ref, "launch_request": {}}}
        settled = []
        service.host = SimpleNamespace(_closing=False, settle_automatic_failure=lambda *args: (
            settled.append(args) or {"outcome": "settled"}))
        service.server = SimpleNamespace(state={"project_ref": project_ref, "task_refs": {"J01": task_ref},
            "workers": {"J01": worker}}, due_port=SimpleNamespace(read_due=lambda _schedule: due))
        app = SimpleNamespace(start=lambda **_kw: {"outcome": "partial", "stage": "runtime",
            "schedule_id": "worker-auto-j01", "assignment_ref": assignment_ref, "generation": 4,
            "error": {"code": "RuntimeUnavailable", "message": "runtime could not be prepared"}})
        service._execution = lambda **_kw: app
        result = service({"command": "start-retained-worker", "task": "J01",
                          "principal": "worker-J01", "schedule_id": "worker-auto-j01"})

        self.assertEqual(result["outcome"], "partial")
        self.assertEqual(result["automatic_failure_settlement"], {"outcome": "settled"})
        self.assertEqual(len(settled), 1)
        self.assertEqual(settled[0][:3], ("project-j01", "J01", "worker-auto-j01"))
        self.assertEqual(settled[0][3]["error"]["message"], "runtime could not be prepared")
        self.assertIs(settled[0][3]["provider_called"], False)
        self.assertIs(settled[0][3]["effects_started"], False)

    def test_automatic_unknown_start_result_does_not_settle_or_retry(self):
        service = ManagerJourneyService.__new__(ManagerJourneyService)
        service.commands = SimpleNamespace(_authorize=lambda: None)
        project_ref = {"authority": "fixture", "kind": "work.project", "id": "project-j01"}
        task_ref = {"authority": "fixture", "kind": "work.task", "id": "task-j01"}
        assignment_ref = {"authority": "fixture", "kind": "work.assignment", "id": "assignment-j01"}
        due = {"assignment_ref": assignment_ref, "generation": 4,
               "host_evidence": {"gateway_attempt": {"state": "unknown"}},
               "target": {"project_ref": project_ref, "task_ref": task_ref, "launch_request": {}}}
        callbacks = []
        service.host = SimpleNamespace(_closing=False, settle_automatic_failure=lambda *args: callbacks.append(args))
        service.server = SimpleNamespace(state={"project_ref": project_ref, "task_refs": {"J01": task_ref},
            "workers": {"J01": {"automatic": True, "schedule_id": "worker-auto-j01",
                "principal": "worker-J01", "model": "fixture", "reasoning": "low"}}},
            due_port=SimpleNamespace(read_due=lambda _schedule: due))
        unknown = {"outcome": "unknown", "provider_called": False, "effects_started": False}
        service._execution = lambda **_kw: SimpleNamespace(start=lambda **_args: unknown)

        result = service({"command": "start-retained-worker", "task": "J01",
                          "principal": "worker-J01", "schedule_id": "worker-auto-j01"})

        self.assertEqual(result, unknown)
        self.assertEqual(callbacks, [])

    def test_automatic_retained_start_does_not_require_manager_occurrence(self):
        service = ManagerJourneyService.__new__(ManagerJourneyService)
        service.commands = SimpleNamespace(_authorize=lambda: None)
        submitted = []
        service.host = SimpleNamespace(_closing=False, submit=lambda request: submitted.append(request))
        state = {"workers": {"J01": {"automatic": True, "schedule_id": "worker-auto-j01",
                                      "principal": "worker-J01", "model": "fixture",
                                      "reasoning": "low"}}}
        due = {"target": {"launch_request": {}}}
        service.server = SimpleNamespace(state=state,
            due_port=SimpleNamespace(read_due=lambda _schedule: due))
        started = []
        app = SimpleNamespace(start=lambda **kw: (started.append(kw) or {"outcome": "succeeded"}),
                              synchronize_manual_manager_occurrence=lambda **_kw:
                                  self.fail("automatic start must not synchronize a manager occurrence"))
        service._execution = lambda **_kw: app
        service._current_manager_schedule = lambda: (_ for _ in ()).throw(
            PermissionError("no current owner-issued manager occurrence"))
        landed_intents = [{"request_key": "accepted-finish", "result": {"outcome": "completed"}}]
        service._settle_shared_completion = lambda result, **_kw: {
            **result, "completion_intents": landed_intents}
        service._with_task_settlement_notification = lambda *_args: self.fail(
            "automatic completion must not prepare a manager settlement notification")

        result = service({"command": "start-retained-worker", "task": "J01",
                          "principal": "worker-J01", "schedule_id": "worker-auto-j01"})

        self.assertEqual(result["outcome"], "succeeded")
        self.assertEqual(started, [{"schedule_id": "worker-auto-j01"}])
        self.assertEqual(result["completion_intents"], landed_intents)
        self.assertEqual(submitted, [], "automatic completion must not schedule a manager continuation")

    def test_manager_run_worker_retains_automatic_task_occurrence(self):
        service = ManagerJourneyService.__new__(ManagerJourneyService)
        service.commands = SimpleNamespace(_authorize=lambda: None,
                                           _key=lambda request: request["request_key"])
        service.host = SimpleNamespace(_closing=False)
        payload = {"kind": "task", "fields": {"check": ["true"]}}
        payload["metadata_namespaces"] = {"work.admission": authoring_stamp(
            "admitted-revision", payload, "owner")}
        service.server = SimpleNamespace(state={
            "task_refs": {"J01": {"authority": "fixture", "kind": "work.task", "id": "task-j01"}},
            "workers": {"J01": {"automatic": True, "schedule_id": "worker-auto-j01",
                                "automatic_revision": "admitted-revision",
                                "assignment_ref": {"id": "assignment-auto-j01"},
                                "retained_handle": "start-auto-j01", "principal": "worker-J01"}}},
            owner=SimpleNamespace(graph=SimpleNamespace(current=lambda _ref: SimpleNamespace(payload=payload))))
        request = {"command": "run-worker", "task": "J01", "route": "xhard",
                   "principal": "manager-selected-worker", "request_key": "different-manager-key",
                   "focus": "Investigate the ready task"}
        result = service._submit_worker(request)
        self.assertEqual(result["outcome"], "retained")
        self.assertEqual(result["schedule_id"], "worker-auto-j01")
        self.assertEqual(result["retained_handle"], "start-auto-j01")
        self.assertFalse(result["provider_called"])


if __name__ == "__main__":
    unittest.main()
