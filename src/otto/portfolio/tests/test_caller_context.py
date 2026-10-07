"""D03 trusted-ingress contracts; no installed authentication claim."""
from dataclasses import replace
from pathlib import Path
from hashlib import sha256
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import json
from concurrent.futures import ThreadPoolExecutor

from herzchen.contracts import ResourceRef
from herzchen.content.instructions import validate_instruction_content
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.identity_context import HostCallerBinding, HostIngress
from otto.portfolio.manager_journey_service import ManagerJourneyService
from . import test_role_context as role_fixtures


class CallerContextTests(unittest.TestCase):
    def setUp(self):
        self.c = role_fixtures.RoleContextTests(); self.c.setUp()
        self.addCleanup(self.c.doCleanups)
        self.f = self.c.f
        self.bindings = {}
        self.effects = []

    def caller(self, role="manager"):
        assignment, schedule, request = self.c.role(role, overrides={"model": "gpt-test", "reasoning": "high"})
        result = self.f.app.start(schedule_id=schedule)
        self.assertEqual(result["outcome"], "succeeded", result)
        due = self.f.app._read(schedule)
        adapter = self.f.app.runtime.adapter
        binding = HostCallerBinding(self.f.binding.authenticated_actor(assignment.principal), assignment.ref,
            assignment.generation, type(adapter).__module__ + "." + type(adapter).__name__,
            due.target["native_id"], schedule)
        self.bindings[role] = binding
        return binding

    def host(self, authorizer=None):
        return ExecutionHost(directory=Path(self.f.temporary.name) / "commands",
            handler=lambda request: self.effects.append(dict(request)) or {"outcome": "committed"},
            caller_binding_reader=lambda ingress: self.bindings.get(ingress.handle),
            caller_context_resolver=self.f.app.caller_context, caller_authorizer=authorizer)

    def test_two_callers_identical_read_payload_and_adapter_contract_variants(self):
        manager = self.caller(); other = self.caller("orchestrator")
        host = self.host()
        payload = {"command": "effective-context"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            a_call = pool.submit(host._dispatch, payload, ingress=HostIngress("fixture-file-ipc", "manager"))
            b_call = pool.submit(host._dispatch, payload, ingress=HostIngress("fixture-unix-socket", "orchestrator"))
            a, b = a_call.result(), b_call.result()
        self.assertEqual(a["outcome"], "read", a)
        self.assertEqual(b["outcome"], "read", b)
        self.assertEqual(a["caller_context"]["assignment_ref"], manager.assignment_ref.to_dict())
        self.assertEqual(b["caller_context"]["assignment_ref"], other.assignment_ref.to_dict())
        self.assertNotEqual(a["caller_context"]["principal"], b["caller_context"]["principal"])
        self.assertEqual(self.effects, [])
        for key, value in (("logical_agent_id", manager.actor.actor), ("caller_principal", manager.actor.actor),
                           ("caller_assignment_ref", manager.assignment_ref.to_dict()),
                           ("caller_native_session_id", manager.native_session_id), ("caller_generation", True)):
            result = host._dispatch(dict(payload, **{key: value}), ingress=HostIngress("fixture-file-ipc", "orchestrator"))
            self.assertEqual(result["outcome"], "error", result)
            self.assertFalse(result["effects_started"])

    def test_missing_binding_json_context_and_unsupported_adapter_fail_before_handler(self):
        manager = self.caller(); host = self.host()
        for payload, handle in (({"command": "report"}, "unknown"),
                ({"command": "effective-context", "caller_context": {"principal": "manager"}}, "manager"),
                ({"command": "effective-context", "principal": "orchestrator"}, "manager")):
            self.assertEqual(host._dispatch(payload, ingress=HostIngress("fixture", handle))["outcome"], "error")
        for binding in (replace(manager, adapter="unsupported-adapter"), replace(manager, native_session_id="copied-session"),
                        replace(manager, actor=self.f.binding.authenticated_actor("orchestrator"))):
            self.bindings["manager"] = binding
            self.assertEqual(host._dispatch({"command": "whoami"}, ingress=HostIngress("fixture", "manager"))["outcome"], "error")
        self.assertEqual(self.effects, [])
        legacy = ExecutionHost(directory=Path(self.f.temporary.name) / "legacy", handler=lambda request: self.effects.append(request))
        self.assertEqual(legacy._dispatch({"command": "whoami"})["outcome"], "held")
        self.assertEqual(legacy._dispatch({"command": "report", "logical_agent_id": "manager"})["outcome"], "held")
        self.assertEqual(self.effects, [])

    def test_owner_reopen_recovers_context_without_prompt_memory_and_no_provider_replay(self):
        binding = self.caller()
        first = self.f.app.caller_context(binding)
        counts = self.f.store.consumer().snapshot_counts()
        self.f.store.close()
        from herzchen.kernel.store import Store
        self.f.store = Store.open(self.f.path, authority="execution-owner", expected_domains=tuple(sorted(self.f.domains, key=lambda d: d.domain_id)))
        self.f.compose()
        recovered = self.f.app.caller_context(binding)
        self.assertEqual(first, recovered)
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)
        self.assertEqual(len(self.f.provider.calls), 1)

    def test_replacement_and_reused_name_cannot_recover_old_session_authority(self):
        binding = self.caller()
        self.f.app.assignments.reassign(binding.assignment_ref, principal=binding.actor.actor,
            session="replacement-session", expected_generation=1, logical_request_key="replace-same-name", actor=self.f.actor)
        with self.assertRaisesRegex(ValueError, "stale"):
            self.f.app.caller_context(binding)
        current = self.f.app.assignments.get(binding.assignment_ref)
        # Copying the new generation onto an old session/occurrence is no bind.
        with self.assertRaises(PermissionError):
            self.f.app.caller_context(replace(binding, assignment_ref=current.ref, generation=2))
        self.assertEqual(len(self.f.provider.calls), 1)

    def test_current_context_survives_project_edits_and_supported_adoption_without_rewriting_occurrence(self):
        binding = self.caller()
        before = self.f.app._read(binding.schedule_id).to_dict()
        project = self.f.owner.graph.revise(self.f.project.ref, title="Current project",
            logical_request_key="project-progress", actor=self.f.actor)
        self.assertEqual(self.f.app.caller_context(binding)["project_ref"], project.ref.to_dict())
        guide = before["context_refs"][0]
        content = self.f.owner.content.read(ResourceRef.from_dict(guide))["content"]
        pin = self.c.revise(guide, dict(content, instructions="Current adopted guide", bundle_digest=sha256(b"Current adopted guide").hexdigest()))
        content = self.f.owner.content.read(ResourceRef.from_dict(pin))["content"]
        current = self.f.app.assignments.adopt_resources(binding.assignment_ref, resources=[{
            "resource_ref": pin, "resource_name": content["name"], "content_digest": validate_instruction_content(content), "required": True}],
            expected_revision=binding.assignment_ref.revision, expected_generation=1,
            logical_request_key="current-adopt", actor=self.f.actor)
        self.f.compose()
        context = self.f.app.caller_context(binding)
        self.assertEqual(context["assignment_ref"], current.ref.to_dict())
        self.assertEqual(context["occurrence_ref"]["assignment_ref"], binding.assignment_ref.to_dict())
        self.assertEqual(self.f.app._read(binding.schedule_id).to_dict(), before)
        self.assertEqual(len(self.f.provider.calls), 1)

    def test_actual_file_dispatch_and_socket_contract_supply_independent_ingress_handles(self):
        binding = self.caller()
        host = self.host()
        host.directory.mkdir()
        request_path = host.directory / "request-aa.json"
        self.bindings[request_path] = binding  # Explicit trusted fixture hook, not path authentication.
        request_path.write_text(json.dumps({"command": "whoami"}))
        host._serve_files(False)
        file_reply = json.loads((host.directory / "response-aa.json").read_text())
        self.assertEqual(file_reply["outcome"], "read", file_reply)
        class Connection:
            def __enter__(connection): return connection
            def __exit__(connection, *args): return False
            def settimeout(connection, seconds): pass
            def recv(connection, count): return b'{"command":"whoami"}\n'
            def sendall(connection, data):
                connection.reply = json.loads(data)
                host._commands_stop.set()
        connection = Connection()
        self.bindings[connection] = binding
        host._socket = SimpleNamespace(accept=lambda: (connection, None))
        host._serve_socket()  # No actual socket bind/network capability required.
        self.assertEqual(connection.reply["caller_context"], file_reply["caller_context"])
        self.assertEqual(self.effects, [])

    def test_worker_context_uses_retained_native_readback_without_an_admission_field(self):
        result = self.f.app.assign_and_start(**self.f.request())
        self.assertEqual(result["outcome"], "succeeded", result)
        assignment = self.f.app.assignments.get(ResourceRef.from_dict(result["assignment_ref"]))
        due = self.f.app._read(result["schedule_id"])
        binding = HostCallerBinding(self.f.binding.authenticated_actor("worker"), assignment.ref, 1,
            self.f.app.native_adapter_identity(), due.host_evidence["gateway_attempt"]["delivery_authorization"]["physical_session_id"], due.schedule_id)
        self.assertEqual(self.f.app.caller_context(binding)["principal"], "worker")
        bad = due.to_dict()
        bad["host_evidence"]["gateway_attempt"]["result"]["context_digest_verified"] = False
        self.f.port.save_due(due.schedule_id, bad, request_id="unverified-worker", expected_version=due.version)
        with self.assertRaises(PermissionError):
            self.f.app.caller_context(binding)

    def test_current_responsibilities_cannot_reuse_one_qualified_native_session(self):
        binding = self.caller()
        assignment, guide, mandate = self.f.role_handles("orchestrator", "orchestrator", binding.native_session_id)
        request = dict(role="orchestrator", project_ref=self.f.project.ref.to_dict(), task_ref=self.f.task.ref.to_dict(),
            assignment_ref=assignment.ref.to_dict(), generation=1, mandate_ref=mandate,
            request_key="reused-session", model="gpt-test", reasoning="high", profile="read-only")
        prepared = self.f.app.prepare_role(**request)
        self.assertEqual(self.f.app.start(schedule_id=prepared["schedule_id"])["outcome"], "succeeded")
        from herzchen.kernel.store import Store
        # The real durable port must retain the cross-assignment fence without
        # hydrating unrelated historical Due events.
        with patch.object(Store, "list_events", side_effect=AssertionError("global history hydration")):
            with self.assertRaisesRegex(PermissionError, "reused"):
                self.f.app.caller_context(binding)
        current = self.f.app.assignments.reassign(assignment.ref, principal=assignment.principal,
            session="replacement-orchestrator-session", expected_generation=1,
            logical_request_key="replace-reused-session", actor=self.f.actor)
        self.assertEqual(current.generation, 2)
        with patch.object(Store, "list_events", side_effect=AssertionError("global history hydration")):
            self.assertEqual(self.f.app.caller_context(binding)["principal"], binding.actor.actor)

    def test_exact_native_due_selector_avoids_event_payloads_and_has_no_read_effects(self):
        binding = self.caller()
        other = self.caller("orchestrator")
        scope = {"native_adapter": binding.adapter, "native_session_id": binding.native_session_id}
        expected = tuple(due for due in self.f.port.list_due() if
            due["target"].get("native_adapter") == binding.adapter and
            ((due.get("host_evidence") or {}).get("gateway_attempt") or {}).get("delivery_authorization", {}).get("physical_session_id") == binding.native_session_id)
        counts = self.f.store.consumer().snapshot_counts()
        from herzchen.kernel.store import Store
        with patch.object(Store, "list_events", side_effect=AssertionError("global history hydration")):
            self.assertEqual(self.f.port.list_due(scope), expected)
            self.assertEqual(self.f.app.caller_context(binding)["principal"], binding.actor.actor)
            self.assertEqual(self.f.port.list_due(dict(scope, native_adapter="different-adapter")), ())
            self.assertEqual(self.f.port.list_due(dict(scope, native_session_id=other.native_session_id)),
                self.f.port.list_due({"native_adapter": other.adapter, "native_session_id": other.native_session_id}))
            self.assertEqual(self.f.port.list_due(dict(scope, recipient=other.actor.actor)), ())
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)
        self.assertEqual(len(self.f.provider.calls), 2)
        reader = self.f.store.consumer()
        for predicates in ({}, {("target.native_adapter",): binding.adapter},
                           {("target", "native_adapter"): True}, {("",): binding.adapter}):
            with self.assertRaises(ValueError):
                reader.find_identity_refs(kind="otto.due-record", payload_matches=predicates)

    def test_manager_authorization_distinguishes_child_target_and_cross_caller_payload_reuse(self):
        manager = self.caller(); self.caller("orchestrator")
        root = Path(self.f.temporary.name).resolve()
        server = SimpleNamespace(owner=self.f.owner, portfolio=self.f.app.portfolio,
            state={"project_ref": self.f.project.ref.to_dict(), "task_refs": {}, "manager": "manager",
                   "assignment_ref": manager.assignment_ref.to_dict(), "manager_generation": 1},
            due_port=self.f.port, _execution=lambda **kwargs: self.f.app)
        service = ManagerJourneyService(server=server, host=None, workspace=root, run_path=root)
        host = self.host(service.authorize_caller)
        payload = {"command": "run-worker", "principal": "child-worker", "request_key": "identical-payload"}
        accepted = host._dispatch(payload, ingress=HostIngress("fixture", "manager"))
        self.assertEqual(accepted["outcome"], "committed", accepted)
        self.assertEqual(accepted["caller_context"]["principal"], "manager")
        self.assertEqual(accepted["target_context"]["principal"], "child-worker")
        rejected = host._dispatch(payload, ingress=HostIngress("fixture", "orchestrator"))
        self.assertEqual(rejected["outcome"], "error", rejected)
        self.assertEqual(self.effects, [payload])
        # An identity-bearing service never falls back to its owner for a
        # command that has no caller-specific authorization policy.
        self.assertEqual(self.host()._dispatch(payload, ingress=HostIngress("fixture", "manager"))["outcome"], "error")
        self.assertEqual(self.effects, [payload])


if __name__ == "__main__":
    unittest.main()
