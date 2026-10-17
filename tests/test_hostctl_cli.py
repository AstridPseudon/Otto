"""End-to-end tests for the ``ottoctl`` host command (``otto.hostctl.cli.main``).

Each test builds its own Otto home, run bundle, worktree and fake Claude
launcher inside a ``tempfile`` directory. The real ``claude`` binary is never
run and nothing under the user's real home directories is touched.

One owner service (``OwnerService``, in a thread here) holds the disposable
Store; every ottoctl call below is a client request through the host's lane,
exactly as from another process.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest

from otto.hostctl import cli
from otto.hostctl import config as host_config

FAKE_VERSION = "2.1.293 (Claude Code)"
DRIFTED_VERSION = "2.1.296 (Claude Code)"
OPERATOR = "otto-test-operator"
SANDBOX_SKIP = "admission dry-run runs the macOS sandbox-exec preflight"

TASKLIST = """# Tasklist: demo-run

## Phase 1: build
| id | repo | branch | outcome | deps | route | proof |
|---|---|---|---|---|---|---|
| T1 | demo | feature/setup | **The first:** build it | - | normal | tests pass |

## Phase 2: harden
| id | repo | branch | outcome | deps | route | proof |
|---|---|---|---|---|---|---|
| T2 | demo | release | **The second:** harden it | T1 | **xhard** | review passes |

