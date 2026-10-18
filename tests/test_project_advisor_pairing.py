import unittest
from types import SimpleNamespace

from herzchen.contracts import ResourceRef
from otto.portfolio import (
    AdvisorPairing, AdvisorPairingError, OperatingBrief,
    conversation_for, establish_pairing, introductions,
)
from otto.portfolio.herzchen_binding import FiniteWorkOperations, HerzchenBindingConfig
from otto.portfolio.intake import OttoPortfolio, PortfolioError
from otto.portfolio.resource_sync import role_resource_pins


def ref(kind, ident, revision="rev-1", authority="owner"):
    return {"authority": authority, "kind": kind, "id": ident, "revision": revision}


PROJECT = ref("work.project", "project-1")
MANAGER = ref("wrk.assignment", "manager-a", "rev-4")
ADVISOR = ref("wrk.assignment", "advisor-a", "rev-7")
MANAGER_CONVERSATION = {"host": "codex", "physical_session_id": "manager-session"}
ADVISOR_CONVERSATION = {
    "host": "codex", "physical_session_id": "advisor-session",
    "conversation_id": "advisor-session",
}


def assignment(role, assignment_ref, principal, generation, *, manager=None, project=PROJECT):
    payload = {
        "scope": project, "role": role, "principal": principal,
        "generation": generation, "status": "queued", "manager": manager,
    }
    return {
        "ref": assignment_ref, "assignment_ref": assignment_ref, "scope": project,
        "role": role, "principal": principal, "manager": principal,
        "stored_manager": manager, "generation": generation,
        "status": "queued", "payload": payload,
    }


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.manager = assignment("manager", MANAGER, "manager-principal", 1, manager="manager-principal")
        self.advisor = assignment("project_advisor", ADVISOR, "advisor-principal", 2, manager="manager-principal")
        foreign = assignment(
            "manager", ref("wrk.assignment", "foreign"), "foreign", 1, manager="foreign",
            project=ref("work.project", "project-1", authority="other-owner"),
        )
        self.pairing = establish_pairing(
            PROJECT, [self.manager, self.advisor, foreign],
            manager_conversation_ref=MANAGER_CONVERSATION,
            advisor_conversation_ref=ADVISOR_CONVERSATION,
            cursor={"message_id": "m-4"},
        )

    def test_independent_generations_and_conversation(self):
        self.assertEqual((self.pairing.manager_generation, self.pairing.advisor_generation), (1, 2))
        self.assertEqual(conversation_for(
            self.pairing, role="project_advisor", assignment_ref=ADVISOR, generation=2,
        ), ADVISOR_CONVERSATION)

    def test_legacy_constructor_preserves_single_generation(self):
        value = AdvisorPairing(PROJECT, MANAGER, ADVISOR, 3, MANAGER_CONVERSATION, ADVISOR_CONVERSATION)
        self.assertEqual((value.manager_generation, value.advisor_generation, value.to_dict()["generation"]), (3, 3, 3))

    def test_stale_or_wrong_recipient_is_rejected(self):
        for values in (
            ("project_advisor", ADVISOR, 1),
            ("project_advisor", ref("wrk.assignment", "old-advisor"), 2),
            ("worker", ADVISOR, 2),
        ):
            with self.assertRaises(AdvisorPairingError):
                conversation_for(self.pairing, role=values[0], assignment_ref=values[1], generation=values[2])

    def test_duplicate_current_advisor_is_rejected(self):
        duplicate = assignment("project_advisor", ref("wrk.assignment", "advisor-b"), "advisor-b", 1, manager="manager-principal")
        with self.assertRaisesRegex(AdvisorPairingError, "exactly one active project advisor"):
            establish_pairing(PROJECT, [self.manager, self.advisor, duplicate],
                              manager_conversation_ref=MANAGER_CONVERSATION,
                              advisor_conversation_ref=ADVISOR_CONVERSATION)

    def test_conflicting_conversation_aliases_are_rejected(self):
        with self.assertRaisesRegex(AdvisorPairingError, "aliases conflict"):
            establish_pairing(PROJECT, [self.manager, self.advisor],
                              manager_conversation_ref=MANAGER_CONVERSATION,
                              advisor_conversation_ref={"host": "codex", "physical_session_id": "a", "conversation_id": "b"})

    def test_introductions_name_both_assignments(self):
        messages = introductions(self.pairing)
        self.assertIn("advisor-a", messages["manager"]["message"])
        self.assertIn("manager-a", messages["project_advisor"]["message"])


class _AssignmentPort:
    def __init__(self): self.calls = []
    def assign(self, scope, **kwargs):
        self.calls.append((scope, kwargs))
        return SimpleNamespace(ref=ref("wrk.assignment", "assignment-" + kwargs["role"]), generation=1, pins=())


class _FiniteFake:
    def __init__(self):
        self.assignments_port = _AssignmentPort(); self.content_port = None; self._owner_reader = None
    def _actor(self, actor): return actor
    def _record_ref(self, value): return value
    def _key(self, request_id, suffix): return request_id + ":" + suffix
    def _receipt(self, request_id): return None
    def _events_for(self, receipt): return []


