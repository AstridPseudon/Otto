"""``otto save`` saves one project from a file, through the work command lane.

A save file has the template seed shape, so a template and a save file are the
same thing. It names the revision it was read at; a save from an older revision
is refused with a diff and changes nothing. Real owner Store, real lane.
"""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import tempfile
import unittest

from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.content import domain_contribution as content_contribution
from herzchen.contracts import ResourceRef
from herzchen.domains.work import contributions
from herzchen.kernel.store import Store
from otto.portfolio import cli
from otto.portfolio.herzchen_binding import HerzchenBindingConfig
from otto.portfolio.intake import OttoPortfolio
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.plan_metadata import PLAN_NAMESPACE, register_plan_metadata
from otto.portfolio.save import SaveFileError, diff_save, parse_save_file, save_request_key


GOOD_PLAN = {"route": "normal", "size": 0.5, "lines": 40, "repo": "otto", "branch": "lab/A2"}


def _task(local_id, **extra):
    return {"id": local_id, "title": "Plan " + local_id, "instructions": "Do " + local_id,
            "acceptance": "Done " + local_id, **extra}


def _file(*tasks, title="Save plan", **extra):
    return {"project": {"title": title, "outcome": "One creation route"}, "tasks": list(tasks), **extra}


class OtToSaveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="a2-otto-save-test-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.sqlite"
        domains = tuple((*contributions(include_assignment_resources=True),
                         authoring_contribution(), content_contribution()))
        self.store = Store.create(self.path, authority="a2-otto-save-test")
        self.store.register_domain_handler(domains)
        self.addCleanup(self.store.close)
        register_plan_metadata()
        binding = HerzchenBindingConfig("a2-otto-save-test", "fixture-credential")
        self.owner = PortfolioOwnerBootstrap(self.store, binding=binding, owner_actor="owner",
                                             operator_actor="fixture-operator")
        self.portfolio = OttoPortfolio(self.owner.consumer_operations())

    def _counts(self):
        return self.store.consumer().snapshot_counts()

    def _save(self, document, **kwargs):
        return self.portfolio.save_project(document, actor="owner", **kwargs)

    def _project(self, ref):
        return self.owner.graph.current(ResourceRef.from_dict(ref))

    def _tasks(self, ref):
        return [self.owner.graph.current(ResourceRef.from_dict(value)) for value in self._project(ref).payload.get("tasks", ())]

    def _created(self, *tasks, **extra):
        saved = self._save(_file(*tasks, **extra))
        self.assertEqual(saved["outcome"], "saved", saved)
        return saved

    def test_save_creates_the_project_from_the_seed_shape(self):
        saved = self._created(_task("A", metadata_namespace={PLAN_NAMESPACE: GOOD_PLAN}), _task("B", dependencies=["A"]))
        self.assertFalse(saved["dispatch"])
        self.assertFalse(saved["launch"])
        self.assertEqual(set(saved["task_refs"]), {"A", "B"})
        project = self._project(saved["project_ref"])
        self.assertEqual((project.lifecycle.value, project.payload["title"]), ("pending", "Save plan"))
        by_title = {task.title: task for task in self._tasks(saved["project_ref"])}
        self.assertEqual(sorted(by_title), ["Plan A", "Plan B"])
        self.assertEqual(by_title["Plan A"].payload["metadata_namespaces"], {PLAN_NAMESPACE: GOOD_PLAN})
        self.assertEqual(by_title["Plan B"].lifecycle.value, "pending")
        self.assertEqual(len(by_title["Plan B"].payload["dependencies"]), 1)

    def test_template_dependency_form_is_accepted(self):
        saved = self._created(_task("A"), _task("B", dependencies=[{"$local": "A"}]))
        by_title = {task.title: task for task in self._tasks(saved["project_ref"])}
        self.assertEqual(len(by_title["Plan B"].payload["dependencies"]), 1)

    def test_unknown_dependency_is_refused_before_any_write(self):
        counts = self._counts()
        refused = self._save(_file(_task("A", dependencies=["GHOST"])))
        self.assertEqual(refused["outcome"], "error", refused)
        self.assertEqual(refused["error"]["code"], "invalid_save_file")
        self.assertIn("GHOST", refused["error"]["message"])
        self.assertEqual(self._counts(), counts)

    def test_dependency_cycle_is_refused_before_any_write(self):
        counts = self._counts()
        refused = self._save(_file(_task("A", dependencies=["B"]), _task("B", dependencies=["A"])))
        self.assertEqual(refused["outcome"], "error", refused)
        self.assertIn("cycle", refused["error"]["message"])
        self.assertEqual(self._counts(), counts)

    def test_unknown_dependency_on_an_existing_project_changes_nothing(self):
        created = self._created(_task("A"))
        counts = self._counts()
        refused = self._save(_file(_task("B", dependencies=["GHOST"]), project_ref=created["project_ref"]))
        self.assertEqual(refused["outcome"], "error", refused)
        self.assertEqual(self._counts(), counts)
        self.assertEqual([task.title for task in self._tasks(created["project_ref"])], ["Plan A"])

    def test_malformed_first_save_leaves_no_project_or_task_or_receipt(self):
        counts = self._counts()
        refused = self._save(_file({"id": "A"}))
        self.assertEqual(refused["outcome"], "error", refused)
        self.assertIn("title", refused["error"]["message"])
        self.assertEqual(self._counts(), counts)

    def test_second_save_detects_cycle_through_a_retained_task(self):
        created = self._created(_task("A"), _task("B", dependencies=["A"]))
        before = self._counts()
        refused = self._save(_file(_task("A", dependencies=["B"]),
                                   project_ref=created["project_ref"]))
        self.assertEqual(refused["outcome"], "error", refused)
        self.assertIn("cycle", refused["error"]["message"])
        self.assertEqual(self._counts(), before)

    def test_saved_criteria_are_present_in_the_authored_project_view(self):
        criteria = [{"id": "C1", "definition": "The saved result is reviewed"}]
        saved = self._created(_task("A"), criteria=criteria)
        from otto.portfolio.herzchen_binding import ProjectReadGrant
        granted_owner = PortfolioOwnerBootstrap(
            self.store, binding=self.owner.binding, owner_actor="owner",
            project_read_grant=ProjectReadGrant(self.owner.owner_actor,
                (saved["project_ref"]["id"],), "fixture-owner", "1"),
        )
        portfolio = OttoPortfolio(granted_owner.consumer_operations())
        from otto.portfolio.show import show_project
        shown = show_project(portfolio, actor="owner", project_ref=saved["project_ref"], limit=100)
        self.assertEqual(shown.get("outcome"), "read", shown)
        self.assertEqual(shown["project"]["criteria"], criteria)

    def test_task_brief_document_round_trips_through_save_and_show(self):
        brief = "Follow the project brief."
        saved = self._created(
            _task("A", instructions=brief),
            documents=[{"local_id": "brief-A", "title": "Brief A", "content": {"text": brief}}],
        )
        self.assertEqual(saved["outcome"], "saved", saved)
        self.assertEqual(parse_save_file(_file(
            _task("A", instructions=brief),
            documents=[{"local_id": "brief-A", "title": "Brief A", "content": {"text": brief}}],
        ))["seed"]["documents"][0]["content"], {"text": brief})

        from otto.portfolio.herzchen_binding import ProjectReadGrant
        from otto.portfolio.show import show_project
        granted_owner = PortfolioOwnerBootstrap(
            self.store, binding=self.owner.binding, owner_actor="owner",
            project_read_grant=ProjectReadGrant(self.owner.owner_actor,
                (saved["project_ref"]["id"],), "fixture-owner", "1"),
        )
        shown = show_project(OttoPortfolio(granted_owner.consumer_operations()), actor="owner",
                             project_ref=saved["project_ref"], limit=100)
        self.assertEqual(shown.get("outcome"), "read", shown)
        self.assertEqual(shown["tasks"][0]["authored"]["instructions"], brief)

    def test_plan_namespace_accepts_replacement_and_null_key_removal(self):
        created = self._created(_task("A", metadata_namespace={PLAN_NAMESPACE: GOOD_PLAN}))
        replacement = dict(GOOD_PLAN, lines=72, size=1.25)
        saved = self._save(_file(_task("A", metadata_namespace={PLAN_NAMESPACE: replacement}),
                                 project_ref=created["project_ref"]))
        self.assertEqual(saved["outcome"], "saved", saved)
        task = self._tasks(saved["project_ref"])[0]
        self.assertEqual(task.payload["metadata_namespaces"][PLAN_NAMESPACE], replacement)
        removed = dict(replacement)
        removed["lines"] = None
        saved = self._save(_file(_task("A", metadata_namespace={PLAN_NAMESPACE: removed}),
                                 project_ref=saved["project_ref"]))
        self.assertEqual(saved["outcome"], "saved", saved)
        task = self._tasks(saved["project_ref"])[0]
        self.assertNotIn("lines", task.payload["metadata_namespaces"][PLAN_NAMESPACE])

    def test_busy_store_refusal_offers_retry_guidance(self):
        import sqlite3
        from unittest import mock
        created = self._created(_task("A"))
        delegate = self.portfolio.operations.sheet_port

        class BusySheetPort:
            def __getattr__(self, name):
                if name == "apply":
                    raise sqlite3.OperationalError("database is locked")
                return getattr(delegate, name)

        with mock.patch.object(self.portfolio.operations, "sheet_port", BusySheetPort()):
            refused = self._save(_file(_task("A", title="Plan A changed"),
                                       project_ref=created["project_ref"]))
        self.assertEqual(refused["outcome"], "error", refused)
        self.assertEqual(refused["error"]["code"], "store_busy")
        self.assertTrue(refused["retry"])
        self.assertIn("Retry", refused["next_action"])

    def test_dependency_on_retired_task_names_successor_and_is_not_redirected(self):
        created = self._created(_task("A"), _task("B"))
        tasks = {task.alias: task for task in self._tasks(created["project_ref"])}
        self.owner.graph.retire(tasks["A"].ref, reason="superseded", by=tasks["B"].ref,
                                logical_request_key="retire-A")
        current_project = self._project(created["project_ref"])
        counts = self._counts()
        refused = self._save(_file(_task("C", dependencies=["A"]),
            project_ref=current_project.ref.to_dict()))
        self.assertEqual(refused["outcome"], "error", refused)
        self.assertIn(tasks["B"].id, refused["error"]["message"])
        self.assertEqual(self._counts(), counts)
        self.assertEqual({task.alias for task in self._tasks(current_project.ref.to_dict())}, {"A", "B"})

    def test_refused_typed_metadata_creates_no_project(self):
        counts = self._counts()
        refused = self._save(_file(_task("A", metadata_namespace={PLAN_NAMESPACE: {"route": "fast"}})))
        self.assertEqual(refused["outcome"], "error", refused)
        self.assertEqual(self._counts(), counts)

    def test_replay_makes_no_duplicates(self):
        document = _file(_task("A"), _task("B", dependencies=["A"]))
        first = self._save(document)
        counts = self._counts()
        again = self._save(document)
        self.assertEqual(again["outcome"], "replayed", again)
        self.assertTrue(again["replayed"])
        self.assertEqual(again["project_ref"]["id"], first["project_ref"]["id"])
        self.assertEqual(self._counts(), counts)
        self.assertEqual(len(self._tasks(first["project_ref"])), 2)

    def test_omitting_a_task_never_withdraws_it(self):
        created = self._created(_task("A"), _task("B"))
        kept = self._save(_file(_task("A", title="Plan A two"), project_ref=created["project_ref"]))
        self.assertEqual(kept["outcome"], "saved", kept)
        by_title = {task.title: task for task in self._tasks(created["project_ref"])}
        self.assertEqual(sorted(by_title), ["Plan A two", "Plan B"])
        self.assertEqual(by_title["Plan B"].lifecycle.value, "pending")

    def test_partial_sheet_update_resolves_id_and_preserves_existing_task_fields(self):
        created = self._created()
        port = self.portfolio.operations.sheet_port
        first = port.apply(ResourceRef.from_dict(created["project_ref"]),
                           {"tasks": [{"id": "A", "title": "Alpha", "body": "Keep this"}]},
                           logical_request_key="partial-sheet-first")
        second = port.apply(first.project.ref, {"tasks": [{"id": "A", "lifecycle": "active"}]},
                            logical_request_key="partial-sheet-second")
        task = self.owner.graph.current(second.mappings["A"])
        self.assertEqual(task.title, "Alpha")
        self.assertEqual(task.payload["body"], "Keep this")
        self.assertEqual(task.lifecycle.value, "active")

    def test_save_from_an_old_revision_after_a_newer_one_is_refused_with_a_diff(self):
        created = self._created(_task("A"), title="Plan one")
        newer = self._save(_file(_task("A", title="Plan A two"), title="Plan two",
                                 project_ref=created["project_ref"]))
        self.assertEqual(newer["outcome"], "saved", newer)
        counts = self._counts()
        stale = self._save(_file(_task("A", title="Plan A three"), title="Plan three",
                                 project_ref=created["project_ref"]))
        self.assertEqual(stale["outcome"], "conflict", stale)
        self.assertEqual(stale["error"]["code"], "stale_base")
        self.assertEqual(stale["base_revision"], created["project_ref"]["revision"])
        self.assertEqual(stale["current_project_ref"]["revision"], newer["project_ref"]["revision"])
        self.assertEqual(stale["diff"]["project"]["title"], {"file": "Plan three", "current": "Plan two"})
        self.assertEqual(stale["diff"]["tasks"]["changed"][0]["id"], "A")
        self.assertEqual(stale["diff"]["tasks"]["changed"][0]["fields"]["title"],
                         {"file": "Plan A three", "current": "Plan A two"})
        self.assertIn("Reread", stale.get("next_action", ""))
        self.assertFalse(stale["dispatch"])
        self.assertEqual(self._counts(), counts)
        self.assertEqual(self._project(newer["project_ref"]).payload["title"], "Plan two")
        self.assertEqual([task.title for task in self._tasks(newer["project_ref"])], ["Plan A two"])

    def test_stale_save_can_be_reread_and_reapplied(self):
        created = self._created(_task("A"), title="Plan one")
        newer = self._save(_file(_task("A", title="Plan A two"), title="Plan two",
                                 project_ref=created["project_ref"]))
        stale = self._save(_file(_task("A", title="Plan A three"), title="Plan three",
                                 project_ref=created["project_ref"]))
        self.assertEqual(stale["outcome"], "conflict", stale)
        current_ref = ResourceRef.from_dict(stale["current_project_ref"])
        reread = self.owner.sheet.export(current_ref)
        self.assertEqual(reread.project["authored"]["title"], "Plan two")
        self.assertEqual(reread.project["ref"].revision, newer["project_ref"]["revision"])
        reapplied = self._save(_file(_task("A", title="Plan A three"), title="Plan three",
                                     project_ref=stale["current_project_ref"]))
        self.assertEqual(reapplied["outcome"], "saved", reapplied)

    def test_save_file_refusals_happen_without_the_owner(self):
        for bad, reason in (
            ([], "JSON object"),
            ({"project": {}, "tasks": [], "efforts": []}, "unknown save-file fields"),
            ({"project": {}, "tasks": [], "project_ref": {"id": "p1"}}, "needs the revision"),
            ({"tasks": [_task("A", lifecycle="active")]}, "must be pending"),
            ({"tasks": [_task("A"), _task("A")]}, "appears twice"),
            ({"tasks": [{"title": "no id"}]}, "needs a non-blank id"),
            ({"tasks": [_task("A", unsupported_control="start")]}, "unsupported fields"),
            ({"tasks": [_task("A", dependencies="B")]}, "dependencies must be an array"),
            ({"tasks": [_task("A", dependencies=[3])]}, "must name a task id"),
        ):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(SaveFileError, reason):
                    parse_save_file(bad)

    def test_request_key_is_deterministic_per_content(self):
        document = _file(_task("A"))
        self.assertEqual(save_request_key(document), save_request_key(json.loads(json.dumps(document))))
        self.assertNotEqual(save_request_key(document), save_request_key(_file(_task("A", title="other"))))

    def test_diff_names_added_changed_and_kept_tasks(self):
        current = {"project": {"authored": {"title": "Old"}},
                   "tasks": [{"authored": {"alias": "A", "aliases": ["A"], "title": "Plan A"}},
                             {"authored": {"alias": "K", "aliases": ["K"], "title": "Kept"}}]}
        seed = {"project": {"title": "New"}, "tasks": [{"id": "A", "title": "Plan A changed"}, {"id": "N", "title": "New"}]}
        diff = diff_save(seed, current)
        self.assertEqual(diff["project"], {"title": {"file": "New", "current": "Old"}})
        self.assertEqual(diff["tasks"]["added"], ["N"])
        self.assertEqual(diff["tasks"]["changed"], [{"id": "A", "fields": {"title": {"file": "Plan A changed", "current": "Plan A"}}}])
        self.assertEqual(diff["tasks"]["kept"], ["K"])

    def test_cli_saves_a_file_and_exits_nonzero_on_a_stale_base(self):
        document = _file(_task("A"), title="Plan one")
        file_path = Path(self.temporary.name) / "plan.json"
        file_path.write_text(json.dumps(document), encoding="utf-8")
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(["save", str(file_path), "--actor", "owner"], portfolio=self.portfolio)
        self.assertEqual(code, 0, out.getvalue())
        created = json.loads(out.getvalue())
        self.assertEqual(created["outcome"], "saved")

        newer = _file(_task("A"), title="Plan two", project_ref=created["project_ref"])
        file_path.write_text(json.dumps(newer), encoding="utf-8")
        with redirect_stdout(StringIO()):
            self.assertEqual(cli.main(["save", str(file_path), "--actor", "owner"], portfolio=self.portfolio), 0)

        stale = _file(_task("A"), title="Plan three", project_ref=created["project_ref"])
        file_path.write_text(json.dumps(stale), encoding="utf-8")
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(["save", str(file_path), "--actor", "owner"], portfolio=self.portfolio)
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["outcome"], "conflict")


if __name__ == "__main__":
    unittest.main()
