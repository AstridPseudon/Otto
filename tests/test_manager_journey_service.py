"""Exercise the delivered service handler with only its provider substituted."""
import importlib.util
from datetime import timedelta
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from herzchen.domains.assessment import AssessmentModule
from herzchen.domains.work import WorkGraph
from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.manager_journey_service import ManagerJourneyService
from tests import test_manager_service_continuation as continuation
from tests.test_execution_application import ProviderBinding, NOW


class ManagerJourneyServiceTests(unittest.TestCase):
    reports = continuation.ManagerServiceContinuationTests.reports

    def setUp(self):
        continuation.ManagerServiceContinuationTests.setUp(self)
        root = Path(__file__).resolve().parents[1]
        baseline = root.parents[1] / "controller" / "manager_server_baseline.py"
        if not baseline.exists():
            self.skipTest("owner service fixture is not installed")
        spec = importlib.util.spec_from_file_location("journey_service_fixture", baseline)
        self.service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.service)
        adapter_path = baseline.with_name("serve_manager_owner.py")
        spec = importlib.util.spec_from_file_location("journey_owner_entry_fixture", adapter_path)
        self.entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.entry)
        self.root = Path(self.fixture.temporary.name).resolve()
        self.directory = self.root / "ipc"
        controller = self.root / "controller"
        controller.mkdir()
        for name, value in {"HERE": controller, "WORKTREE": self.root,
                            "RUN": root.parents[1], "EVIDENCE": self.root,
                            "STATE_PATH": self.root / "state.json"}.items():
            setattr(self.service, name, value)
        self.service.WORKER_RUN_CONFIG = self.service.RUN / "run.yaml"
        application = self.fixture
        state = {"authority": application.actor.authority, "owner": "manager", "manager": "manager",
                 "project_ref": application.project.ref.to_dict(), "task_refs": {"J01": application.task.ref.to_dict()},
                 "criterion_refs": {}, "assignment_ref": application.app._read(self.anchor).assignment_ref,
                 "manager_generation": 1, "schedule_id": self.anchor,
                 "requested_model": "gpt-test", "requested_reasoning": "high",
                 "manager_continuation": {"schedule_id": self.anchor,
                                          "native_session_id": "manager-session"}}
        self.server = self.entry.lifecycle_server_class(self.service)(owner=application.owner, portfolio=application.app.portfolio,
            state=state, due_port=application.port, binding=application.binding, store=application.store)
        self.owner_threads = []

        def execution(**options):
            application.app.runtime.adapter.requested_model = options["model"]
            application.app.runtime.adapter.requested_reasoning = options["reasoning"]
            return application.app

        self.server._execution = execution
        self.fixture.provider.work_started = threading.Event()
        self.fixture.provider.work_release = threading.Event()
        self.host = ExecutionHost(directory=self.directory, handler=self.server.handle,
                                  owner_path=self.directory / "manager-status-owner.json")
        self.host.start()
        self.addCleanup(self.close_host)

    def close_host(self):
        self.fixture.provider.work_release.set()
        self.host.close()

    def send(self, token, request):
        (self.directory / ("request-" + token + ".json")).write_text(json.dumps(request))
        return self.directory / ("response-" + token + ".json")

    def wait_response(self, path):
        deadline = time.monotonic() + 15
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(path.exists(), str(path))
        return json.loads(path.read_text())

    def worker_request(self):
        return {"command": "run-worker", "task": "J01", "route": "xhard", "principal": "worker",
                "request_key": "service-j01", "focus": "Inspect the bounded J01 seam"}

    def test_worker_result_notification_stays_retained_until_manager_settlement(self):
        self.install_candidate()
        f = self.fixture
        prior = f.app._read(self.anchor)
        f.port.save_due(self.anchor, replace(prior, stop_state="active", completion_state="none",
            in_flight_request="fixture-live-manager").to_dict(),
            request_id="fixture-live-manager", expected_version=prior.version)
        admitted = self.wait_response(self.send("1111", self.worker_request()))
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

    def test_baseline_real_run_worker_starves_nested_report_until_worker_returns(self):
        worker = self.send("1111", self.worker_request())
        started = self.fixture.provider.work_started.wait(20)
        self.assertTrue(started, worker.read_text() if worker.exists() else "no response")
        report = self.send("2222", {"command": "report", "task": "J01", "summary": "nested report",
            "next_action": "inspect evidence", "request_key": "nested-report"})
        status = self.send("3333", {"command": "status"})
        self.assertEqual(self.wait_response(status)["outcome"], "ok")
        time.sleep(.2)
        self.assertFalse(report.exists())
        self.assertFalse(worker.exists())
        self.fixture.provider.work_release.set()
        self.assertEqual(self.wait_response(worker)["outcome"], "succeeded")
        self.assertEqual(self.wait_response(report)["outcome"], "committed")

    def install_candidate(self):
        application = self.fixture
        scope = AssessmentModule(application.store, actor=application.actor).declare_scope("criteria", parent_obligation=application.project.ref,
            protocol="fixture", criteria=[{"id": "C01"}], logical_request_key="journey-criteria")
        self.server.state["criterion_refs"] = {"C01": scope.criterion_refs[0].to_dict()}
        config = {"kind": "owner_local_bookkeeping", "local_only": True, "purpose": "isolated journey",
                  "pool_id": "journey-local", "capacity_units": 1, "cumulative_allowance_units": 1,
                  "task_criterion_pairs": ["J01/C01"]}
        policy = LocalAssessmentPolicy.from_run_config(config, state=self.server.state)
        self.host.handler = ManagerJourneyService(server=self.server, host=self.host,
            run_path=self.service.RUN, workspace=self.root, policy=policy,
            orchestrator_principal="orchestrator", observe_schedules=lambda project: {
                "mode": "no-owned-schedule", "pm_owned_schedule_ids": [],
                "coverage": {"project": project, "fixture": "no schedule automation configured"},
                "shared_records": []})

    def status_request(self, admitted):
        return {"command": "worker-status", "task": "J01", "principal": "worker",
                "schedule_id": admitted["schedule_id"]}

    def test_retained_worker_admission_nested_commands_native_review_finish_and_terminal_project(self):
        self.install_candidate()
        application = self.fixture
        original = type(application.port).save_due

        def save(port, *args, **kwargs):
            self.owner_threads.append(threading.get_ident())
            return original(port, *args, **kwargs)

        with patch.object(type(application.port), "save_due", new=save):
            admitted = self.wait_response(self.send("1111", self.worker_request()))
            self.assertEqual(admitted["outcome"], "admitted", admitted)
            self.assertTrue(application.provider.work_started.wait(10))
            self.assertFalse(Path(admitted["response_path"]).exists())
            nested = [
                ("2222", {"command": "report", "task": "J01", "summary": "nested progress",
                          "next_action": "review returned evidence", "request_key": "nested-report"}),
                ("3333", {"command": "project-lifecycle-read", "task": "J01"}),
                ("4444", self.status_request(admitted)),
                ("5555", {"command": "status"}),
            ]
            results = [self.wait_response(self.send(token, request)) for token, request in nested]
            self.assertEqual([result["outcome"] for result in results], ["committed", "read", "pending", "ok"])
            repeated = self.wait_response(self.send("6666", self.worker_request()))
            self.assertEqual(repeated["retained_handle"], admitted["retained_handle"])
            self.assertEqual(len(application.provider.calls), 2)
            application.provider.work_release.set()
            settled_worker = self.wait_response(Path(admitted["response_path"]))
            self.assertEqual(settled_worker["outcome"], "succeeded")
            resumed = self.wait_response(Path(settled_worker["manager_result_notification"]["response_path"]))
            self.assertEqual(resumed["outcome"], "succeeded", resumed)
            self.assertEqual(len(set(self.owner_threads)), 1)
        candidate = application.app.assignments.list_observations(ResourceRef.from_dict(admitted["assignment_ref"]), kind="result")[0].ref.to_dict()
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
        report = self.wait_response(self.send("a001", {
            "command": "report", "task": "J01", "summary": "Current artifact accepted and completed",
            "next_action": "Inspect current terminal tasks and close this project through normal finish-project",
            "request_key": "post-completion-close", "continue_project": True}))
        self.assertEqual(report["outcome"], "committed", report)
        continued = self.wait_response(self.send("a002", {
            "command": "manager-continue", "report_key": "post-completion-close", "operation": "dispatch"}))
        self.assertEqual(continued["outcome"], "succeeded", continued)
        callback = application.port.read_due(continued["continuation"]["schedule_id"])
        self.assertEqual(callback["target"]["task_ref"], current_task)
        self.assertEqual(callback["target"]["native_id"], "manager-session")
        self.assertNotEqual(callback["target"]["mandate_ref"], anchor_before["target"]["mandate_ref"])
        before_content = application.owner.content.read(ResourceRef.from_dict(anchor_before["target"]["mandate_ref"]))["content"]
        after_content = application.owner.content.read(ResourceRef.from_dict(callback["target"]["mandate_ref"]))["content"]
        self.assertEqual(after_content, {**before_content, "task_ref": current_task,
            "instruction_contract": {**before_content["instruction_contract"], "task_ref": current_task}})
        self.assertEqual(application.port.read_due(self.anchor), anchor_before)
        duplicate = self.wait_response(self.send("a003", {
            "command": "manager-continue", "report_key": "post-completion-close", "operation": "dispatch"}))
        self.assertEqual(duplicate["outcome"], "replayed", duplicate)
        self.assertEqual(application.port.read_due(callback["schedule_id"]), callback)
        closed = self.wait_response(self.send("8888", {"command": "finish-project", "request_key": "terminal-project",
            "dispositions": {name: {"status": "qualified", "rationale": "Isolated fixture with no publication, remote or scheduled runtime obligation"}
                             for name in ("acceptance", "publication", "remote", "runtime")}}))
        self.assertEqual(closed["outcome"], "completed", closed)
        self.assertEqual(closed["readback"]["lifecycle"], "completed")
        self.assertEqual(len(application.provider.calls), 4, "anchor, worker, result inspection and terminal continuation")
        self.assertEqual(application.port.read_due(admitted["schedule_id"])["last_result"]["observed_model"], "gpt-6.1-sol")

    def test_current_manager_lifecycle_read_uses_the_finite_owner_grant(self):
        f = self.fixture
        f.compose(owner_actor="service-owner", manager_actor="manager")
        self.server.owner, self.server.portfolio = f.owner, f.app.portfolio
        self.server.state["owner"] = "service-owner"
        legacy = self.server.handle({"command": "project-lifecycle-read", "task": "J01"})
        self.assertEqual(legacy["error"]["code"], "project_scope_denied")
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
        before = self.fixture.port.read_due(self.anchor)
        pending = {**before, "completion_state": "none", "stop_state": "active"}
        original = self.server.due_port.read_due
        with patch.object(type(self.server.due_port), "read_due",
                side_effect=lambda schedule: pending if schedule == self.anchor else original(schedule)):
            held = self.host.handler({"command": "manager-continue", "report_key": self.key})
        self.assertEqual(held["outcome"], "held", held)
        self.assertIn("return from the current native turn", held["next_action"])
        self.assertEqual(held["current_schedule_id"], self.anchor)
        self.assertEqual(self.fixture.port.read_due(self.anchor), before)
        self.assertEqual(len(self.fixture.provider.calls), 1)

    def test_worker_roots_follow_actual_adapter_and_owner_configured_cold_operation(self):
        self.install_candidate()
        config = json.loads((self.service.RUN / "run.yaml").read_text())
        config["worker_operation_profiles"] = {"J01": "cold_manager_operation"}
        self.fixture.app.runtime.adapter.writable_roots = (str(self.root / "controller"),)
        real_read = Path.read_text
        def read(path, *args, **kwargs):
            return json.dumps(config) if path == self.service.RUN / "run.yaml" else real_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", read):
            admitted = self.wait_response(self.send("cccc", self.worker_request()))
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
        config = json.loads((self.service.RUN / "run.yaml").read_text())
        config["worker_operation_profiles"] = {"J01": "invented_authority"}
        real_read = Path.read_text
        def read(path, *args, **kwargs):
            return json.dumps(config) if path == self.service.RUN / "run.yaml" else real_read(path, *args, **kwargs)
        calls = len(self.fixture.provider.calls)
        with patch.object(Path, "read_text", read):
            result = self.wait_response(self.send("dddd", self.worker_request()))
        self.assertEqual(result["outcome"], "error")
        self.assertIn("owner must correct run policy", result["message"])
        self.assertEqual(len(self.fixture.provider.calls), calls)
        self.assertNotIn("J01", self.server.state.get("workers", {}))

    def test_unknown_send_keeps_handle_and_restart_cannot_repeat_provider(self):
        self.install_candidate()
        application = self.fixture
        application.provider.unknown = True
        admitted = self.wait_response(self.send("1111", self.worker_request()))
        self.assertTrue(application.provider.work_started.wait(10))
        application.provider.work_release.set()
        unknown = self.wait_response(Path(admitted["response_path"]))
        self.assertEqual(unknown["outcome"], "unknown", unknown)
        before = application.port.read_due(admitted["schedule_id"])
        calls = len(application.provider.calls)
        self.host.close()
        self.host = ExecutionHost(directory=self.directory, handler=self.server.handle,
                                  owner_path=self.directory / "manager-status-owner.json")
        self.install_candidate()
        self.host.start()
        repeated = self.wait_response(self.send("2222", self.worker_request()))
        self.assertEqual(repeated["retained_handle"], admitted["retained_handle"])
        self.assertEqual(len(application.provider.calls), calls)
        self.assertEqual(application.port.read_due(admitted["schedule_id"]), before)
        held = self.wait_response(self.send("3333", {**self.worker_request(), "request_key": "unknown-new-key"}))
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
        release = self.root / "release-parent"
        receipt = self.root / "native-commands.json"
        script = self.root / "native-manager.py"
        installed_client = Path(__file__).resolve().parents[3] / "controller" / "manager_ctl.py"
        client = self.root / "manager_ctl.py"
        client.write_text(installed_client.read_text().replace("read_command_status(IPC, token)",
                                                             "read_command_status(IPC, token, pending_only=True)"))
        script.write_text('''import importlib.util,json,sys,time
from pathlib import Path
spec=importlib.util.spec_from_file_location("journey_client",sys.argv[1]);client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
client.IPC=Path(sys.argv[2]);client.HERE=client.IPC;client.SERVICE=client.IPC/"unused.sock"
results=[client.call(request) for request in json.loads(Path(sys.argv[3]).read_text())]
Path(sys.argv[4]).write_text(json.dumps(results))
deadline=time.monotonic()+20
while not Path(sys.argv[5]).exists() and time.monotonic()<deadline:time.sleep(.01)
if not Path(sys.argv[5]).exists():raise RuntimeError("parent release expired")
''')
        self.addCleanup(release.touch)
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
                native = subprocess.run([sys.executable, str(script), str(client), str(outer.directory),
                                         str(plan), str(receipt), str(release)],
                                        capture_output=True, text=True, timeout=25)
                if native.returncode:
                    (outer.root / "native-error.txt").write_text(native.stderr)
                    raise RuntimeError(native.stderr)
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
        self.assertEqual([value["outcome"] for value in nested], ["admitted", "read", "committed", "accepted"], nested)
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
            release.touch()
            result = self.wait_response(response)
            self.assertEqual(result["outcome"], "succeeded", result)
            self.assertEqual(result["completion_intents"][0]["result"]["outcome"], "completed", result)
        finally:
            application.provider.work_release.set()
            release.touch()
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
        self.assertEqual(application.owner.graph.get(application.task.ref).lifecycle.value, "completed")
        self.host = ExecutionHost(directory=self.directory, handler=self.server.handle,
                                  owner_path=self.directory / "manager-status-owner.json")
        self.install_candidate()
        self.host.start()
        terminal = self.wait_response(self.send("3333", {"command": "finish-project", "request_key": "continued-terminal",
            "dispositions": {name: {"status": "qualified", "rationale": "Local connected journey; native occurrences settled, no external publication obligations"}
                             for name in ("acceptance", "publication", "remote", "runtime")}}))
        self.assertEqual(terminal["outcome"], "completed", terminal)
        self.assertEqual(terminal["readback"]["lifecycle"], "completed")
        self.assertEqual(len(application.provider.calls), 3)

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


if __name__ == "__main__":
    unittest.main()
