"""D01 pure cross-adapter Usage/cost contract and mechanical fixtures."""
from __future__ import annotations

import unittest

from herzchen.usage.contract import (
    CHARGEABLE_FIELDS,
    SOURCE_COMMIT,
    UsageContractError,
    contract_definition,
    fixture_catalog,
    normalize_usage_event,
    physical_span_identity,
    run_fixture_contract,
    validate_rate_schedule,
)


class UsageContractTests(unittest.TestCase):
    def test_contract_freezes_adapters_seams_pins_and_explicit_coverage(self):
        contract = contract_definition()
        self.assertEqual(contract["schema"], "otto.usage-cost.contract.v1")
        self.assertEqual(contract["provenance"]["source"]["commit"], SOURCE_COMMIT)
        self.assertEqual(set(contract["adapters"]), {"codex-direct", "codex-host", "claude-code"})
        self.assertEqual(contract["adapters"]["codex-direct"]["coverage"], {"mechanical": "supported", "live": "supported"})
        self.assertEqual(contract["adapters"]["codex-host"]["coverage"], {"mechanical": "supported", "live": "supported"})
        self.assertEqual(contract["adapters"]["claude-code"]["coverage"], {"mechanical": "supported", "live": "unverified"})
        self.assertEqual(contract["adapters"]["claude-code"]["routes"]["resume"], "unsupported")
        self.assertIn("adapter_records", contract["predecessor_seams"])
        self.assertIn("evidence", contract["predecessor_seams"])
        self.assertIn("recovery", contract["predecessor_seams"])
        self.assertIn("events", contract["predecessor_seams"])
        self.assertFalse(contract["metric_schema"]["unknown_is_zero"])

    def test_same_contract_normalizes_both_codex_paths_and_selected_claude_fixture(self):
        catalog = fixture_catalog()
        for adapter_id, fixture in catalog["fixtures"].items():
            with self.subTest(adapter_id=adapter_id):
                value = normalize_usage_event(fixture["event"], adapter_id=adapter_id)
                self.assertEqual(value["usage"]["state"], "observed")
                self.assertEqual(value["identity"]["metric_scope"], "turn")
                self.assertEqual(value["identity"]["namespace"], value["provider_environment"]["namespace"])
                self.assertEqual(value["schema"], "otto.usage-cost.contract.v1.observation.v1")
                self.assertEqual(value["requested"], {"model": None, "tier": None})
        self.assertFalse(catalog["paid_provider_calls"])

    def test_missing_empty_zero_malformed_schema_partial_truncated_and_conflict_stay_distinct(self):
        catalog = fixture_catalog()["negative_distinctions"]
        expected = {
            "missing": "missing", "empty": "empty", "zero": "zero", "malformed": "invalid",
            "unsupported_schema": "unsupported_schema", "partial": "partial",
            "truncated": "truncated", "conflict": "conflict",
        }
        for name, event in catalog.items():
            with self.subTest(name=name):
                adapter_id = "claude-code" if name == "unsupported_schema" else "codex-direct"
                value = normalize_usage_event(event, adapter_id=adapter_id,
                                             session_id="fixture-session", turn_id="fixture-turn")
                self.assertEqual(value["usage"]["state"], expected[name])
                if name == "zero":
                    self.assertEqual(value["usage"]["metrics"], {"input_tokens": 0})
                else:
                    self.assertIsNone(value["usage"]["metrics"])

    def test_positive_usage_requires_exact_schema_and_qualified_zero_remains_zero(self):
        schema_less_positive = normalize_usage_event(
            {"type": "turn.completed", "usage": {"input_tokens": 1}},
            adapter_id="codex-direct", session_id="fixture-session", turn_id="positive",
        )
        self.assertEqual(schema_less_positive["usage"]["state"], "unsupported_schema")
        self.assertIsNone(schema_less_positive["usage"]["metrics"])

        qualified_zero = normalize_usage_event(
            {
                "schema": "codex-cli-jsonl.turn-completed.v1",
                "type": "turn.completed",
                "usage": {"input_tokens": 0},
            },
            adapter_id="codex-direct", session_id="fixture-session", turn_id="zero",
        )
        self.assertEqual(qualified_zero["usage"]["state"], "zero")
        self.assertEqual(qualified_zero["usage"]["metrics"], {"input_tokens": 0})

        schema_less_zero = normalize_usage_event(
            {"type": "turn.completed", "usage": {"input_tokens": 0}},
            adapter_id="codex-direct", session_id="fixture-session", turn_id="unqualified-zero",
        )
        self.assertEqual(schema_less_zero["usage"]["state"], "unsupported_schema")
        self.assertIsNone(schema_less_zero["usage"]["metrics"])

    def test_invalid_values_and_cumulative_scope_fail_closed(self):
        event = {"type": "turn.completed", "usage": {"input_tokens": -1}}
        self.assertEqual(
            normalize_usage_event(event, adapter_id="codex-direct", session_id="s", turn_id="t")["usage"]["state"],
            "invalid",
        )
        with self.assertRaises(UsageContractError):
            physical_span_identity(namespace="openai/managed-codex-cli", metric_scope="cumulative",
                                   session_id="s", turn_id="t")
        with self.assertRaises(UsageContractError):
            normalize_usage_event({
                "schema": "codex-cli-jsonl.turn-completed.v1",
                "type": "turn.completed", "usage": {"input_tokens": 1},
            },
                                  adapter_id="codex-direct", session_id="s")

    def test_physical_span_identity_is_stable_and_scope_sensitive(self):
        first = physical_span_identity(namespace="openai/managed-codex-cli", metric_scope="turn",
                                       session_id="session", turn_id="turn")
        duplicate = physical_span_identity(namespace="openai/managed-codex-cli", metric_scope="turn",
                                           session_id="session", turn_id="turn")
        other_scope = physical_span_identity(namespace="openai/managed-codex-cli", metric_scope="invocation",
                                              session_id="session", turn_id="turn")
        self.assertEqual(first, duplicate)
        self.assertNotEqual(first["span_id"], other_scope["span_id"])

    def test_static_decimal_rate_schedule_is_complete_and_reasoning_is_not_additive(self):
        schedule = validate_rate_schedule()
        self.assertFalse(schedule["reasoning_additive"])
        self.assertEqual(set(schedule["entries"]["gpt-5.6-luna/default"]), set(CHARGEABLE_FIELDS))
        self.assertTrue(all(isinstance(value, str) for value in schedule["entries"]["gpt-5.6-luna/default"].values()))
        broken = {**schedule, "reasoning_additive": True}
        with self.assertRaises(UsageContractError):
            validate_rate_schedule(broken)

    def test_fixture_report_is_mechanical_only_and_passes(self):
        report = run_fixture_contract()
        self.assertEqual(report["outcome"], "passed", report)
        self.assertFalse(report["paid_provider_calls"])
        self.assertIn("codex-direct", report["passed"])
        self.assertIn("codex-host", report["passed"])
        self.assertIn("claude-code", report["passed"])


if __name__ == "__main__":
    unittest.main()
