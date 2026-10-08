"""Focused D04 capability binding checks over the shared Due gate."""

from datetime import datetime, timezone
import unittest

from otto.attention import DueRecord, validate_execution_configuration


def ref(kind, ident):
    return {"authority": "owner", "kind": kind, "id": ident, "revision": "rev-1"}


class DueConfigurationTests(unittest.TestCase):
    def record(self, *, target=None):
        target = {"host": "local", "native_id": "advisor-session", **(target or {})}
        return DueRecord(
            schedule_id="advisor-schedule",
            recipient="advisor",
            instruction="Inspect the current project.",
            profile="read-only",
            anchor=datetime(2026, 10, 8, tzinfo=timezone.utc).isoformat(),
            due_at=datetime(2026, 10, 8, tzinfo=timezone.utc).isoformat(),
            last_covered_slot=-1,
            invocation_identity="advisor-occurrence",
            assignment_ref=ref("wrk.assignment", "advisor-1"),
            allowance_ref=ref("limit", "advisor-pool"),
            target=target,
            requested_model="gpt-test",
            requested_reasoning="high",
        )

    def allowance(self):
        return {
            "ref": ref("limit", "advisor-pool"),
            "assignment_ref": ref("wrk.assignment", "advisor-1"),
            "generation": 1,
            "available": True,
            "remaining": 1,
        }

    def capability(self, **overrides):
        value = {
            "revision": "codex-route-v1",
            "models": {"gpt-test": {"reasoning": ["high"]}},
        }
        value.update(overrides)
        return value

    def test_explicitly_unavailable_provider_is_rejected_before_allowance(self):
        result = validate_execution_configuration(
            self.record(), capability_evidence=self.capability(available=False),
            allowance_evidence=self.allowance(),
        )
        self.assertEqual(result["outcome"], "rejected")
        self.assertEqual(result["error"]["code"], "unsupported_provider")

    def test_explicit_adapter_mismatch_is_rejected(self):
        result = validate_execution_configuration(
            self.record(target={"native_adapter": "codex-route"}),
            capability_evidence=self.capability(adapter_identity="other-route"),
            allowance_evidence=self.allowance(),
        )
        self.assertEqual(result["outcome"], "rejected")
        self.assertEqual(result["error"]["code"], "unsupported_provider")

    def test_matching_explicit_adapter_is_retained_in_supported_result(self):
        result = validate_execution_configuration(
            self.record(target={"native_adapter": "codex-route"}),
            capability_evidence=self.capability(adapter_identity="codex-route"),
            allowance_evidence=self.allowance(),
        )
        self.assertEqual(result["outcome"], "configuration_supported")
        self.assertEqual(result["capability"]["adapter_identity"], "codex-route")


if __name__ == "__main__":
    unittest.main()
