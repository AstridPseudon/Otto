"""Cold manager preparation and recovery through the real CLI composition.

Only the provider executable is a disposable fixture. Store, owner operations,
CLI admission, native parsing, and result custody are the maintained code.
"""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

from herzchen.content.instructions import validate_instruction_content
from herzchen.contracts import ResourceRef
from otto.agents.herzchen_adapter import HerzchenCodexAdapter, JsonlHostTurnContextReader
from tests import test_execution_application as application

SESSION = "bootstrap-session"

# This transport emits native-shaped records without calling a model. It retains
# submitted bytes separately so the test can inspect what actually crossed stdin.
CLI = r'''
import json, sys, time
from pathlib import Path
root = Path(__file__).parent
prompt = sys.stdin.read()
resume = "resume" in sys.argv
session = "bootstrap-session"
turn = "work-turn" if resume else "ready-turn"
now = int(time.time())
trace = root / "native.jsonl"
records = []
if not resume:
    records.append({"type": "session_meta", "payload": {"session_id": session}})
records.extend([
    {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn, "started_at": now}},
    {"type": "turn_context", "payload": {"turn_id": turn, "model": "gpt-test",
        "collaboration_mode": {"settings": {"reasoning_effort": "high"}},
        "sandbox_policy": {"type": "workspace-write", "writable_roots": [str(root)]},
        "approval_policy": "never"}},
    {"type": "event_msg", "payload": {"type": "item_completed", "turn_id": turn,
        "thread_id": session, "item": {"type": "UserMessage", "id": "input-" + turn,
        "content": [{"type": "Text", "text": prompt}]}}},
])
if resume:
    records.append({"type": "event_msg", "payload": {"type": "item_completed", "turn_id": turn,
        "thread_id": session, "item": {"type": "CommandExecution", "id": "check",
        "command": ["python", "check.py"], "cwd": str(root),
        "parsed_cmd": [{"type": "unknown", "cmd": "check"}], "status": "completed",
        "exit_code": 0, "stdout": "passed\n", "stderr": "", "aggregated_output": "passed\n"}}})
records.extend([
    {"type": "event_msg", "payload": {"type": "item_completed", "turn_id": turn,
        "thread_id": session, "started_at_ms": now * 1000, "completed_at_ms": now * 1000,
        "item": {"type": "AgentMessage", "id": "final-" + turn, "phase": "final_answer",
        "content": [{"type": "Text", "text": "Work returned." if resume else "READY"}]}}},
    {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn, "completed_at": now}},
])
with trace.open("a") as stream:
    stream.write("".join(json.dumps(value) + "\n" for value in records))
with (root / "submitted.jsonl").open("a") as stream:
    stream.write(json.dumps({"resume": resume, "session": session, "prompt": prompt, "argv": sys.argv}) + "\n")
print(json.dumps({"type": "thread.started", "thread_id": session}), flush=True)
print(json.dumps({"type": "turn.started", "turn_id": turn}), flush=True)
print(json.dumps({"type": "turn.completed", "turn_id": turn}), flush=True)
'''


