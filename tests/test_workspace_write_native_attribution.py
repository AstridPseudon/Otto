import json
import unittest

from herzchen.adapters.host import _digest_json, _native_host_context, _owner_delivery_appendix
from herzchen.contracts.model import HostIdentity, HostOperation, HostRequest, ResourceRef


SESSION = "fixture-session"
TURN = "fixture-turn"
TARGET = ResourceRef("fixture-owner", "work.task", "task-1", "rev-1")
ASSIGNMENT = {
    "authority": "fixture-owner", "kind": "wrk.assignment",
    "id": "assignment-1", "revision": "rev-2",
}
AUTHORIZATION = {
    "status": "authorized", "physical_session_id": SESSION,
    "assignment_ref": ASSIGNMENT, "generation": 1,
}


def _line(event_type, payload):
    return json.dumps({"type": event_type, "payload": payload}, separators=(",", ":"))


def _context(profile):
    brief = {
        "instruction_contract": {
            "task_ref": TARGET.to_dict(),
            "read_targets": ["/tmp/input.txt"] if profile == "read-only" else [],
        },
        "resource_resolution": {"responsibility_ref": ASSIGNMENT, "generation": 1},
    }
    prompt = (
        'Verified owner context.\n<otto-resource-brief sha256="' + _digest_json(brief) + '">\n'
        + json.dumps(brief, sort_keys=True, ensure_ascii=False)
        + "\n</otto-resource-brief>\n" + _owner_delivery_appendix(AUTHORIZATION, profile)
    )
    lines = [
        _line("session_meta", {"session_id": SESSION}),
        _line("turn_context", {
            "turn_id": TURN, "model": "gpt-test",
            "collaboration_mode": {"settings": {"reasoning_effort": "high"}},
            "sandbox_policy": {"type": profile, "writable_roots": ["/tmp"]},
            "approval_policy": "never",
        }),
        _line("event_msg", {
            "type": "item_completed", "turn_id": TURN, "thread_id": SESSION,
            "item": {"type": "UserMessage", "id": "user-1", "content": [{"type": "Text", "text": prompt}]},
        }),
    ]
    for identifier, status, exit_code, stdout in (
        ("test-failed", "failed", 1, "failed\n"),
        ("repair", "completed", 0, "repaired\n"),
        ("test-passed", "completed", 0, "passed\n"),
    ):
        parsed = ([{"type": "read", "path": "/tmp/input.txt"}]
                  if profile == "read-only" else [{"type": "unknown", "cmd": identifier}])
        lines.append(_line("event_msg", {
            "type": "item_completed", "turn_id": TURN, "thread_id": SESSION,
            "item": {
                "type": "CommandExecution", "id": identifier,
                "command": ["/bin/zsh", "-lc", identifier], "cwd": "/tmp",
                "parsed_cmd": parsed, "status": status, "exit_code": exit_code,
                "stdout": stdout, "stderr": "", "aggregated_output": stdout,
            },
        }))
    lines.extend([
        _line("event_msg", {
            "type": "item_completed", "turn_id": TURN, "thread_id": SESSION,
            "started_at_ms": 10, "completed_at_ms": 11,
            "item": {"type": "AgentMessage", "id": "final-1", "phase": "final_answer",
                     "content": [{"type": "Text", "text": "Repair complete; tests pass."}]},
        }),
        _line("event_msg", {"type": "task_complete", "turn_id": TURN}),
    ])
    return _native_host_context(
        lines,
        request=HostRequest(HostOperation.RESUME, HostIdentity("fixture-agent", SESSION), TARGET, profile),
        session_id=SESSION, turn_id=TURN, observed_model="gpt-test", observed_reasoning="high",
        worker_content=[], delivered_brief=brief, delivered_authorization=AUTHORIZATION,
    )


class WorkspaceWriteAttributionTests(unittest.TestCase):
    def test_failed_test_then_repair_and_pass_remains_attributed(self):
        value = _context("workspace-write")
        self.assertIsNotNone(value)
        output = value["task_bound_evidence"]["operation_result"]["output"]
        self.assertEqual([item["exit_code"] for item in output["commands"]], [1, 0, 0])
        self.assertEqual(output["command_execution"], {
            "status": "completed", "command_count": 3, "nonzero_exit_count": 1,
        })

    def test_read_only_failed_command_remains_unattributed(self):
        self.assertIsNone(_context("read-only"))


if __name__ == "__main__":
    unittest.main()
