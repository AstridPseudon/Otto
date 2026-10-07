"""D03 source-only owner/native integration; providers and Stores are fixtures."""
from hashlib import sha256
from types import SimpleNamespace
from pathlib import Path
import json
import unittest

from herzchen.content.instructions import validate_instruction_content
from herzchen.contracts import ResourceRef
from herzchen.kernel.limits import LimitService
from otto.agents.orchestrator_route import prepare_canonical_assignment_role_brief
from otto.portfolio.direction import owner_direction_subject
from . import test_role_context as role_fixtures


class DirectionInvocationTests(unittest.TestCase):
    def setUp(self):
        self.c = role_fixtures.RoleContextTests(); self.c.setUp()
        self.addCleanup(self.c.doCleanups)
        self.f = self.c.f
        self.directions = self.f.owner.direction_bindings()

    def direction(self, subject, text):
        # Owner-wide documents require the actual owner scope, not a project.
        if subject.kind == "fnd.owner":
            from herzchen.content import ContentDocument, ContentRevision
            from herzchen.contracts import TransactionContext
            doc = ContentDocument(ResourceRef(subject.authority, "dat.content.document", "overall"),
                "direction", "private", "append", self.f.actor.actor, authoring_scope=subject)
            rev = ContentRevision(doc.ref, "rev-1", {"text": text}, self.f.actor, initial=True)
            self.f.owner.content.execute(self.f.owner.content.build_create_document(
                TransactionContext(self.f.actor, "overall-create", "0" * 64, expected_version=0), doc, rev))
            pin = {**doc.ref.to_dict(), "revision": "rev-1"}
        else:
            pin = self.c.document("direction", {"text": text})
        identity = ResourceRef(pin["authority"], pin["kind"], pin["id"])
        bound = self.directions.bind(subject, identity, actor=self.f.actor, logical_request_key="bind:" + identity.id)
        self.directions.adopt(subject, ResourceRef.from_dict(pin), expected_binding_ref=bound["binding_ref"],
            actor=self.f.actor, logical_request_key="adopt:" + identity.id)
        return pin

    def directed_role(self, role="manager", *, override=True):
        f = self.f
        if role == "worker":
            handles = f.app.assign_worker(**f.request())
            assignment = f.app.assignments.get(ResourceRef.from_dict(handles["assignment_ref"]))
            guide, mandate = handles["guide_ref"], handles["mandate_ref"]
        else:
            assignment, guide, mandate = f.role_handles(role, "advisor" if role == "project_advisor" else role, role + "-session")
        subject = ResourceRef.from_dict(assignment.payload["responsibility_ref"])
        specific = self.direction(subject, "Specific enduring priority")
        overall = self.direction(owner_direction_subject(f.actor.authority), "Overall owner priority")
        pins = [overall, specific]
        content = f.owner.content.read(ResourceRef.from_dict(guide))["content"]
        guide = self.c.document("role_instructions", dict(content, supporting_refs=pins))
        content = f.owner.content.read(ResourceRef.from_dict(guide))["content"]
        assignment = f.app.assignments.adopt_resources(assignment.ref, resources=[{
            "resource_ref": guide, "resource_name": content["name"],
            "content_digest": validate_instruction_content(content), "required": True}],
            expected_revision=assignment.revision, expected_generation=assignment.generation,
            logical_request_key="direction-base:" + role, actor=f.actor)
        old = f.owner.content.read(ResourceRef.from_dict(mandate))["content"]
        mandate = self.c.revise(mandate, dict(old, assignment_ref=assignment.ref.to_dict()))
        request = dict(role=role, project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            assignment_ref=assignment.ref.to_dict(), generation=1, mandate_ref=mandate,
            request_key="direction-role:" + role, model="gpt-test", reasoning="high",
            profile="workspace-write" if role in {"worker", "manager"} else "read-only")
        if override:
            request.update(context_refs=(), instruction="Explicit bounded presentation override")
        return assignment, pins, request

    def packet(self):
        return self.c.packet()

    def test_first_substantive_prompt_and_overrides_across_four_routes(self):
        for role in ("worker", "manager", "orchestrator", "project_advisor"):
            with self.subTest(role=role):
                case = DirectionInvocationTests(); case.setUp(); self.addCleanup(case.doCleanups)
                f = case.f
                if role == "project_advisor":
                    # Existing pairing and allowance semantics are retained.
                    f.role_handles("manager", "manager", "manager-session")
                assignment, pins, request = case.directed_role(role)
                if role == "project_advisor":
                    pool = LimitService(f.store).create_pool(ResourceRef(f.actor.authority, "limit", "direction-advisor"),
                        capacity_units=1, cumulative_allowance_units=1, logical_request_key="advisor-pool", actor=f.actor)
                    request["allowance_ref"] = pool.ref.to_dict()
                prepared = f.app.prepare_role(**request)
                self.assertEqual(prepared["outcome"], "committed", prepared)
                self.assertEqual(set(p["id"] for p in f.app._read(prepared["schedule_id"]).context_refs), set(p["id"] for p in pins))
                result = f.app.start(schedule_id=prepared["schedule_id"])
                self.assertEqual(result["outcome"], "succeeded", result)
                self.assertEqual(len(f.provider.calls), 1)
                packet = case.packet()
                context = packet["context"]["direction_context"]
                self.assertEqual([scope["effective_ref"] for scope in context], pins)
                self.assertEqual([scope["inputs"][0]["content"]["text"] for scope in context],
                    ["Overall owner priority", "Specific enduring priority"])
                launch = packet["operating_core"]["introduction"]["launch_context"]
                self.assertFalse(launch["credential"])
                self.assertEqual(launch["direction_refs"], pins)
                self.assertEqual(launch["responsibility_ref"], assignment.payload["responsibility_ref"])

    def test_new_draft_is_not_selected_and_continuation_keeps_attributed_direction(self):
        assignment, pins, request = self.directed_role()
        self.c.revise(pins[1], {"text": "Unadopted draft"})
        prepared = self.f.app.prepare_role(**request)
        self.assertEqual(self.f.app.start(schedule_id=prepared["schedule_id"])["outcome"], "succeeded")
        self.assertEqual(self.packet()["context"]["direction_context"][1]["effective_ref"], pins[1])
        continued = self.f.app.prepare_role(**dict(request, request_key="continued"))
        self.assertEqual(self.f.app.start(schedule_id=continued["schedule_id"])["outcome"], "succeeded")
        self.assertEqual([x["effective_ref"] for x in self.packet()["context"]["direction_context"]], pins)
        self.assertNotIn("Unadopted draft", str(self.packet()["context"]["direction_context"][1]["inputs"]))

    def test_callback_omitting_optional_role_context_still_includes_direction(self):
        assignment, pins, request = self.directed_role()
        runtime = self.f.app.runtime
        prepared = prepare_canonical_assignment_role_brief(role="manager", project_ref=request["project_ref"],
            task_ref=request["task_ref"], assignment_ref=request["assignment_ref"], mandate_ref=request["mandate_ref"],
            expected_generation=1, project_reader=runtime._project_reader(request["project_ref"]),
            task_reader=runtime._task_reader(request["project_ref"], request["task_ref"]),
            assignment_reader=runtime._assignment_reader(request["assignment_ref"]),
            mandate_reader=runtime._mandate_reader(request["project_ref"], request["mandate_ref"]),
            resource_reader=runtime.operations.content_port, lifecycle="callback", as_of=self.f.app._now(),
            include_role_context=False, direction_context_reader=runtime.operations.direction_context_reader)
        self.assertNotIn("introduction", prepared["brief"]["operating_core"])
        self.assertEqual([scope["effective_ref"] for scope in prepared["brief"]["context"]["direction_context"]], pins)
        self.assertEqual(self.f.provider.calls, [])

    def test_read_hook_cannot_use_foreign_task_to_escape_project_grant(self):
        other = self.f.owner.graph.create_project(title="Foreign", logical_request_key="foreign-project")
        task = self.f.owner.graph.create_task(other.ref, title="Foreign task", logical_request_key="foreign-task")
        reader = self.f.app.portfolio.operations.direction_context_reader
        with self.assertRaisesRegex(PermissionError, "another project"):
            reader(assignment_ref=None, generation=None, project_ref=self.f.project.ref.to_dict(), task_ref=task.ref.to_dict())
        with self.assertRaisesRegex(PermissionError, "read grant"):
            reader(assignment_ref=None, generation=None, project_ref=other.ref.to_dict())

    def test_disabled_advisor_is_inert_when_manager_has_direction(self):
        assignment, pins, request = self.directed_role()
        prepared = self.f.app.prepare_role(**request)
        setup = self.c.setup({"manager": prepared["schedule_id"]})
        adopted = self.f.app.prepare_operating_setup(project_ref=request["project_ref"], setup=setup, request_key="disabled-advisor")
        self.assertEqual(adopted["outcome"], "prepared", adopted)
        self.assertEqual(self.f.app.activate_operating_setup(project_ref=request["project_ref"])["outcome"], "succeeded")
        self.assertEqual(len(self.f.provider.calls), 1)
        self.assertFalse(any(due.get("role") == "project_advisor" for due in self.f.port.list_due()))
        self.assertEqual([scope["effective_ref"] for scope in self.packet()["context"]["direction_context"]], pins)

    def test_missing_assignment_direction_rejects_before_occurrence_or_provider(self):
        assignment, pins, request = self.directed_role()
        # A perfectly valid ordinary BASE adoption cannot drop a bound scope.
        base = self.c.document("role_instructions", {"schema": "herzchen.instructions.v1", "name": "omit",
            "entrypoint": "MANAGER.md", "instructions": "Only generic guide", "required": True,
            "bundle_digest": sha256(b"Only generic guide").hexdigest(), "export_manifest_digest": "fixture", "supporting_refs": []})
        value = self.f.owner.content.read(ResourceRef.from_dict(base))["content"]
        current = self.f.app.assignments.adopt_resources(assignment.ref, resources=[{
            "resource_ref": base, "resource_name": "omit", "content_digest": validate_instruction_content(value), "required": True}],
            expected_revision=assignment.revision, expected_generation=1, logical_request_key="omit-direction", actor=self.f.actor)
        before = len(self.f.port.list_due())
        with self.assertRaisesRegex(ValueError, "missing_assignment_direction"):
            self.f.app.prepare_role(**dict(request, assignment_ref=current.ref.to_dict(), request_key="missing"))
        self.assertEqual(len(self.f.port.list_due()), before)
        self.assertEqual(self.f.provider.calls, [])

    def test_delegated_worker_inherits_shared_direction_without_parent_primary(self):
        assignment, pins, request = self.directed_role()
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        root = Path(self.f.temporary.name).resolve()
        (root / "run.yaml").write_text(json.dumps({"roles": {"worker_normal": {"model": "gpt-test", "reasoning": "high"}}}))
        state = {"project_ref": self.f.project.ref.to_dict(), "task_refs": {"D03": self.f.task.ref.to_dict()},
            "assignment_ref": assignment.ref.to_dict(), "manager_generation": 1, "manager": "manager"}
        host = SimpleNamespace(_closing=False, submit=lambda request: {"outcome": "admitted"})
        server = SimpleNamespace(owner=self.f.owner, portfolio=self.f.app.portfolio, state=state,
            due_port=self.f.port, _execution=lambda **kwargs: self.f.app, _save_state=lambda: None)
        service = ManagerJourneyService(server=server, host=host, workspace=root, run_path=root)
        child = service._submit_worker({"command": "run-worker", "task": "D03", "route": "normal",
            "principal": "child", "request_key": "child", "focus": "Implement the bounded task"})
        self.assertEqual(child["outcome"], "admitted", child)
        result = self.f.app.start(schedule_id=child["schedule_id"])
        self.assertEqual(result["outcome"], "succeeded", result)
        self.assertEqual([scope["effective_ref"] for scope in self.packet()["context"]["direction_context"]], pins[:1])
        self.assertNotIn(pins[1], self.f.app._read(child["schedule_id"]).context_refs)

    def test_replacement_preserves_responsibility_direction_and_rejects_old_generation(self):
        assignment, pins, request = self.directed_role()
        replacement = self.f.app.assignments.reassign(assignment.ref, principal="replacement", session="replacement-session",
            expected_generation=1, logical_request_key="replace-direction-manager", actor=self.f.actor)
        old = self.f.owner.content.read(ResourceRef.from_dict(request["mandate_ref"]))["content"]
        contract = dict(old["instruction_contract"], authority=dict(old["instruction_contract"]["authority"], owner_actor="replacement"))
        mandate = self.c.revise(request["mandate_ref"], dict(old, assignment_ref=replacement.ref.to_dict(), generation=2,
                                                         instruction_contract=contract))
        new = dict(request, assignment_ref=replacement.ref.to_dict(), generation=2, mandate_ref=mandate, request_key="replacement")
        prepared = self.f.app.prepare_role(**new)
        self.assertEqual(self.f.app.start(schedule_id=prepared["schedule_id"])["outcome"], "succeeded")
        self.assertEqual([x["effective_ref"] for x in self.packet()["context"]["direction_context"]], pins)
        self.assertEqual(self.packet()["operating_core"]["introduction"]["principal"], "replacement")
        with self.assertRaisesRegex(ValueError, "stale"):
            self.f.app.prepare_role(**dict(request, request_key="old-session"))


if __name__ == "__main__":
    unittest.main()
