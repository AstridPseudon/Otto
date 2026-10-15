"""Disposable owner-lane coverage for whole-portfolio apply."""
import json
from pathlib import Path

from herzchen.contracts import ResourceRef
from otto.hostctl import config as host_config
from otto.hostctl.owner import HostSession
from otto.portfolio.shared_documents import _document_ref, _write, document_namespace
from test_hostctl_cli import HostctlFixture, _write_bundle


class HostctlPortfolioApplyTests(HostctlFixture):
    def setUp(self):
        super().setUp()
        self._init()
        self.portfolio_id = host_config.load(Path(self.home))["hosts"]["claude-code"]["portfolio_ref"]["id"]
        self.root = Path(self.home).parent / "portfolio"
        self.root.mkdir()
        projects = self.root / "projects"
        projects.mkdir()
        self._write_project(projects, "A", "apply-A")
        self._write_project(projects, "B", "apply-B")
        evidence = projects / 'A' / 'evidence'
        evidence.mkdir()
        for name in ('alpha', 'published'):
            (evidence / (name + '.md')).write_text('NOT ACCEPTED: planned proof placeholder\n')
        self.manifest = {
            "schema": "otto.portfolio-setup.v1",
            "portfolio": {"name": "apply-test", "root_project_id": "apply-test", "root": "."},
            "projects": [
                {"id": "A", "folder": "A", "run_id": "apply-A", "dependencies": []},
                {"id": "B", "folder": "B", "run_id": "apply-B",
                 "dependencies": [{"on": "A", "gate": "alpha", "milestone": "alpha"}]},
            ],
            "gates": [{"project": "A", "id": "alpha", "milestone": "alpha", "title": "Alpha",
                       "owner": "orchestrator", "proof": "projects/A/evidence/alpha.md"}],
            "external_prerequisites": [{"id": "published", "project": "A", "gate": "published",
                                         "proof": "projects/A/evidence/published.md"}],
        }
        self._write_manifest()

    def _write_project(self, projects, letter, run_id):
        path = projects / letter
        path.mkdir()
        _write_bundle(str(path))
        value = json.loads((path / "run.json").read_text())
        value["run_id"] = run_id
        (path / "run.json").write_text(json.dumps(value))

    def _write_manifest(self):
        (self.root / "portfolio-setup.json").write_text(json.dumps(self.manifest, indent=2))

    def _apply(self, *args):
        return self._ottoctl("portfolio", "apply", "--portfolio", self.portfolio_id,
                             "--root", str(self.root), "--json", *args)

    def _owner(self, callback):
        def run():
            config = host_config.load(Path(self.home))
            with HostSession(config, host=config["hosts"]["claude-code"]) as session:
                return callback(session)
        return self.owner_service.call(run)

    def _counts(self):
        return self.owner_service.call(lambda: self.owner_service.store.consumer().snapshot_counts())

    def test_apply_is_owner_routed_idempotent_and_retains_gate_evidence(self):
        before = self._counts()
        code, dry = self._apply("--dry-run")
        self.assertEqual(code, 0, dry)
        self.assertEqual(dry["outcome"], "plan")
        self.assertFalse(dry["writes"])
        self.assertEqual(before, self._counts())

        code, applied = self._apply()
        self.assertEqual(code, 0, applied)
        self.assertEqual(applied["outcome"], "applied")
        after = self._counts()
        code, replay = self._apply()
        self.assertEqual(code, 0, replay)
        self.assertEqual(replay["outcome"], "in_sync")
        self.assertEqual(after, self._counts())

        code, complete = self._ottoctl("portfolio", "prerequisite", "complete", "--portfolio", self.portfolio_id,
                                       "--project", "A", "--id", "published", "--evidence", "release published")
        self.assertEqual(code, 0, complete)
        code, complete = self._ottoctl("portfolio", "gate", "complete", "--portfolio", self.portfolio_id,
                                       "--project", "A", "--gate", "alpha", "--evidence", "alpha accepted")
        self.assertEqual(code, 0, complete)
        gate = self._owner(lambda session: [g for g in session.owner.graph.list(kind="work.gate")
            if "alpha" in g.aliases][0])
        setup = gate.payload["fields"]["portfolio_setup"]
        self.assertEqual(setup["completion"]["evidence"], "alpha accepted")

    def test_otto_edit_blocks_apply_without_writing_and_foreign_portfolio_is_refused(self):
        code, applied = self._apply()
        self.assertEqual(code, 0, applied)
        before = self._counts()
        def alter(session):
            session.host = None
            portfolio = ResourceRef(session.store.authority, "wrk.portfolio", self.portfolio_id)
            ref = _document_ref(portfolio, "portfolio-setup.json",
                                root_namespace=document_namespace(root=str(self.root)))
            return _write(session.owner, session.actor, portfolio, ref, "Otto-owned edit\n")
        self._owner(alter)
        before = self._counts()
        code, held = self._apply()
        self.assertEqual(code, 0, held)
        self.assertEqual(held["outcome"], "held")
        self.assertTrue(any(path.endswith("portfolio-setup.json") for path in held["conflicts"]))
        self.assertEqual(before, self._counts())
        code, refused = self._ottoctl("portfolio", "apply", "--portfolio", "foreign", "--root", str(self.root))
        self.assertNotEqual(code, 0)

    def test_manifest_removal_unlinks_only_the_previously_managed_edge(self):
        code, applied = self._apply()
        self.assertEqual(code, 0, applied)
        self.manifest["projects"][1]["dependencies"] = []
        self._write_manifest()
        before = self._counts()
        code, dry = self._apply('--dry-run')
        self.assertEqual(code, 0, dry)
        self.assertEqual(before, self._counts(), 'dry-run must not remove managed edges')
        code, updated = self._apply()
        self.assertEqual(code, 0, updated)
        self.assertTrue(any(row.get("outcome") == "removed" for row in updated["dependencies"]))
        code, status = self._ottoctl("project", "dependencies", "--project", "apply-B")
        self.assertEqual(code, 0, status)
        self.assertEqual(status["dependencies"], [])
        self.manifest['projects'][1]['dependencies'] = [{'on': 'A', 'gate': 'alpha'}]
        self._write_manifest()
        code, added = self._apply()
        self.assertEqual(code, 0, added)
        self.assertTrue(any(row.get('outcome') == 'linked' for row in added['dependencies']), added)

    def test_invalid_manifest_dry_run_is_read_only(self):
        before = self._counts()
        (self.root / "portfolio-setup.json").write_text("{bad json")
        code, result = self._apply("--dry-run")
        self.assertNotEqual(code, 0)
        self.assertEqual(before, self._counts())

    def test_registration_plan_preserves_mixed_adapters_and_card_milestone_dependencies(self):
        from otto.agents.host_profiles import profile
        from otto.hostctl.bundle import read_bundle
        from otto.hostctl.register import plan
        bundle = read_bundle(self.root / "projects" / "A")
        bundle["run"] = {**bundle["run"], "card_dependencies": {
            "T1": ["A#spec0", "user:Codex deploy"]}}
        registration = plan(bundle, profile=profile("claude"), manager_principal="manager",
                            worktree=str(self.root), tool_entrypoint="ottoctl")
        task = next(task for task in registration["tasks"] if task["id"] == "T1")
        self.assertEqual(task["custom"]["megado"]["card_dependencies"],
                         ["A#spec0", "user:Codex deploy"])
        coordinator = registration["configuration"]["roles"]["coordinator"]
        self.assertEqual(coordinator["adapter"], "claude-code")
        bundle["run"]["roles"] = {**bundle["run"].get("roles", {}),
                                  "coordinator": {"model": "gpt-5.6-luna"}}
        mixed = plan(bundle, profile=profile("claude"), manager_principal="manager",
                     worktree=str(self.root), tool_entrypoint="ottoctl")
        self.assertEqual(mixed["configuration"]["model_profile"], "mixed")
        self.assertEqual(mixed["configuration"]["roles"]["coordinator"]["adapter"], "codex")
        self.assertEqual(mixed["configuration"]["roles"]["coordinator"]["model"], "gpt-5.6-luna")



    # --- existing registrations: baselines advance only with the revision ---

    def _documents(self, run_id):
        code, status = self._ottoctl("project", "status", "--project", run_id)
        self.assertEqual(code, 0, status)
        return {row["path"]: row for row in status["documents"]}

    def _edit_tasklist(self, letter="A", marker="Revised after registration."):
        path = self.root / "projects" / letter / "tasklist.md"
        path.write_text(path.read_text() + "\n" + marker + "\n")
        return path

    def test_apply_of_changed_existing_document_commits_revision_and_baseline_together(self):
        import hashlib
        code, applied = self._apply()
        self.assertEqual(code, 0, applied)
        path = self._edit_tasklist()
        new_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        code, changed = self._apply()
        self.assertEqual(code, 0, changed)
        self.assertEqual(changed["outcome"], "applied", changed)
        doc = self._documents("apply-A")["tasklist.md"]
        self.assertEqual(doc["revision_ref"]["revision"], "rev-2")
        self.assertEqual(doc["stored_text_sha256"], new_hash)
        self.assertEqual(doc["registered_raw_sha256"], new_hash)
        self.assertIs(doc["matches_registered_bytes"], True)
        self.assertIs(self._documents("apply-B")["tasklist.md"]["matches_registered_bytes"], True)
        code, again = self._apply()
        self.assertEqual(code, 0, again)
        self.assertEqual(again["outcome"], "in_sync", again)
        code, sync = self._ottoctl("project", "sync-docs", "--project", "apply-A")
        self.assertEqual(sync["outcome"], "in_sync", sync)
        self.assertEqual(sync["not_overwritten"], [])

    def test_failed_document_write_keeps_old_baseline_and_later_sync_writes_source(self):
        import hashlib
        from unittest import mock
        from otto.portfolio.intake import OttoPortfolio
        code, applied = self._apply()
        self.assertEqual(code, 0, applied)
        old = self._documents("apply-A")["tasklist.md"]["registered_raw_sha256"]
        path = self._edit_tasklist()
        new_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        real = OttoPortfolio.check_in_project
        def failing(self_, *args, **kwargs):
            if str(kwargs.get("request_id", "")).startswith("sync:"):
                raise RuntimeError("simulated document write failure")
            return real(self_, *args, **kwargs)
        with mock.patch.object(OttoPortfolio, "check_in_project", failing):
            code, failed = self._apply()
        self.assertNotEqual(code, 0, failed)
        doc = self._documents("apply-A")["tasklist.md"]
        self.assertEqual(doc["registered_raw_sha256"], old)
        self.assertEqual(doc["stored_text_sha256"], old)
        self.assertEqual(doc["revision_ref"]["revision"], "rev-1")
        code, check = self._ottoctl("project", "sync-docs", "--project", "apply-A", "--check")
        states = {row["path"]: row["state"] for row in check["documents"]}
        self.assertEqual(states["tasklist.md"], "changed", check)
        self.assertEqual(check["not_overwritten"], [])
        code, synced = self._ottoctl("project", "sync-docs", "--project", "apply-A")
        self.assertEqual(synced["outcome"], "synced", synced)
        doc = self._documents("apply-A")["tasklist.md"]
        self.assertEqual((doc["stored_text_sha256"], doc["registered_raw_sha256"]), (new_hash, new_hash))

    def test_genuine_otto_side_edit_of_existing_document_still_holds_apply(self):
        from otto.hostctl.cli import _resolve_project
        code, applied = self._apply()
        self.assertEqual(code, 0, applied)
        def edit(session):
            principal = session.host["principal"]
            record = _resolve_project(session, "apply-A")
            opened = session.portfolio.checkout_project(record.ref.to_dict(), actor=principal, request_id="otto-edit:open")
            done = session.portfolio.check_in_project(opened["project_ref"], session_id=opened["session_id"],
                project_json=opened["project_json"], actor=principal, request_id="otto-edit:check-in",
                document_changes=[{"operation": "edit", "path": "plan.md", "content": "# Plan\n\nOtto edit.\n"}])
            self.assertEqual(done["outcome"], "finished", done)
        self._owner(edit)
        code, held = self._apply()
        self.assertEqual(code, 0, held)
        self.assertEqual(held["outcome"], "held", held)
        self.assertIn("apply-A:plan.md", held["conflicts"])


if __name__ == "__main__":
    import unittest
    unittest.main()
