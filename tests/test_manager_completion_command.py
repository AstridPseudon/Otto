"""Completion command coverage without Store access or provider execution."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from otto.portfolio.execution_operations import complete_task_from_command

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


client = load("completion_client", ROOT / "manager_ctl.py")


def ref(kind, identity):
    return {"authority": "completion-test", "kind": kind, "id": identity, "revision": "rev-1"}


class CompletionCommandTests(unittest.TestCase):
    def setUp(self):
        self.complete = Mock(return_value={"outcome": "completed"})
        self.server = SimpleNamespace()
        self.server.state = {
            "task_refs": {"PA01": ref("work.task", "task")},
            "project_ref": ref("work.project", "project"),
            "assignment_ref": ref("wrk.assignment", "manager"),
            "manager": "manager-principal", "manager_generation": 7,
        }
        self.server.portfolio = SimpleNamespace(complete_task=self.complete)
        def handle(request):
            state = self.server.state
            return complete_task_from_command(
                self.server.portfolio, request=request,
                project_ref=state["project_ref"], task_ref=state["task_refs"][request["task"]],
                manager_assignment_ref=state["assignment_ref"],
                manager_actor=state["manager"], manager_generation=state["manager_generation"],
            )
        self.server.handle = handle
        self.evidence = ref("wrk.result", "evidence")
        self.gate = ref("assessment.acceptance", "gate")
        self.payload = {
            "command": "complete-task", "task": "PA01", "request_key": "same-request-key",
            "disposition": "accepted", "evidence_refs": [json.dumps(self.evidence)],
            "evidence_hashes": ["review=" + "a" * 64], "gate_refs": [json.dumps(self.gate)],
        }

    def argv(self):
        return ["manager_ctl.py", "complete-task", "--task", "PA01", "--request-key", "same-request-key",
                "--disposition", "accepted", "--evidence-ref", json.dumps(self.evidence),
                "--evidence-hash", "review=" + "a" * 64, "--gate-ref", json.dumps(self.gate)]

    def test_cli_and_handler_forward_repeated_gates_and_optional_pins(self):
        second_gate = ref("assessment.acceptance", "second-gate")
        optional = {"candidate_ref": ref("dat.content.document", "candidate"),
                    "result_ref": ref("assessment.result", "result"),
                    "attempt_ref": ref("assessment.attempt", "attempt")}
        argv = self.argv() + ["--gate-ref", json.dumps(second_gate), "--source-set-digest", "b" * 64]
        for name, value in optional.items():
            argv.extend(["--" + name.replace("_", "-"), json.dumps(value)])
        # The only command destination is an inert spy, never the real IPC port.
        with patch.object(client, "call", side_effect=self.server.handle), patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
            client.main()
        args, kwargs = self.complete.call_args
        self.assertEqual(args, (self.server.state["project_ref"], self.server.state["task_refs"]["PA01"], self.server.state["assignment_ref"]))
        self.assertEqual(kwargs, {
            "actor": "manager-principal", "request_id": "same-request-key", "expected_generation": 7,
            "expected_project_revision": "rev-1", "expected_task_revision": "rev-1", "disposition": "accepted",
            "evidence_refs": [self.evidence], "evidence_hashes": {"review": "a" * 64},
            "gate_refs": [self.gate, second_gate], "source_set_digest": "b" * 64, **optional,
        })

    def test_required_fields_preserve_same_request_without_optional_pins(self):
        self.server.handle(self.payload)
        self.server.handle(dict(self.payload))
        self.assertEqual(self.complete.call_count, 2)
        first, second = self.complete.call_args_list
        self.assertEqual(first, second)
        self.assertEqual(first.kwargs["request_id"], "same-request-key")
        for name in ("candidate_ref", "result_ref", "attempt_ref", "source_set_digest"):
            self.assertNotIn(name, first.kwargs)

    def test_cli_requires_gate_before_contacting_ipc(self):
        argv = self.argv()[:-2]
        with patch.object(client, "call") as call, patch("sys.argv", argv), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                client.main()
        self.assertEqual(error.exception.code, 2)
        call.assert_not_called()

    def test_cli_preserves_rejected_owner_outcome(self):
        with patch.object(client, "call", return_value={"outcome": "held"}), patch("sys.argv", self.argv()), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                client.main()
        self.assertEqual(error.exception.code, 1)

    def test_handler_rejects_missing_or_malformed_gates_before_owner_call(self):
        for gates in (None, [], "not-a-list", ["not-json"], ["[]"], ["{}"], [json.dumps({**self.gate, "authority": ""})]):
            with self.subTest(gates=gates):
                request = {**self.payload, "gate_refs": gates}
                with self.assertRaises(ValueError):
                    self.server.handle(request)
        self.complete.assert_not_called()

    def test_handler_rejects_malformed_optional_refs_and_source_digest(self):
        for name in ("candidate_ref", "result_ref", "attempt_ref"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.server.handle({**self.payload, name: "{}"})
        with self.assertRaises(ValueError):
            self.server.handle({**self.payload, "source_set_digest": " "})
        self.complete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
