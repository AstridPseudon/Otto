"""One existing authenticated request; full response/UNKNOWN stays unchanged."""
from copy import deepcopy
import argparse
import hashlib
import json
import unittest
from unittest.mock import MagicMock, patch

from herzchen.contracts import canonical_json
from otto.portfolio.compact_reads import compact_read_request, compact_read_response
from otto.portfolio.caller_client import call
from otto.portfolio.manager_journey_client import add_manager_journey_parsers, requires_native_caller
from otto.portfolio.identity_context import HostIngress
from otto.portfolio.operating_setup import evaluate_setup
from otto.portfolio.direction_context import read_direction_context
from otto.portfolio.tests import test_caller_context as caller_fixture
from otto.portfolio.tests import test_portfolio_direction as direction_fixture


def ref(kind, identifier):
    return {"authority": "owner", "kind": kind, "id": identifier, "revision": "rev-1"}


class CompactAuthenticatedReadTests(unittest.TestCase):
    def response(self):
        return {"outcome": "read", "provider_called": False, "effects_started": False,
            "caller_context": {"source": "current canonical records", "principal": "manager", "role": "manager",
                "assignment_ref": ref("wrk.assignment", "manager"), "generation": 1,
                "project_ref": ref("work.project", "project"), "task_ref": ref("work.task", "task"),
                "native_session": {"adapter": "installed", "id": "native"},
                "occurrence_ref": {"schedule_id": "current", "logical_request_key": "original"},
                "direction_context": [{"effective_ref": ref("dat.content.document", "direction"),
                    "inputs": [{"ref": ref("dat.content.document", "direction"), "content_sha256": "a" * 64}],
                    "instructions": "DIRECTION PROSE " * 10000}]},
            "outer_command": {"transport": "unix-socket", "request_id": "a" * 32, "retained": True}}

    def test_one_existing_socket_read_no_claim_or_projection_selector_sent(self):
        raw = self.response()
        unchanged = deepcopy(raw)
        socket = MagicMock()
        socket.__enter__.return_value = socket
        with patch("otto.portfolio.caller_client.socket.socket", return_value=socket), \
             patch("otto.portfolio.caller_client.call_connection", return_value=raw) as dispatch:
            compact = call("/installed/caller.sock", {"command": "compact-read", "read": "effective-context"})
        dispatch.assert_called_once_with(socket, {"command": "effective-context"})
        socket.connect.assert_called_once_with("/installed/caller.sock")
        self.assertTrue(requires_native_caller("compact-read"))
        parser = argparse.ArgumentParser()
        add_manager_journey_parsers(parser.add_subparsers(dest="command", required=True))
        parsed = vars(parser.parse_args(["compact-read", "--read", "effective-context"]))
        self.assertEqual(parsed, {"command": "compact-read", "read": "effective-context"})
        self.assertEqual(compact_read_request(parsed), {"command": "effective-context"})
        parsed = vars(parser.parse_args(["compact-read", "--read", "read-help", "--delivery-id", "exact"]))
        self.assertEqual(compact_read_request(parsed), {"command": "read-help", "delivery_id": "exact"})
        self.assertEqual(raw, unchanged)
        identity = compact["projection"]["caller_context"]
        for key in ("principal", "role", "assignment_ref", "generation", "project_ref", "task_ref", "native_session", "occurrence_ref"):
            self.assertEqual(identity[key], raw["caller_context"][key])
        self.assertEqual(compact["projection"]["direction_pins"][0]["inputs"][0]["content_sha256"], "a" * 64)
        self.assertEqual(compact["full_response"]["canonical_json_sha256"],
                         hashlib.sha256(canonical_json(raw).encode()).hexdigest())
        self.assertEqual(compact["full_response"]["digest_serialization"], "canonical-json")
        self.assertIn("instructions", compact["availability"]["direction.0.excluded_fields"])
        self.assertNotIn("DIRECTION PROSE", json.dumps(compact))
        self.assertLess(len(json.dumps(compact).encode()), 8000)

    def test_foreign_selectors_mutation_and_broad_help_refused_before_connection(self):
        for request in ({"command": "compact-read", "read": "run-worker"},
                        {"command": "compact-read", "read": "whoami", "caller_principal": "foreign"},
                        {"command": "compact-read", "read": "operating-setup", "operation": "apply"},
                        {"command": "compact-read", "read": "read-help"},
                        {"command": "compact-read", "read": "review-input", "project_ref": ref("work.project", "foreign")}):
            with self.subTest(request=request), patch("otto.portfolio.caller_client.socket.socket") as socket:
                with self.assertRaises(ValueError): call("/installed/caller.sock", request)
                socket.assert_not_called()
        self.assertEqual(compact_read_request({"command": "compact-read", "read": "operating-setup"}),
                         {"command": "operating-setup", "operation": "read"})
        self.assertEqual(compact_read_request({"command": "compact-read", "read": "read-help", "delivery_id": "delivery"}),
                         {"command": "read-help", "delivery_id": "delivery"})

    def test_setup_and_help_keep_exact_pins_report_digest_and_explicit_overbound(self):
        raw = self.response()
        raw.update(ready=True, state="active", setup_ref=ref("dat.content.document", "setup"),
            roles={"manager": "role-current"}, introductions={"manager": {"principal": "manager", "generation": 1,
                "assignment_ref": ref("wrk.assignment", "manager"), "mandate_ref": ref("dat.content.document", "mandate"),
                "mandate": "MANDATE PROSE " * 10000}}, blockers=[])
        compact = compact_read_response(raw, operation="operating-setup")
        self.assertTrue(compact["projection"]["ready"])
        self.assertEqual(compact["projection"]["role_pins"]["manager"]["mandate_ref"], raw["introductions"]["manager"]["mandate_ref"])
        self.assertNotIn("MANDATE PROSE", json.dumps(compact))
        help = {"outcome": "pending", "retry": False, "delivery_id": "delivery", "issue_id": "issue",
                "report_ref": ref("wrk.report", "reply"), "report_sha256": "b" * 64,
                "supported_application": {"command": "resolve-help", "issue_id": "issue"},
                "retained_report": {"schema": "otto.issue.response.v1", "response": "R" * 4000,
                                    "next_action": "apply exact response"}, "outer_command": raw["outer_command"]}
        compact = compact_read_response(help, operation="read-help")
        self.assertEqual(compact["projection"]["report_ref"], help["report_ref"])
        self.assertEqual(compact["projection"]["report_sha256"], help["report_sha256"])
        self.assertEqual(compact["projection"]["supported_application"], help["supported_application"])
        self.assertIsNone(compact["projection"]["retained_report"]["response"])
        self.assertIn("not truncated", compact["availability"]["retained_report.response"])
        self.assertIn("command-status", compact["full_response"]["receipt_read"])

    def test_unknown_foreign_stale_denial_preserved_without_replay_or_retention_claim(self):
        for outcome, error in (("unknown", "timeout"), ("error", "foreign caller"), ("error", "stale assignment")):
            raw = {"outcome": outcome, "error": error, "retry": False,
                   "outer_command": {"request_id": "original", "retained": None, "retention": "unconfirmed"}}
            compact = compact_read_response(raw, operation="effective-context")
            self.assertEqual(compact["outcome"], outcome)
            self.assertEqual(compact["projection"]["error"], error)
            self.assertFalse(compact["projection"]["retry"])
            self.assertEqual(compact["full_response"]["availability"], "retention unconfirmed")
            self.assertEqual(compact["availability"]["caller_context"], "absent")

    def test_maintained_owner_identity_setup_and_direction_envelope_shapes(self):
        # Real disposable owner records and the maintained ingress/resolvers;
        # provider is the existing fixture substitution, never a live call.
        f = caller_fixture.CallerContextTests(); f.setUp(); self.addCleanup(f.doCleanups)
        binding = f.caller(); host = f.host()
        before = f.f.store.consumer().snapshot_counts()
        calls = len(f.f.provider.calls)
        for operation in ("whoami", "effective-context"):
            raw = host._dispatch({"command": operation}, ingress=HostIngress("fixture", "manager"))
            compact = compact_read_response(raw, operation=operation)
            for key in ("schema", "principal", "role", "responsibility_ref", "assignment_ref", "generation",
                        "project_ref", "task_ref", "native_session", "occurrence_ref", "manager_worker_route"):
                self.assertEqual(compact["projection"]["caller_context"][key], raw["caller_context"][key])
            self.assertEqual(compact["projection"]["caller_context"]["assignment_ref"], binding.assignment_ref.to_dict())
        decision = evaluate_setup(f.f.app.runtime, f.f.project.ref.to_dict(), f.c.setup({"manager": binding.schedule_id}))
        raw = {"outcome": "read", **decision, "setup_ref": ref("dat.content.document", "setup"),
               "canonical_lifecycle": "active", "caller_context": raw["caller_context"]}
        compact = compact_read_response(raw, operation="operating-setup")
        for key in ("state", "ready", "mode", "capabilities", "blockers"):
            self.assertEqual(compact["projection"][key], raw[key])
        for key in ("schedule_id", "principal", "assignment_ref", "generation", "conversation_ref", "base_resource", "mandate_ref", "task_ref"):
            self.assertEqual(compact["projection"]["roles"]["manager"][key], raw["roles"]["manager"][key])
        # Deep optional selection detail may exceed the finite presentation;
        # its exact location must remain explicitly available in the full read.
        for path, reason in compact["availability"].items():
            if path.startswith("response.roles."):
                self.assertIn("use full receipt", reason)
        for key in ("assignment_ref", "generation", "mandate_ref", "base_resource", "supporting_refs", "conversation_ref", "execution"):
            self.assertEqual(compact["projection"]["role_pins"]["manager"][key], raw["introductions"]["manager"][key])
        self.assertEqual(f.f.store.consumer().snapshot_counts(), before)
        self.assertEqual(len(f.f.provider.calls), calls)
        self.assertEqual(f.effects, [])

        d = direction_fixture.PortfolioDirectionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        root, _subject, pin, project = d.setup_portfolio()
        directions = read_direction_context(d.directions, actor=d.actor, assignment_ref=root.ref.to_dict(),
            generation=root.generation, project_ref=project.ref.to_dict())
        self.assertEqual(directions[-1]["effective_ref"], pin.to_dict())
        raw = {"outcome": "read", "caller_context": {"direction_context": directions}}
        compact = compact_read_response(raw, operation="effective-context")
        for actual, projected in zip(directions, compact["projection"]["direction_pins"]):
            for key in ("subject_ref", "binding_ref", "document_ref", "latest_ref", "scope_adopted_ref", "assignment_adopted_ref", "effective_ref"):
                self.assertEqual(projected[key], actual[key])
            for item, pins in zip(actual["inputs"], projected["inputs"]):
                self.assertEqual(pins["ref"], item["ref"])
                self.assertEqual(pins["content_sha256"], item["content_sha256"])
                self.assertNotIn("content", pins)
        self.assertNotIn("Priorities", json.dumps(compact))
        self.assertIn("do not establish absent authority", compact["availability_semantics"])


if __name__ == "__main__":
    unittest.main()
