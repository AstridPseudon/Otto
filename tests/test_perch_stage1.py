"""PERCH stage 1: a save through the owner socket, and the stage 1 assertions with their seeded faults.

The socket tests run the owner service of the real host fixture (real lanes, real Store). The assertion tests build
one stage 1 run folder, check that it is green, then seed one fault through the same CLI perch.sh uses and check
that only the assertion that reads it turns red.
"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from otto.hostctl import lanes
from otto.hostctl.service import owner_lane
from test_hostctl_cli import HostctlFixture

HERE = Path(__file__).resolve().parent.parent / "ops" / "bootstrap"
sys.path.insert(0, str(HERE))
import perch_report as report  # noqa: E402


SAVE_DOCUMENT = {"project": {"title": "Canary plan", "outcome": "One creation route"}, "tasks": [
    {"id": "A", "title": "Plan A", "instructions": "Do A", "acceptance": "Done A"},
    {"id": "B", "title": "Plan B", "instructions": "Do B", "acceptance": "Done B", "dependencies": ["A"]},
    {"id": "C", "title": "Plan C", "instructions": "Do C", "acceptance": "Done C"}]}


def _save_file(home, name, document, project_ref=None):
    body = copy.deepcopy(document)
    if project_ref is not None:
        body["project_ref"] = project_ref
    path = Path(home) / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return str(path)


class OwnerSocketSaveTests(HostctlFixture):
    """The owner lane's portfolio-operation branch: a save is accepted, a stale save is refused, a non-allowlisted command is refused."""

    def setUp(self):
        super().setUp()
        self._init()

    def _owner(self, command, sub, args):
        request = {"command": "portfolio-operation",
                   "args": {"schema": lanes.REQUEST_SCHEMA, "command": command, "sub": sub, "args": args}}
        lane = owner_lane(Path(self.home))
        token = lanes.submit(lane, request)
        return lanes.wait(lane, token, timeout_seconds=60)

    def _save(self, name, document=SAVE_DOCUMENT, project_ref=None):
        path = _save_file(self.home, name, document, project_ref)
        return self._owner("portfolio", None, {"portfolio": "claude-code-portfolio",
                                               "portfolio_args": ["save", path]})

    def test_save_sent_through_the_owner_socket_is_accepted(self):
        result = self._save("create.json")
        self.assertEqual(result.get("outcome"), "saved", result)
        self.assertFalse(result["dispatch"], result)
        self.assertFalse(result["launch"], result)

    def test_the_save_names_each_task_with_a_typed_ref_as_the_store_holds_it(self):
        # The shape the staging gate reads: a ResourceRef's dict, with its record type under `kind`.
        created = self._save("create.json")
        self.assertEqual(created.get("outcome"), "saved", created)
        self.assertEqual(set(created["task_refs"]), {"A", "B", "C"}, created)
        self.assertEqual({ref["kind"] for ref in created["task_refs"].values()}, {"work.task"}, created)
        for ref in created["task_refs"].values():
            self.assertEqual(set(ref) - {"revision"}, {"authority", "kind", "id"}, ref)
            for key in ("authority", "kind", "id"):
                self.assertTrue(str(ref[key]).strip(), ref)

    def test_show_readback_through_owner_lane_returns_the_saved_tasks(self):
        created = self._save("create.json")
        self.assertEqual(created.get("outcome"), "saved", created)
        project_ref = json.dumps(created["project_ref"], separators=(",", ":"))
        code, shown = self._ottoctl("portfolio", "--portfolio", "claude-code-portfolio", "show", "project",
                                    "--project-ref", project_ref, "--actor", "otto-test-owner")
        self.assertEqual(code, 0, shown)
        self.assertEqual(shown.get("outcome"), "read", shown)
        self.assertEqual(len(shown.get("tasks", [])), 3, shown)
        self.assertFalse(shown["dispatch"], shown)
        self.assertFalse(shown["launch"], shown)

    def test_store_snapshot_reads_saved_task_records_and_kept_project_revision(self):
        canary = json.loads((HERE / "canary" / "project.json").read_text(encoding="utf-8"))["stages"]["1"]["saves"]
        created = self._save("create.json", canary["create"])
        self.assertEqual(created.get("outcome"), "saved", created)
        edit = copy.deepcopy(canary["edit"])
        edit["project_ref"] = created["project_ref"]
        edited = self._save("edit.json", edit, created["project_ref"])
        self.assertEqual(edited.get("outcome"), "saved", edited)
        refs = Path(self.home) / "refs.json"
        refs.write_text(json.dumps(created), encoding="utf-8")
        edited_refs = Path(self.home) / "edited-refs.json"
        edited_refs.write_text(json.dumps(edited), encoding="utf-8")
        snapshot_path = Path(self.home) / "store-snapshot.json"
        from otto.hostctl import config as host_config
        report.cmd_store(type("Args", (), {"store": host_config.load(Path(self.home))["store"]["path"],
                                             "refs": [str(refs), str(edited_refs)], "src": "", "admission": "",
                                             "out": str(snapshot_path)})())
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot.get("project_revision"), edited["project_ref"]["revision"], snapshot)
        for alias, ref in edited["task_refs"].items():
            key = "%s:%s@%s" % (ref["kind"], ref["id"], ref["revision"])
            self.assertIsNotNone(snapshot["records"].get(key), (alias, snapshot))
        b_ref = edited["task_refs"]["B"]
        b_key = "%s:%s@%s" % (b_ref["kind"], b_ref["id"], b_ref["revision"])
        self.assertEqual(snapshot["records"][b_key]["payload"]["metadata_namespaces"]["otto.plan"]["size"], 0.75)
        c_ref, b_ref = edited["task_refs"]["C"], edited["task_refs"]["B"]
        c_key = "%s:%s@%s" % (c_ref["kind"], c_ref["id"], c_ref["revision"])
        self.assertIn(b_ref["id"], {dep["id"] for dep in snapshot["records"][c_key]["payload"]["dependencies"]})
        project_ref = created["project_ref"]
        history_key = "%s:%s@%s" % (project_ref["kind"], project_ref["id"], project_ref["revision"])
        self.assertEqual(snapshot["records"][history_key]["payload"]["title"], "Canary plan", snapshot)

    def test_stale_save_sent_through_the_owner_socket_is_refused(self):
        created = self._save("create.json")
        edited = copy.deepcopy(SAVE_DOCUMENT)
        edited["tasks"][0]["title"] = "Plan A two"
        self.assertEqual(self._save("edit.json", edited, created["project_ref"]).get("outcome"), "saved")
        stale = copy.deepcopy(SAVE_DOCUMENT)
        stale["tasks"][0]["title"] = "Plan A three"
        refused = self._save("stale.json", stale, created["project_ref"])
        self.assertEqual(refused.get("outcome"), "conflict", refused)
        self.assertEqual(refused["error"]["code"], "stale_base", refused)
        self.assertFalse(refused["dispatch"], refused)

    def test_cold_client_save_reaches_the_owner_socket(self):
        # The client forwards save to the owner lane (hostctl/portfolio.py prepare_portfolio_request, client_request).
        code, result = self._ottoctl("portfolio", "--portfolio", "claude-code-portfolio",
                                     "save", _save_file(self.home, "cold.json", SAVE_DOCUMENT))
        self.assertEqual(code, 0, result)
        self.assertEqual(result.get("outcome"), "saved", result)

    def test_save_with_a_mistyped_portfolio_is_refused_naming_it_and_the_owner_is_untouched(self):
        before = self.owner_service.call(self._store_events)
        code, result = self._ottoctl("portfolio", "--portfolio", "claude-cod-portfolio",
                                     "save", _save_file(self.home, "typo.json", SAVE_DOCUMENT))
        self.assertNotEqual(code, 0, result)
        self.assertEqual(result.get("outcome"), "error", result)
        self.assertIn("claude-cod-portfolio", result["error"]["message"], result)
        self.assertEqual(self.owner_service.call(self._store_events), before)

    def test_the_admitted_portfolio_is_the_one_the_stage_names(self):
        code, admitted = self._ottoctl("service", "admit-host", "--host", "claude-code", "--launcher", self.launcher)
        self.assertEqual(code, 0, admitted)
        self.assertEqual(admitted["host"]["portfolio_ref"]["id"], report.portfolio_id("claude-code"), admitted)

    def _store_events(self):
        from otto.hostctl import config as host_config
        from otto.hostctl.owner import HostSession
        config = host_config.load(Path(self.home))
        with HostSession(config, host=config["hosts"]["claude-code"]) as session:
            return len(session.store.list_events())

    def test_non_allowlisted_operation_is_still_refused(self):
        result = self._owner("host", "show", {"portfolio": "claude-code-portfolio"})
        self.assertEqual(result.get("outcome"), "error", result)
        self.assertEqual(result["error"]["code"], "PermissionError", result)


