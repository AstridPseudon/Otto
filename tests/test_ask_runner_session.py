"""Runner-side fence for resuming the exact asking session and generation."""
import unittest

from herzchen.fleet.runner import AskingSessionMismatch, require_asking_session


def binding(*, assignment="assignment-A", revision="rev-3", generation=4,
            native_session="native-17", schedule="schedule-9"):
    return {
        "assignment_ref": {"authority": "owner", "kind": "wrk.assignment", "id": assignment, "revision": revision},
        "generation": generation,
        "native_session_id": native_session,
        "schedule_id": schedule,
    }


class AskRunnerSessionTests(unittest.TestCase):
    def test_accepts_only_the_exact_asking_assignment_session_generation_and_schedule(self):
        asking = binding()
        require_asking_session(asking, dict(asking))

    def test_rejects_task_only_match_and_every_stale_binding_component(self):
        asking = binding()
        for candidate in (
            {"task_ref": {"authority": "owner", "kind": "wrk.task", "id": "same-task", "revision": "rev-1"}},
            binding(revision="rev-2"),
            binding(generation=5),
            binding(native_session="replacement-session"),
            binding(schedule="replacement-schedule"),
        ):
            with self.subTest(candidate=candidate), self.assertRaises(AskingSessionMismatch):
                require_asking_session(asking, candidate)

    def test_rejects_incomplete_or_invalid_fence_values(self):
        for asking in (binding(generation=True), binding(generation=0), binding(native_session=" "),
                       binding(schedule=""), binding(assignment=""), binding(revision=None)):
            with self.subTest(asking=asking), self.assertRaises(AskingSessionMismatch):
                require_asking_session(asking, asking)


if __name__ == "__main__":
    unittest.main()
