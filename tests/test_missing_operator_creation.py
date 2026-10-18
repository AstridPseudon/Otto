"""Missing operator authority must refuse before project and replay writes."""
from __future__ import annotations

import hashlib
from herzchen.contracts import ResourceRef
from test_hostctl_cli import HostctlFixture, OPERATOR


HOST = "claude-code-orchestrator"


class MissingOperatorCreationTests(HostctlFixture):
    def setUp(self):
        super().setUp()
        self._init()
        self.snapshot = self._owner(lambda session: self._make_snapshot(session))
        # OwnerSession is composed for each real owner request. Removing the
        # configured value exercises the same boundary as an absent operator.
        self.owner_service.config["operator"]["actor"] = None

    @staticmethod
    def _make_snapshot(session):
        source = session.portfolio.create_pending(actor=HOST, request_id="missing-operator-source",
            edit={"title": "Import source", "outcome": "Source"})
        exported = session.portfolio.export_project(source["project_ref"], actor=HOST,
            request_id="missing-operator-export")
        return exported["snapshot"]

    def _owner(self, callback, *, host=False):
        from otto.hostctl.owner import HostSession

        def run():
            config = self.owner_service.config
            owner_host = config["hosts"].get("claude-code") if host else None
            with HostSession(config, host=owner_host) as session:
                return callback(session)
        return self.owner_service.call(run)

    def _create(self, entrance, key):
        def invoke(session):
            portfolio = session.portfolio
            if entrance == "pending":
                return portfolio.create_pending(actor=HOST, request_id=key,
                    edit={"title": key, "outcome": "Retry without consuming the key"})
            if entrance == "template":
                return portfolio.create_pending(actor=HOST, request_id=key,
                    edit={"title": key, "outcome": "Retry without consuming the key"},
                    template={"kind": "work_template", "id": "fixture-template", "revision": "v1",
                        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                        "seed": {}}, template_parameters={})
            if entrance == "orchestrated":
                raise AssertionError("orchestrated entrance uses a host owner session")
            if entrance == "open":
                return portfolio.create_and_open(actor=HOST, request_id=key,
                    edit={"title": key, "outcome": "Retry without consuming the key"})
            if entrance == "save":
                return portfolio.save_project({"project": {"title": key, "outcome": "Retry"},
                    "tasks": []}, actor=HOST, request_id=key)
            if entrance == "import":
                return portfolio.import_project(self.snapshot, actor=HOST, request_id=key)
            raise AssertionError(entrance)
        if entrance == "orchestrated":
            return self._owner(lambda session: session.portfolio.create_pending(actor=HOST,
                request_id=key, edit={"title": key, "outcome": "Retry without consuming the key"},
                orchestrated=True), host=True)
        return self._owner(invoke)

    def _assert_unwritten(self, key):
        def inspect(session):
            reader = session.owner.graph.reader
            for candidate in (key, key + ":project", key + ":template", key + ":actor",
                              key + ":open", key + ":initial-sheet"):
                self.assertIsNone(reader.get_receipt(candidate), candidate)
            authority = session.store.authority
            for request_key in (key, key + ":project"):
                project_id = "project-" + hashlib.sha256(
                    (authority + ":" + request_key).encode("utf-8")
                ).hexdigest()[:28]
                self.assertIsNone(reader.get_identity(ResourceRef(authority, "work.project", project_id)))
            open_project_id = "project-" + hashlib.sha256(
                (authority + ":" + key + ":project").encode("utf-8")
            ).hexdigest()[:28]
            self.assertIsNone(reader.get_identity(
                ResourceRef(authority, "authoring-scope", open_project_id)))
        self._owner(inspect)

    def _allow_operator(self):
        self.owner_service.config["operator"]["actor"] = OPERATOR

    def test_missing_operator_refuses_creation_before_receipt_and_same_key_retries(self):
        for entrance in ("pending", "template", "orchestrated", "open", "save", "import"):
            with self.subTest(entrance=entrance):
                self.owner_service.config["operator"]["actor"] = None
                key = "missing-operator-" + entrance
                refused = self._create(entrance, key)
                self.assertEqual(refused["outcome"], "error", refused)
                self.assertIn("operator", refused["error"]["message"].casefold())
                self._assert_unwritten(key)

                self._allow_operator()
                created = self._create(entrance, key)
                self.assertNotEqual(created["outcome"], "error", created)
                self.assertTrue(created.get("project_ref"), created)
                self.assertFalse(created.get("replayed", False), created)

    def test_direct_orchestration_port_requires_operator_before_replay_receipt(self):
        key = "missing-operator-direct-orchestration"

        def create(session):
            return session.owner.orchestration_port.create_pending_with_supervisor(
                actor=session.actor, request_id=key,
                portfolio_ref=session.owner.orchestration_portfolio,
                title="Direct orchestration", outcome="Retry same key",
                expected_project_version=0)

        with self.assertRaisesRegex(ValueError, "operator"):
            self._owner(create, host=True)
        self._assert_unwritten(key)

        self._allow_operator()
        result = self._owner(create, host=True)
        self.assertEqual(result["outcome"], "created", result)
        self.assertFalse(result["replayed"], result)
        self.assertTrue(result["project_ref"], result)
