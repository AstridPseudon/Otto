"""Real file IPC and Store custody while an admitted manager waits on its child."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from herzchen.domains.work import WorkGraph, Lifecycle
from otto.portfolio.execution_host import ExecutionHost
from tests import test_manager_service_continuation as service
from tests.test_execution_application import ProviderBinding


class ManagerReentrantIPCTests(unittest.TestCase):
    reports = service.ManagerServiceContinuationTests.reports

    def setUp(self):
        service.ManagerServiceContinuationTests.setUp(self)
        f = self.fixture
        self.directory = Path(f.temporary.name).resolve() / "manager-ipc"
        self.sibling = WorkGraph(f.store, actor=f.actor).create_task(f.project.ref,
            title="PA06 lifecycle", logical_request_key="pa06-child-task")
        self.tasks = {"PA02": f.task.ref.to_dict(), "PA06": self.sibling.ref.to_dict()}
        self.release = self.directory.parent / "release-manager"
        self.child_receipt = self.directory.parent / "child-responses.json"
        self.child_ready = self.directory.parent / "child-ready.json"
        self.allow_commands = self.directory.parent / "allow-child-commands"
        self.allow_commands.touch()
        self.transport_threads, self.mutation_threads, self.handler_threads = [], [], []
        self.client = Path(__file__).resolve().parents[1] / "manager_ctl.py"
        self.native_child = self.directory.parent / "native-child.py"
        self.requests_file = self.directory.parent / "child-requests.json"
        self.requests_file.write_text(json.dumps([
            {"command": "task-state", "task": "PA06", "lifecycle": "active", "request_key": "native-pa06-active"},
            {"command": "report", "task": "PA06", "summary": "Assessment evidence retained", "next_action": "Review owner acceptance", "request_key": "native-assessment-report"},
            {"command": "project-lifecycle-read", "task": "PA06"}]))
        self.native_child.write_text('''import importlib.util,json,sys,time
from pathlib import Path
spec=importlib.util.spec_from_file_location("owner_manager_ctl",sys.argv[1]);client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
client.IPC=Path(sys.argv[2]);client.STATUS_OWNER=client.IPC/"owner.json";client.SERVICE=client.IPC/"unused.sock"
Path(sys.argv[5]).write_text(json.dumps({"ready":True}))
deadline=time.monotonic()+10
while not Path(sys.argv[6]).exists() and time.monotonic()<deadline:time.sleep(.01)
if not Path(sys.argv[6]).exists():raise RuntimeError("child command admission expired")
results=[]
for request in json.loads(Path(sys.argv[7]).read_text()):
    results.append(client.call(request))
Path(sys.argv[3]).write_text(json.dumps(results))
deadline=time.monotonic()+10
while not Path(sys.argv[4]).exists() and time.monotonic()<deadline:time.sleep(.01)
if not Path(sys.argv[4]).exists():raise RuntimeError("manager release deadline expired")
''')
        outer = self
        class NativeChildBinding(ProviderBinding):
            def execute(self, request):
                outer.transport_threads.append(threading.get_ident())
                # Real adapter/gateway authorization and native-start callbacks;
                # this fixture supplies transcript data instead of a model call.
                observed = super().execute(request)
                result = subprocess.run([sys.executable, str(outer.native_child), str(outer.client),
                    str(outer.directory), str(outer.child_receipt), str(outer.release), str(outer.child_ready), str(outer.allow_commands), str(outer.requests_file)],
                    capture_output=True, text=True, timeout=12)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                return observed
        self.native_binding = lambda **options: NativeChildBinding(f.provider, options)
        self.host = ExecutionHost(directory=self.directory, handler=self.handle)
        self.host.start()
        self.addCleanup(self.cleanup_host)

    def cleanup_host(self):
        self.allow_commands.touch()
        self.release.touch()
        self.host.close()

    def wait_file(self, path):
        deadline = time.monotonic() + 8
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(path.exists(), str(path))
        return json.loads(path.read_text())

    def send(self, token, request):
        path = self.directory / ("request-" + token + ".json")
        path.write_text(json.dumps(request))
        return self.directory / ("response-" + token + ".json")

    def handle(self, request):
        f = self.fixture
        command = request["command"]
        if command == "status":
            return {"outcome": "read", "owner_available": True}
        self.handler_threads.append(threading.get_ident())
        if command == "commit":
            from otto.portfolio.execution_operations import commit_local_checkpoint
            return commit_local_checkpoint(self.directory.parent, request["paths"], message=request["message"])
        if command == "task-state":
            task = f.owner.graph.set_lifecycle(ResourceRef.from_dict(self.tasks[request["task"]]),
                Lifecycle(request["lifecycle"]), logical_request_key=request["request_key"], actor=f.actor)
            self.tasks[request["task"]] = task.ref.to_dict()
            return {"outcome": "committed", "ref": task.ref.to_dict(), "lifecycle": task.lifecycle.value}
        if command == "report":
            report = f.app.assignments.append_report(f.app._read(self.anchor).assignment_ref,
                {"schema": "otto.manager-progress.v1", "project_ref": f.project.ref.to_dict(),
                 "task_alias": request["task"], "task_ref": self.tasks[request["task"]],
                 "summary": request["summary"], "next_action": request["next_action"],
                 "logical_request_key": request["request_key"], "continue_requested": False,
                 "recorded_at": service.NOW.isoformat()}, expected_generation=1,
                logical_request_key=request["request_key"], actor=f.actor)
            return {"outcome": "committed", "ref": report.ref.to_dict()}
        if command == "project-lifecycle-read":
            return {"outcome": "read", "lifecycle": "active", "read_only": True,
                    "writes": 0, "dispatch": False, "launch": False}
        return service.manager_continuation_from_command(request=request, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor, task_refs=self.tasks,
            native_session_id="manager-session", read_reports=self.reports)

    def dispatch(self):
        f = self.fixture
        def save(port, *args, **kwargs):
            self.mutation_threads.append(threading.get_ident())
            return original(port, *args, **kwargs)
        original = type(f.port).save_due
        self.save_patch = patch.object(type(f.port), "save_due", new=save)
        self.save_patch.start(); self.addCleanup(self.save_patch.stop)
        self.adapter_patch = patch.object(f.app.runtime.adapter, "binding_factory", self.native_binding)
        self.adapter_patch.start(); self.addCleanup(self.adapter_patch.stop)
        return self.send("abc123", {"command": "manager-continue", "operation": "dispatch", "report_key": self.key})

    def test_child_task_state_and_report_respond_before_native_manager_finishes(self):
        f = self.fixture
        response = self.dispatch()
        child = self.wait_file(self.child_receipt)
        self.assertEqual([r["outcome"] for r in child], ["committed", "committed", "read"])
        self.assertEqual(child[0]["lifecycle"], "active")
        self.assertFalse(response.exists())
        self.assertFalse((self.directory / "pending-abc123.json").exists())
        self.assertTrue(self.host.owner_path.exists())
        self.assertEqual(len(set(self.handler_threads + self.mutation_threads)), 1)
        self.assertNotEqual(self.transport_threads[0], self.handler_threads[0])
        self.release.touch()
        result = self.wait_file(response)
        self.assertEqual(result["outcome"], "succeeded", result)
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)
        self.assertTrue(any(row["value"].get("logical_request_key") == "native-assessment-report" for row in self.reports()))
        # Canonical attempt/result custody persists; this is not a fake success.
        callback = result["continuation"]["schedule_id"]
        attempt = f.port.read_due(callback)["host_evidence"]["gateway_attempt"]
        self.assertEqual(attempt["state"], "result")
        self.assertEqual(attempt["delivery_admission"]["native_turn_started"], True)
        self.assertEqual(len(set(self.mutation_threads)), 1)

    def test_close_retains_child_responses_and_defers_second_dispatch_to_restart(self):
        f = self.fixture
        self.allow_commands.unlink()
        response = self.dispatch()
        self.wait_file(self.child_ready)
        queued = self.send("ffffff", {"command": "manager-continue", "operation": "dispatch", "report_key": self.key})
        closing = threading.Thread(target=self.host.close)
        closing.start()
        try:
            deadline = time.monotonic() + 5
            while not self.host._closing and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(self.host._closing)
            self.assertTrue(closing.is_alive())
            with self.assertRaisesRegex(RuntimeError, "draining"):
                self.host.retain(name="new-child-during-drain", operation=lambda: None)
            self.allow_commands.touch()
            child = self.wait_file(self.child_receipt)
            self.assertEqual([r["outcome"] for r in child], ["committed", "committed", "read"])
            self.assertFalse(response.exists())
            status = self.send("777777", {"command": "status"})
            self.assertEqual(self.wait_file(status)["outcome"], "read")
            self.assertFalse(queued.exists())
            pending = self.wait_file(self.directory / "pending-ffffff.json")
            self.assertTrue(pending["request_retained"])
            self.assertFalse(pending["effects_started"])
            self.assertFalse(pending["retry"])
            from otto.portfolio.manager_journey_client import read_command_status
            retained_path = self.directory / "pending-ffffff.json"
            retained_bytes = retained_path.read_bytes()
            observed = read_command_status(self.directory, "ffffff")
            # A later offline read adds timing gaps; it must preserve the
            # retained request and all dispatch/effect state exactly.
            self.assertEqual({k: v for k, v in observed.items() if k != "receipt_timing"},
                             {k: v for k, v in pending.items() if k != "receipt_timing"})
            self.assertEqual(retained_path.read_bytes(), retained_bytes)
            self.assertEqual(observed["receipt_timing"]["correlation_id"],
                             pending["receipt_timing"]["correlation_id"])
            self.assertTrue((self.directory / "request-ffffff.json").exists())
            self.release.touch()
            self.wait_file(response)
        finally:
            self.release.touch(); closing.join(10)
        self.assertFalse(closing.is_alive())
        self.assertFalse(self.host.owner_path.exists())
        self.assertFalse(queued.exists())
        self.assertTrue((self.directory / "request-ffffff.json").exists())
        calls = len(f.provider.calls)
        # Restart serves the durable same-key request through canonical replay/
        # unknown fencing, never a second native transport/model effect.
        self.host = ExecutionHost(directory=self.directory, handler=self.handle)
        self.host.start()
        replay = self.wait_file(queued)
        self.assertEqual(replay["outcome"], "replayed", replay)
        self.assertEqual(len(f.provider.calls), calls)
        self.assertFalse((self.directory / "pending-ffffff.json").exists())
        self.assertEqual(read_command_status(self.directory, "ffffff")["summary"]["outcome"], replay["outcome"])

    def test_native_manager_commit_and_unsupported_command_respond_before_child_exit(self):
        root = self.directory.parent
        def git(*args):
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()
        git("init", "-q")
        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.invalid")
        (root / "checkpoint.txt").write_text("before")
        git("add", "checkpoint.txt")
        git("commit", "-qm", "Fixture baseline")
        initial = git("rev-parse", "HEAD")
        (root / "checkpoint.txt").write_text("tested source")
        requests = json.loads(self.requests_file.read_text())
        requests.extend([
            {"command": "commit", "paths": ["checkpoint.txt"], "message": "Owner nested checkpoint"},
            {"command": "unsupported-owner-operation", "request_key": "no-effects"}])
        self.requests_file.write_text(json.dumps(requests))
        response = self.dispatch()
        child = self.wait_file(self.child_receipt)
        self.assertFalse(response.exists())
        self.assertEqual(child[-2]["outcome"], "committed")
        self.assertNotEqual(child[-2]["commit"], initial)
        self.assertEqual(child[-2]["commit"], git("rev-parse", "HEAD"))
        self.assertEqual(git("status", "--porcelain", "--", "checkpoint.txt"), "")
        self.assertEqual(child[-1]["outcome"], "held")
        self.assertFalse(child[-1]["effects_started"])
        self.assertFalse(child[-1]["retry"])
        self.assertIn("Do not resend", child[-1]["next_action"])
        self.assertEqual(len(set(self.handler_threads + self.mutation_threads)), 1)
        calls = len(self.fixture.provider.calls)
        self.release.touch()
        self.assertEqual(self.wait_file(response)["outcome"], "succeeded")
        self.assertEqual(len(self.fixture.provider.calls), calls)

    def test_explicit_manager_commands_may_advance_bound_task_after_exact_admission(self):
        requests = json.loads(self.requests_file.read_text())
        requests.append({"command": "task-state", "task": "PA02", "lifecycle": "active",
                         "request_key": "bound-task-change"})
        self.requests_file.write_text(json.dumps(requests))
        response = self.dispatch()
        self.wait_file(self.child_receipt)
        self.release.touch()
        result = self.wait_file(response)
        self.assertEqual(result["outcome"], "succeeded", str({k: result.get("continuation",{}).get(k) for k in ("outcome","stage","error")}))
        attempt = self.fixture.port.read_due(result["continuation"]["schedule_id"])["host_evidence"]["gateway_attempt"]
        self.assertEqual(attempt["result"]["outcome"], "succeeded")
        self.assertTrue(attempt["delivery_admission"]["native_turn_started"])
        self.assertTrue(attempt["result"]["context_digest_verified"])
        before = len(self.fixture.provider.calls)
        self.assertEqual(self.fixture.app.recover(schedule_id=result["continuation"]["schedule_id"], execute=False)["outcome"], "replayed")
        self.assertEqual(len(self.fixture.provider.calls), before)

    def test_terminal_status_is_bounded_and_preserves_full_response(self):
        from otto.portfolio.manager_journey_client import read_command_status, read_command_response
        path = self.directory / "response-abcdef.json"
        value = {"outcome": "unknown", "continuation": {"schedule_id": "same-occurrence",
            "result": {"outcome": "unknown", "unknown_reason": "real-fence", "raw_result": {
                "stdout": "nested evidence" * 100000}}}}
        path.write_text(json.dumps(value))
        raw = path.read_bytes()
        self.assertIsNone(read_command_status(self.directory, "abcdef", pending_only=True))
        status = read_command_status(self.directory, "abcdef")
        self.assertLess(len(json.dumps(status).encode()), 4096)
        self.assertEqual(status["summary"]["continuation"]["result"]["unknown_reason"], "real-fence")
        self.assertEqual(status["response_utf8_bytes"], len(raw))
        self.assertEqual(status["response_sha256"], __import__("hashlib").sha256(raw).hexdigest())
        self.assertEqual(read_command_response(self.directory, "abcdef"), status)
        small = self.directory / "response-123abc.json"
        small.write_text(json.dumps({"outcome": "admitted", "response_path": "worker-exact-path", "retained_handle": "worker-handle"}))
        self.assertEqual(read_command_response(self.directory, "123abc")["response_path"], "worker-exact-path")
        self.assertEqual(path.read_bytes(), raw)
        self.assertTrue(status["terminal"])
        self.assertFalse(status["retry"])
        canonical_ref = {"authority": "owner", "kind": "work.task", "id": "actual-task", "revision": "rev-2"}
        value = {"outcome": "ok", "project_ref": {**canonical_ref, "kind": "work.project"},
                 "task_refs": {"J04": canonical_ref}, "workers": {"J04": {"principal": "cold-operator",
                    "schedule_id": "exact-prepared", "generation": 2, "assignment_ref": canonical_ref,
                    "submission": {"focus": "nested prose" * 100000}}},
                 "manager_assignment": {"reports": ["native prose" * 100000]}}
        path.write_text(json.dumps(value))
        summary = read_command_response(self.directory, "abcdef")["summary"]
        self.assertEqual(summary["task_refs"]["J04"], canonical_ref)
        self.assertEqual(summary["workers"]["J04"]["schedule_id"], "exact-prepared")
        self.assertNotIn("reports", summary["manager_assignment"])
        self.assertLess(len(json.dumps(summary)), 4096)

    def test_context_manager_closes_idle_host_on_bootstrap_exception(self):
        directory = self.directory.parent / "bootstrap-ipc"
        guarded = ExecutionHost(directory=directory, handler=lambda request: {})
        with self.assertRaisesRegex(RuntimeError, "bootstrap output failed"):
            with guarded:
                raise RuntimeError("bootstrap output failed")
        self.assertFalse(guarded.owner_path.exists())
        self.assertTrue(all(not thread.is_alive() for thread in guarded._threads))

    def test_current_review_and_lifecycle_context_survives_preparation_and_delivery(self):
        f = self.fixture
        self.key = "review-informed-owner-intent"
        evidence = {"accepted_review_refs": [{"path": "/accepted/final-review.json", "sha256": "a" * 64}],
                    "lifecycle_evidence_refs": [{"path": "/bounded/lifecycle-receipt.json", "sha256": "b" * 64}]}
        report = f.app.assignments.append_report(f.app._read(self.anchor).assignment_ref,
            {"schema": "otto.manager-progress.v1", "project_ref": f.project.ref.to_dict(),
             "task_alias": "PA02", "task_ref": f.task.ref.to_dict(), "continue_requested": True,
             "summary": "Accepted consolidation source with bounded lifecycle proof; preserve unknowns.",
             "continuation_evidence": evidence, "next_action": "Continue only the remaining accepted work",
             "logical_request_key": self.key, "recorded_at": service.NOW.isoformat()}, expected_generation=1,
            logical_request_key=self.key, actor=f.actor)
        result = self.handle({"command": "manager-continue", "operation": "prepare", "report_key": self.key})
        callback = result["continuation"]["schedule_id"]
        context = json.loads(f.port.read_due(callback)["message"].split("\n", 1)[1])
        self.assertEqual(context["report_ref"], report.ref.to_dict())
        self.assertEqual(context["continuation_evidence"], evidence)
        self.assertIn("owner task and assessment gates", context["acceptance_authority"])
        response = self.dispatch()
        self.wait_file(self.child_receipt)
        self.assertIn("a" * 64, f.provider.calls[-1])
        self.assertIn("b" * 64, f.provider.calls[-1])
        self.release.touch(); self.wait_file(response)

    def test_oversized_durable_report_context_cannot_prepare_or_execute(self):
        f = self.fixture
        self.key = "oversized-evidence-owner-intent"
        before = f.port.list_due()
        f.app.assignments.append_report(f.app._read(self.anchor).assignment_ref,
            {"schema": "otto.manager-progress.v1", "project_ref": f.project.ref.to_dict(),
             "task_alias": "PA02", "task_ref": f.task.ref.to_dict(), "continue_requested": True,
             "summary": "evidence" * 3000, "next_action": "Continue only admitted work",
             "logical_request_key": self.key, "recorded_at": service.NOW.isoformat()}, expected_generation=1,
            logical_request_key=self.key, actor=f.actor)
        with self.assertRaisesRegex(ValueError, "bounded context size"):
            self.handle({"command": "manager-continue", "operation": "dispatch", "report_key": self.key})
        self.assertEqual(f.port.list_due(), before)
        self.assertEqual(len(f.provider.calls), self.provider_calls)


if __name__ == "__main__": unittest.main()