| id | dispatched | worker |
|---|---|---|
| T1 | 2026-10-10 | w1 |
"""

RUN = {
    "run_id": "demo-run",
    "mode": "setup_awaiting_trigger",
    "activation_trigger": "Operator says go.",
    "roles": {
        "coordinator": {"model": "claude-haiku-5-5"},
        "worker_normal": {"model": "claude-haiku-5-5"},
        "worker_xhard": {"model": "claude-sonnet-5-5"},
    },
    "oracle": {"max_calls": 5},
    "assessment_accounting": {"kind": "owner_local_bookkeeping", "purpose": "task review",
                              "local_only": True, "capacity_units": 1, "cumulative_allowance_units": 1,
                              "task_criterion_pairs": ["T1/C1"]},
    "review_stages": [
        {"id": "RS-1", "max_calls": 2, "scope": "s", "reviewer": "reviewer_xhard"},
        {"id": "RS-F", "max_calls": 1, "repeat_allowance": 1, "scope": "f", "reviewer": "final_reviewer"},
    ],
    "scheduled_checks": [
        {"id": "LOOP-1H", "cadence": "hourly via /loop"},
        {"id": "SC-6H", "cadence": "every 6 h once cooking"},
    ],
}


def _write_bundle(directory: str) -> None:
    texts = {
        "northstar.md": "# Northstar\n\nDemo north star.\n",
        "agent_goal.md": "# Agent goal: demo-run (a demo)\n\n## Objective\n\nShip the demo outcome.\n",
        "plan.md": "# Plan\n\nTwo tasks.\n",
        "status.md": "# Status\n\nAwaiting the trigger.\n",
        "manager-brief.md": "# Manager brief\n\nCoordinate demo-run.\n",
        "tasklist.md": TASKLIST,
    }
    for name, text in texts.items():
        Path(directory, name).write_text(text, encoding="utf-8")
    Path(directory, "run.json").write_text(json.dumps(RUN, indent=2), encoding="utf-8")


def _write_launcher(path: str, version: str) -> None:
    with open(path, "w") as stream:
        stream.write("#!/bin/sh\necho '" + version + "'\n")
    os.chmod(path, 0o755)


def _sha256(path: str) -> str:
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


class HostctlFixture(unittest.TestCase):
    """Temp home, bundle, worktree and fake launcher; helpers only (no tests)."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="hostctl-cli-test-")
        self.addCleanup(tmp.cleanup)
        # realpath: on macOS /var is a symlink, and the Store path check refuses symlinked parents.
        root = os.path.realpath(tmp.name)
        self.home = os.path.join(root, "otto-home")
        self.bundle = os.path.join(root, "projects", "demo-run")
        self.worktree = os.path.join(root, "projects", "worktree")
        self.launcher = os.path.join(root, "bin", "claude-fake")
        os.makedirs(self.bundle)
        os.makedirs(self.worktree)
        os.makedirs(os.path.dirname(self.launcher))
        _write_bundle(self.bundle)
        _write_launcher(self.launcher, FAKE_VERSION)

    # -- helpers -----------------------------------------------------------
    def _ottoctl(self, *args: str):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--home", self.home, *args])
        return code, json.loads(out.getvalue())

    service_adapter_factory = None

    def _init(self):
        """One Otto: install a disposable Store, run its ONE owner service, and have
        the owner admit Claude Code as its own principal (the host is then a client)."""
        code, out = self._ottoctl("install", "--store", self._store_path(), "--authority", "otto-test-owner-v1",
                                  "--owner", "otto-test-owner", "--operator", OPERATOR,
                                  "--credential-ref", "otto-test-owner-credential",
                                  "--create")
        self.assertEqual(code, 0, out)
        self._start_service()
        code, admitted = self._ottoctl("service", "admit-host", "--host", "claude-code", "--launcher", self.launcher)
        self.assertEqual((code, admitted["outcome"]), (0, "admitted"), admitted)
        return out

    def _start_service(self):
        from otto.hostctl.service import OwnerService
        config = host_config.load(Path(self.home))
        self.service_events = queue.Queue()
        self.owner_service = OwnerService(config, adapter_factory=self.service_adapter_factory, poll_seconds=0.02)
        thread = threading.Thread(target=lambda: self.service_events.put(("closed", self.owner_service.run(
            emit=lambda value: self.service_events.put(("emit", value))))), daemon=True)
        thread.start()
        self.service_thread = thread
        kind, ready = self.service_events.get(timeout=60)
        self.assertEqual((kind, ready["outcome"], ready["dues_started"]), ("emit", "ready", 0), ready)
        self.addCleanup(self._stop_service, thread)
        return ready

    def _stop_service(self, thread):
        from otto.hostctl.service import stop_marker
        if not thread.is_alive():
            return
        stop_marker(Path(self.home)).write_text("stop\n")
        thread.join(timeout=60)
        self.assertFalse(thread.is_alive(), "the owner service did not close")

    def _register(self, *extra: str):
        code, out = self._ottoctl("project", "register", "--bundle", self.bundle,
                                  "--worktree", self.worktree, *extra)
        self.assertEqual(code, 0, out)
        return out

    def _activate(self):
        code, out = self._ottoctl("project", "activate", "--project", "demo-run", "--worktree", self.worktree)
        self.assertEqual(code, 0, out)
        return out

    def _ready(self):
        """Installed, joined, registered as a draft, and activated (prepared; nothing started)."""
        self._init()
        self._register()
        return self._activate()

    def _store_path(self) -> str:
        return os.path.join(self.home, "store", "owner.sqlite")

    # -- 1. init -----------------------------------------------------------


