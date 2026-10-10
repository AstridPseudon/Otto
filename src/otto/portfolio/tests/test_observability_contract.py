"""D01 contract qualification; no Store, owner service, or provider is used."""

import unittest

from herzchen.contracts import ResourceRef
from otto.portfolio.observability_contract import (
    CANDIDATE_ROOT,
    CONTRACT_SCHEMA,
    EVENTS_READ_LIMITS,
    FIXTURE_INVENTORY,
    HISTORICAL_FIELDS,
    LEGACY_GAP_RULES,
    ObservationRef,
    ObservabilityContractError,
    RESOURCE_PINS,
    RUNTIME_PIN,
    SOURCE_COMMIT,
    SOURCE_SEAMS,
    contract_digest,
    contract_record,
)


class ObservabilityContractTests(unittest.TestCase):
    def test_record_freezes_source_runtime_resource_and_contract_identity(self):
        record = contract_record()
        self.assertEqual(record["schema"], CONTRACT_SCHEMA)
        self.assertEqual(record["source"]["root"], CANDIDATE_ROOT)
        self.assertEqual(record["source"]["commit"], SOURCE_COMMIT)
        self.assertEqual(record["runtime"], RUNTIME_PIN)
        self.assertEqual(record["resources"], RESOURCE_PINS)
        self.assertEqual(len(record["source"]["seams"]), len(SOURCE_SEAMS))
        self.assertEqual(contract_digest(), contract_digest())
        self.assertEqual(len({pin.path for pin in SOURCE_SEAMS}), len(SOURCE_SEAMS))

    def test_historical_contract_is_explicit_and_does_not_invent_legacy_state(self):
        self.assertIn("before_after_project_membership", HISTORICAL_FIELDS)
        self.assertIn("assignment_responsibility_and_generation", HISTORICAL_FIELDS)
        self.assertIn("exact_detail_locator", HISTORICAL_FIELDS)
        self.assertIn("missing_membership_is_unknown_not_silently_inactive", LEGACY_GAP_RULES)
        self.assertIn("projection_rows_never_replace_authoritative_source_history", LEGACY_GAP_RULES)
        self.assertEqual(contract_record()["usage_cost"]["state"], "pending_successor")
        self.assertFalse(contract_record()["usage_cost"]["synthetic_totals"])
        self.assertFalse(contract_record()["usage_cost"]["billing_claims"])

    def test_read_limits_bound_candidates_rows_projects_and_details(self):
        EVENTS_READ_LIMITS.validate(rows=50, project_count=1, detail_bytes=0, metadata_candidates=0)
        EVENTS_READ_LIMITS.validate(rows=200, project_count=32, detail_bytes=64 * 1024, metadata_candidates=1000)
        for kwargs in (
            {"rows": 201, "project_count": 1},
            {"rows": 1, "project_count": 33},
            {"rows": 1, "project_count": 1, "detail_bytes": 64 * 1024 + 1},
            {"rows": 1, "project_count": 1, "metadata_candidates": 1001},
            {"rows": 1, "project_count": 0},
        ):
            with self.assertRaises(ObservabilityContractError):
                EVENTS_READ_LIMITS.validate(**kwargs)

    def test_observation_ref_is_reference_only_and_bounded(self):
        value = ObservationRef(
            facet_type="usage.cost.future.observation",
            subject_ref=ResourceRef("owner", "work.project", "project"),
            source_ref=ResourceRef("owner", "dat.content.document", "source", "rev-1"),
            recorded_at="2026-10-10T04:00:00Z",
            occurrence_at="2026-10-10T03:59:00+00:00",
            detail_ref=ResourceRef("owner", "dat.content.document", "detail", "rev-1"),
            summary={"availability": "qualified", "provider": "future-successor"},
        ).to_dict()
        self.assertEqual(value["schema"], "otto.events.observation-ref.v1")
        self.assertNotIn("amount", value)
        self.assertNotIn("cost", value)
        self.assertEqual(value["subject_ref"]["id"], "project")

    def test_observation_ref_rejects_unbounded_summary_and_timezone_less_time(self):
        base = dict(
            facet_type="future",
            subject_ref=ResourceRef("owner", "work.project", "project"),
            source_ref=ResourceRef("owner", "event", "source", "rev-1"),
            recorded_at="2026-10-10T04:00:00Z",
        )
        with self.assertRaises(ObservabilityContractError):
            ObservationRef(**{**base, "recorded_at": "2026-10-10T04:00:00"})
        with self.assertRaises(ObservabilityContractError):
            ObservationRef(**{**base, "summary": {"blob": "x" * (64 * 1024)}})

    def test_fixture_inventory_covers_each_d01_qualification_risk(self):
        names = {fixture.name for fixture in FIXTURE_INVENTORY}
        self.assertEqual(len(names), len(FIXTURE_INVENTORY))
        for expected in (
            "atomic-batch-lifecycle-replacement",
            "old-reference-current-head-gap",
            "active-project-without-events",
            "large-sparse-bounded-read",
            "grant-and-snapshot-stability",
            "migration-interruption-copy-backfill-switch",
            "deterministic-rebuild",
        ):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