STAGE1_FAULTS = {
    "admit": "portfolio-admitted-before-saves",
    "canary": "canary-has-three-planned-tasks",
    "readback": "show-readback-available",
    "typed": "store-has-typed-tasks",
    "edit": "edit-is-persisted",
    "nothing": "nothing-runs",
    "revision": "edit-makes-revision",
    "history": "project-history-keeps-old-revision",
    "stale": "stale-save-refused",
    "growth": "store-growth-per-save",
}


def stage_one_run(root):
    """A stage 1 run folder as perch.sh leaves it, green on every assertion."""
    raw = Path(root) / "raw"
    raw.mkdir(parents=True)

    def put(name, value):
        (raw / name).write_text(value if isinstance(value, str) else json.dumps(value, indent=2) + "\n", encoding="utf-8")

    ref = {"authority": "otto-staging-owner-v1", "kind": "work.project", "id": "p1"}
    tasks = {alias: {"authority": "otto-staging-owner-v1", "kind": "work.task", "id": "t" + alias}
             for alias in ("A", "B", "C")}
    put("admission.json", {"outcome": "admitted", "host": {"portfolio_ref": dict(ref, id=report.portfolio_id("claude-code"))}})
    put("config.json", {"stage": "1", "fake": True, "tasks": [], "check": "true", "stage_root": "", "pool_limit": 1, "host": "claude-code",
                        "store": {"store_events": 3, "store_tasks": 1, "store_bytes_max": 262144, "rows_per_save_max": 50},
                        "faults": [], "staging_restart": 0, "staging_sha": "x", "canon_main_sha": "x",
                        "started_at": "x", "finished_at": "x"})
    put("notes.json", {"save-through-socket": "ran"})
    put("events.tsv", "")
    put("census.after.txt", "")
    put("leftovers.txt", "")
    put("timeline.json", {"store_events": 3, "error": None, "tasks": [{"task_id": "boot", "complete": True, "gaps": [], "events": []}]})
    put("store-at-rest.json", {"error": None, "bytes": 90000, "rows": {"events": 4}})
    put("at-rest.json", {"home_run": ["generation", "service-stop", "service.json"], "service_state": "closed",
                         "sockets": [], "store_holders": {}, "perch_canary": [], "error": None})
    put("save-create.json", {"outcome": "saved", "dispatch": False, "launch": False,
                             "project_ref": dict(ref, revision="rev-2"), "task_refs": tasks})
    put("read-back.json", {"outcome": "read", "dispatch": False, "launch": False,
                            "tasks": [{"authored": {"alias": alias}} for alias in tasks]})
    put("save-edit.json", {"outcome": "saved", "dispatch": False, "launch": False,
                           "project_ref": dict(ref, revision="rev-3"), "task_refs": tasks})
    put("save-stale.json", {"outcome": "conflict", "dispatch": False, "launch": False, "project_ref": dict(ref, revision="rev-3"),
                            "error": {"code": "stale_base"}, "diff": {"project": {}, "tasks": {"changed": []}}})
    project_old = {"ref": dict(ref, revision="rev-2"), "payload": {"title": "Canary plan"}}
    project_new = {"ref": dict(ref, revision="rev-3"), "payload": {"title": "Canary plan"}}
    task_records = {}
    create_task_records = {}
    for alias, value in tasks.items():
        payload = {"alias": alias, "title": {"A": "Plan A edited", "B": "Plan B", "C": "Plan C"}[alias],
                   "metadata_namespaces": {"otto.plan": {"route": "normal", "size": 0.75 if alias == "B" else 0.25, "lines": 12}},
                   "dependencies": ([dict(tasks["B"], revision=None)] if alias == "C" else
                                   [dict(tasks["A"], revision=None)] if alias == "B" else [])}
        task_records["work.task:%s@rev-2" % value["id"]] = {"ref": dict(value, revision="rev-2"), "payload": payload}
        create_payload = {"alias": alias, "acceptance": "Done " + alias,
                          "metadata_namespaces": {"otto.plan": {"route": "normal", "size": 0.5 if alias == "B" else 0.25,
                                                                  "lines": {"A": 20, "B": 30, "C": 15}[alias]}},
                          "dependencies": ([dict(tasks["A"], revision=None)] if alias == "B" else [])}
        create_task_records["work.task:%s@rev-2" % value["id"]] = {
            "ref": dict(value, revision="rev-2"), "payload": create_payload}
    put("store-before-saves.json", {"error": None, "rows": {"events": 1}, "admission_outcome": "admitted"})
    put("store-after-create.json", {"error": None, "rows": {"events": 3}, "records": {
        "work.project:p1@rev-2": project_old, **create_task_records}})
    put("store-after-edit.json", {"error": None, "rows": {"events": 4}, "records": {
        "work.project:p1@rev-2": project_old, "work.project:p1@rev-3": project_new, **task_records},
        "project_revision": "rev-3", "event_types": []})
    put("store-after-stale.json", {"error": None, "rows": {"events": 4}, "records": task_records})
    return raw


class StageOneAssertionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="perch-stage1-")
        self.addCleanup(self.temporary.cleanup)

    def _run(self, name):
        return Path(self.temporary.name) / name

    def _results(self, raw):
        return {r["name"]: r for r in report.assertions(raw)}

    def test_a_clean_stage_one_run_is_green_on_every_stage_one_assertion(self):
        got = self._results(stage_one_run(self._run("clean")))
        for name in report.STAGE1:
            self.assertEqual(got[name]["status"], "pass", got[name])

    def test_each_seeded_fault_turns_only_its_own_assertion_red(self):
        baseline = {name: r["status"] for name, r in self._results(stage_one_run(self._run("base"))).items()}
        for kind, target in STAGE1_FAULTS.items():
            with self.subTest(fault=kind):
                raw = stage_one_run(self._run(kind))
                subprocess.run([sys.executable, "-I", str(HERE / "perch_report.py"), "seed", "--raw", str(raw),
                                "--fault", kind], check=True)
                got = {name: r["status"] for name, r in self._results(raw).items()}
                self.assertEqual(got[target], "fail", got)
                self.assertEqual({n: s for n, s in got.items() if n != target},
                                 {n: s for n, s in baseline.items() if n != target}, got)

    def test_check_exits_red_for_a_seeded_stage_one_fault(self):
        raw = stage_one_run(self._run("exit"))
        subprocess.run([sys.executable, "-I", str(HERE / "perch_report.py"), "seed", "--raw", str(raw), "--fault", "stale"],
                       check=True)
        code = subprocess.run([sys.executable, "-I", str(HERE / "perch_report.py"), "check", "--raw", str(raw)]).returncode
        self.assertEqual(code, 1)

    def test_a_stage_one_fault_is_refused_in_a_run_without_its_observation(self):
        raw = self._run("stage0-fault")
        raw.mkdir()
        for kind in STAGE1_FAULTS:
            with self.subTest(fault=kind):
                done = subprocess.run([sys.executable, "-I", str(HERE / "perch_report.py"), "seed", "--raw", str(raw),
                                       "--fault", kind], capture_output=True, text=True)
                self.assertNotEqual(done.returncode, 0, kind)
                self.assertEqual(list(raw.iterdir()), [], kind)

    def test_a_stage_without_the_save_scenario_reports_no_stage_one_rows(self):
        raw = stage_one_run(self._run("stage0"))
        (raw / "notes.json").write_text(json.dumps({}), encoding="utf-8")
        names = {r["name"] for r in report.assertions(raw)}
        self.assertFalse(names & set(report.STAGE1), names)

    def test_a_save_scenario_that_did_not_run_skips_each_stage_one_assertion_and_says_why(self):
        raw = stage_one_run(self._run("skipped"))
        (raw / "notes.json").write_text(json.dumps({"save-through-socket": "skipped: staging did not start"}), encoding="utf-8")
        got = self._results(raw)
        for name in report.STAGE1:
            self.assertEqual(got[name]["status"], "skip", got[name])
            self.assertIn("staging did not start", got[name]["detail"])

    def test_an_unavailable_save_fails_the_assertions_that_read_it(self):
        raw = stage_one_run(self._run("unavailable"))
        (raw / "save-stale.json").write_text(json.dumps({"outcome": "unavailable"}), encoding="utf-8")
        got = self._results(raw)
        self.assertEqual(got["stale-save-refused"]["status"], "fail", got)
        self.assertEqual(got["nothing-runs"]["status"], "fail", got)
        self.assertEqual(got["edit-makes-revision"]["status"], "pass", got)