class HostctlCliTest(HostctlFixture):
    def test_install_creates_private_installation_and_refuses_a_second_install(self):
        out = self._init()
        self.assertEqual(out["outcome"], "created")
        self.assertFalse(out["provider_called"])
        config_path = os.path.join(self.home, "installation.json")
        self.assertEqual(os.stat(config_path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.home).st_mode & 0o777, 0o700)
        before = _sha256(self._store_path())
        code, out = self._ottoctl("install", "--store", self._store_path(), "--authority", "otto-test-owner-v1",
                                  "--owner", "otto-test-owner", "--operator", OPERATOR,
                                  "--credential-ref", "x", "--create")
        self.assertNotEqual(code, 0)
        self.assertEqual(out["outcome"], "unavailable")
        self.assertEqual(_sha256(self._store_path()), before, "a second install must not touch the Store")
        code, replay = self._ottoctl("service", "admit-host", "--host", "claude-code")
        self.assertEqual((code, replay["outcome"]), (0, "replayed"))

    def test_install_refuses_a_runtime_home_inside_codex_documents(self):
        # Pure check: refused before anything is created, so nothing is written.
        with self.assertRaises(host_config.HostConfigError):
            host_config.new_installation(Path("~/Documents/Codex/otto-test-home"), store_path="/x/owner.sqlite",
                authority="a", owner_actor="o", credential_ref="c", python="/usr/bin/python3")

    def test_repo_map_command_updates_owner_installation(self):
        self._init()
        checkout = os.path.join(os.path.dirname(self.bundle), "checkout")
        code, out = self._ottoctl("repo", "map", "--name", "demo", "--path", checkout)
        self.assertEqual((code, out["outcome"]), (0, "mapped"), out)
        config = host_config.load(Path(self.home))
        self.assertEqual(config["repositories"]["demo"], os.path.abspath(checkout))

    def test_a_second_host_joins_the_same_store_as_its_own_principal(self):
        self._init()
        code, codex = self._ottoctl("service", "admit-host", "--host", "codex", "--principal", "codex-orchestrator")
        self.assertEqual((code, codex["outcome"]), (0, "admitted"), codex)
        for host, principal in (("claude-code", "claude-code-orchestrator"), ("codex", "codex-orchestrator")):
            code, who = self._ottoctl("--host", host, "whoami")
            self.assertEqual((code, who["principal"], who["host"]), (0, principal, host), who)
            self.assertEqual(who["owner"], "otto-test-owner")
        code, ambiguous = self._ottoctl("whoami")
        self.assertEqual(ambiguous["outcome"], "unavailable")

    # -- 2. whoami / effective-context -------------------------------------
    def test_whoami_and_effective_context_are_read_only_orchestrator(self):
        self._init()
        for command in ("whoami", "effective-context"):
            with self.subTest(command=command):
                code, out = self._ottoctl(command)
                self.assertEqual(code, 0, out)
                self.assertEqual(out["outcome"], "read")
                self.assertEqual(out["role"], "orchestrator")
                self.assertEqual(out["principal"], "claude-code-orchestrator")
                self.assertIs(out["native_process_identity_claimed"], False)
                self.assertIs(out["provider_called"], False)

    # -- 3. register --------------------------------------------------------
    def test_register_plan_only_writes_nothing(self):
        self._init()
        code, out = self._ottoctl("project", "register", "--bundle", self.bundle,
                                  "--worktree", self.worktree, "--plan-only")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["outcome"], "plan")
        self.assertIs(out["writes"], False)
        code, listing = self._ottoctl("projects")
        self.assertEqual(listing["projects"], [])
        self.assertFalse(os.path.exists(os.path.join(self.home, "receipts", "register-demo-run.json")))

    def test_register_creates_only_a_draft_and_activation_materializes(self):
        self._init()
        receipt = self._register()
        self.assertEqual((receipt["outcome"], receipt["lifecycle"]), ("registered", "pending"))
        self.assertIs(receipt["dispatch"], False)
        self.assertEqual(receipt["steps"]["registration"]["tasks"], 0)
        code, planned = self._ottoctl("project", "register", "--bundle", self.bundle,
                                      "--worktree", self.worktree, "--plan-only")
        self.assertEqual(code, 0, planned)
        task = next(row for row in planned["plan"]["tasks"] if row["id"] == "T1")
        self.assertEqual(task["custom"]["otto.plan"], {"repo": "demo", "branch": "feature/setup"})
        # Queued in the host's own portfolio: its orchestrator supervises (help routes there).
        enrollment = receipt["steps"]["enrollment"]
        self.assertEqual(enrollment["portfolio_ref"]["id"], "claude-code-portfolio")
        self.assertIsNotNone(enrollment["supervisor_assignment_ref"])
        code, draft = self._ottoctl("project", "status", "--project", "demo-run")
        self.assertEqual((draft["tasks"], draft["schedules"], draft["allowances"]), ([], [], []))
        self.assertEqual(draft["assessment_scope"], RUN["assessment_accounting"])
        self.assertEqual([a["role"] for a in draft["assignments"]], [])
        code, refused = self._ottoctl("admission", "dry-run", "--project", "demo-run")
        self.assertNotEqual(code, 0)

        prepared = self._activate()
        self.assertEqual((prepared["outcome"], prepared["started"]), ("prepared", False))
        steps = prepared["activation"]["steps"]
        self.assertEqual(sorted(steps["tasks"]["task_refs"]), ["T1", "T2"])
        manager = steps["manager"]
        self.assertEqual((manager["principal"], manager["status"]), ("demo-run-manager", "queued"))
        self.assertEqual(steps["orchestrator"]["principal"], "claude-code-orchestrator")
        allowances = {item["id"]: item["cumulative_allowance_units"] for item in steps["allowances"]}
        self.assertEqual(allowances, {"oracle": 5, "rs-1": 2, "rs-f": 2})
        checks = {item["id"]: item for item in steps["orchestrator_checks"]}
        self.assertEqual({k: (v["interval_seconds"], v["host_state"]) for k, v in checks.items()},
                         {"LOOP-1H": (3600, "paused"), "SC-6H": (21600, "paused")})
        setup = prepared["operating_setup"]
        self.assertEqual(setup["outcome"], "applied", setup)
        self.assertIn("manager", setup["setup"]["roles"])

    def test_register_refuses_duplicate_and_activate_replay_changes_nothing(self):
        self._ready()
        _, before = self._ottoctl("project", "status", "--project", "demo-run")
        code, duplicate = self._ottoctl("project", "register", "--bundle", self.bundle,
                                        "--worktree", self.worktree)
        self.assertNotEqual(code, 0, duplicate)
        self.assertIn("already registered", duplicate["error"]["message"])
        again = self._activate()
        self.assertEqual(again["activation"]["steps"]["tasks"]["outcome"], "replayed")
        self.assertEqual(again["operating_setup"]["outcome"], "replayed")
        _, after = self._ottoctl("project", "status", "--project", "demo-run")
        self.assertEqual(after, before)

    # -- 5. project status --------------------------------------------------
    def test_project_status_reads_stored_documents_and_roles(self):
        self._ready()
        code, out = self._ottoctl("project", "status", "--project", "demo-run")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["outcome"], "read")
        self.assertIs(out["provider_called"], False)

        # The onboarding route adds its own brief.md; run file text is read from Otto's records.
        paths = {d["path"] for d in out["documents"]}
        self.assertEqual(paths - {"brief.md"}, {"agent_goal.md", "manager-brief.md", "northstar.md", "plan.md",
                                                "run.json", "status.md", "tasklist.md"})
        for document in out["documents"]:
            self.assertNotIn("registered_raw_sha256", document)
            self.assertNotIn("matches_registered_bytes", document)
            self.assertEqual(len(document["stored_text_sha256"]), 64, document["path"])

        managers = [item for item in out["assignments"] if item["role"] == "manager"]
        self.assertEqual(len(managers), 1)
        self.assertEqual(managers[0]["principal"], "demo-run-manager")
        orchestrators = [item for item in out["assignments"] if item["role"] == "orchestrator"]
        self.assertEqual([item["principal"] for item in orchestrators], ["claude-code-orchestrator"])

        purposes = sorted(row["purpose"] for row in out["schedules"])
        self.assertEqual(purposes, ["orchestrator-check", "orchestrator-check", "role-execution"])
        manager_due = next(row for row in out["schedules"] if row["purpose"] == "role-execution")
        self.assertEqual(manager_due["execution_mode"], "fresh_manager")
        tasks = {task["id"]: task for task in out["tasks"]}
        self.assertEqual(set(tasks), {"T1", "T2"})
        self.assertEqual(tasks["T2"]["route"], "xhard")
        self.assertEqual(tasks["T2"]["depends_on"], 1)
        self.assertEqual((tasks["T1"]["repo"], tasks["T1"]["branch"]), ("demo", "feature/setup"))

    # -- 6. operating-setup ------------------------------------------------
    def test_operating_setup_read_reports_ready_but_not_started(self):
        self._init()
        self._register()
        code, draft = self._ottoctl("operating-setup", "--project", "demo-run")
        self.assertNotEqual(code, 0, "a draft has no roles yet")
        self._activate()
        code, out = self._ottoctl("operating-setup", "--project", "demo-run")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["outcome"], "read")
        self.assertEqual(out["state"], "ready")
        self.assertIs(out["execution_observed"], False)
        self.assertEqual(out["canonical_lifecycle"], "pending")
        self.assertIs(out["adapter_composition"]["ok"], True)
        self.assertIs(out["provider_called"], False)

    # -- 7. admission dry-run ----------------------------------------------
    @unittest.skipUnless(sys.platform == "darwin" and os.path.exists("/usr/bin/sandbox-exec"), SANDBOX_SKIP)
    def test_admission_dry_run_would_admit(self):
        self._ready()
        code, out = self._ottoctl("admission", "dry-run", "--project", "demo-run")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["outcome"], "would_admit")
        self.assertIs(out["checks"]["inert"]["ok"], True)
        admission = out["checks"]["owner_admission"]
        self.assertIs(admission["ok"], True)
        self.assertEqual(admission["conversation_binding_source"], "fresh_manager_first_launch")
        self.assertEqual(admission["execution"]["model"], "claude-haiku-5-5")
        self.assertIs(out["provider_called"], False)

    # -- 8. launcher drift --------------------------------------------------
    @unittest.skipUnless(sys.platform == "darwin" and os.path.exists("/usr/bin/sandbox-exec"), SANDBOX_SKIP)
    def test_launcher_version_drift_blocks_until_qualified(self):
        self._ready()
        _write_launcher(self.launcher, DRIFTED_VERSION)

        code, out = self._ottoctl("admission", "dry-run", "--project", "demo-run")
        self.assertEqual(code, 1, out)
        self.assertEqual(out["outcome"], "blocked")
        self.assertIs(out["checks"]["launcher"]["ok"], False)

        code, out = self._ottoctl("host", "qualify-launcher", "--version", DRIFTED_VERSION, "--evidence", "test")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["outcome"], "recorded")
        self.assertIn(DRIFTED_VERSION, out["qualified_versions"])

        code, out = self._ottoctl("admission", "dry-run", "--project", "demo-run")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["outcome"], "would_admit")

    # -- 9. projects --------------------------------------------------------
    def test_projects_lists_exactly_one_pending_project(self):
        self._ready()
        code, out = self._ottoctl("projects")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["outcome"], "read")
        self.assertEqual(len(out["projects"]), 1)
        project = out["projects"][0]
        self.assertEqual(project["run_id"], "demo-run")
        self.assertEqual(project["lifecycle"], "pending")



