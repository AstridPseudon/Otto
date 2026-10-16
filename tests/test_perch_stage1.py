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


SAVE_DOCUMENT = {"project": {"title": "Canary plan", "outcome": "One creation route"},
                 "tasks": [{"id": "A", "title": "Plan A", "instructions": "Do A", "acceptance": "Done A"}]}


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
                                               "portfolio_args": ["save", path, "--actor", "owner"]})

    def test_save_sent_through_the_owner_socket_is_accepted(self):
        result = self._save("create.json")
        self.assertEqual(result.get("outcome"), "saved", result)
        self.assertFalse(result["dispatch"], result)
        self.assertFalse(result["launch"], result)

    def test_the_save_names_each_task_with_a_typed_ref_as_the_store_holds_it(self):
        # The shape the staging gate reads: a ResourceRef's dict, with its record type under `kind`.
        created = self._save("create.json")
        self.assertEqual(created.get("outcome"), "saved", created)
        self.assertEqual(set(created["task_refs"]), {"A"}, created)
        ref = created["task_refs"]["A"]
        self.assertEqual(set(ref) - {"revision"}, {"authority", "kind", "id"}, ref)
        for key in ("authority", "kind", "id"):
            self.assertTrue(str(ref[key]).strip(), ref)

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
                                     "save", _save_file(self.home, "cold.json", SAVE_DOCUMENT), "--actor", "owner")
        self.assertEqual(code, 0, result)
        self.assertEqual(result.get("outcome"), "saved", result)

    def test_save_with_a_mistyped_portfolio_is_refused_naming_it_and_the_owner_is_untouched(self):
        before = self.owner_service.call(self._store_events)
        code, result = self._ottoctl("portfolio", "--portfolio", "claude-cod-portfolio",
                                     "save", _save_file(self.home, "typo.json", SAVE_DOCUMENT), "--actor", "owner")
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
    "typed": "tasks-are-typed-records",
    "nothing": "nothing-runs",
    "revision": "edit-makes-revision",
    "stale": "stale-save-refused",
    "growth": "store-growth-per-save",
}


def stage_one_run(root):
    """A stage 1 run folder as perch.sh leaves it, green on every assertion."""
    raw = Path(root) / "raw"
    raw.mkdir(parents=True)

    def put(name, value):
        (raw / name).write_text(value if isinstance(value, str) else json.dumps(value, indent=2) + "\n", encoding="utf-8")

    ref = {"authority": "otto-staging-owner-v1", "kind": "wrk.project", "id": "p1"}
    task = {"authority": "otto-staging-owner-v1", "kind": "wrk.assignment", "id": "t1"}
    put("admission.json", {"outcome": "admitted", "host": {"portfolio_ref": dict(ref, id=report.portfolio_id("claude-code"))}})
    put("config.json", {"stage": "1", "fake": True, "tasks": [], "check": "true", "stage_root": "", "pool_limit": 1, "host": "claude-code",
                        "store": {"store_events": 4, "store_tasks": 1, "store_bytes_max": 262144, "rows_per_save_max": 50},
                        "faults": [], "staging_restart": 0, "staging_sha": "x", "canon_main_sha": "x",
                        "started_at": "x", "finished_at": "x"})
    put("notes.json", {"save-through-socket": "ran"})
    put("events.tsv", "")
    put("census.after.txt", "")
    put("leftovers.txt", "")
    put("timeline.json", {"store_events": 4, "error": None, "tasks": [{"task_id": "A", "complete": True, "gaps": [], "events": []}]})
    put("store-at-rest.json", {"error": None, "bytes": 90000, "rows": {"events": 4}})
    put("at-rest.json", {"home_run": ["generation", "service-stop", "service.json"], "service_state": "closed",
                         "sockets": [], "store_holders": {}, "perch_canary": [], "error": None})
    put("save-create.json", {"outcome": "saved", "dispatch": False, "launch": False,
                             "project_ref": dict(ref, revision="rev-2"), "task_refs": {"A": task}})
    put("read-back.json", {"outcome": "read"})
    put("save-edit.json", {"outcome": "saved", "dispatch": False, "launch": False,
                           "project_ref": dict(ref, revision="rev-3"), "task_refs": {"A": task}})
    put("save-stale.json", {"outcome": "conflict", "dispatch": False, "launch": False, "project_ref": dict(ref, revision="rev-3"),
                            "error": {"code": "stale_base"}, "diff": {"project": {}, "tasks": {"changed": []}}})
    put("store-before-saves.json", {"error": None, "rows": {"events": 1}})
    put("store-after-create.json", {"error": None, "rows": {"events": 3}})
    put("store-after-edit.json", {"error": None, "rows": {"events": 4}})
    put("store-after-stale.json", {"error": None, "rows": {"events": 4}})
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


if __name__ == "__main__":
    unittest.main()