class StageOneProjectFileTests(unittest.TestCase):
    PROJECT = HERE / "canary" / "project.json"

    def test_stage_one_is_listed_and_starts_on_an_empty_store(self):
        self.assertIn("1", subprocess.run([sys.executable, "-I", str(HERE / "perch_report.py"), "stages", "--project",
                                           str(self.PROJECT)], capture_output=True, text=True, check=True).stdout.split())
        wipe = subprocess.run([sys.executable, "-I", str(HERE / "perch_report.py"), "stage", "--project", str(self.PROJECT),
                               "--stage", "1", "--key", "wipe"], capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(wipe, "true")

    def test_three_task_canary_has_plan_metadata_and_edits_dependency_and_values(self):
        project = json.loads(self.PROJECT.read_text(encoding="utf-8"))
        saves = project["stages"]["1"]["saves"]
        create = {row["id"]: row for row in saves["create"]["tasks"]}
        edit = {row["id"]: row for row in saves["edit"]["tasks"]}
        self.assertEqual(set(create), {"A", "B", "C"})
        self.assertEqual(create["B"]["dependencies"], ["A"])
        self.assertEqual(edit["C"]["dependencies"], ["B"])
        self.assertNotEqual(create["A"]["title"], edit["A"]["title"])
        self.assertNotEqual(create["B"]["metadata_namespace"]["otto.plan"]["size"],
                            edit["B"]["metadata_namespace"]["otto.plan"]["size"])
        for task in create.values():
            self.assertTrue(all(key in task["metadata_namespace"]["otto.plan"] for key in ("route", "size", "lines")))
            self.assertTrue(task["acceptance"])

    def test_save_documents_edit_and_stale_keep_the_create_base(self):
        temporary = tempfile.TemporaryDirectory(prefix="perch-stage1-doc-")
        self.addCleanup(temporary.cleanup)
        created = Path(temporary.name) / "create.json"
        created.write_text(json.dumps({"outcome": "saved", "project_ref": {"id": "p1", "revision": "rev-2"}}), encoding="utf-8")
        docs = {}
        for name in ("create", "edit", "stale"):
            out = Path(temporary.name) / (name + ".out.json")
            args = ["save-doc", "--project", str(self.PROJECT), "--stage", "1", "--name", name, "--out", str(out)]
            if name != "create":
                args += ["--ref-from", str(created)]
            report.main(args)
            docs[name] = json.loads(out.read_text(encoding="utf-8"))
        self.assertNotIn("project_ref", docs["create"])
        self.assertEqual(docs["edit"]["project_ref"], {"id": "p1", "revision": "rev-2"})
        self.assertEqual(docs["stale"]["project_ref"], {"id": "p1", "revision": "rev-2"})
        self.assertNotEqual(docs["edit"]["tasks"], docs["create"]["tasks"])


class StageFourLandingAssertionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="perch-stage4-")
        self.addCleanup(self.temporary.cleanup)

    def _raw(self, *, fake=True):
        raw = stage_one_run(Path(self.temporary.name) / "clean")
        config = json.loads((raw / "config.json").read_text(encoding="utf-8"))
        config.update(stage="4", fake=fake, tasks=[{"name": "canary-stage4-happy", "expect": "landed"},
                                         {"name": "canary-stage4-conflict", "expect": "conflict",
                                          "landing_conflict": True}])
        (raw / "config.json").write_text(json.dumps(config), encoding="utf-8")
        rows = [
            ("canary-stage4-happy", "owner-admitted"),
            ("canary-stage4-happy", "owner-task-admitted"),
            ("canary-stage4-happy", "owner-dispatch-launched"),
            ("canary-stage4-happy", "lab-created"), ("canary-stage4-happy", "check-passed"),
            ("canary-stage4-happy", "landed"), ("canary-stage4-happy", "lab-deleted"),
            ("canary-stage4-conflict", "lab-created"), ("canary-stage4-conflict", "check-passed"),
            ("canary-stage4-conflict", "landing-conflict"), ("canary-stage4-conflict", "refused"),
            ("canary-stage4-conflict", "lab-deleted"),
        ]
        (raw / "events.tsv").write_text("".join("2026-10-16T10:00:00Z\t%s\t%s\t\n" % row for row in rows),
                                             encoding="utf-8")
        for name, turns in (("canary-stage4-happy", 2), ("canary-stage4-conflict", 1)):
            events = [{"at": "2026-10-16T10:00:00Z", "kind": "turn", "task": name, "turn": 1, "sha": "c1"}]
            if turns == 2:
                events.append({"at": "2026-10-16T10:00:00Z", "kind": "turn", "task": name, "turn": 2, "sha": "c2"})
            events.append({"at": "2026-10-16T10:00:00Z", "kind": "done", "task": name, "turns": turns})
            (raw / ("worker-%s.jsonl" % name)).write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
        return raw

    def test_a_green_check_is_refused_at_conflict_and_the_lab_is_deleted(self):
        raw = self._raw()
        got = {row["name"]: row["status"] for row in report.assertions(raw)}
        self.assertEqual(got["timeline-events"], "pass", got)
        self.assertEqual(got["landing-conflict-refused"], "pass", got)
        self.assertEqual(got["landing-conflict-lab-deleted"], "pass", got)
        self.assertEqual(got["owner-driven-canary"], "skip", got)

    def test_missing_owner_dispatch_turns_only_owner_journey_assertion_red(self):
        raw = self._raw(fake=False)
        before = {row["name"]: row["status"] for row in report.assertions(raw)}
        report.seed(raw, "owner")
        after = {row["name"]: row["status"] for row in report.assertions(raw)}
        self.assertEqual(after["owner-driven-canary"], "fail", after)
        self.assertEqual({name: state for name, state in after.items() if name != "owner-driven-canary"},
                         {name: state for name, state in before.items() if name != "owner-driven-canary"}, after)

    def test_direct_fake_worktree_events_do_not_count_as_owner_journey(self):
        raw = self._raw()
        events = raw / "events.tsv"
        events.write_text("".join(line for line in events.read_text(encoding="utf-8").splitlines(keepends=True)
                                   if "\towner-" not in line), encoding="utf-8")
        got = {row["name"]: row["status"] for row in report.assertions(raw)}
        self.assertEqual(got["owner-driven-canary"], "skip", got)

    def test_seeded_missing_conflict_turns_only_the_conflict_assertion_red(self):
        raw = self._raw()
        before = {row["name"]: row["status"] for row in report.assertions(raw)}
        report.seed(raw, "conflict")
        after = {row["name"]: row["status"] for row in report.assertions(raw)}
        self.assertEqual(after["landing-conflict-refused"], "fail", after)
        self.assertEqual({name: state for name, state in after.items() if name != "landing-conflict-refused"},
                         {name: state for name, state in before.items() if name != "landing-conflict-refused"}, after)

    def test_a_conflicted_lab_left_behind_fails_its_dedicated_assertion(self):
        raw = self._raw()
        path = raw / "events.tsv"
        path.write_text("".join(line for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
                                 if not ("canary-stage4-conflict" in line and "lab-deleted" in line)), encoding="utf-8")
        got = {row["name"]: row["status"] for row in report.assertions(raw)}
        self.assertEqual(got["landing-conflict-lab-deleted"], "fail", got)


