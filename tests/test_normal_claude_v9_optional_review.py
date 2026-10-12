"""Provider-free unit coverage for the optional review projection boundary.

Run with the patched runtime source first on PYTHONPATH, for example:

    PYTHONPATH=/path/to/runtime-source python3 -m unittest \
      test_normal_claude_v9_optional_review
"""

import unittest
from types import SimpleNamespace

from otto.portfolio.manager_journey_service import ManagerJourneyService


class _Commands:
    def __init__(self, *, policy=None, review_error=None):
        self.policy = policy
        self.review_error = review_error
        self.review_calls = []

    def settle_completion_intents(self):
        return [{"intent_id": "intent-1"}]

    def review_input(self, task):
        self.review_calls.append(task)
        if self.review_error is not None:
            raise self.review_error
        return {"outcome": "succeeded", "task": task}


def _service(commands, state):
    service = ManagerJourneyService.__new__(ManagerJourneyService)
    service.commands = commands
    service.server = SimpleNamespace(state=state)
    service._refresh_refs = lambda: None
    return service


class OptionalReviewProjectionTests(unittest.TestCase):
    def test_absent_policy_is_explicitly_unavailable_and_captured_result_survives(self):
        commands = _Commands()
        service = _service(commands, {"manager": "manager-1"})
        captured = {
            "outcome": "succeeded",
            "provider_called": True,
            "captured_result": {"answer": "worker artifact"},
        }

        settled = service._settle_shared_completion(captured, review_task="worker-1", refresh=False)

        self.assertEqual(settled["outcome"], "succeeded")
        self.assertIs(settled["captured_result"], captured["captured_result"])
        self.assertEqual(settled["completion_intents"], [{"intent_id": "intent-1"}])
        self.assertEqual(settled["review_input"]["outcome"], "unavailable")
        self.assertFalse(settled["review_input"]["provider_called"])
        self.assertFalse(settled["review_input"]["effects_started"])
        self.assertFalse(settled["review_input"]["retry"])
        self.assertEqual(settled["review_input"]["assessment_policy_selection"]["state"], "unavailable")
        self.assertEqual(commands.review_calls, [])

    def test_configured_policy_keeps_strict_review_failures(self):
        error = PermissionError("configured policy rejected the review task")
        commands = _Commands(policy={"mode": "strict"}, review_error=error)
        service = _service(commands, {"manager": "manager-1"})

        with self.assertRaisesRegex(PermissionError, "configured policy"):
            service._settle_shared_completion({"outcome": "succeeded"}, review_task="worker-1", refresh=False)
        self.assertEqual(commands.review_calls, ["worker-1"])

    def test_present_policy_state_keeps_strict_review_failures(self):
        error = ValueError("stale or foreign assessment policy")
        commands = _Commands(review_error=error)
        service = _service(commands, {
            "manager": "manager-1",
            "assessment_policy": {"policy_id": "foreign-policy"},
        })

        with self.assertRaisesRegex(ValueError, "stale or foreign"):
            service._settle_shared_completion({"outcome": "succeeded"}, review_task="worker-1", refresh=False)
        self.assertEqual(commands.review_calls, ["worker-1"])


if __name__ == "__main__":
    unittest.main()
