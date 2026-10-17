"""Installed ``otto`` owner wiring reuses the exact project read grant."""

import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from herzchen.contracts import AuthenticatedActor
from otto.hostctl import cli as hostctl_cli
from otto.portfolio.cli import owner_verb
from otto.portfolio.herzchen_binding import ProjectReadGrant


PROJECT = {"authority": "owner", "kind": "work.project", "id": "p1", "revision": "r1"}
FOREIGN = {"authority": "owner", "kind": "work.project", "id": "p2", "revision": "r1"}


class HistoryReader:
    def __init__(self):
        self.calls = []

    def read(self, **kwargs):
        self.calls.append(kwargs)
        projects = kwargs["projects"]
        return {"outcome": "read", "rows": [], "projects": projects,
                "coverage": {"lag": 0}, "next_cursor": None, "partial": False,
                "snapshot": {"scope": {"projects": [["owner", ref["id"]] for ref in projects]}}}


class OwnerObservabilityCliTests(unittest.TestCase):
    def setUp(self):
        self.actor = AuthenticatedActor("owner", "installed-owner", "credential")
        self.read_grant = ProjectReadGrant(self.actor, (PROJECT["id"],), "otto.host-owner.v1", "v1")
        self.reader = HistoryReader()
        self.session = SimpleNamespace(
            owner=SimpleNamespace(owner_actor=self.actor, project_read_grant=self.read_grant),
            store=SimpleNamespace(project_history_reader=lambda **kwargs: self.reader),
            portfolio=object(),
        )

    def test_installed_show_history_binds_actor_and_project_grant(self):
        result = owner_verb(["show", "history", "overview", "--project-ref", json.dumps(PROJECT)],
                            session=self.session, home=Path("/tmp/otto-owner-test"))
        self.assertEqual(result["outcome"], "read", result)
        self.assertEqual(result["view"], "overview")
        call = self.reader.calls[0]
        self.assertIs(call["grant"].principal, self.actor)
        self.assertEqual(call["grant"].project_ids, (PROJECT["id"],))
        self.assertEqual(call["projects"], (PROJECT,))
        self.assertIs(call["actor"], self.actor)

    def test_hostctl_portfolio_path_forwards_cli_project_into_existing_owner_grant(self):
        reader = self.reader
        actor = self.actor

        class SessionContext:
            def __init__(self, _config, *, host, project_ids):
                self.project_ids = project_ids
                self.session = SimpleNamespace(
                    owner=SimpleNamespace(owner_actor=actor,
                        project_read_grant=ProjectReadGrant(actor, project_ids, "otto.host-owner.v1", "v1")),
                    store=SimpleNamespace(project_history_reader=lambda **kwargs: reader),
                    portfolio=object(),
                )

            def __enter__(self):
                return self.session

            def __exit__(self, *_exc):
                return False

        args = SimpleNamespace(caller="otto", home="/tmp/otto-owner-test", host=None,
            portfolio_args=["show", "history", "overview", "--project-ref=" + json.dumps(PROJECT)])
        with patch.object(hostctl_cli.host_config, "load", return_value={"hosts": {}}), \
             patch.object(hostctl_cli.host_config, "otto_home", return_value=Path("/tmp/otto-owner-test")), \
             patch.object(hostctl_cli, "HostSession", SessionContext):
            result = hostctl_cli.cmd_portfolio(args)
        self.assertEqual(result["outcome"], "read", result)
        self.assertEqual(reader.calls[0]["grant"].project_ids, (PROJECT["id"],))
        self.assertIs(reader.calls[0]["actor"], actor)

    def test_installed_history_cannot_expand_the_host_issued_project_grant(self):
        result = owner_verb(["show", "history", "overview", "--project-ref", json.dumps(FOREIGN)],
                            session=self.session, home=Path("/tmp/otto-owner-test"))
        self.assertEqual(result["outcome"], "unavailable", result)
        self.assertEqual(result["error"]["code"], "observability_views_unavailable")
        self.assertEqual(self.reader.calls, [])

    def test_installed_history_cannot_choose_another_actor(self):
        result = owner_verb(["show", "history", "overview", "--actor", "other",
                             "--project-ref", json.dumps(PROJECT)],
                            session=self.session, home=Path("/tmp/otto-owner-test"))
        self.assertEqual(result["outcome"], "denied", result)
        self.assertEqual(result["error"]["code"], "bound_actor_mismatch")
        self.assertEqual(self.reader.calls, [])

    def test_installed_status_friction_reads_only_explicit_granted_projects(self):
        status = {"outcome": "read", "projects": [{"project_ref": PROJECT}]}
        with patch("otto.portfolio.status.portfolio_status", return_value=status):
            result = owner_verb(["status", "--friction", "--project-ref", json.dumps(PROJECT)],
                                session=self.session, home=Path("/tmp/otto-owner-test"))
        self.assertEqual(result["friction"]["coverage"], "complete", result)
        call = self.reader.calls[0]
        self.assertIs(call["grant"].principal, self.actor)
        self.assertEqual(call["grant"].project_ids, (PROJECT["id"],))
        self.assertEqual(call["projects"], [PROJECT])
        self.assertIs(call["actor"], self.actor)


if __name__ == "__main__":
    unittest.main()
