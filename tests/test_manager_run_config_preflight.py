"""Single-config guard precedes manager/native and worker canonical effects."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from otto.portfolio.manager_journey_service import ManagerJourneyService


class ManagerRunConfigPreflightTests(unittest.TestCase):
    def test_duplicate_config_prevents_manager_composition_before_initializer(self):
        with TemporaryDirectory() as root:
            path = Path(root)
            for name in ("run.json", "run.yaml"):
                (path / name).write_text('{}')
            service = object.__new__(ManagerJourneyService)
            service.run_path = path
            service.server = SimpleNamespace(state={"manager": "manager"})
            service._host_execution = Mock(side_effect=AssertionError("initializer must not run"))
            with self.assertRaisesRegex(ValueError, "both run.json and run.yaml"):
                service._execution(principal="manager")
            service._host_execution.assert_not_called()

    def test_worker_duplicate_rejection_has_no_due_or_allowance_effect(self):
        with TemporaryDirectory() as root:
            path = Path(root)
            for name in ("run.json", "run.yaml"):
                (path / name).write_text('{}')
            service = object.__new__(ManagerJourneyService)
            service.run_path = path
            service.host = SimpleNamespace(_closing=False)
            service.server = SimpleNamespace(state={"task_refs": {"T1": {}}, "manager": "manager"})
            service.commands = SimpleNamespace(_authorize=Mock(), _key=lambda request: request["request_key"])
            value = service._submit_worker({"command": "run-worker", "task": "T1", "route": "xhard",
                "principal": "worker", "request_key": "exact-key", "focus": "bounded intent"})
            self.assertEqual(value["outcome"], "rejected")
            self.assertEqual(value["error"]["code"], "run_config_declaration")
            self.assertFalse(value["effects_started"])
            self.assertFalse(value["provider_called"])
            # The fixture intentionally has no Due or allowance ports: crossing
            # either boundary fails, rather than merely counting a mocked call.

if __name__ == "__main__":
    unittest.main()