class ManagerBootstrapRecoveryTests(unittest.TestCase):
    def test_missing_contract_stops_work_then_owner_reassign_resumes_same_session(self):
        f = application.ExecutionApplicationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        root = Path(f.temporary.name).resolve()
        launcher = root / "fixture-cli"
        launcher.write_text("#!" + sys.executable + "\n" + CLI)
        launcher.chmod(0o700)
        capture = root / "context.jsonl"
        adapter = HerzchenCodexAdapter(owner="manager", source=str(root), worktree=str(root),
            launcher=str(launcher), requested_model="gpt-test", requested_reasoning="high",
            require_host_context=True, native_trace_path=str(root / "native.jsonl"),
            host_context_path=str(capture), turn_context_reader=JsonlHostTurnContextReader(capture))
        assignment, guide, _ = f.role_handles("manager", "manager", None)
        f.app = f.owner.execution_application(due_port=f.port, adapter=adapter, manager_actor="manager")
        bad_mandate = f.app.portfolio.create_document(f.project.ref.to_dict(), actor="manager",
            request_id="bootstrap-mandate", document_id="bootstrap-mandate", role="mandate",
            content={"role": "manager", "scope_ref": f.project.ref.to_dict(), "status": "active",
                     "brief": {"role": "manager", "mandate": "Complete the project"}})
        mandate_ref = bad_mandate["record"]["payload"]["current_revision"]
        worker = f.app._read(f.app.assign_worker(**f.request())["schedule_id"])
        base = assignment.payload["resource_adoption_base_ref"]
        original = replace(worker, schedule_id="bootstrap-manager", recipient="manager",
            instruction="Begin the full authorized project", role="manager", purpose="bootstrap",
            assignment_ref=base, host_evidence=None, in_flight_request="bootstrap-manager",
            invocation_identity="bootstrap-manager", execution_mode="fresh_manager",
            context_refs=(guide, mandate_ref), target={**worker.target, "role": "manager",
                "principal": "manager", "assignment_ref": base, "mandate_ref": mandate_ref})
        created = f.port.save_due(original.schedule_id, original.to_dict(),
            request_id="bootstrap-manager:create", expected_version=0)
        f.port.reconcile_assignment_resources(original.schedule_id, assignment_ref=assignment.ref.to_dict(),
            request_id="bootstrap-manager:resources", expected_version=created["version"])
        failed = f.app.start(schedule_id=original.schedule_id)
        self.assertEqual(failed["outcome"], "unknown", failed)
        retained = f.port.read_due(original.schedule_id)
        raw = retained["host_evidence"]["gateway_attempt"]["result"]["raw_result"]
        self.assertTrue(raw["initialization_envelope"]["host_evidence"]["invocation_turn_verified"])
        self.assertEqual(raw["initialization_receipt"]["identity"]["physical_session_id"], SESSION)
        self.assertEqual(raw["work_envelope"]["delivery_state"], "not_started")
        self.assertEqual(raw["work_envelope"]["reconciliation"], "trusted recipient authorization is not exact")
        self.assertIsNone(raw["work_envelope"]["process_id"])
        submitted = [json.loads(line) for line in (root / "submitted.jsonl").read_text().splitlines()]
        self.assertEqual(len(submitted), 1)
        self.assertIn("Return READY", submitted[0]["prompt"])
        self.assertNotIn("Begin the full authorized project", submitted[0]["prompt"])

        rebound = f.app.assignments.reassign(assignment.ref, principal="manager", session=SESSION,
            reason="Owner verified READY-only initialization and exact pre-work contract failure",
            expected_generation=1, logical_request_key="owner-session-recovery", actor=f.actor)
        content = f.owner.content.read(ResourceRef.from_dict(guide))["content"]
        adopted = f.app.assignments.adopt_resources(rebound.ref,
            resources=[{"resource_ref": guide, "resource_name": content["name"],
                "content_digest": validate_instruction_content(content), "required": True}],
            expected_revision=rebound.revision, expected_generation=2,
            logical_request_key="recovered-guide-adoption", actor=f.actor)
        contract = f.request()["instruction_contract"]
        contract["authority"]["owner_actor"] = "manager"
        contract["authority"]["effect_profile"] = "workspace-write-manager"
        contract["allowed_operations"].append("canonical_manager_commands")
        contract["authority"]["permitted_effects"].append("canonical_manager_commands")
        mandate = f.app.portfolio.create_document(f.project.ref.to_dict(), actor="manager",
            request_id="recovered-mandate", document_id="recovered-mandate", role="mandate",
            content={"role": "manager", "scope_ref": f.project.ref.to_dict(), "status": "active",
                "dispatch_enabled": True, "task_ref": f.task.ref.to_dict(),
                "assignment_ref": adopted.ref.to_dict(), "generation": 2,
                "brief": {"role": "manager", "mandate": "Complete the project"},
                "instruction_contract": contract})
        current_mandate = mandate["record"]["payload"]["current_revision"]
        instruction = "Continue the actual full request intact: café, J01–J04; suggestions are advice."
        prepared = f.app.prepare_role(role="manager", project_ref=f.project.ref.to_dict(),
            task_ref=f.task.ref.to_dict(), assignment_ref=adopted.ref.to_dict(), generation=2,
            mandate_ref=current_mandate, context_refs=(guide, current_mandate),
            request_key="recovered-manager-work", instruction=instruction, model="gpt-test",
            reasoning="high", profile="workspace-write", native_session_id=SESSION)
        self.assertEqual(prepared["outcome"], "committed", prepared)
        success = f.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(success["outcome"], "succeeded", success)
        self.assertEqual(f.port.read_due(original.schedule_id), retained)
        self.assertEqual(adopted.generation, 2)
        self.assertEqual(adopted.history[-1]["session"], SESSION)
        result = success["result"]
        self.assertEqual(result["physical_session_id"], SESSION)
        self.assertEqual(result["observed_turn_id"], "work-turn")
        self.assertIsNone(result["raw_result"]["initialization_envelope"])
        submitted = [json.loads(line) for line in (root / "submitted.jsonl").read_text().splitlines()]
        self.assertEqual([row["resume"] for row in submitted], [False, True])
        self.assertIn(instruction, submitted[1]["prompt"])
        self.assertIn(SESSION, submitted[1]["argv"])
        brief = result["resource_evidence"]["brief"]
        self.assertIn(json.dumps(brief, sort_keys=True, ensure_ascii=False, separators=(",", ":")), submitted[1]["prompt"])
        evidence = result["task_bound_evidence"]
        self.assertEqual(evidence["owner_delivery_authorization"]["brief_sha256"],
                         result["resource_evidence"]["brief_sha256"])
        duplicate = f.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(duplicate["outcome"], "replayed")
        self.assertEqual(len((root / "submitted.jsonl").read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
