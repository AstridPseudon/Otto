"""D06 connected candidate journey. All authentication/provider inputs are fixtures.

The real owner Store, application, command dispatcher and history facade are
exercised together. File handles below are explicitly bound by the test host;
neither those handles nor the fabricated native transcript authenticate a live
caller. Installed qualification remains an owner operation, outside this suite.
"""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from herzchen.content.instructions import validate_instruction_content
from herzchen.contracts import ResourceRef, canonical_json
from hashlib import sha256
from herzchen.kernel.store import Store
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.identity_context import HostCallerBinding, HostIngress
from otto.portfolio.manager_application import ManagerApplication
from otto.portfolio.manager_journey_service import ManagerJourneyService
from . import test_direction_invocation as invocation_fixtures


class DirectionJourneyTests(unittest.TestCase):
    def setUp(self):
        self.c = invocation_fixtures.DirectionInvocationTests()
        self.c.setUp()
        self.addCleanup(self.c.doCleanups)
        self.f = self.c.f
        self.bindings = {}

    def surface(self):
        return ManagerApplication.from_owner(self.f.owner, due_port=self.f.port).direction_operations

    def reopen(self):
        domains = self.f.store.registered_domains()
        self.f.store.close()
        self.f.store = Store.open(self.f.path, authority=self.f.binding.authority, expected_domains=domains)
        self.f.compose()
        self.c.directions = self.f.owner.direction_bindings()

    def binding(self, assignment, schedule):
        due = self.f.app._read(schedule)
        auth = due.host_evidence["gateway_attempt"]["delivery_authorization"]
        return HostCallerBinding(self.f.binding.authenticated_actor(assignment.principal),
            assignment.ref, assignment.generation, self.f.app.native_adapter_identity(),
            auth["physical_session_id"], schedule)

    def deliver(self, request):
        prepared = self.f.app.prepare_role(**request)
        self.assertEqual(prepared["outcome"], "committed", prepared)
        result = self.f.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(result["outcome"], "succeeded", result)
        return prepared["schedule_id"]

    def test_draft_update_prepare_reopen_continue_replace_and_retained_history(self):
        handles = self.f.app.assign_worker(**self.f.request())
        unbound = self.f.app.assignments.get(ResourceRef.from_dict(handles["assignment_ref"]))
        self.assertEqual(self.surface().read(unbound.payload["responsibility_ref"])["state"], "unbound")
        assignment, pins, request = self.c.directed_role()
        subject = ResourceRef.from_dict(assignment.payload["responsibility_ref"])
        surface = self.surface()
        counts = self.f.store.consumer().snapshot_counts()
        surface.initial_bind(subject, {**pins[1], "revision": None}, logical_request_key="journey-bind-retry")
        with self.assertRaisesRegex(ValueError, "fixed"):
            surface.initial_bind(subject, {**pins[0], "revision": None}, logical_request_key="journey-bind-changed")
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)
        first = self.deliver(request)
        original_due = self.f.app._read(first).to_dict()
        original_packet = self.c.packet()
        binding = self.binding(assignment, first)
        # This is useful-work *fixture evidence*, never a claim of live work.
        self.assertIn("test-passed", json.dumps(original_due["host_evidence"]["gateway_attempt"]["result"]))
        self.assertEqual(original_packet["context"]["direction_context"][1]["effective_ref"], pins[1])

        # Delegate through the existing manager/worker composition. Its host
        # admission and external provider are fixtures, while assignment,
        # inheritance, native parsing and result publication are real ports.
        root = Path(self.f.temporary.name).resolve()
        (root / "run.yaml").write_text(json.dumps({"roles": {"worker_normal": {"model": "gpt-test", "reasoning": "high"}}}))
        state = {"project_ref": self.f.project.ref.to_dict(), "task_refs": {"D06": self.f.task.ref.to_dict()},
            "assignment_ref": assignment.ref.to_dict(), "manager_generation": 1, "manager": "manager"}
        host = SimpleNamespace(_closing=False, submit=lambda req: {"outcome": "admitted"})
        server = SimpleNamespace(owner=self.f.owner, portfolio=self.f.app.portfolio, state=state,
            due_port=self.f.port, _execution=lambda **kwargs: self.f.app, _save_state=lambda: None)
        service = ManagerJourneyService(server=server, host=host, workspace=root, run_path=root)
        child = service._submit_worker({"command": "run-worker", "task": "D06", "route": "normal",
            "principal": "journey-child", "request_key": "journey-child", "focus": "Repair the bounded fixture task"})
        self.assertEqual(child["outcome"], "admitted", child)
        self.assertEqual(self.f.app.start(schedule_id=child["schedule_id"])["outcome"], "succeeded")
        observations = self.f.app.assignments.list_observations(ResourceRef.from_dict(child["assignment_ref"]), kind="result")
        self.assertEqual(len(observations), 1)
        self.assertIn("test-passed", json.dumps(observations[0].value))
        self.assertEqual([scope["effective_ref"] for scope in self.c.packet()["context"]["direction_context"]], pins[:1])

        draft = surface.draft(subject, {"text": "Explicit future priority"},
            logical_request_key="journey-draft", expected_revision="rev-1")
        before_update = surface.read(subject, assignment_ref=assignment.ref, generation=1)
        self.assertEqual(before_update["latest_ref"], draft["revision_ref"])
        self.assertEqual(before_update["scope_adopted_ref"], pins[1])
        self.assertEqual(before_update["assignment_adopted_ref"], pins[1])
        continued = self.deliver(dict(request, request_key="journey-draft-continuation"))
        self.assertEqual(self.c.packet()["context"]["direction_context"][1]["effective_ref"], pins[1])
        self.assertNotIn("Explicit future priority", self.f.provider.calls[-1])

        # Scope update and assignment refresh reuse their maintained ports.
        scope = surface.update(subject, draft["revision_ref"], logical_request_key="journey-scope-update")
        self.assertEqual(scope["outcome"], "updated", scope)
        pending = surface.read(subject, assignment_ref=assignment.ref, generation=1)
        self.assertEqual(pending["scope_adopted_ref"], draft["revision_ref"])
        self.assertEqual(pending["assignment_adopted_ref"], pins[1])
        self.assertTrue(pending["pending_assignment_application"])
        guide = self.f.app.assignments.get(assignment.ref).payload["resource_adoptions"][0]["resource_ref"]
        content = self.f.owner.content.read(ResourceRef.from_dict(guide))["content"]
        new_guide = self.c.c.document("role_instructions", dict(content, supporting_refs=[pins[0], draft["revision_ref"]]))
        content = self.f.owner.content.read(ResourceRef.from_dict(new_guide))["content"]
        resources = [{"resource_ref": new_guide, "resource_name": content["name"],
            "content_digest": validate_instruction_content(content), "required": True}]
        update_args = dict(logical_request_key="journey-assignment-update",
            expected_binding_ref=pending["binding_ref"], assignment_ref=assignment.ref,
            expected_generation=1, assignment_resources=resources, assignment_actor=self.f.actor)
        refreshed = surface.update(subject, draft["revision_ref"], **update_args)
        self.assertEqual(refreshed["outcome"], "updated", refreshed)
        current = self.f.app.assignments.get(ResourceRef.from_dict(refreshed["assignment_refresh"]["assignment_ref"]))
        old = self.f.owner.content.read(ResourceRef.from_dict(request["mandate_ref"]))["content"]
        mandate = self.c.c.revise(request["mandate_ref"], dict(old, assignment_ref=current.ref.to_dict()))
        future = dict(request, assignment_ref=current.ref.to_dict(), mandate_ref=mandate, request_key="journey-updated")
        prepared = self.f.app.prepare_role(**future)
        self.assertEqual(prepared["outcome"], "committed", prepared)
        counts = self.f.store.consumer().snapshot_counts()
        provider_count = len(self.f.provider.calls)
        self.reopen()
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)
        context = self.f.app.caller_context(binding)
        self.assertEqual(context["assignment_ref"], current.ref.to_dict())
        self.assertEqual(context["direction_context"][1]["effective_ref"], draft["revision_ref"])
        self.assertEqual(self.f.app._read(first).to_dict(), original_due)
        # Retry the exact composed update after owner reopen. No new revisions
        # or adoptions may result from recovery of the committed boundaries.
        replay = self.surface().update(subject, draft["revision_ref"], **update_args)
        self.assertEqual(replay, refreshed)
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)
        changed = [dict(resources[0], content_digest="0" * 64)]
        conflict = self.surface().update(subject, draft["revision_ref"],
            **dict(update_args, assignment_resources=changed))
        self.assertEqual(conflict["outcome"], "partial")
        self.assertEqual(conflict["assignment_refresh"]["code"], "ReplayConflictError")
        with self.assertRaisesRegex(ValueError, "stale_assignment"):
            self.surface().update(subject, draft["revision_ref"],
                **dict(update_args, logical_request_key="new-intent-stale-assignment"))
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)
        updated = self.f.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(updated["outcome"], "succeeded", updated)
        self.assertEqual(self.c.packet()["context"]["direction_context"][1]["effective_ref"], draft["revision_ref"])
        self.assertIn("Explicit future priority", self.f.provider.calls[-1])
        self.f.app.recover(schedule_id=prepared["schedule_id"], execute=True)
        self.assertEqual(len(self.f.provider.calls), provider_count + 1)

        replacement = self.f.app.assignments.reassign(current.ref, principal=current.principal,
            session="new-session-same-display-name", expected_generation=1,
            logical_request_key="journey-replacement", actor=self.f.actor)
        old = self.f.owner.content.read(ResourceRef.from_dict(mandate))["content"]
        mandate = self.c.c.revise(mandate, dict(old, assignment_ref=replacement.ref.to_dict(), generation=2))
        with self.assertRaisesRegex(ValueError, "stale"):
            self.f.app.caller_context(binding)
        with self.assertRaises(PermissionError):
            self.f.app.caller_context(replace(binding, assignment_ref=replacement.ref, generation=2))
        next_request = dict(future, assignment_ref=replacement.ref.to_dict(), generation=2,
            mandate_ref=mandate, request_key="journey-replacement-delivery")
        replaced = self.deliver(next_request)
        new_binding = self.binding(replacement, replaced)
        self.assertEqual(self.f.app.caller_context(new_binding)["responsibility_ref"], subject.to_dict())
        self.assertEqual(self.c.packet()["context"]["direction_context"][1]["effective_ref"], draft["revision_ref"])
        self.assertEqual(self.f.app._read(first).to_dict(), original_due)
        history = self.surface().history(subject)
        self.assertEqual(history["document_ref"]["id"], pins[1]["id"])
        self.assertEqual([item["content"]["text"] for item in history["revisions"]],
            ["Specific enduring priority", "Explicit future priority"])
        occurrences = {item["schedule_id"]: item for item in history["occurrence_evidence"]}
        self.assertEqual(set(occurrences), {first, continued, prepared["schedule_id"], replaced})
        self.assertEqual(occurrences[first]["delivery_status"], "delivered")
        self.assertEqual(occurrences[first]["rendered_evidence"],
            original_due["host_evidence"]["gateway_attempt"]["result"]["task_bound_evidence"])
        self.assertEqual(occurrences[first]["delivered_brief"], original_packet)
        self.assertEqual(occurrences[first]["delivered_brief_digest"],
            sha256(canonical_json(original_packet).encode()).hexdigest())
        self.assertEqual(occurrences[first]["direction_refs"], original_due["context_refs"])

    def test_shared_file_transport_same_payload_isolation_and_socket_contract(self):
        # Establish generic handles before overall direction is bound. Reusing
        # the generic helper's worker request after binding would change its
        # automatically inherited direction inputs under the same request key.
        other, _, other_request = self.c.c.role("orchestrator")
        manager, pins, request = self.c.directed_role()
        first = self.deliver(request)
        # The second caller must adopt shared overall direction independently.
        guide = other.payload["resource_adoptions"][0]["resource_ref"]
        content = self.f.owner.content.read(ResourceRef.from_dict(guide))["content"]
        new_guide = self.c.c.document("role_instructions", dict(content, supporting_refs=pins[:1]))
        content = self.f.owner.content.read(ResourceRef.from_dict(new_guide))["content"]
        other = self.f.app.assignments.adopt_resources(other.ref, resources=[{
            "resource_ref": new_guide, "resource_name": content["name"],
            "content_digest": validate_instruction_content(content), "required": True}],
            expected_revision=other.revision, expected_generation=1,
            logical_request_key="other-caller-guide", actor=self.f.actor)
        old = self.f.owner.content.read(ResourceRef.from_dict(other_request["mandate_ref"]))["content"]
        mandate = self.c.c.revise(other_request["mandate_ref"], dict(old, assignment_ref=other.ref.to_dict()))
        second = self.deliver(dict(other_request, assignment_ref=other.ref.to_dict(), mandate_ref=mandate,
            request_key="second-caller"))
        manager_binding, other_binding = self.binding(manager, first), self.binding(other, second)
        root = Path(self.f.temporary.name).resolve()
        server = SimpleNamespace(owner=self.f.owner, portfolio=self.f.app.portfolio,
            state={"project_ref": self.f.project.ref.to_dict(), "task_refs": {}, "manager": "manager",
                "assignment_ref": manager.ref.to_dict(), "manager_generation": 1},
            due_port=self.f.port, _execution=lambda **kwargs: self.f.app)
        service = ManagerJourneyService(server=server, host=None, workspace=root, run_path=root)
        effects = []
        host = ExecutionHost(directory=root / "commands", handler=lambda req: effects.append(dict(req)) or {"outcome": "committed"},
            caller_binding_reader=lambda ingress: self.bindings.get(ingress.handle),
            caller_context_resolver=lambda binding: self.f.app.caller_context(binding),
            caller_authorizer=service.authorize_caller)
        host.directory.mkdir()

        def file_call(token, binding, payload):
            path = host.directory / ("request-" + token + ".json")
            self.bindings[path] = binding  # Trusted host fixture, not filename auth.
            path.write_text(json.dumps(payload))
            host._serve_files(False)
            return json.loads((host.directory / ("response-" + token + ".json")).read_text())

        counts = self.f.store.consumer().snapshot_counts()
        payload = {"command": "effective-context"}
        a = file_call("aa", manager_binding, payload)
        b = file_call("bb", other_binding, payload)
        self.assertEqual(a["caller_context"]["principal"], "manager")
        self.assertEqual(b["caller_context"]["principal"], "orchestrator")
        self.assertEqual([scope["effective_ref"] for scope in a["caller_context"]["direction_context"]], pins)
        self.assertEqual([scope["effective_ref"] for scope in b["caller_context"]["direction_context"]], pins[:1])
        rejected = file_call("cc", other_binding, dict(payload, caller_principal="manager"))
        self.assertFalse(rejected["effects_started"])
        self.assertEqual(rejected["outcome"], "error")
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)

        child_payload = {"command": "run-worker", "principal": "child", "request_key": "same-payload"}
        allowed = file_call("dd", manager_binding, child_payload)
        denied = file_call("ee", other_binding, child_payload)
        self.assertEqual(allowed["caller_context"]["principal"], "manager")
        self.assertEqual(allowed["target_context"]["principal"], "child")
        self.assertEqual(denied["outcome"], "error", denied)
        self.assertEqual(effects, [child_payload])  # Handler is a spy, no live child.

        # A second *adapter contract variant*, with a stub connection only.
        class Connection:
            def __enter__(connection): return connection
            def __exit__(connection, *args): return False
            def settimeout(connection, seconds): pass
            def recv(connection, count): return b'{"command":"effective-context"}\n'
            def sendall(connection, data):
                connection.reply = json.loads(data)
                host._commands_stop.set()
        connection = Connection()
        self.bindings[connection] = other_binding
        host._socket = SimpleNamespace(accept=lambda: (connection, None))
        host._serve_socket()
        self.assertEqual(connection.reply["caller_context"], b["caller_context"])
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)

    def test_unknown_attempt_survives_owner_reopen_and_direction_draft_without_replay(self):
        assignment, pins, request = self.c.directed_role()
        self.f.provider.unknown = True
        prepared = self.f.app.prepare_role(**request)
        result = self.f.app.start(schedule_id=prepared["schedule_id"])
        self.assertNotEqual(result["outcome"], "succeeded")
        retained = self.f.app._read(prepared["schedule_id"]).to_dict()
        subject = ResourceRef.from_dict(assignment.payload["responsibility_ref"])
        self.surface().draft(subject, {"text": "Draft during unknown effect"},
            logical_request_key="unknown-draft", expected_revision="rev-1")
        self.reopen()
        self.f.app.recover(schedule_id=prepared["schedule_id"], execute=True)
        self.assertEqual(len(self.f.provider.calls), 1)
        after = self.f.app._read(prepared["schedule_id"]).to_dict()
        self.assertEqual(after["host_evidence"]["gateway_attempt"], retained["host_evidence"]["gateway_attempt"])
        self.assertEqual(self.surface().read(subject)["scope_adopted_ref"], pins[1])
        occurrence = self.surface().history(subject)["occurrence_evidence"][0]
        self.assertNotEqual(occurrence["delivery_status"], "delivered")


if __name__ == "__main__":
    unittest.main()
