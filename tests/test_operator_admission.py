"""Operator identity and owner-local presence admission over disposable lanes."""
from __future__ import annotations

import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from herzchen.domains.work.admission import task_content_matches
from herzchen.domains.work.admission import TaskNotAdmittedError
from otto.hostctl import cli as host_cli, config as host_config, lanes
from otto.hostctl.owner import HostSession
from otto.hostctl.presence import LocalAuthenticationProver, PresenceResult
from otto.hostctl.service import owner_lane
from otto.portfolio import cli as portfolio_cli
from test_hostctl_cli import HostctlFixture


PORTFOLIO = "claude-code-portfolio"


class OperatorInstallTests(unittest.TestCase):
    def test_unbound_save_still_requires_actor(self):
        with patch("sys.stderr", new_callable=StringIO) as stderr:
            with self.assertRaises(SystemExit) as failure:
                portfolio_cli.build_parser().parse_args(["save", "project.json"])
        self.assertEqual(failure.exception.code, 2)
        self.assertIn("the following arguments are required: --actor", stderr.getvalue())

    def test_install_records_explicit_distinct_operator(self):
        with tempfile.TemporaryDirectory(prefix="operator-install-") as directory:
            home = Path(directory) / "home"
            store = home / "store" / "owner.sqlite"
            args = host_cli.build_parser().parse_args([
                "--home", str(home), "install", "--store", str(store),
                "--authority", "operator-install", "--owner", "service-owner",
                "--operator", "human-operator", "--credential-ref", "test-credential", "--create"])
            host_cli.cmd_install(args)
            self.assertEqual(host_config.load(home)["operator"]["actor"], "human-operator")

    def test_local_authentication_child_timeout_fails_closed(self):
        with patch("otto.hostctl.presence.platform.system", return_value="Darwin"), \
             patch("otto.hostctl.presence.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(["/usr/bin/swift"], 1)):
            self.assertEqual(LocalAuthenticationProver().prove(
                reason="Admit Otto task test at revision abc123", timeout_seconds=1).status, "timeout")


class FakePresence:
    def __init__(self, status="approved"):
        self.status = status
        self.calls = 0
        self.reasons = []

    def prove(self, *, reason, timeout_seconds):
        self.calls += 1
        self.reasons.append(reason)
        return PresenceResult(self.status)


class OperatorAdmissionTests(HostctlFixture):
    def setUp(self):
        super().setUp()
        self.prover = FakePresence()
        self._init()
        self.owner_service.presence_prover = self.prover
        self.operator = host_config.load(Path(self.home))["operator"]["actor"]
        self.registration = self._register()
        self.activation = self._activate()
        self.project_ref = ResourceRef.from_dict(self.registration["project_ref"])
        self.task_ref = ResourceRef.from_dict(
            self.activation["activation"]["steps"]["tasks"]["task_refs"]["T1"])
        self.review_ref = self._owner(lambda session: session.owner.graph.create_effort(
            self.project_ref, title="Operator review", logical_request_key="operator-review",
            actor=session.actor).ref)

    def _owner(self, callback):
        def run():
            config = host_config.load(Path(self.home))
            with HostSession(config, host=config["hosts"]["claude-code"]) as session:
                return callback(session)
        return self.owner_service.call(run)

    def _store_bytes(self):
        path = Path(self._store_path())
        return {item.name: hashlib.sha256(item.read_bytes()).hexdigest()
                for item in path.parent.glob(path.name + "*") if item.is_file()}

    def _admit(self, key="operator-admit", **extra):
        return self._ottoctl("service", "admit", "--task-ref", json.dumps(self.task_ref.to_dict()),
                             "--revision", self.task_ref.revision,
                             "--review-ref", json.dumps(self.review_ref.to_dict()),
                             "--request-key", key)

    def _audit(self):
        path = Path(self.home) / "run" / "operator-admission.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_registered_project_has_operator_creator_host_curator_and_unadmitted_tasks(self):
        def inspect(session):
            project = session.owner.graph.current(self.project_ref)
            task = session.owner.graph.current(self.task_ref)
            assignment = session.owner.assignments.assign(
                ResourceRef(task.ref.authority, task.ref.kind, task.ref.id), role="worker", principal="worker",
                logical_request_key="operator-dispatch", actor=session.actor)
            with self.assertRaises(TaskNotAdmittedError):
                session.owner.assignments.dispatch(assignment, logical_request_key="operator-dispatch-1",
                                                   actor=session.binding.authenticated_actor("worker"))
            return project, task
        project, task = self._owner(inspect)
        self.assertEqual(project.payload["provenance"]["creator"]["actor"], self.operator)
        self.assertEqual(project.payload["provenance"]["curator"]["actor"], "claude-code-orchestrator")
        self.assertNotIn("work.admission", task.payload.get("metadata_namespaces") or {})

    def test_host_created_pending_and_saved_projects_keep_operator_as_creator(self):
        host = "claude-code-orchestrator"
        pending = self._owner(lambda session: session.portfolio.create_pending(
            actor=host, request_id="operator-created-pending",
            edit={"title": "Pending sibling", "outcome": "No admission"}))
        imported = self._owner(lambda session: session.portfolio.import_folder(
            project_json={"title": "Imported sibling", "outcome": "No admission"}, files={},
            actor=host, request_id="operator-imported-folder"))
        save = Path(self.home) / "host-save.json"
        save.write_text(json.dumps({"project": {"title": "Saved sibling", "outcome": "No admission"},
                                    "tasks": [{"id": "t1", "title": "Host plan", "instructions": "Plan",
                                               "acceptance": "Done"}]}))
        code, saved = self._ottoctl("--host", "claude-code", "portfolio", "save", str(save),
                                    "--actor", host)
        self.assertEqual(code, 0, saved)
        owner_save = Path(self.home) / "owner-save.json"
        owner_save.write_text(json.dumps({"project": {"title": "Owner lane sibling", "outcome": "No admission"},
                                          "tasks": []}))
        code, owner_saved = self._ottoctl("portfolio", "--portfolio", PORTFOLIO, "save",
                                          str(owner_save), "--actor", "otto-test-owner")
        self.assertEqual(code, 0, owner_saved)
        for result in (pending, imported, saved):
            project = self._owner(lambda session: session.owner.graph.current(
                ResourceRef.from_dict(result["project_ref"])))
            self.assertEqual(project.payload["provenance"]["creator"]["actor"], self.operator)
            self.assertEqual(project.payload["provenance"]["curator"]["actor"], host)
        owner_project = self._owner(lambda session: session.owner.graph.current(
            ResourceRef.from_dict(owner_saved["project_ref"])))
        self.assertEqual(owner_project.payload["provenance"]["creator"]["actor"], self.operator)
        self.assertEqual(owner_project.payload["provenance"]["curator"]["actor"], "otto-test-owner")
        task_ref = ResourceRef.from_dict(saved["task_refs"]["t1"])
        task = self._owner(lambda session: session.owner.graph.current(task_ref))
        self.assertNotIn("work.admission", task.payload.get("metadata_namespaces") or {})

    def test_bound_save_defaults_actor_and_mismatch_writes_nothing(self):
        save = Path(self.home) / "owner-selector-save.json"
        save.write_text(json.dumps({"project": {"title": "Owner selector", "outcome": "Saved"},
                                    "tasks": []}))
        code, result = self._ottoctl("portfolio", "--portfolio", PORTFOLIO, "save",
                                     str(save))
        self.assertEqual((code, result["outcome"]), (0, "saved"), result)
        project = self._owner(lambda session: session.owner.graph.current(
            ResourceRef.from_dict(result["project_ref"])))
        self.assertEqual(project.payload["provenance"]["creator"]["actor"], self.operator)
        self.assertEqual(project.payload["provenance"]["curator"]["actor"], "otto-test-owner")
        baseline = self._store_bytes()
        code, denied = self._ottoctl("portfolio", "--portfolio", PORTFOLIO, "save",
                                    str(save), "--actor", "owner")
        self.assertNotEqual(code, 0)
        self.assertEqual(denied["error"]["code"], "bound_actor_mismatch")
        self.assertEqual(self._store_bytes(), baseline)

    def test_owner_proves_presence_writes_as_operator_and_logs_once(self):
        code, answer = self._admit()
        self.assertEqual((code, answer["outcome"]), (0, "admitted"), answer)
        state = self._owner(lambda session: session.owner.graph.admission_state(self.task_ref))
        self.assertEqual(state["admitted_revision"], self.task_ref.revision)
        self.assertEqual(state["stamp"]["admitted_by"]["actor"], self.operator)
        def dispatch(session):
            assignment = session.owner.assignments.assign(
                ResourceRef(self.task_ref.authority, self.task_ref.kind, self.task_ref.id), role="worker",
                principal="worker", logical_request_key="operator-dispatch-after", actor=session.actor)
            return session.owner.assignments.dispatch(
                assignment, logical_request_key="operator-dispatch-after-1",
                actor=session.binding.authenticated_actor("worker"))
        self.assertIsNotNone(self._owner(dispatch))
        self.assertEqual(self.prover.calls, 1)
        self.assertEqual(len(self._audit()), 1)
        self.assertEqual({key: self._audit()[0][key] for key in
                          ("task", "revision", "review", "prover_result", "outcome")},
                         {"task": self.task_ref.id, "revision": self.task_ref.revision,
                          "review": self.review_ref.id, "prover_result": "approved", "outcome": "admitted"})

    def test_presence_prompt_names_validated_task_and_revision(self):
        code, answer = self._admit("named-presence-prompt")
        self.assertEqual((code, answer["outcome"]), (0, "admitted"), answer)
        self.assertEqual(self.prover.reasons,
                         [f"Admit Otto task {self.task_ref.id} at revision {self.task_ref.revision[:12]}"])

    def test_unrelated_worker_capacity_does_not_hold_admission_or_change_its_content_pin(self):
        """An owner can admit B while A runs; the metadata stamp preserves A's pin."""
        worker_a = {"running": True, "schedule_id": "worker-a"}
        host = SimpleNamespace(
            _external_waiting=1,
            _capacity_holds=1,
            _executions={"worker-a": worker_a},
            _status_read=lambda _request, operation: operation(),
        )
        self.owner_service.journeys["project-a"] = SimpleNamespace(
            execution_host=host, run_id="project-a")
        previous_project = getattr(self.owner_service._dispatch_context, "project_id", None)
        self.owner_service._dispatch_context.project_id = "project-a"

        def pin_matches(session):
            current = session.owner.graph.current(ResourceRef(
                self.task_ref.authority, self.task_ref.kind, self.task_ref.id))
            return task_content_matches(session.owner.store, self.task_ref, current.payload,
                                        current_ref=current.ref)

        try:
            self.assertTrue(self._owner(pin_matches))
            request = {"command": "admit", "args": {
                "task_ref": self.task_ref.to_dict(), "revision": self.task_ref.revision,
                "review_ref": self.review_ref.to_dict(), "request_key": "admit-during-worker"}}
            answer = self.owner_service._owner_command("owner", request, "admit-token", Path(self.home))
            self.assertEqual(answer["outcome"], "admitted", answer)
            self.assertEqual(host._capacity_holds, 1, "admission released the unrelated worker's capacity")
            self.assertIs(host._executions["worker-a"], worker_a)
            self.assertTrue(worker_a["running"], "admission interrupted the unrelated worker")
            self.assertEqual(self.prover.calls, 1)
            self.assertTrue(self._owner(pin_matches), "metadata-only admission invalidated the running task pin")
        finally:
            self.owner_service.journeys.pop("project-a", None)
            self.owner_service._dispatch_context.project_id = previous_project

    def _submit_while_dispatching(self, *, request_key, status="approved"):
        """Exercise the owner lane while an attached execution host is waiting."""
        from otto.hostctl.service import owner_lane
        host = SimpleNamespace(_external_waiting=1, begin_drain=lambda: None, close=lambda: None)
        self.owner_service.journeys["dispatching-project"] = SimpleNamespace(
            execution_host=host, run_id="dispatching-project", state={"manager": "test"},
            paths={"ipc": Path(self.home) / "ipc", "socket": Path(self.home) / "socket"})
        self.prover.status = status
        request = {"command": "admit", "args": {
            "task_ref": self.task_ref.to_dict(), "revision": self.task_ref.revision,
            "review_ref": self.review_ref.to_dict(), "request_key": request_key}}
        lane = owner_lane(Path(self.home))
        token = lanes.submit(lane, request)
        # The request remains pending, with no presence prompt or audit entry,
        # for the whole open dispatch boundary.
        import time
        time.sleep(0.15)
        self.assertTrue((lane / ("request-" + token + ".json")).exists())
        self.assertEqual(self.prover.calls, 0)
        self.assertEqual(self._audit(), [])
        host._external_waiting = 0
        reply = lanes.wait(lane, token, timeout_seconds=10)
        self.owner_service.journeys.pop("dispatching-project")
        return reply

    def test_admission_waits_for_dispatch_then_checks_presence_and_applies_once(self):
        reply = self._submit_while_dispatching(request_key="same-held-admission")
        self.assertEqual(reply["outcome"], "admitted", reply)
        state = self._owner(lambda session: session.owner.graph.admission_state(self.task_ref))
        self.assertEqual(state["admitted_revision"], self.task_ref.revision)
        self.assertEqual(state["stamp"]["admitted_by"]["actor"], self.operator)
        self.assertEqual(self.prover.calls, 1)
        self.assertEqual(len(self._audit()), 1)
        self.assertEqual(self._audit()[0]["outcome"], "admitted")

    def test_admission_declined_after_dispatch_wait_leaves_store_unchanged(self):
        baseline = self._store_bytes()
        reply = self._submit_while_dispatching(request_key="declined-held-admission", status="declined")
        self.assertEqual(reply["error"]["code"], "presence_declined", reply)
        self.assertEqual(self.prover.calls, 1)
        self.assertEqual(self._store_bytes(), baseline)
        self.assertEqual(len(self._audit()), 1)
        self.assertEqual(self._audit()[0]["outcome"], "rejected")

    def test_decline_missing_prover_and_timeout_leave_store_byte_identical(self):
        baseline = self._store_bytes()
        for index, status in enumerate(("declined", "unavailable", "timeout")):
            self.owner_service.presence_prover = None if status == "unavailable" else self.prover
            self.prover.status = status
            code, answer = self._admit("refused-" + status)
            self.assertNotEqual(code, 0, answer)
            self.assertEqual(answer["error"]["code"], "presence_" + status)
            self.assertEqual(self._store_bytes(), baseline)
            self.assertIsNone(self._owner(lambda session: session.owner.graph.admission_state(self.task_ref)["admitted_revision"]))
        self.assertEqual([row["prover_result"] for row in self._audit()],
                         ["declined", "unavailable", "timeout"])

    def test_agent_actor_selection_and_forged_presence_are_refused_without_store_writes(self):
        baseline = self._store_bytes()
        save = Path(self.home) / "forged-save.json"
        save.write_text(json.dumps({"project": {"title": "Forged", "outcome": ""}, "tasks": []}))
        requests = (
            ("--host", "claude-code", "portfolio", "admit", "--task-ref", json.dumps(self.task_ref.to_dict()),
             "--revision", self.task_ref.revision, "--review-ref", json.dumps(self.review_ref.to_dict()),
             "--request-key", "host-admit"),
            ("--host", "claude-code", "portfolio", "save", str(save), "--actor", self.operator),
            ("--host", "claude-code", "portfolio", "save", str(save), "--actor", "owner"),
            ("portfolio", "--portfolio", PORTFOLIO, "save", str(save), "--actor", self.operator),
        )
        for request in requests:
            code, answer = self._ottoctl(*request)
            self.assertNotEqual(code, 0, answer)
            self.assertEqual(self._store_bytes(), baseline)
        forged = {"command": "admit", "args": {
            "task_ref": self.task_ref.to_dict(), "revision": self.task_ref.revision,
            "review_ref": self.review_ref.to_dict(), "request_key": "forged-presence",
            "presence": "approved"}}
        lane = owner_lane(Path(self.home))
        token = lanes.submit(lane, forged)
        reply = lanes.wait(lane, token, timeout_seconds=10)
        self.assertEqual(reply["error"]["code"], "PermissionError", reply)
        self.assertEqual(self.prover.calls, 0)
        self.assertEqual(self._store_bytes(), baseline)

    def test_operator_must_differ_from_owner_and_host_principals(self):
        with self.assertRaises(host_config.HostConfigError):
            host_config.new_installation(Path(self.home), store_path=self._store_path(),
                authority="owner", owner_actor="same", operator_actor="same", credential_ref="credential",
                python="/usr/bin/python3")
        before = Path(self.home, "installation.json").read_bytes()
        code, answer = self._ottoctl("service", "admit-host", "--host", "codex", "--principal", self.operator)
        self.assertNotEqual(code, 0, answer)
        self.assertEqual(Path(self.home, "installation.json").read_bytes(), before)

    def test_worker_facade_cannot_admit_a_task(self):
        before = self._store_bytes()
        answer = self._owner(lambda session: session.portfolio.operations.execute(
            "work.task.admit", {"task_ref": self.task_ref.to_dict(),
                                "revision": self.task_ref.revision,
                                "review_ref": self.review_ref.to_dict()},
            request_id="worker-forged-admit", actor=session.host_principal()))
        self.assertEqual(answer["outcome"], "unavailable", answer)
        self.assertEqual(self._store_bytes(), before)

    def test_forged_manager_lane_admit_has_no_task_admission(self):
        before = self._store_bytes()
        host_lane = Path(host_config.load(Path(self.home))["hosts"]["claude-code"]["lane"])
        body = {"schema": lanes.REQUEST_SCHEMA, "command": "manager", "sub": None,
                "args": {"project": "demo-run", "request": {"command": "admit",
                    "task_ref": self.task_ref.to_dict(), "revision": self.task_ref.revision,
                    "review_ref": self.review_ref.to_dict(), "request_key": "manager-forged-admit"}}}
        token = lanes.submit(host_lane, body)
        reply = lanes.wait(host_lane, token, timeout_seconds=20)
        self.assertNotEqual(reply.get("outcome"), "admitted", reply)
        state = self._owner(lambda session: session.owner.graph.admission_state(self.task_ref))
        self.assertIsNone(state["admitted_revision"])
        self.assertEqual(self._store_bytes(), before)

    @unittest.skipUnless(os.environ.get("OTTO_REAL_MAC_PROBE") == "1", "opt-in real macOS owner-lane probe")
    def test_unattended_real_mac_owner_lane_refuses_admit(self):
        self.owner_service.presence_prover = LocalAuthenticationProver()
        before = self._store_bytes()
        code, answer = self._admit("real-mac-unattended")
        self.assertNotEqual(code, 0, answer)
        self.assertEqual(self._store_bytes(), before)
        if answer.get("error", {}).get("code") == "presence_unavailable":
            self.skipTest("LocalAuthentication policy unavailable to this agent session")
        self.assertEqual(answer["error"]["code"], "presence_timeout", answer)