class IntegrationTests(unittest.TestCase):
    def test_assignment_and_resource_admission(self):
        roles = OttoPortfolio._roles({
            "parent": PROJECT, "manager": "manager-principal",
            "project_advisor": "advisor-principal", "executor": "worker-principal",
        }, responsibility_ref=PROJECT)
        fake = _FiniteFake()
        result = FiniteWorkOperations._assign_roles(
            fake, {"project_ref": PROJECT, "roles": roles}, request_id="assign", actor="owner",
        )
        advisor_calls = [call for call in fake.assignments_port.calls if call[1]["role"] == "project_advisor"]
        self.assertEqual(result["outcome"], "assigned")
        self.assertEqual(advisor_calls[0][1]["manager"], "manager-principal")

    def test_resource_pin_and_brief_role(self):
        descriptor = {
            "role": "project_advisor", "responsibility_ref": PROJECT,
            "resource_ref": ref("dat.content.document", "advisor-guide"),
            "resource_name": "advisor-guide", "adopted_revision": "rev-1",
            "entrypoint": "GUIDE.md", "bundle_digest": "b", "export_manifest_digest": "e",
            "supporting_refs": [], "required": True,
        }
        self.assertEqual(role_resource_pins({"project_advisor": [descriptor]}, "project_advisor"), [descriptor["resource_ref"]])
        self.assertEqual(OperatingBrief.empty("project_advisor").role, "project_advisor")
        with self.assertRaisesRegex(PortfolioError, "project_advisor resources require"):
            OttoPortfolio._roles({
                "parent": PROJECT, "manager": "manager-principal", "executor": "worker-principal",
                "resources": {"project_advisor": [descriptor]},
            }, responsibility_ref=PROJECT)


class _PairReceipt:
    replayed = False

    def to_dict(self):
        # Mutation receipts name their event subject; the owner reader filters on it.
        return {"status": "committed", "event_ids": ["advisor-created"],
                "result_ref": {"authority": "owner", "kind": "wrk.assignment", "id": "advisor-created", "revision": "rev-1"}}


class _PairReader:
    def __init__(self):
        self.receipts = {}

    def get_receipt(self, key):
        return self.receipts.get(key)

    def list_events(self, **_subjects):
        return (SimpleNamespace(event_id="advisor-created"),)


class _PairAssignments:
    def __init__(self, reader):
        self.reader = reader
        manager_ref = ResourceRef.from_dict(MANAGER)
        self.values = {
            MANAGER["id"]: SimpleNamespace(
                ref=manager_ref, assignment_ref=manager_ref,
                scope=ResourceRef.from_dict(PROJECT), role="manager",
                principal="manager-principal", generation=1, status="queued",
                pins=(), history=(), payload={"manager": "manager-principal"},
            ),
        }
        self.assign_calls = []

    def get(self, value):
        return self.values[value.id]

    def assign(self, scope, **kwargs):
        self.assign_calls.append((scope, kwargs))
        advisor_ref = ResourceRef("owner", "wrk.assignment", "advisor-created", "rev-1")
        advisor = SimpleNamespace(
            ref=advisor_ref, assignment_ref=advisor_ref, scope=scope,
            role="project_advisor", principal=kwargs["principal"], generation=1,
            status="queued", pins=tuple(kwargs.get("pins", ())), history=(),
            payload={"manager": kwargs["manager"]},
        )
        self.values[advisor_ref.id] = advisor
        self.reader.receipts[kwargs["logical_request_key"]] = _PairReceipt()
        return advisor


class _PairSheet:
    def __init__(self, assignments):
        self.assignments = assignments

    def export(self, _project):
        return {"project": {"ref": PROJECT, "observed": {"assignments": [
            {"ref": value.ref.to_dict()} for value in self.assignments.values.values()
        ]}}}


class OwnerPairFixtureTests(unittest.TestCase):
    """Reusable owner seam fixture; this is not native PA06 pilot evidence."""

    def setUp(self):
        reader = _PairReader()
        assignments = _PairAssignments(reader)
        operations = FiniteWorkOperations(
            port=SimpleNamespace(), reader=reader,
            binding=HerzchenBindingConfig("owner", "credential"),
            sheet_port=_PairSheet(assignments), assignments_port=assignments,
        )
        self.assignments = assignments
        self.portfolio = OttoPortfolio(operations)

    def call(self, *, principal=None, generation=1, request_id="pair-v1"):
        return self.portfolio.pair_project_advisor(
            PROJECT, MANAGER, actor="manager-principal", request_id=request_id,
            manager_generation=generation, advisor_principal=principal,
        )

    def test_read_create_and_replay_use_one_generic_assignment(self):
        missing = self.call(request_id="pair-read")
        self.assertEqual((missing["outcome"], missing["advisor"]), ("missing", None))
        self.assertEqual(self.assignments.assign_calls, [])

        created = self.call(principal="advisor-principal")
        self.assertEqual(created["outcome"], "created")
        self.assertEqual(created["advisor"]["role"], "project_advisor")
        self.assertEqual(created["advisor"]["stored_manager"], "manager-principal")
        self.assertFalse(created["dispatch"])
        self.assertFalse(created["execution"])
        self.assertEqual(len(self.assignments.assign_calls), 1)

        replay = self.call(principal="advisor-principal", request_id="pair-v2")
        self.assertEqual((replay["outcome"], replay["replayed"]), ("read", True))
        self.assertEqual(created["pairing_request_key"], replay["pairing_request_key"])
        self.assertEqual(len(self.assignments.assign_calls), 1)

    def test_stale_manager_generation_is_rejected_before_creation(self):
        result = self.call(principal="advisor-principal", generation=2)
        self.assertEqual(result["error"]["code"], "project_advisor_pairing_rejected")
        self.assertIn("stale", result["error"]["message"])
        self.assertEqual(self.assignments.assign_calls, [])


if __name__ == "__main__":
    unittest.main()
