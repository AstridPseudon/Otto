"""Completion command coverage without Store access or provider execution."""
from tests.execution_helpers import start_worker
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from herzchen.contracts import ResourceRef
from otto.portfolio.intake import OttoPortfolio
from otto.portfolio.execution_operations import complete_task_from_command
from tests import test_evidence_wiring as managed_evidence
from tests import test_execution_application as execution

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

    def test_real_owner_managed_evidence_completion_and_missing_evidence_block(self):
        # Reuse the production evidence owner and the real worker execution
        # fixture, then compose execution on the resolver-equipped owner.
        fixture = managed_evidence.ProductionEvidenceWiringTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        f = fixture.f
        adapter = f.app.runtime.adapter

        # Activate the existing task through the reviewed-plan owner boundary
        # before composing the manager execution application.
        portfolio = OttoPortfolio(fixture.owner.consumer_operations())
        plan = portfolio.create_document(f.project.ref.to_dict(), actor="manager",
            request_id="managed-completion-plan", role="plan", content={
                "schema": "otto.plan.v1", "deliverables": [{"id": "one", "title": f.task.payload["title"],
                    "acceptance": ["manager verifies exact managed evidence"]}]})
        plan_ref = {**plan["document_ref"], "revision": "rev-1"}
        review = portfolio.create_document(f.project.ref.to_dict(), actor="manager",
            request_id="managed-completion-plan-review", role="review", content={
                "plan_ref": plan_ref, "disposition": "approved"})
        review_ref = {**review["document_ref"], "revision": "rev-1"}
        fixture.owner.graph.admit(ResourceRef(f.task.ref.authority, f.task.ref.kind, f.task.ref.id),
            revision=f.task.ref.revision, review_ref=ResourceRef.from_dict(review_ref), disposition="approved",
            logical_request_key="managed-completion-admit", actor=f.actor)
        f.task = fixture.owner.graph.reader.get_identity(ResourceRef(f.task.ref.authority, f.task.ref.kind, f.task.id))
        self.assertEqual(fixture.owner.graph.admission_state(f.task.ref)["admitted_revision"], f.task.ref.revision)
        fixture.state["task_refs"]["PA01"] = f.task.ref.to_dict()
        policy = {"task_specs": [{"id": "one", "title": f.task.payload["title"]}],
            "task_criterion_pairs": [{"task_ref": f.task.ref.to_dict(),
                "criterion_ref": fixture.state["criterion_refs"]["C01"]}]}
        activation = fixture.owner.reviewed_plan_activation(owner_policy=policy).activate(
            project_ref=f.project.ref.to_dict(), plan_ref=plan_ref, review_ref=review_ref,
            owner_policy=policy, request_key="managed-completion-activate", manager="manager")
        self.assertEqual(activation["outcome"], "activated", activation)
        f.project = fixture.owner.graph.reader.get_identity(ResourceRef.from_dict(activation["project_ref"]))
        fixture.state["project_ref"] = f.project.ref.to_dict()
        f.app = fixture.owner.execution_application(due_port=f.port, adapter=adapter, clock=lambda: execution.NOW)

        dispatched = start_worker(f.app, f.request())
        self.assertEqual(dispatched["outcome"], "succeeded", dispatched)

        decision_ref = fixture._accept_managed("manager-completion")
        decision = f.store.get_identity(ResourceRef.from_dict(decision_ref))
        evidence_ref = decision.payload["evidence_refs"][0]
        digest_record = decision.payload["evidence_digests"][0]
        digest = digest_record.get("digest") if isinstance(digest_record, dict) else digest_record
        kwargs = dict(actor="manager", request_id="managed-evidence-completion", expected_generation=1,
            expected_project_revision=f.project.revision, expected_task_revision=f.task.revision,
            disposition="accepted", evidence_refs=[evidence_ref], evidence_hashes={"review": digest},
            gate_refs=[decision_ref], candidate_ref=fixture.candidate)

        status = fixture.handler.status(ResourceRef.from_dict(evidence_ref), actor=f.actor)
        payload_path = Path(fixture.directory.name) / "managed" / status["manifest"]["storage"]["location"]
        original = payload_path.read_bytes()
        try:
            payload_path.unlink()
            missing = f.app.portfolio.complete_task(f.project.ref.to_dict(), f.task.ref.to_dict(),
                fixture.manager.ref.to_dict(), **{**kwargs, "request_id": "managed-evidence-missing"})
            self.assertEqual(missing.get("outcome"), "held", missing)
            self.assertIn("completion_evidence_unverified", missing["error"]["message"])
            current = fixture.owner.graph.reader.get_identity(f.task.ref)
            self.assertNotEqual(current.payload.get("lifecycle"), "completed")

            payload_path.write_bytes(bytes([original[0] ^ 0xFF]) + original[1:])
            tampered = f.app.portfolio.complete_task(f.project.ref.to_dict(), f.task.ref.to_dict(),
                fixture.manager.ref.to_dict(), **{**kwargs, "request_id": "managed-evidence-tampered"})
            self.assertEqual(tampered.get("outcome"), "held", tampered)
            self.assertIn("completion_evidence_mismatch", tampered["error"]["message"])
            current = fixture.owner.graph.reader.get_identity(f.task.ref)
            self.assertNotEqual(current.payload.get("lifecycle"), "completed")
        finally:
            payload_path.write_bytes(original)

        gate_state = fixture.owner.assignments.completion_blockers(f.task.ref,
            candidate=ResourceRef.from_dict(fixture.candidate), gate_refs=[ResourceRef.from_dict(decision_ref)],
            actor=f.actor, completion_evidence_refs=[ResourceRef.from_dict(evidence_ref)],
            completion_evidence_hashes=[digest])
        self.assertEqual(gate_state["evidence_verification"], "verified", gate_state)
        self.assertEqual(gate_state["blockers"], [], gate_state)

        completed = f.app.portfolio.complete_task(f.project.ref.to_dict(), f.task.ref.to_dict(),
            fixture.manager.ref.to_dict(), **kwargs)
        self.assertEqual(completed["outcome"], "completed", completed)
        self.assertEqual(completed["completion"]["assessment_gate_check"]["evidence_verification"], "verified")


if __name__ == "__main__":
    unittest.main()
