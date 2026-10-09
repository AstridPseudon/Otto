"""Focused D05 checks for additive timing and skill discoverability."""

from datetime import datetime, timezone
from pathlib import Path
import unittest

from otto.portfolio.recovery_timing import ReceiptTiming, timing_from_receipt


ROOT = Path(__file__).parents[1]


class RecoveryTimingTests(unittest.TestCase):
    def test_same_process_duration_and_clock_discontinuity_are_explicit(self):
        wall = [datetime(2026, 10, 9, 12, tzinfo=timezone.utc)]
        ticks = [10.0]
        timing = ReceiptTiming("logical-request", utc_clock=lambda: wall[0],
                               monotonic_clock=lambda: ticks[0])
        timing.observe("queued")
        ticks[0] = 10.25
        wall[0] = datetime(2026, 10, 9, 11, 59, tzinfo=timezone.utc)
        timing.observe("processing")
        value = timing.as_dict()
        self.assertEqual(value["correlation_id"], "logical-request")
        self.assertEqual(value["durations"]["queued_to_processing_seconds"], .25)
        self.assertTrue(any(gap["kind"] == "clock_discontinuity" for gap in value["gaps"]))

    def test_cross_process_receipt_does_not_invent_elapsed_time(self):
        value = timing_from_receipt({
            "logical_request_key": "same-request", "started_at": "2026-10-09T12:00:00Z",
            "ended_at": "2026-10-09T12:00:02Z", "outcome": "unknown",
        })
        self.assertEqual(value["correlation_id"], "same-request")
        self.assertNotIn("processing_to_terminal_seconds", value["durations"])
        self.assertTrue(any(gap["kind"] == "offline" for gap in value["gaps"]))
        self.assertEqual(value["phases"]["native"]["state"], "offline")

    def test_otto_index_links_only_installed_recovery(self):
        index = (ROOT / "src/otto/portfolio/skills/SKILL.md").read_text()
        skill = (ROOT / "src/otto/portfolio/skills/recovery/SKILL.md").read_text()
        self.assertIn("recovery/SKILL.md", index)
        self.assertIn("execution-control", skill)
        self.assertIn("reminder", skill)
        self.assertNotIn("evidence/SKILL.md", index)


if __name__ == "__main__":
    unittest.main()
