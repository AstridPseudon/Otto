"""Bounded D01 proof over disposable FND/EDT/WRK and the actual owner pump.

Run with PYTHONPATH=src python src/otto/portfolio/fixtures/project_authoring.py.
No installed owner, controller state, provider or operational Store is accessed.
"""
import argparse
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.content import domain_contribution as content_contribution
from herzchen.contracts import ResourceRef
from herzchen.domains.work import contributions
from herzchen.kernel.store import Store
from otto.portfolio.execution_host import ExecutionHost, _nested_capability
from otto.portfolio.herzchen_binding import HerzchenBindingConfig
from otto.portfolio.intake import OttoPortfolio
from otto.portfolio.manager_journey_client import add_manager_journey_parsers
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap


class ProjectAuthoringProof(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="portable-d01-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "fixture.sqlite"
        self.domains = tuple((*contributions(include_assignment_resources=True),
                              authoring_contribution(), content_contribution()))
        self.store = Store.create(self.path, authority="d01-fixture")
        self.store.register_domain_handler(self.domains)
        self.addCleanup(lambda: self.store.close())
        self.bind()

    def materialize(self, checkout, initial_bytes, **values):
        path = self.root / checkout.session_id
        path.mkdir()
        (path / "project.json").write_bytes(initial_bytes)
        return {"path": str(path), "registered_files": ["project.json"]}

    def bind(self):
        self.owner = PortfolioOwnerBootstrap(self.store,
            binding=HerzchenBindingConfig("d01-fixture", "fixture-credential"),
            owner_actor="owner", materializer=self.materialize)
        self.portfolio = OttoPortfolio(self.owner.consumer_operations())

    def restart(self):
        self.store.close()
        self.store = Store.open(self.path, authority="d01-fixture",
            expected_domains=tuple(sorted(self.domains, key=lambda domain: domain.domain_id)))
        self.bind()

    def create(self, key="create"):
        result = self.portfolio.create_pending(actor="owner", request_id=key,
            edit={"title": "Research", "outcome": "Useful pending work"})
        self.assertEqual(result["outcome"], "created", result)
        return result["project_ref"]

    def open(self, ref, key="open"):
        result = self.portfolio.checkout_project(ref, actor="owner", request_id=key)
        self.assertEqual(result["outcome"], "opened", result)
        return result

    def finish(self, opened, key="finish"):
        return self.portfolio.check_in_project(opened["project_ref"], session_id=opened["session_id"],
            project_json=opened["project_json"], actor="owner", request_id=key)

    def test_create_open_local_projection_finish_and_exact_replay(self):
        created = self.portfolio.create_and_open(actor="owner", request_id="create-open",
            edit={"title": "Research", "outcome": "Useful pending work"})
        self.assertEqual(created["outcome"], "created", created)
        opened = created["open"]
        path = self.root / opened["session_id"] / "project.json"
        self.assertEqual(json.loads(path.read_text()), opened["project_json"])
        self.assertFalse({"session", "ref", "metadata", "execution", "manager"} & set(opened["project_json"]))
        original = ResourceRef.from_dict(created["project_ref"])
        draft = opened["project_json"]
        draft["title"] = "Edited locally"
        path.write_text(json.dumps(draft))
        self.assertEqual(self.owner.sheet.export(original).project["authored"]["title"], "Research")
        committed = self.finish(opened)
        self.assertEqual(committed["outcome"], "finished", committed)
        self.assertEqual(committed["project_ref"]["revision"], "rev-2")
        replay = self.finish(opened)
        self.assertEqual(replay["outcome"], "replayed", replay)
        self.assertEqual(replay["sheet_receipt"], committed["sheet_receipt"])
        draft["title"] = "Changed request input"
        conflict = self.finish(opened)
        self.assertEqual(conflict["outcome"], "conflict", conflict)
        self.assertEqual(conflict["error"]["code"], "replay_conflict")
        self.assertTrue(path.exists())
        record = self.owner.graph.get(original)
        self.assertEqual(record.lifecycle.value, "pending")
        for field in ("manager", "worker", "budget", "execution"):
            self.assertIsNone(record.payload[field])
        self.assertEqual(record.payload["tasks"], [])

    def test_restart_retains_project_and_task_bases_and_commits_task(self):
        ref = ResourceRef.from_dict(self.create())
        applied = self.owner.sheet.apply(ref, {"tasks": [{"id": "D", "title": "First task"}]},
            logical_request_key="add-task", base_revision=ref.revision)
        opened = self.open(applied.project.ref)
        self.assertNotIn("ref", opened["project_json"]["tasks"][0])
        opened["project_json"]["tasks"][0]["title"] = "Edited task"
        session = opened["session_id"]
        self.restart()
        replay = self.portfolio.checkout_project(opened["project_ref"], actor="owner", request_id="open")
        self.assertEqual(replay["session_id"], session)
        finished = self.finish(opened)
        self.assertEqual(finished["outcome"], "finished", finished)
        self.assertEqual(self.owner.sheet.export(ref).tasks[0]["authored"]["title"], "Edited task")
        self.restart()
        replay = self.finish(opened)
        self.assertEqual(replay["outcome"], "replayed", replay)
        self.assertEqual(replay["project_ref"], finished["project_ref"])

    def test_stale_task_without_parent_change_keeps_checkout(self):
        ref = ResourceRef.from_dict(self.create())
        task = self.owner.graph.create_task(ref, title="Task", logical_request_key="task")
        opened = self.open(ref)
        self.owner.graph.revise(task.ref, title="Concurrent task edit", logical_request_key="other-task")
        self.assertEqual(self.owner.graph.get(ref).ref, ref)
        result = self.finish(opened)
        self.assertEqual(result["outcome"], "conflict", result)
        self.assertTrue((self.root / opened["session_id"] / "project.json").exists())
        scope = self.owner.authoring.read(ref, self.owner.owner_actor)
        self.assertEqual(scope.checkout.state.value, "open")
        self.restart()
        self.assertEqual(self.finish(opened)["outcome"], "conflict")

    def test_stale_project_and_stale_open(self):
        ref = ResourceRef.from_dict(self.create())
        opened = self.open(ref)
        self.owner.sheet.apply(ref, {"title": "Concurrent project edit"},
            base_revision=ref.revision, logical_request_key="concurrent-project")
        self.assertEqual(self.finish(opened)["outcome"], "conflict")
        stale = self.portfolio.checkout_project(ref, actor="different", request_id="stale-open")
        self.assertEqual(stale["outcome"], "conflict", stale)
        self.assertEqual(self.owner.graph.get(ref).title, "Concurrent project edit")

    def test_identity_replay_and_foreign_actor(self):
        ref = self.create()
        replay = self.portfolio.create_pending(actor="owner", request_id="create", edit={"title": "Research", "outcome": "Useful pending work"})
        self.assertEqual(replay["project_ref"], ref)
        changed = self.portfolio.create_pending(actor="owner", request_id="create", edit={"title": "Other"})
        self.assertEqual(changed["error"]["code"], "replay_conflict")
        opened = self.open(ref)
        foreign = self.portfolio.check_in_project(ref, session_id=opened["session_id"],
            project_json=opened["project_json"], actor="foreign", request_id="foreign-finish")
        self.assertEqual(foreign["outcome"], "error")
        first = self.finish(opened)
        reopened = self.open(first["project_ref"], "new-open")
        old = self.portfolio.checkout_project(ref, actor="owner", request_id="open")
        self.assertEqual(old["outcome"], "conflict", old)
        self.assertNotEqual(reopened["session_id"], opened["session_id"])

    def test_pending_sparse_update_guards_and_exact_replay(self):
        ref = self.create()
        edited = self.portfolio.edit_pending(ref, {"title": "Updated"}, actor="owner", request_id="update")
        self.assertEqual(edited["outcome"], "edited", edited)
        replay = self.portfolio.edit_pending(ref, {"title": "Updated"}, actor="owner", request_id="update")
        self.assertEqual(replay["outcome"], "replayed", replay)
        stale = self.portfolio.edit_pending(ref, {"title": "Stale"}, actor="owner", request_id="stale-update")
        self.assertEqual(stale["outcome"], "conflict", stale)
        changed = self.portfolio.edit_pending(ref, {"title": "Changed input"}, actor="owner", request_id="update")
        self.assertEqual(changed["error"]["code"], "replay_conflict", changed)
        self.assertEqual(self.owner.graph.get(ResourceRef.from_dict(ref)).title, "Updated")

    def test_predecessor_pending_edit_receipt_remains_replayable(self):
        ref = ResourceRef.from_dict(self.create())
        # This is the exact pre-D01 pending-edit producer shape: no explicit
        # base argument, but a revisioned target already enters its digest.
        previous = self.owner.graph.revise(ref, title="Earlier edit", fields={},
            logical_request_key="legacy-edit", actor=self.owner.owner_actor)
        replay = self.portfolio.edit_pending(ref, {"title": "Earlier edit"}, actor="owner", request_id="legacy-edit")
        self.assertEqual(replay["outcome"], "replayed", replay)
        self.assertEqual(replay["project_ref"], previous.ref.to_dict())

    def test_invalid_sheet_is_durable_recovery_without_semantic_effect(self):
        opened = self.open(self.create())
        opened["project_json"]["manager"] = "invented"
        result = self.finish(opened)
        self.assertEqual(result["outcome"], "recovery_pending", result)
        self.assertTrue(result["recovery_pending"])
        self.assertIsNone(result["sheet_receipt"])
        self.assertEqual(json.loads(self.owner.authoring.read_snapshot(ResourceRef.from_dict(result["snapshot_ref"]))), opened["project_json"])
        self.assertEqual(self.owner.graph.get(ResourceRef.from_dict(opened["project_ref"])).revision, "rev-1")
        self.assertTrue((self.root / opened["session_id"] / "project.json").exists())

    def test_real_parser_and_sibling_authoring_in_live_owner_wait(self):
        parser = argparse.ArgumentParser()
        commands = parser.add_subparsers(dest="command", required=True)
        add_manager_journey_parsers(commands)
        request = vars(parser.parse_args(["project-authoring", "--operation", "create", "--request-key", "sibling",
            "--edit", '{"title":"Sibling","outcome":"Author while waiting"}']))
        self.assertEqual(_nested_capability(request), "admitted")
        server = SimpleNamespace(owner=self.owner, portfolio=self.portfolio, state={}, due_port=None, _execution=lambda **kw: None)
        service = ManagerJourneyService(server=server, host=None, run_path=self.root, workspace=self.root,
            authoring_authorizer=lambda req: self.owner.owner_actor)
        denied = ManagerJourneyService(server=server, host=None, run_path=self.root, workspace=self.root)
        self.assertEqual(denied(request)["outcome"], "denied")
        owner_thread = []
        sibling_thread = []
        ipc = self.root / "ipc"
        host = None

        def wait_response(token):
            path = ipc / ("response-" + token + ".json")
            deadline = time.monotonic() + 5
            while not path.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            if not path.exists():
                raise AssertionError("finite sibling authoring blocked behind native work")
            return json.loads(path.read_text())

        def handler(value):
            if value["command"] == "start-manager":
                owner_thread.append(threading.get_ident())

                def native_wait():
                    (ipc / "request-bbbb.json").write_text(json.dumps(request))
                    created = wait_response("bbbb")
                    self.assertEqual(created["outcome"], "created", created)
                    self.assertFalse(created["executable"])
                    sibling_ref = created["project_ref"]
                    # Parser serialization includes null optional fields.
                    read = vars(parser.parse_args(["project-authoring", "--operation", "read",
                        "--project-ref", json.dumps(sibling_ref)]))
                    (ipc / "request-cccc.json").write_text(json.dumps(read))
                    result = wait_response("cccc")
                    self.assertEqual(result["outcome"], "read", result)
                    self.assertEqual(result["record"]["lifecycle"], "pending")
                    opening = vars(parser.parse_args(["project-authoring", "--operation", "open",
                        "--request-key", "sibling-open", "--project-ref", json.dumps(sibling_ref)]))
                    (ipc / "request-dddd.json").write_text(json.dumps(opening))
                    opened = wait_response("dddd")
                    self.assertEqual(opened["outcome"], "opened", opened)
                    opened["project_json"]["title"] = "Sibling authored during native wait"
                    finish = vars(parser.parse_args(["project-authoring", "--operation", "check-in",
                        "--request-key", "sibling-finish", "--project-ref", json.dumps(sibling_ref),
                        "--project-json", json.dumps(opened["project_json"]), "--session-id", opened["session_id"]]))
                    (ipc / "request-eeee.json").write_text(json.dumps(finish))
                    finished = wait_response("eeee")
                    self.assertEqual(finished["outcome"], "finished", finished)
                    read["project_ref"] = finished["project_ref"]
                    (ipc / "request-ffff.json").write_text(json.dumps(read))
                    result = wait_response("ffff")
                    self.assertEqual(result["record"]["title"], "Sibling authored during native wait")
                    self.assertEqual(result["record"]["lifecycle"], "pending")
                    return {"outcome": "succeeded"}

                return ExecutionHost.external_call(native_wait)
            sibling_thread.append(threading.get_ident())
            return service(value)

        host = ExecutionHost(directory=ipc, handler=handler)
        try:
            host.start()
            (ipc / "request-aaaa.json").write_text(json.dumps({"command": "start-manager"}))
            result = wait_response("aaaa")
            self.assertEqual(result["outcome"], "succeeded", result)
            self.assertTrue(sibling_thread)
            self.assertTrue(all(ident == owner_thread[0] for ident in sibling_thread))
        finally:
            host.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
