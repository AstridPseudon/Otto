"""Exercise the delivered service handler with only its provider substituted."""
import importlib.util
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
        fixture = os.environ.get("OTTO_OWNER_SERVICE_TEST_FIXTURE")
        baseline = Path(fixture) if fixture else root.parents[1] / "controller" / "manager_server_baseline.py"
        self.fixture_controller = baseline.parent
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
                            "RUN": baseline.parent.parent, "EVIDENCE": self.root,
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
        self.assertEqual(application.port.read_due(admitted["schedule_id"])["last_result"]["observed_model"], "gpt-6.1-sol")

    def test_native_review_pending_own_settlement_automatically_continues_to_close(self):
        self.install_candidate()
        f = self.fixture
        client = self.fixture_controller / "manager_ctl.py"
        script = self.root / "ordinary-manager.py"
        script.write_text('''import importlib.util,json,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("client",sys.argv[1]);client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
client.IPC=Path(sys.argv[2]);client.HERE=client.IPC;client.SERVICE=client.IPC/"unused.sock"
if sys.argv[3]=="review":
    inputs=client.call({"command":"review-input","task":"J01"})
    result=client.call({"command":"review-task","task":"J01","request_key":"native-retained-review",
        "candidate_ref":inputs["candidate_ref"],"source_refs":inputs["source_refs"],
        "inspection":{"observed":"actual retained failed check, repair and passed check inspected"},
        "judgments":{"C01":{"verdict":"PASS","rationale":"retained_native_inspection_pass","evidence_refs":inputs["evidence_refs"]}}})
else:
    result=client.call({"command":"finish-project","request_key":"native-terminal-close",
        "dispositions":{name:{"status":"qualified","rationale":"isolated fixture has no publication remote or owned schedule"}
                        for name in ("acceptance","publication","remote","runtime")}})
Path(sys.argv[4]).write_text(json.dumps(result))
''')
        outer = self

        class OrdinaryManager(ProviderBinding):
            def execute(self, request):
                result = super().execute(request)
                if request.identity.logical_agent_id == "manager" and self.options.get("delivered_brief"):
                    phase = "close" if "Observed owner task-settlement context:" in self.options["prompt"] else "review"
                    child = subprocess.run([sys.executable, str(script), str(client), str(outer.directory), phase,
                                            str(outer.root / (phase + ".json"))], capture_output=True, text=True, timeout=20)
                    if child.returncode:
                        raise RuntimeError(child.stderr)
                return result

        f.app.runtime.adapter.binding_factory = lambda **options: OrdinaryManager(f.provider, options)
        reports_before = self.reports()
        f.provider.work_release.set()
        worker = self.wait_response(self.send("1111", self.worker_request()))
        result = self.wait_response(Path(worker["response_path"]))
        reviewed = self.wait_response(Path(result["manager_result_notification"]["response_path"]))
        self.assertEqual(reviewed["outcome"], "succeeded", reviewed)
        self.assertEqual(json.loads((self.root / "review.json").read_text())["completion"]["outcome"], "pending")
        self.assertEqual(reviewed["completion_intents"][0]["result"]["outcome"], "completed")
        final = self.wait_response(Path(reviewed["task_settlement_notification"]["response_path"]))
        self.assertEqual(final["outcome"], "succeeded", final)
        closed = json.loads((self.root / "close.json").read_text())
        self.assertEqual(closed["outcome"], "completed", closed)
        self.assertEqual(f.owner.graph.get(f.project.ref).lifecycle.value, "completed")
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
        with patch.object(self.host.handler.commands, "_journal", wraps=self.host.handler.commands._journal) as journal:
            response = self.wait_response(self.send("abcd", review))
        self.assertEqual(response["outcome"], "error", response)
        self.assertIn("GUIDE/MANDATE", response["message"])
        self.assertFalse(any(len(call.args) > 2 for call in journal.call_args_list), "no ordinary journal mutation")
        self.assertEqual(f.owner.graph.get(f.task.ref).lifecycle.value, "pending")
        self.assertEqual(len(f.provider.calls), 1)

    def test_review_input_exact_result_and_stale_worker_fence_and_cli_shape(self):
        self.install_candidate()
        f = self.fixture
        f.provider.work_release.set()
        admitted = self.wait_response(self.send("1111", self.worker_request()))
        settled = self.wait_response(Path(admitted["response_path"]))
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
        candidate = f.app._read(self.anchor).target["mandate_ref"]
        request = {"command": "review-task", "task": "J01", "request_key": "historical-bad-candidate",
            "candidate_ref": candidate, "source_refs": [candidate], "inspection": {"observed": "artifact described but not bound"},
            "judgments": {"C01": {"verdict": "PASS", "rationale": "historical_pass", "evidence_refs": [candidate]}}}
        # Establish the authentic shape of an older accepted instruction-only
        # completion. The repair must expose it without rewriting the history.
        with patch.object(self.host.handler.commands, "_instruction_document", return_value=False), \
                patch.object(self.host.handler, "_retain_task_settlement", return_value={"outcome": "held"}):
            accepted = self.wait_response(self.send("abcd", request))
        self.assertEqual(accepted["completion"]["outcome"], "completed", accepted)
        before = f.owner.graph.get(f.task.ref).payload
        from herzchen.kernel.limits import LimitService
        pool = ResourceRef(f.actor.authority, "limit", "journey-local")
        usage = LimitService(f.store).get_pool(pool).cumulative_used_units
        closed = self.wait_response(self.send("bbbb", {"command": "finish-project", "request_key": "blocked-close",
            "dispositions": {name: {"status": "qualified", "rationale": "historical completion alone"}
                             for name in ("acceptance", "publication", "remote", "runtime")}}))
        self.assertEqual(closed["outcome"], "held", closed)
        self.assertIn("genuine artifact", closed["reason"])
        self.assertEqual(f.owner.graph.get(f.task.ref).payload, before)
        self.assertEqual(LimitService(f.store).get_pool(pool).cumulative_used_units, usage)
        self.assertEqual(usage, 1)
        self.assertEqual(f.owner.graph.get(f.project.ref).lifecycle.value, "pending")
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
        candidate = f.app._read(self.anchor).target["mandate_ref"]
        request = {"command": "review-task", "task": "J01", "request_key": "old-wrong-binding",
            "candidate_ref": candidate, "source_refs": [candidate], "inspection": {"observed": "historical artifact prose"},
            "judgments": {"C01": {"verdict": "PASS", "rationale": "old_pass", "evidence_refs": [candidate]}}}
        with patch.object(self.host.handler.commands, "_instruction_document", return_value=False), \
                patch.object(self.host.handler, "_retain_task_settlement", return_value={"outcome": "held"}):
            old_review = self.wait_response(self.send("abcd", request))
        self.assertEqual(old_review["completion"]["outcome"], "completed")
        old = f.owner.graph.get(f.task.ref)
        old_payload = json.loads(json.dumps(old.payload))
        project = f.owner.graph.get(f.project.ref)
        outcome = "Repair the promised artifact path and verify its actual contents under C01"
        batch = f.owner.sheet.apply(project.ref, {"tasks": [{"id": "J02", "title": "Correct preserved artifact obligation",
            "outcome": outcome, "acceptance": ["C01"]}]}, logical_request_key="corrective-task", actor=f.actor)
        corrective = f.owner.graph.get(batch.mappings["J02"])
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
        policy = LocalAssessmentPolicy.from_run_config({"kind": "owner_local_bookkeeping", "local_only": True,
            "purpose": "explicit correction bookkeeping without resetting prior consumption", "pool_id": "corrective-local",
            "capacity_units": 1, "cumulative_allowance_units": 1, "task_criterion_pairs": ["J02/C01"]}, state=self.server.state)
        self.host.handler.commands.policy = policy
        project = f.owner.graph.get(f.project.ref)
        self.assertEqual(self.host.handler.commands._completed_task_corrections(project, list(f.owner.graph.list(project=project.ref, kind="task"))), (set(), []))
        content_type = type(f.owner.content)
        original_read = content_type.read
        def tampered_read(port, ref, *args, **kwargs):
            value = original_read(port, ref, *args, **kwargs)
            if ref == ResourceRef.from_dict(source_ref):
                value = json.loads(json.dumps(value, default=lambda item: item.to_dict()))
                value["content"]["replaces"][0]["completion_sha256"] = "0" * 64
            return value
        with patch.object(content_type, "read", new=tampered_read), self.assertRaisesRegex(ValueError, "pin distinct preserved"):
            self.host.handler.commands._completed_task_corrections(project, list(f.owner.graph.list(project=project.ref, kind="task")))
        self.assertEqual(f.owner.graph.get(old.ref).payload, old_payload)
        f.provider.work_release.set()
        admitted = self.wait_response(self.send("1111", {**self.worker_request(), "task": "J02", "route": "normal",
            "principal": "corrective-worker", "request_key": "corrective-artifact-worker", "focus": outcome}))
        settled = self.wait_response(Path(admitted["response_path"]))
        self.wait_response(Path(settled["manager_result_notification"]["response_path"]))
        inputs = self.wait_response(self.send("2222", {"command": "review-input", "task": "J02"}))
        reviewed = self.wait_response(self.send("3333", {"command": "review-task", "task": "J02",
            "request_key": "corrective-genuine-review", "candidate_ref": inputs["candidate_ref"], "source_refs": inputs["source_refs"],
            "inspection": {"observed": "actual promised path and criterion contents inspected"},
            "judgments": {"C01": {"verdict": "PASS", "rationale": "corrected_artifact_pass", "evidence_refs": inputs["evidence_refs"]}}}))
        self.assertEqual(reviewed["completion"]["outcome"], "completed", reviewed)
        self.wait_response(Path(reviewed["task_settlement_notification"]["response_path"]))
        project = f.owner.graph.get(f.project.ref)
        rows = list(f.owner.graph.list(project=project.ref, kind="task"))
        covered, proof = self.host.handler.commands._completed_task_corrections(project, rows)
        self.assertEqual(covered, {old.ref.id})
        self.assertEqual(proof[0]["candidate_ref"], inputs["candidate_ref"])
        from herzchen.kernel.limits import LimitService
        limits = LimitService(f.store)
        self.assertEqual(limits.get_pool(ResourceRef(f.actor.authority, "limit", "journey-local")).cumulative_used_units, 1)
        self.assertEqual(limits.get_pool(policy.pool_ref).cumulative_used_units, 1)
        self.assertEqual(f.owner.graph.get(old.ref).payload, old_payload)
        closed = self.wait_response(self.send("4444", {"command": "finish-project", "request_key": "corrected-terminal-close",
            "dispositions": {name: {"status": "qualified", "rationale": "corrective obligation verified; old acceptance retained as history"}
                             for name in ("acceptance", "publication", "remote", "runtime")}}))
        self.assertEqual(closed["outcome"], "completed", closed)
        self.assertEqual(f.owner.graph.get(old.ref).payload, old_payload)
        project = f.owner.graph.get(f.project.ref)
        self.assertEqual(project.lifecycle.value, "completed")
        control = project.payload["lifecycle_control"]
        self.assertIn("completed_task_corrections", json.dumps(control))

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

    def test_manager_continue_reads_only_current_manager_stream_before_prepare(self):
        self.install_candidate()
        f = self.fixture
        assignment = ResourceRef.from_dict(self.server.state["assignment_ref"])
        key = "bounded-current-manager-continuation"
        f.app.assignments.append_report(assignment,
            {"schema": "otto.manager-progress.v1", "project_ref": f.project.ref.to_dict(),
             "task_alias": "J01", "task_ref": f.task.ref.to_dict(), "continue_requested": True,
             "next_action": "Inspect the retained J01 evidence without resubmitting prior work.",
             "logical_request_key": key, "recorded_at": NOW.isoformat()},
            expected_generation=1, logical_request_key=key, actor=f.actor)
        reader = f.store.consumer()
        streams = []

        class CurrentAssignmentReader:
            def list_events(self, *, stream=None):
                if stream is None:
                    raise AssertionError("manager continuation must not hydrate unscoped event history")
                streams.append(stream)
                return reader.list_events(stream=stream)

            def get_record(self, ref):
                return reader.get_record(ref)

        calls = len(f.provider.calls)
        with patch.object(f.store, "consumer", return_value=CurrentAssignmentReader()):
            prepared = self.host.handler({"command": "manager-continue", "operation": "prepare",
                                          "report_key": key})
        self.assertEqual(prepared["outcome"], "committed", prepared)
        self.assertEqual(prepared["request"]["logical_request_key"], key)
        self.assertEqual(streams, ["report:" + assignment.id])
        self.assertFalse(prepared["provider_called"])
        self.assertEqual(len(f.provider.calls), calls)

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
        installed_client = self.fixture_controller / "manager_ctl.py"
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

    def test_deferred_intermediate_finish_wakes_same_manager_to_delegate_next_task(self):
        self.install_candidate()
        f = self.fixture
        next_task = WorkGraph(f.store, actor=f.actor).create_task(f.project.ref,
            title="Next useful delivery", logical_request_key="intermediate-next-task")
        self.server.state["task_refs"]["J02"] = next_task.ref.to_dict()
        client = self.fixture_controller / "manager_ctl.py"
        next_request = {**self.worker_request(), "task": "J02", "principal": "next-worker",
                        "request_key": "intermediate-next-worker", "focus": "Implement next useful delivery"}
        script = self.root / "intermediate-manager.py"
        script.write_text('''import importlib.util,json,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("client",sys.argv[1]);client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
client.IPC=Path(sys.argv[2]);client.HERE=client.IPC;client.SERVICE=client.IPC/"unused.sock"
if sys.argv[3]=="review":
    inputs=client.call({"command":"review-input","task":"J01"})
    result=client.call({"command":"review-task","task":"J01","request_key":"intermediate-review",
        "candidate_ref":inputs["candidate_ref"],"source_refs":inputs["source_refs"],"finish":False,
        "inspection":{"observed":"genuine retained worker result inspected"},
        "judgments":{"C01":{"verdict":"PASS","rationale":"retained_native_inspection_pass","evidence_refs":inputs["evidence_refs"]}}})
    result=client.call({"command":"finish-task","task":"J01","request_key":"intermediate-finish","review_key":"intermediate-review"})
elif sys.argv[3]=="advance":
    result=client.call(json.loads(sys.argv[5]))
else:
    result=client.call({"command":"project-lifecycle-read","task":"J02"})
Path(sys.argv[4]).write_text(json.dumps(result))
''')
        outer = self
        phases = []
        class OrdinaryManager(ProviderBinding):
            def execute(self, request):
                result = super().execute(request)
                if request.identity.logical_agent_id == "manager" and self.options.get("delivered_brief"):
                    phase = "review" if not phases else "advance" if len(phases) == 1 else "inspect"
                    if phase == "advance":
                        outer.assertIn("Observed owner task-settlement context:", self.options["prompt"])
                        outer.assertIn("advance ready unfinished tasks", self.options["prompt"])
                    phases.append(phase)
                    child = subprocess.run([sys.executable, str(script), str(client), str(outer.directory), phase,
                        str(outer.root / (phase + ".json")), json.dumps(next_request)],
                        capture_output=True, text=True, timeout=20)
                    if child.returncode: raise RuntimeError(child.stderr)
                return result
        f.app.runtime.adapter.binding_factory = lambda **options: OrdinaryManager(f.provider, options)
        reports_before = self.reports()
        f.provider.work_release.set()
        first = self.wait_response(self.send("a101", self.worker_request()))
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
        self.wait_response(Path(settled_next["manager_result_notification"]["response_path"]))
        self.assertEqual(f.owner.graph.get(f.task.ref).lifecycle.value, "completed")
        self.assertEqual(f.owner.graph.get(next_task.ref).lifecycle.value, "pending")
        callback = f.port.read_due(advanced["schedule_id"])
        facts = callback["host_evidence"]["task_settlement_continuation"]
        self.assertEqual(len(facts["completed_tasks"]), 1)
        self.assertEqual(facts["completed_tasks"][0]["task_ref"]["id"], f.task.ref.id)
        calls = len(f.provider.calls)
        self.host.close()
        self.host = ExecutionHost(directory=self.directory, handler=self.server.handle,
                                  owner_path=self.directory / "manager-status-owner.json")
        self.install_candidate()
        self.host.start()
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


if __name__ == "__main__":
    unittest.main()
