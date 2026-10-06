"""S03: real owner Store, ManagerApplication, IssueLoop and retained file host.

Only the native provider is substituted. No live owner/controller is mutated.
"""
from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import unittest

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.domains.work import WorkGraph
from otto.portfolio.execution_host import ExecutionHost, _nested_capability
from otto.portfolio.help_delivery import BoundHelpDelivery, ExecutionHelpDelivery
from otto.portfolio.issue_loop import IssueLoopError
from otto.portfolio.manager_journey_service import ManagerJourneyService, install_manager_journey_service
from otto.portfolio.owner_issue_loop import OwnerIssueReaders
from tests import test_execution_application as owner_fixture


class HelpRoutingTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_fixture.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        f = self.f
        self.manager, guide, mandate = f.role_handles("manager", "manager", "manager-session")
        self.supervisor, self.supervisor_guide, self.supervisor_mandate = f.role_handles("orchestrator", "root", "root-session")
        self.binding = {"project_ref": f.project.ref.to_dict(), "assignment_ref": self.supervisor.ref.to_dict(),
                        "generation": self.supervisor.generation, "principal": "root",
                        "conversation_ref": {"host": "codex", "native_id": "root-session"}}
        self.readers = OwnerIssueReaders(f.owner.consumer_operations(), f.port)
        self.delivery = BoundHelpDelivery(readers=self.readers, interim_supervision=self.binding)
        self.manager_app = f.owner.manager_application(due_port=f.port, issue_delivery=self.delivery)
        self.portfolio = self.manager_app.portfolio
        self.loop = self.portfolio._issue_loop()
        # Bind the same production composition to manager execution readiness.
        f.app.portfolio = f.app.runtime.portfolio = self.portfolio
        prepared = f.app.prepare_role(role="manager", project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            assignment_ref=self.manager.ref.to_dict(), generation=1, mandate_ref=mandate, context_refs=(guide, mandate),
            request_key="help-manager", instruction="Advance project", model="gpt-test", reasoning="high",
            profile="workspace-write", native_session_id="manager-session")
        self.anchor = prepared["schedule_id"]
        setup = {"schema": "otto.operating-setup.v1", "mode": "manual", "roles": {"manager": self.anchor},
                 "advisor_policy": {"mode": "disabled", "reason": "No advisor campaign authorized"}, "acceptance_tasks": []}
        result = f.app.prepare_operating_setup(project_ref=f.project.ref.to_dict(), setup=setup, request_key="help-setup")
        self.assertEqual(result["outcome"], "prepared", result)
        self.state = {"authority": f.actor.authority, "owner": "manager", "manager": "manager",
            "assignment_ref": self.manager.ref.to_dict(), "manager_generation": 1,
            "project_ref": f.project.ref.to_dict(), "task_refs": {"S03": f.task.ref.to_dict()},
            "schedule_id": self.anchor, "requested_model": "gpt-test", "requested_reasoning": "high"}
        self.server = SimpleNamespace(owner=f.owner, portfolio=self.portfolio, state=self.state, due_port=f.port,
            _execution=lambda **_: f.app, _save_state=lambda: None, handle=lambda r: {"outcome": "unsupported"})
        self.directory = Path(f.temporary.name) / "help-ipc"
        self.host = ExecutionHost(directory=self.directory, handler=self.server.handle)
        self.server.execution_host = self.host
        self.service = self.install_service(lambda _: f.binding.authenticated_actor("root"))

    def install_service(self, authorizer=None):
        service = install_manager_journey_service(self.server,
            run_path=self.f.temporary.name, workspace=self.f.temporary.name,
            orchestrator_principal="root", help_reply_authorizer=authorizer)
        self.assertIsInstance(service, ManagerJourneyService)
        self.assertIs(self.server.execution_host, self.host)
        self.assertIs(service.host, self.host)
        self.assertIs(self.host.handler, service)
        return service

    def effects(self):
        return (self.readers.reports(self.f.project.ref.to_dict()),
                self.f.port.list_due(), self.f.provider.calls[:],
                sorted(path.name for path in self.directory.glob("request-*.json")))

    def request(self, **updates):
        return {"command": "request-help", "request_key": "help-request", "issue_key": "dispatch-blocked",
            "problem": "Required worker route is unavailable", "impact": "This operation is held",
            "evidence": [{"operation": "run-worker", "outcome": "held"}],
            "requested_decision": "Bind the supported worker route", "return_condition": "Worker route verifies", **updates}

    def reply(self, issue_id, **updates):
        return {"command": "respond-help", "issue_id": issue_id, "request_key": "root-reply",
            "authority_source": "Owner adopted binding", "response": "Route corrected",
            "proposed_solution": "Use the current worker route", "next_action": "Inspect then continue ready work", **updates}

    def send(self, token, request):
        self.directory.mkdir(exist_ok=True)
        (self.directory / ("request-" + token + ".json")).write_text(json.dumps(request))
        return self.directory / ("response-" + token + ".json")

    def wait_response(self, path):
        deadline = time.monotonic() + 10
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(path.exists(), str(path))
        return json.loads(path.read_text())

    def test_manager_application_cli_has_real_issue_ports_and_no_actor_override(self):
        f = self.f
        request = self.request()
        argv = ["request-help", "--actor", "manager", "--project-ref", json.dumps(f.project.ref.to_dict()),
                "--assignment-ref", json.dumps(self.manager.ref.to_dict()), "--generation", "1"]
        for field, value in request.items():
            if field != "command":
                argv.extend(["--" + field.replace("_", "-"), json.dumps(value) if field == "evidence" else value])
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.manager_app.run(argv)
        result = json.loads(out.getvalue())
        self.assertEqual(result["outcome"], "submitted", result)
        self.assertEqual(result["delivery"]["receipt"]["conversation_id"], "root-session")
        out = io.StringIO()
        with redirect_stdout(out):
            self.manager_app.run(["read-help", "--actor", "root", "--project-ref", json.dumps(f.project.ref.to_dict())])
        self.assertEqual(json.loads(out.getvalue())["outcome"], "denied")
        self.assertEqual(f.provider.calls, [])

    def test_manual_destination_delivered_in_manager_packet_and_truthful_pending(self):
        result = self.service(self.request())
        self.assertEqual(result["delivery"]["state"], "pending")
        self.assertFalse(result["delivery"]["receipt"]["notification_sent"])
        self.assertEqual(result["resolution"], "open")
        self.assertEqual(self.service({"command": "read-help"})["issues"][0]["awaiting"], "orchestrator")
        started = self.f.app.start(schedule_id=self.anchor)
        self.assertEqual(started["outcome"], "succeeded", started)
        prompt = self.f.provider.calls[-1]
        self.assertIn("root-session", prompt)
        self.assertIn("receipt-inspection", prompt)
        self.assertIn("No advisor campaign authorized", prompt)
        decision = self.f.app.read_operating_setup(project_ref=self.f.project.ref.to_dict())
        self.assertFalse(decision["autonomous_ready"])
        self.assertFalse(decision["capabilities"]["operational_help_delivery"])

    def test_disabled_advice_has_no_reports_sends_or_allowance_effect(self):
        before = self.readers.reports(self.f.project.ref.to_dict())
        with self.assertRaisesRegex(IssueLoopError, "advisor_disabled"):
            self.service(self.request(command="request-advice"))
        self.assertEqual(self.readers.reports(self.f.project.ref.to_dict()), before)
        self.assertEqual(self.f.provider.calls, [])

    def test_duplicate_unknown_delivery_never_resends(self):
        calls = []
        def unknown(intent):
            calls.append(intent)
            raise TimeoutError("reply lost after send")
        self.delivery.sender = unknown
        first = self.service(self.request())
        second = self.service(self.request())
        self.assertEqual(first["delivery"]["state"], "unknown")
        self.assertEqual(second["delivery"]["delivery_id"], first["delivery"]["delivery_id"])
        self.assertEqual(len(calls), 1)
        read = self.service({"command": "read-help", "delivery_id": first["delivery"]["delivery_id"]})
        self.assertFalse(read["retry"])
        self.assertEqual(len(calls), 1)
        with self.assertRaisesRegex(IssueLoopError, "changed issue input"):
            self.service(self.request(problem="Different problem"))

    def test_bound_sender_receives_exact_current_conversation_and_sent_is_not_resolved(self):
        calls = []
        def send(intent):
            calls.append(intent)
            return {"state": "sent", "transport": "exact-host", "receipt": {"native_id": intent["recipient_conversation"]}}
        self.delivery.sender = send
        result = self.service(self.request())
        self.assertEqual(result["delivery"]["state"], "sent")
        self.assertEqual(result["resolution"], "open")
        self.assertEqual(calls[0]["recipient_assignment_ref"], self.supervisor.ref.to_dict())
        self.assertEqual(calls[0]["recipient_generation"], 1)
        self.assertEqual(calls[0]["recipient_conversation"], "root-session")
        self.service(self.request())
        self.assertEqual(len(calls), 1)

    def test_missing_recipient_is_reported_unresolved_not_delivered(self):
        self.loop.ports = replace(self.loop.ports, current_supervisor=lambda _: None)
        result = self.service(self.request())
        self.assertEqual(result["routing"]["state"], "unresolved")
        self.assertEqual(result["delivery"]["transport"], "unsupported")
        self.assertIsNone(result["recipient_assignment_ref"])

    def test_stale_interim_conversation_rejects_readiness_and_never_sends(self):
        self.delivery.interim["conversation_ref"]["native_id"] = "unbound-name"
        with self.assertRaisesRegex(IssueLoopError, "stale"):
            self.delivery.current_supervisor(self.f.project.ref.to_dict())
        before = self.f.provider.calls[:]
        result = self.f.app.start(schedule_id=self.anchor)
        self.assertIn(result["outcome"], {"partial", "blocked"})
        self.assertEqual(self.f.provider.calls, before)

    def test_reply_and_application_use_retained_automatic_same_manager_continuations(self):
        self.assertEqual(self.f.app.start(schedule_id=self.anchor)["outcome"], "succeeded")
        self.host.start()
        self.addCleanup(self.host.close)
        requested = self.wait_response(self.send("a1", self.request()))
        reply = self.wait_response(self.send("a2", self.reply(requested["issue_id"])))
        callback = self.wait_response(Path(reply["continuation"]["response_path"]))
        self.assertEqual(callback["outcome"], "succeeded", callback)
        self.assertEqual(callback["result"]["physical_session_id"], "manager-session")
        self.assertEqual(len(self.f.provider.calls), 2)
        self.assertEqual(self.service({"command": "read-help"})["issues"][0]["state"], "open")
        resolve = {"command": "resolve-help", "issue_id": requested["issue_id"], "request_key": "apply-root-reply",
            "evidence": [{"worker_route": "verified"}], "next_action": "Delegate the remaining work"}
        applied = self.wait_response(self.send("a3", resolve))
        continued = self.wait_response(Path(applied["continuation"]["response_path"]))
        self.assertEqual(continued["outcome"], "succeeded", continued)
        self.assertEqual(len(self.f.provider.calls), 3)
        self.assertEqual(self.service({"command": "read-help"})["issues"][0]["state"], "resolved")
        replay = self.wait_response(self.send("a4", resolve))
        self.assertIn(self.wait_response(Path(replay["continuation"]["response_path"]))["outcome"], {"succeeded", "replayed"})
        self.assertEqual(len(self.f.provider.calls), 3)

    def test_request_and_reply_do_not_wait_behind_requester_native_turn(self):
        self.f.provider.work_started, self.f.provider.work_release = threading.Event(), threading.Event()
        self.addCleanup(self.f.provider.work_release.set)
        def handler(request):
            if request["command"] == "start-manager":
                return self.f.app.start(schedule_id=self.anchor)
            return self.service(request)
        self.host.handler = handler
        self.host.start()
        self.addCleanup(self.host.close)
        started = self.send("b1", {"command": "start-manager"})
        self.assertTrue(self.f.provider.work_started.wait(3))
        requested = self.wait_response(self.send("b2", self.request()))
        reply = self.wait_response(self.send("b3", self.reply(requested["issue_id"])))
        self.assertFalse(started.exists())
        self.assertFalse(Path(reply["continuation"]["response_path"]).exists())
        self.assertEqual(len(self.f.provider.calls), 1)
        self.f.provider.work_release.set()
        self.assertEqual(self.wait_response(started)["outcome"], "succeeded")
        self.assertEqual(self.wait_response(Path(reply["continuation"]["response_path"]))["outcome"], "succeeded")
        self.assertEqual(len(self.f.provider.calls), 2)
        self.assertEqual(_nested_capability({"command": "request-help"}), "admitted")
        self.assertEqual(_nested_capability({"command": "manager-help-result"}), "retained")

    def test_unknown_manager_effect_blocks_continuation_and_remains_immutable(self):
        request = self.service(self.request())
        reply = self.portfolio.respond_to_issue(project_ref=self.f.project.ref.to_dict(), actor="root",
            **{k: v for k, v in self.reply(request["issue_id"]).items() if k not in {"command", "request_key"}}, request_id="reply-direct")
        self.f.provider.unknown = True
        self.assertEqual(self.f.app.start(schedule_id=self.anchor)["outcome"], "unknown")
        before = self.f.port.read_due(self.anchor)
        result = self.f.app.continue_manager_from_help(manager_schedule_id=self.anchor, report_ref=reply["report_ref"], execute=True)
        self.assertEqual(result["outcome"], "held")
        self.assertFalse(result["retry"])
        self.assertEqual(self.f.port.read_due(self.anchor), before)
        self.assertEqual(len(self.f.provider.calls), 1)

    def test_enabled_advice_reuses_pairing_and_preserves_suggestion_authority(self):
        from herzchen.kernel.limits import LimitService
        from otto.portfolio.operating_setup import setup_reference
        from otto.portfolio.tests import test_role_context
        f = self.f
        advisor, guide, mandate = f.role_handles("project_advisor", "advisor", "advisor-session")
        prepared = f.app.prepare_role(role="project_advisor", project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            assignment_ref=advisor.ref.to_dict(), generation=1, mandate_ref=mandate, context_refs=(guide, mandate),
            request_key="advice-role", instruction="Inspect consequential uncertainty", model="gpt-test", reasoning="high",
            profile="read-only", native_session_id="advisor-session")
        pool = LimitService(f.store).create_pool(ResourceRef(f.actor.authority, "limit", "advice-allowance"),
            capacity_units=1, cumulative_allowance_units=2, logical_request_key="advice-allowance", actor=f.actor)
        due = f.app._read(prepared["schedule_id"])
        f.port.save_due(due.schedule_id, replace(due, allowance_ref=pool.ref.to_dict()).to_dict(),
            request_id="advice-allowance-binding", expected_version=due.version)
        ref = setup_reference(f.project.ref.to_dict())
        document = f.owner.content.read(ref)
        revise = test_role_context.RoleContextTests()
        revise.f, revise.number = f, 0
        revise.revise(document["current_revision"], {**document["revision"]["content"],
            "roles": {"manager": self.anchor, "project_advisor": due.schedule_id}, "advisor_policy": {"mode": "enabled"}})
        calls = []
        self.delivery.sender = lambda intent: calls.append(intent) or {"state": "sent", "receipt": {"native_id": intent["recipient_conversation"]}}
        before = LimitService(f.store).get_pool(pool.ref)
        advice = self.service(self.request(command="request-advice"))
        help_request = self.service(self.request(request_key="separate-help"))
        self.assertNotEqual(advice["issue_id"], help_request["issue_id"])
        self.assertEqual(advice["purpose"], "advice")
        self.assertEqual(calls[0]["recipient_assignment_ref"], advisor.ref.to_dict())
        self.assertEqual(calls[0]["recipient_conversation"], "advisor-session")
        fields = {k: v for k, v in self.reply(advice["issue_id"]).items() if k not in {"command", "request_key"}}
        with self.assertRaisesRegex(IssueLoopError, "current issue recipient"):
            self.portfolio.respond_to_issue(project_ref=f.project.ref.to_dict(), actor="root", request_id="wrong-reply", **fields)
        with self.assertRaisesRegex(IssueLoopError, "suggestions"):
            self.portfolio.respond_to_issue(project_ref=f.project.ref.to_dict(), actor="advisor", request_id="bad-authority", user_decision="must stop", **fields)
        reply = self.portfolio.respond_to_issue(project_ref=f.project.ref.to_dict(), actor="advisor", request_id="advisor-reply", **fields)
        report = next(r for r in self.readers.reports(f.project.ref.to_dict()) if r["ref"] == reply["report_ref"])
        self.assertEqual(report["value"]["authority_kind"], "suggestion")
        self.assertEqual(LimitService(f.store).get_pool(pool.ref), before)
        self.assertEqual(f.provider.calls, [])

    def test_retained_reply_cannot_be_applied_or_resumed_after_supervisor_replacement(self):
        requested = self.service(self.request())
        fields = {k: v for k, v in self.reply(requested["issue_id"]).items() if k not in {"command", "request_key"}}
        reply = self.portfolio.respond_to_issue(project_ref=self.f.project.ref.to_dict(), actor="root", request_id="reply", **fields)
        self.f.app.assignments.reassign(self.supervisor.ref, principal="replacement", session="replacement-session",
            expected_generation=1, logical_request_key="replace-supervisor", actor=self.f.actor)
        with self.assertRaisesRegex(IssueLoopError, "stale"):
            self.portfolio.resolve_help(project_ref=self.f.project.ref.to_dict(), assignment_ref=self.manager.ref.to_dict(),
                generation=1, actor="manager", issue_id=requested["issue_id"], evidence=["checked"], request_id="apply-stale")
        with self.assertRaisesRegex(IssueLoopError, "stale"):
            self.f.app.continue_manager_from_help(manager_schedule_id=self.anchor, report_ref=reply["report_ref"], execute=True)
        self.assertEqual(self.f.provider.calls, [])

    def test_foreign_project_help_read_and_routing_overrides_are_rejected(self):
        foreign = WorkGraph(self.f.store, actor=self.f.actor).create_project(title="Other project", logical_request_key="foreign")
        with self.assertRaisesRegex(IssueLoopError, "project grant"):
            self.portfolio.read_issues(project_ref=foreign.ref.to_dict())
        for update in ({"actor": "root"}, {"project_ref": foreign.ref.to_dict()}, {"recipient": "root"}):
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, "no routing overrides"):
                self.service(self.request(**update))

    def test_committed_intent_without_receipt_is_unknown_and_not_resent(self):
        sends = []
        self.delivery.sender = lambda intent: sends.append(intent) or {"state": "sent", "receipt": {"ok": True}}
        original = self.loop._append
        def lose_receipt(assignment, body, **values):
            if body.get("state") == "sent":
                raise RuntimeError("lost result persistence")
            return original(assignment, body, **values)
        self.loop._append = lose_receipt
        with self.assertRaisesRegex(RuntimeError, "lost result persistence"):
            self.service(self.request())
        self.loop._append = original
        replay = self.service(self.request())
        self.assertEqual(replay["delivery"]["state"], "unknown")
        self.assertEqual(len(sends), 1)

    def test_manager_transport_cannot_impersonate_supervisor_reply(self):
        requested = self.service(self.request())
        self.service.help_reply_authorizer = None
        with self.assertRaisesRegex(PermissionError, "authenticated recipient reply port"):
            self.service(self.reply(requested["issue_id"]))
        self.assertEqual(self.service({"command": "read-help"})["issues"][0]["awaiting"], "orchestrator")

    def test_installer_without_reply_port_rejects_file_ipc_response_before_effects(self):
        self.service = self.install_service()
        self.host.start()
        self.addCleanup(self.host.close)
        requested = self.wait_response(self.send("d1", self.request()))
        before = self.effects()[:3]
        result = self.wait_response(self.send("d2", self.reply(requested["issue_id"])))
        self.assertEqual(result["outcome"], "error", result)
        self.assertIn("authenticated recipient reply port", result["message"])
        self.assertEqual(self.effects()[:3], before)
        self.assertFalse(any(json.loads(path.read_text()).get("command") == "manager-help-result"
                             for path in self.directory.glob("request-*.json")))

    def test_installed_reply_rejects_foreign_authentication_and_wrong_actor_without_effects(self):
        requested = self.service(self.request())
        binding = self.f.binding
        for responder, error, message in (
                ({"actor": "root"}, PermissionError, "owner-issued recipient authentication"),
                (AuthenticatedActor("foreign", "root", binding.credential_ref), PermissionError,
                 "owner-issued recipient authentication"),
                (AuthenticatedActor(binding.authority, "root", "foreign-credential"), PermissionError,
                 "owner-issued recipient authentication"),
                (binding.authenticated_actor("manager"), IssueLoopError, "current issue recipient")):
            with self.subTest(responder=responder):
                self.service = self.install_service(lambda _, responder=responder: responder)
                before = self.effects()
                with self.assertRaisesRegex(error, message):
                    self.service(self.reply(requested["issue_id"]))
                self.assertEqual(self.effects(), before)

    def test_installed_reply_rejects_identity_overrides_before_authentication(self):
        requested = self.service(self.request())
        authenticated = []
        self.service = self.install_service(lambda request: authenticated.append(request)
                                            or self.f.binding.authenticated_actor("root"))
        for override in ({"actor": "root"}, {"recipient": "root"},
                         {"project_ref": self.f.project.ref.to_dict()}):
            with self.subTest(override=override):
                before = self.effects()
                with self.assertRaisesRegex(ValueError, "cannot choose its own actor or recipient"):
                    self.service(self.reply(requested["issue_id"], **override))
                self.assertEqual(self.effects(), before)
        self.assertEqual(authenticated, [])

    def test_installed_reply_rejects_same_principal_stale_supervisor_generation(self):
        requested = self.service(self.request())
        self.f.app.assignments.reassign(self.supervisor.ref, principal="root", session="root-session",
            expected_generation=1, logical_request_key="same-principal-supervisor", actor=self.f.actor)
        before = self.effects()
        with self.assertRaisesRegex(IssueLoopError, "stale"):
            self.service(self.reply(requested["issue_id"]))
        self.assertEqual(self.effects(), before)

    def test_installed_reply_rejects_stale_manager_before_authentication_or_effects(self):
        requested = self.service(self.request())
        authenticated = []
        self.service = self.install_service(lambda request: authenticated.append(request)
                                            or self.f.binding.authenticated_actor("root"))
        self.f.app.assignments.reassign(self.manager.ref, principal="manager", session="manager-session",
            expected_generation=1, logical_request_key="same-principal-manager", actor=self.f.actor)
        before = self.effects()
        with self.assertRaisesRegex(PermissionError, "current bound manager"):
            self.service(self.reply(requested["issue_id"]))
        self.assertEqual(self.effects(), before)
        self.assertEqual(authenticated, [])

    def test_installed_reply_rejects_missing_recipient_without_effects(self):
        requested = self.service(self.request())
        self.loop.ports = replace(self.loop.ports, current_supervisor=lambda _: None)
        before = self.effects()
        with self.assertRaisesRegex(IssueLoopError, "current issue recipient"):
            self.service(self.reply(requested["issue_id"]))
        self.assertEqual(self.effects(), before)

    def test_duplicate_issue_with_another_request_key_reports_original_delivery(self):
        calls = []
        self.delivery.sender = lambda intent: calls.append(intent) or {"state": "sent", "receipt": {"native_id": "root-session"}}
        first = self.service(self.request())
        duplicate = self.service(self.request(request_key="duplicate-intent"))
        self.assertEqual(duplicate["outcome"], "existing")
        self.assertEqual(duplicate["report_ref"], first["report_ref"])
        self.assertEqual(duplicate["delivery"]["state"], "sent")
        self.assertEqual(len(calls), 1)

    def test_supervisor_user_only_response_replays_without_manager_delivery(self):
        issue = self.service(self.request())
        fields = {k: v for k, v in self.reply(issue["issue_id"]).items() if k not in {"command", "request_key"}}
        request = {"project_ref": self.f.project.ref.to_dict(), "actor": "root", "request_id": "user-only",
                   "user_decision": "Owner must choose a new permitted route", **fields}
        first = self.portfolio.respond_to_issue(**request)
        second = self.portfolio.respond_to_issue(**request)
        self.assertEqual(second["outcome"], "awaiting_user")
        self.assertEqual(second["report_ref"], first["report_ref"])
        self.assertEqual(self.f.provider.calls, [])

    def test_automatic_help_uses_retained_role_execution_and_real_native_readback(self):
        from otto.portfolio.operating_setup import setup_reference
        from otto.portfolio.tests import test_role_context
        f = self.f
        prepared = f.app.prepare_role(role="orchestrator", project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            assignment_ref=self.supervisor.ref.to_dict(), generation=1, mandate_ref=self.supervisor_mandate,
            context_refs=(self.supervisor_guide, self.supervisor_mandate), request_key="automatic-help-role",
            instruction="Inspect operational help", model="gpt-test", reasoning="high", profile="read-only", native_session_id="root-session")
        document = f.owner.content.read(setup_reference(f.project.ref.to_dict()))
        revise = test_role_context.RoleContextTests()
        revise.f, revise.number = f, 0
        revise.revise(document["current_revision"], {**document["revision"]["content"],
            "roles": {"manager": self.anchor, "orchestrator": prepared["schedule_id"]}})
        delivery = ExecutionHelpDelivery(readers=self.readers, project_ref=f.project.ref.to_dict(),
            execution=lambda **_: f.app, submit=self.host.submit, interim_supervision=self.binding)
        app = f.owner.manager_application(due_port=f.port, issue_delivery=delivery)
        self.portfolio = self.server.portfolio = f.app.portfolio = f.app.runtime.portfolio = app.portfolio
        self.host.start()
        self.addCleanup(self.host.close)
        result = self.wait_response(self.send("c1", self.request()))
        self.assertEqual(result["delivery"]["state"], "prepared", result)
        receipt = result["delivery"]["receipt"]
        delivered = self.wait_response(Path(receipt["response_path"]))
        self.assertEqual(delivered["outcome"], "succeeded", delivered)
        self.assertEqual(delivered["result"]["physical_session_id"], "root-session")
        read = self.service({"command": "read-help", "delivery_id": result["delivery"]["delivery_id"]})
        self.assertEqual(read["outcome"], "sent", read)
        self.assertTrue(read["receipt"]["context_digest_verified"])
        self.assertIn(result["issue_id"], f.provider.calls[0])
        self.assertEqual(self.service({"command": "read-help"})["issues"][0]["state"], "open")
        self.wait_response(self.send("c2", self.request()))
        self.assertEqual(len(f.provider.calls), 1)


if __name__ == "__main__":
    unittest.main()