class StageFourProjectFileTests(unittest.TestCase):
    def test_stage_four_canary_declares_green_and_landing_conflict_tasks(self):
        project = json.loads((HERE / "canary" / "project.json").read_text(encoding="utf-8"))
        stage = project["stages"]["4"]
        self.assertEqual(stage["tasks"], ["canary-stage4-happy", "canary-stage4-conflict"])
        self.assertIn("landing-conflict", stage["scenarios"])
        self.assertEqual(project["tasks"][stage["tasks"][0]]["expect"], "landed")
        self.assertTrue(project["tasks"][stage["tasks"][1]]["landing_conflict"])

    def test_fake_worker_check_conflict_refusal_and_lab_cleanup(self):
        temporary = tempfile.TemporaryDirectory(prefix="perch-stage4-git-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        canon = root / "canon"
        canon.mkdir()
        (canon / "toy").mkdir()
        (canon / "toy" / "mathx.py").write_text('STAGE4_CONFLICT_SLOT = "base"\n', encoding="utf-8")
        (canon / "tests").mkdir()
        (canon / "tests" / "test_mathx.py").write_text("import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(canon), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(canon), "-c", "user.name=perch", "-c", "user.email=perch@localhost",
                        "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(canon), "-c", "user.name=perch", "-c", "user.email=perch@localhost",
                        "commit", "-q", "-m", "base"], check=True)
        lab = root / "labs" / "conflict"
        lab.parent.mkdir()
        subprocess.run(["git", "-C", str(canon), "worktree", "add", "-q", "-b", "lab/conflict", str(lab)], check=True)
        events = root / "worker.jsonl"
        worker_project = HERE / "canary" / "project.json"
        subprocess.run([sys.executable, "-I", str(HERE / "canary" / "fake_worker.py"), "--lab", str(lab),
                        "--task", "canary-stage4-conflict", "--project", str(worker_project), "--events", str(events)],
                       check=True)
        checked = subprocess.run([sys.executable, "-m", "unittest", "discover", "-q", "-s", str(lab / "tests")],
                                 cwd=lab, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        (canon / "toy" / "mathx.py").write_text('STAGE4_CONFLICT_SLOT = "owner"\n', encoding="utf-8")
        subprocess.run(["git", "-C", str(canon), "add", "toy/mathx.py"], check=True)
        subprocess.run(["git", "-C", str(canon), "-c", "user.name=perch", "-c", "user.email=perch@localhost",
                        "commit", "-q", "-m", "concurrent"], check=True)
        merge = subprocess.run(["git", "-C", str(canon), "merge", "--no-ff", "lab/conflict"],
                               capture_output=True, text=True)
        self.assertNotEqual(merge.returncode, 0, merge.stdout + merge.stderr)
        subprocess.run(["git", "-C", str(canon), "merge", "--abort"], check=True)
        self.assertTrue(lab.exists())
        subprocess.run(["git", "-C", str(canon), "worktree", "remove", "--force", str(lab)], check=True)
        subprocess.run(["git", "-C", str(canon), "branch", "-D", "lab/conflict"], check=True,
                       stdout=subprocess.DEVNULL)
        self.assertFalse(lab.exists())


if __name__ == "__main__":
    unittest.main()