class OwnerServiceClientTests(HostctlFixture):
    """ONE owner service holds the Store; a host is only a client of it."""

    def _client(self, home, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--home", home, *args])
        return code, json.loads(out.getvalue())

    def test_a_separate_client_home_names_no_store_and_works_only_through_the_service(self):
        code, out = self._ottoctl("install", "--store", self._store_path(), "--authority", "otto-test-owner-v1",
                                  "--owner", "otto-test-owner", "--operator", OPERATOR,
                                  "--credential-ref", "otto-test-owner-credential",
                                  "--create")
        self.assertEqual(code, 0, out)
        client = os.path.join(os.path.dirname(self.home), "claude-client")
        before = self._client(client, "whoami")
        self.assertEqual((before[0], before[1]["error"]["code"]), (3, "host_unavailable"), before)
        self._start_service()
        code, admitted = self._ottoctl("service", "admit-host", "--host", "claude-code", "--client-home", client,
                                       "--launcher", self.launcher)
        self.assertEqual((code, admitted["outcome"]), (0, "admitted"), admitted)
        self.assertFalse(os.path.exists(os.path.join(client, "installation.json")))
        with open(os.path.join(client, "client.json")) as stream:
            text = stream.read()
        self.assertNotIn("owner.sqlite", text, "a client home must not name the Store")
        self.assertEqual(os.stat(os.path.join(client, "lanes", "claude-code")).st_mode & 0o777, 0o700)

        code, who = self._client(client, "whoami")
        self.assertEqual((code, who["principal"], who["role"]), (0, "claude-code-orchestrator", "orchestrator"), who)
        code, registered = self._client(client, "project", "register", "--bundle", self.bundle,
                                        "--worktree", self.worktree)
        self.assertEqual((code, registered["outcome"], registered["lifecycle"]), (0, "registered", "pending"))

        code, status = self._client(client, "service", "status")
        self.assertEqual((code, status["outcome"], status["busy"]), (0, "running", False), status)
        self.assertEqual(status["holder"]["pid"], os.getpid())
        self.assertEqual((status["generation"], status["as_host"]), (1, "claude-code"))
        self.assertIsNone(status["attached_project"])

        code, busy = self._ottoctl("service", "run")
        self.assertEqual((code, busy["error"]["code"]), (3, "owner_service_running"), busy)

        self._stop_service(self.service_thread)
        code, down = self._client(client, "whoami")
        self.assertEqual((code, down["error"]["code"]), (3, "owner_service_not_running"), down)
        code, status = self._client(client, "service", "status")
        self.assertEqual(status["outcome"], "closed", status)

    def test_a_closed_run_is_kept_as_withdrawn_history_with_its_whole_run_dir(self):
        self._init()
        Path(self.bundle, "run.json").write_text(json.dumps({**RUN, "run_id": "old-run"}))
        os.makedirs(os.path.join(self.bundle, "reviews"))
        Path(self.bundle, "reviews", "final.md").write_text("# Final review\n")
        code, imported = self._ottoctl("project", "import-history", "--bundle", self.bundle,
                                       "--note", "Closed and recut as demo-run r2")
        self.assertEqual((code, imported["outcome"], imported["lifecycle"]), (0, "imported_history", "withdrawn"),
                         imported)
        code, status = self._ottoctl("project", "status", "--project", "old-run")
        self.assertEqual((status["lifecycle"], status["tasks"], status["schedules"]), ("withdrawn", [], []))
        self.assertEqual(status["registration"]["mode"], "history")
        self.assertIn("reviews/final.md", {row["path"] for row in status["documents"]})
        code, replay = self._ottoctl("project", "import-history", "--bundle", self.bundle, "--note", "x")
        self.assertEqual(code, 0, replay)
        self.assertEqual(replay["project_ref"]["id"], imported["project_ref"]["id"])

    def test_nested_run_documents_are_registered_at_their_paths(self):
        os.makedirs(os.path.join(self.bundle, "briefs"))
        Path(self.bundle, "briefs", "T1.md").write_text("# Brief: T1\n\nBuild it.\n")
        Path(self.bundle, "spec.md").write_text("# Spec\n")
        self._init()
        self._register()
        code, status = self._ottoctl("project", "status", "--project", "demo-run")
        paths = {row["path"]: row for row in status["documents"]}
        self.assertIn("briefs/T1.md", paths)
        self.assertEqual(len(paths["briefs/T1.md"]["stored_text_sha256"]), 64)
        self.assertIn("spec.md", paths)


if __name__ == "__main__":
    unittest.main()
