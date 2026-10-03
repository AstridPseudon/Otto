import json
import unittest

from herzchen.adapters.host import (
    _digest_json, _native_host_context, _owner_delivery_appendix,
    _select_invocation_turn,
)
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


def _context(profile, *, delayed_command_started_at_ms=None):
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
            "started_at_ms": 100, "completed_at_ms": 110,
            "item": {"type": "AgentMessage", "id": "final-1", "phase": "final_answer",
                     "content": [{"type": "Text", "text": "Repair complete; tests pass."}]},
        }),
        _line("event_msg", {"type": "task_complete", "turn_id": TURN,
                            "completed_at": 1}),
    ])
    if delayed_command_started_at_ms is not None:
        lines.append(_line("event_msg", {
            "type": "item_completed", "turn_id": TURN, "thread_id": SESSION,
            "started_at_ms": delayed_command_started_at_ms, "completed_at_ms": 1200,
            "item": {
                "type": "CommandExecution", "id": "delayed-cancelled-search",
                "command": ["/bin/zsh", "-lc", "delayed-search"], "cwd": "/tmp",
                "parsed_cmd": [{"type": "unknown", "cmd": "delayed-search"}],
                "status": "failed", "exit_code": 137,
                "stdout": "partial results\n", "stderr": "",
                "aggregated_output": "partial results\n",
            },
        }))
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

    def test_delayed_cancelled_command_started_before_final_remains_attributed(self):
        value = _context("workspace-write", delayed_command_started_at_ms=90)
        self.assertIsNotNone(value)
        output = value["task_bound_evidence"]["operation_result"]["output"]
        self.assertEqual([item["exit_code"] for item in output["commands"]], [1, 0, 0, 137])
        self.assertEqual(output["command_execution"]["nonzero_exit_count"], 2)

    def test_delayed_command_started_after_final_is_not_attributed(self):
        self.assertIsNone(_context("workspace-write", delayed_command_started_at_ms=101))

    def test_turn_selection_accepts_only_logically_prior_delayed_command(self):
        prompt = "exact owner prompt"
        def fixture(started_at_ms):
            return [
                _line("event_msg", {"type": "task_started", "turn_id": TURN, "started_at": 1}),
                _line("turn_context", {"turn_id": TURN}),
                _line("event_msg", {"type": "item_completed", "turn_id": TURN,
                    "thread_id": SESSION, "started_at_ms": 10, "completed_at_ms": 10,
                    "item": {"type": "UserMessage", "id": "user-select",
                             "content": [{"type": "Text", "text": prompt}]}}),
                _line("event_msg", {"type": "task_complete", "turn_id": TURN, "completed_at": 1}),
                _line("event_msg", {"type": "item_completed", "turn_id": TURN,
                    "thread_id": SESSION, "started_at_ms": started_at_ms, "completed_at_ms": 1200,
                    "item": {"type": "CommandExecution", "id": "late-select"}}),
            ]
        self.assertEqual(
            _select_invocation_turn(fixture(900), session_id=SESSION, prompt=prompt,
                                    boundary=0, started_at="1970-01-01T00:00:00+00:00")[0],
            TURN,
        )
        self.assertIsNone(
            _select_invocation_turn(fixture(1001), session_id=SESSION, prompt=prompt,
                                    boundary=0, started_at="1970-01-01T00:00:00+00:00")
        )


if __name__ == "__main__":
    unittest.main()
