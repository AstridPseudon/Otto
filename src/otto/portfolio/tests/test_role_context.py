"""S02 owner composition and actual provider-bound packet regressions.

All records and transports are disposable fixtures. No live host, allowance,
owner database or installed service is changed by this suite.
"""
from dataclasses import replace
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from herzchen.content import ContentDocument, ContentRevision
from herzchen.content.instructions import validate_instruction_content
from herzchen.contracts import ResourceRef, TransactionContext, canonical_json
from herzchen.kernel.limits import LimitService
from otto.portfolio.operating_setup import evaluate_setup
from tests import test_execution_application as owner_fixture
from otto.portfolio.role_context import _compose_role, selected_configuration


class RolePackSelectorTests(unittest.TestCase):
    def adopted_configuration(self, content):
        return selected_configuration([{"ref": {"authority": "local", "kind": "dat.content.document",
            "id": "cfg", "revision": "rev-1"}, "content": content}])

    def native_role_pin(self):
        from herzchen.packs.authoring import read_managed_pack
        from otto.hostctl.owner import _managed_source_state_path
        root = Path(__file__).resolve().parents[4]
        pack = read_managed_pack("otto-roles", project_root=root,
            native_pack_root=Path(__file__).resolve().parents[2] / "packs",
            source_state_path=_managed_source_state_path())
        resource = next(item for item in pack.resources if item.path == "roles.json")
        return {"pack_id": pack.pack_id, "pack_version": pack.version,
            "source_revision": pack.source.source_revision,
            "source_inventory_identity": pack.source.source_inventory_identity,
            "resource_path": resource.path, "resource_digest": resource.source_digest}

    def test_role_introduction_uses_adopted_override_and_pack_brief(self):
        from otto.portfolio.role_context import effective_context_projection, role_introduction
        config_ref = {"authority": "local", "kind": "dat.content.document", "id": "cfg", "revision": "rev-1"}
        configuration = self.adopted_configuration({"schema": "otto.role-configuration.v1", "roles": {},
            "role_bindings": {}, "role_pack": self.native_role_pin(),
            "role_policies": {"manager": "Adopted project policy"},
            "tool_entrypoints": {"manager": "adopted-project-tool"}})
        configuration["ref"] = config_ref
        rogue = {"ref": {"authority": "local", "kind": "dat.content.document", "id": "rogue", "revision": "rev-1"},
            "content": {"role_policies": {"manager": "unadopted project payload policy"},
                        "tool_entrypoints": {"manager": "unadopted-project-tool"}}}
        project_ref = {"authority": "local", "kind": "work.project", "id": "project", "revision": "rev-1"}
        canonical = {"role": "manager", "supporting_context": [configuration, rogue], "direction_context": [],
            "base_resource": {"ref": {"authority": "local", "kind": "dat.content.document", "id": "base", "revision": "rev-1"},
                              "content_sha256": "d" * 64},
            "render": {"project_state": {"project": {"ref": project_ref,
                "payload": {"title": "Project", "metadata": {}}}, "task": None},
                "snapshot": {"principal": "manager", "assignment_ref": {"id": "assignment"},
                    "generation": 1, "responsibility_ref": {"id": "responsibility"},
                    "mandate_ref": {"id": "mandate"}, "native_session": "manager-session"},
                "brief": {"mandate": "Deliver project", "user_constraints": [],
                    "operational_constraints": [], "links": []}}}
        with patch.dict("os.environ", {"OTTO_TOOL_ENTRYPOINT": "/installed/ottoctl"}):
            introduction = role_introduction(canonical)
            direct_context = effective_context_projection(canonical, tool_entrypoint="adopted-project-tool")
        self.assertEqual(introduction["selected_policy"], "Adopted project policy")
        self.assertEqual(introduction["selected_policy_source"], config_ref)
        self.assertEqual(introduction["tool_entrypoint"], "adopted-project-tool")
        self.assertEqual(introduction["tool_entrypoint_source"], config_ref)
        self.assertIn("run-worker --task TASK", introduction["responsibility"])
        self.assertIn("Installed tool entrypoint: `/installed/ottoctl`.", introduction["responsibility"])
        self.assertEqual(introduction["effective_context"]["remit"]["responsibility"],
                         introduction["responsibility"])
        self.assertEqual(direct_context["remit"]["responsibility"], introduction["responsibility"])
        self.assertEqual(introduction["role_pack"]["pack_id"], "otto-roles")
        self.assertEqual(introduction["effective_context"]["effective_manager_brief"]["base_manager_brief"]["schema"],
                         "otto.base-manager-brief.v1")

    def test_runtime_role_pack_root_is_inside_runtime_source(self):
        from otto.portfolio.role_context import _role_pack_locations
        project_root, pack_root = _role_pack_locations("/controller/runtime-source/otto/portfolio/role_context.py")
        self.assertEqual(project_root, Path("/controller"))
        self.assertEqual(pack_root, Path("/controller/runtime-source/otto/packs"))

    def test_installed_runtime_loads_role_pack_from_controller_root(self):
        from herzchen.packs.authoring import read_managed_pack as source_loader
        checkout = Path(__file__).resolve().parents[4]
        source_pack = source_loader("otto-roles", project_root=checkout,
            native_pack_root=checkout / "src" / "otto" / "packs")
        with tempfile.TemporaryDirectory() as temporary:
            controller = Path(temporary)
            source_root = controller / "runtime-source"
            authoring_path = source_root / "herzchen" / "packs" / "authoring.py"
            role_pack_root = source_root / "otto" / "packs" / "otto-roles"
            authoring_path.parent.mkdir(parents=True)
            role_pack_root.mkdir(parents=True)
            shutil.copyfile(Path(source_loader.__code__.co_filename), authoring_path)
            for resource in source_pack.resources:
                target = role_pack_root / resource.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(resource.content)
            shutil.copyfile(checkout / "src" / "otto" / "packs" / "otto-roles" / "pack.yaml",
                            role_pack_root / "pack.yaml")
            file_pins = {}
            for path in source_root.rglob("*"):
                if path.is_file():
                    relative = path.relative_to(source_root).as_posix()
                    file_pins[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            (controller / "runtime-manifest.json").write_text(json.dumps({
                "source_commit": "a" * 40, "files": file_pins}, sort_keys=True), encoding="utf-8")
            module_name = "otto_runtime_authoring_test"
            spec = importlib.util.spec_from_file_location(module_name, authoring_path)
            runtime_authoring = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = runtime_authoring
            try:
                spec.loader.exec_module(runtime_authoring)
                loaded = runtime_authoring.read_managed_pack("otto-roles", project_root=controller,
                    native_pack_root=source_root / "otto" / "packs")
            finally:
                sys.modules.pop(module_name, None)
            self.assertEqual(loaded.pack_id, "otto-roles")
            self.assertEqual(loaded.resources[0].source_digest, source_pack.resources[0].source_digest)

    def test_adopted_override_composes_and_unadopted_override_is_ignored(self):
        packed = {"responsibility": "pack baseline", "guidance": {"context": "pack context"},
                  "tools": ["status"]}
        adopted = self.adopted_configuration({"schema": "otto.role-configuration.v1", "roles": {},
            "role_bindings": {}, "role_policies": {"manager": "project policy"},
            "tool_entrypoints": {"manager": "project tool"}})
        composed = _compose_role(packed, adopted, "manager")
        self.assertEqual(composed["responsibility"], "pack baseline")
        self.assertEqual(composed["selected_policy"], "project policy")
        self.assertEqual(composed["tool_entrypoint"], "project tool")
        self.assertEqual(composed["selected_policy_source"], adopted["ref"])
        self.assertEqual(composed["tool_source"], adopted["ref"])
        unadopted = selected_configuration([{"ref": {"id": "loose"}, "content": {
            "role_policies": {"manager": "unadopted policy"},
            "tool_entrypoints": {"manager": "unadopted tool"}}}])
        self.assertIsNone(unadopted)
        self.assertEqual(_compose_role(packed, unadopted, "manager"), packed)

    def test_selected_role_pack_requires_exact_source_and_resource_pin(self):
        from otto.portfolio.role_context import _role_pack
        valid_content = {"schema": "otto.role-pack.v1", "adapter_role_guidance": "adapter guidance",
            "base_manager_brief": {
            "schema": "otto.base-manager-brief.v1", "mandate": "manager mandate", "constraints": ["bounded"]},
            "roles": {"manager": {"responsibility": "pack", "guidance": {"help": "help"}, "tools": [],
                                    "tool_entrypoint": "otto help", "manager_actions": []}}}
        resource = SimpleNamespace(path="roles.json", kind="role_guidance", source_digest="a" * 64,
                                   content=json.dumps(valid_content).encode())
        source = SimpleNamespace(source_revision="b" * 40, source_inventory_identity="d" * 64)
        pack = SimpleNamespace(pack_id="otto-roles", source=source, resources=(resource,))
        pack.version = "1.0.0"
        with patch("herzchen.packs.authoring.read_managed_pack", return_value=pack):
            selected, _ = _role_pack(self.adopted_configuration({"schema": "otto.role-configuration.v1", "roles": {},
                "role_bindings": {}, "role_pack": {
                "pack_id": "otto-roles", "pack_version": "1.0.0", "source_revision": "b" * 40,
                "source_inventory_identity": "d" * 64,
                "resource_path": "roles.json", "resource_digest": "a" * 64}}), "manager")
            self.assertEqual(selected["pin"]["resource_digest"], "a" * 64)
            with self.assertRaisesRegex(ValueError, "stale or inconsistent"):
                _role_pack(self.adopted_configuration({"schema": "otto.role-configuration.v1", "roles": {},
                    "role_bindings": {}, "role_pack": {
                    "pack_id": "otto-roles", "pack_version": "1.0.0", "source_revision": "old",
                    "source_inventory_identity": "d" * 64,
                    "resource_path": "roles.json", "resource_digest": "a" * 64}}), "manager")
            with self.assertRaisesRegex(ValueError, "stale or inconsistent"):
                _role_pack(self.adopted_configuration({"schema": "otto.role-configuration.v1", "roles": {},
                    "role_bindings": {}, "role_pack": {
                    "pack_id": "otto-roles", "pack_version": "1.0.0", "source_revision": "b" * 40,
                    "source_inventory_identity": "d" * 64,
                    "resource_path": "roles.json", "resource_digest": "c" * 64}}), "manager")
            invalid_contents = []
            malformed_guidance = json.loads(json.dumps(valid_content))
            malformed_guidance["roles"]["manager"]["guidance"] = {"help": None}
            invalid_contents.append(malformed_guidance)
            malformed_brief = json.loads(json.dumps(valid_content))
            malformed_brief["base_manager_brief"]["constraints"] = "not-a-list"
            invalid_contents.append(malformed_brief)
            selected_config = self.adopted_configuration({"schema": "otto.role-configuration.v1", "roles": {},
                "role_bindings": {}, "role_pack": {"pack_id": "otto-roles", "pack_version": "1.0.0",
                "source_revision": "b" * 40, "source_inventory_identity": "d" * 64,
                "resource_path": "roles.json", "resource_digest": "a" * 64}})
            for malformed in invalid_contents:
                resource.content = json.dumps(malformed).encode()
                with self.assertRaises(ValueError):
                    _role_pack(selected_config, "manager")
        with patch("herzchen.packs.authoring.read_managed_pack", side_effect=ValueError("missing")):
            with self.assertRaisesRegex(ValueError, "unavailable or changed"):
                _role_pack(self.adopted_configuration({"schema": "otto.role-configuration.v1", "roles": {},
                    "role_bindings": {}, "role_pack": {"pack_id": "missing"}}), "manager")

    def test_operating_brief_guidance_compatibility_reads_role_pack_and_appends_command(self):
        from otto.portfolio import operating_brief
        base = operating_brief._CODEX_ADAPTER_ROLE_BASE_GUIDANCE
        self.assertEqual(operating_brief._host_role_guidance({}), base)
        self.assertIn("`/installed/ottoctl`", operating_brief._host_role_guidance(
            {"OTTO_TOOL_ENTRYPOINT": "/installed/ottoctl"}))
        with patch.dict("os.environ", {"OTTO_TOOL_ENTRYPOINT": "/installed/package-ottoctl"}):
            from otto.portfolio import ROLE_OPERATING_CONTRACTS
            self.assertIn("Installed tool entrypoint: `/installed/package-ottoctl`.",
                          ROLE_OPERATING_CONTRACTS["manager"])
class RoleContextTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_fixture.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.number = 0

    def document(self, role, content):
        self.number += 1
        result = self.f.app.portfolio.create_document(self.f.project.ref.to_dict(), actor="manager",
            request_id="context-doc-" + str(self.number), document_id="context-doc-" + str(self.number),
            role=role, content=content)
        return result["record"]["payload"]["current_revision"]

    def revise(self, ref, content):
        self.number += 1
        port = self.f.app.portfolio.operations.content_port
        stable = ResourceRef(ref["authority"], ref["kind"], ref["id"])
        current = port.read(stable)
        doc = ContentDocument.from_dict(current["document"])
        revision = "rev-" + str(int(current["current_revision"]["revision"].split("-")[1]) + 1)
        value = ContentRevision(stable, revision, content, self.f.actor,
            parent_revision=current["current_revision"]["revision"])
        payload = {"document": doc, "revision": value}
        context = TransactionContext(self.f.actor, "context-revise-" + str(self.number),
            hashlib.sha256(canonical_json(payload).encode()).hexdigest(), expected_revision=value.parent_revision)
        port.execute(port.build_append_revision(context, doc, value))
        return {**ref, "revision": revision}

    def configuration(self):
        return {"schema": "otto.role-configuration.v1", "pack": "selected-fixture-pack",
                "role_bindings": {"manager": "coordinator", "orchestrator": "help", "project_advisor": "advisor"},
                "roles": {"coordinator": {"model": "gpt-test", "reasoning": "high"},
                          "help": {"model": "gpt-test", "reasoning": "high"},
                          "advisor": {"model": "gpt-test", "reasoning": "high"},
                          "worker_xhard": {"model": "configured-worker", "reasoning": "high"}},
                "tool_entrypoints": {"manager": "manager_ctl.py --help",
                                     "orchestrator": "python -m otto.portfolio.cli help --format text"}}

    def role(self, role="manager", sources=None, overrides=None):
        f = self.f
        principal = "advisor" if role == "project_advisor" else role
        assignment, guide, mandate = f.role_handles(role, principal, role + "-session")
        if sources is not None:
            instructions = "Selected pack policy: coordinate, delegate implementation to configured workers, review and bookkeep; ask for operational help when dispatch is unavailable."
            content = {"schema": "herzchen.instructions.v1", "name": "selected-" + role,
                       "entrypoint": role.upper() + ".md", "instructions": instructions,
                       "bundle_digest": hashlib.sha256(instructions.encode()).hexdigest(),
                       "export_manifest_digest": "selected-pack-manifest", "required": True,
                       "supporting_refs": sources}
            guide = self.document("role_instructions", content)
            assignment = f.app.assignments.adopt_resources(assignment.ref,
                resources=[{"resource_ref": guide, "resource_name": content["name"],
                            "content_digest": validate_instruction_content(content), "required": True}],
                expected_revision=assignment.revision, expected_generation=assignment.generation,
                logical_request_key="selected-" + role, actor=f.actor)
            old = f.app.portfolio.operations.content_port.read(ResourceRef.from_dict(mandate))["content"]
            mandate = self.document("mandate", {**old, "assignment_ref": assignment.ref.to_dict()})
        request = dict(role=role, project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            assignment_ref=assignment.ref.to_dict(), generation=assignment.generation, mandate_ref=mandate,
            request_key="sparse-" + role, profile="workspace-write" if role == "manager" else "read-only")
        if sources is None:
            request.update(model="gpt-test", reasoning="high")
        request.update(overrides or {})
        prepared = f.app.prepare_role(**request)
        self.assertEqual(prepared["outcome"], "committed", prepared)
        return assignment, prepared["schedule_id"], request

    def setup(self, schedules, *, advisor=False):
        return {"schema": "otto.operating-setup.v1", "mode": "manual", "roles": schedules,
                "advisor_policy": {"mode": "enabled"} if advisor else
                    {"mode": "disabled", "reason": "No advisor execution allowance selected"},
                "acceptance_tasks": []}

    def packet(self, index=-1):
        match = re.search(r'<otto-resource-brief[^>]*>\s*(.*?)\s*</otto-resource-brief>',
                          self.f.provider.calls[index], re.S)
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

    def strict_manager_context(self, *, guide=True, supervisor=True):
        standard = self.document("skill", {"text": "Canonical manager duties and blocker receipt contract"})
        content = self.f.owner.content.read(ResourceRef.from_dict(standard))["content"]
        pin = {"ref": standard, "content_sha256": hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()}
        recipient = {"project_ref": self.f.project.ref.to_dict(), "assignment_ref": {"authority": self.f.actor.authority, "kind": "wrk.assignment", "id": "root", "revision": "rev-1"}, "generation": 1, "principal": "root", "conversation_ref": {"host": "codex", "native_id": "root-chat"}}
        config = dict(self.configuration(), manager_context_required=True)
        if guide: config["standard_manager_guide"] = pin
        if supervisor: config["operational_supervisor"] = recipient
        self.f.app.runtime._manager_supervisor = lambda _project: recipient if supervisor else None
        ref = self.document("run_configuration", config)
        return [ref, standard], recipient

    def test_enrolled_manager_default_derives_standard_context_without_config_flag(self):
        sources, recipient = self.strict_manager_context()
        configuration = self.f.owner.content.read(ResourceRef.from_dict(sources[0]))["content"]
        for key in ("manager_context_required", "standard_manager_guide", "operational_supervisor"):
            configuration.pop(key)
        sources[0] = self.document("run_configuration", configuration)
        self.f.project = self.f.owner.graph.create_project(title="New enrolled project", metadata={"otto_orchestrator": {"assignment_ref": recipient["assignment_ref"], "generation": 1}}, logical_request_key="enrolled-manager")
        self.f.task = self.f.owner.graph.create_task(self.f.project.ref, title="First useful task", logical_request_key="enrolled-first-task")
        self.f.compose()
        recipient["project_ref"] = self.f.project.ref.to_dict()
        self.f.app.runtime._manager_supervisor = lambda _: recipient
        _manager, schedule, request = self.role(sources=sources)
        result = self.f.app.start(schedule_id=schedule)
        self.assertEqual(result["outcome"], "succeeded", result.get("error"))
        context = self.packet()["operating_core"]["introduction"]["manager_operating_context"]
        self.assertEqual(context["operational_supervisor"], recipient)
        self.assertEqual(context["standard_manager_guide"]["ref"], context["base_resource"])
        self.assertTrue(context["standard_manager_guide"]["standard_contract_sha256"])

    def test_new_manager_custom_mandate_cannot_omit_standard_context(self):
        sources, recipient = self.strict_manager_context()
        _manager, schedule, request = self.role(sources=sources, overrides={"instruction": "Custom project inventory, then return"})
        self.assertEqual(self.f.app.start(schedule_id=schedule)["outcome"], "succeeded")
        context = self.packet()["operating_core"]["introduction"]["manager_operating_context"]
        self.assertEqual(context["operational_supervisor"], recipient)
        self.assertEqual(context["standard_manager_guide"]["ref"], sources[1])
        from otto.agents.orchestrator_route import prepare_canonical_assignment_role_brief
        runtime = self.f.app.runtime
        callback = prepare_canonical_assignment_role_brief(role="manager", project_ref=request["project_ref"], task_ref=request["task_ref"], assignment_ref=request["assignment_ref"], mandate_ref=request["mandate_ref"], expected_generation=1, project_reader=runtime._project_reader(request["project_ref"]), task_reader=runtime._task_reader(request["project_ref"], request["task_ref"]), assignment_reader=runtime._assignment_reader(request["assignment_ref"]), mandate_reader=runtime._mandate_reader(request["project_ref"], request["mandate_ref"]), resource_reader=runtime.operations.content_port, lifecycle="callback", as_of=self.f.app._now(), include_role_context=False, direction_context_reader=runtime.operations.direction_context_reader, supervisor_reader=lambda: recipient)
        self.assertEqual(callback["brief"]["operating_core"]["introduction"]["manager_operating_context"]["operational_supervisor"], recipient)

    def test_new_manager_missing_standard_guide_or_supervisor_is_pre_effect(self):
        for guide, supervisor in ((False, True), (True, False)):
            with self.subTest(guide=guide, supervisor=supervisor):
                case = RoleContextTests(); case.setUp(); self.addCleanup(case.doCleanups)
                sources, _ = case.strict_manager_context(guide=guide, supervisor=supervisor)
                _manager, schedule, _ = case.role(sources=sources, overrides={"instruction": "Custom mandate cannot remove manager duties"})
                result = case.f.app.start(schedule_id=schedule)
                self.assertEqual(result["outcome"], "partial")
                self.assertIn("requires its adopted standard guide and current supervisor", result["error"]["message"])
                self.assertEqual(case.f.provider.calls, [])

    def test_new_manager_changed_supervisor_is_not_config_authority(self):
        sources, recipient = self.strict_manager_context()
        self.f.app.runtime._manager_supervisor = lambda _: {**recipient, "generation": 2}
        _manager, schedule, _ = self.role(sources=sources)
        result = self.f.app.start(schedule_id=schedule)
        self.assertEqual(result["outcome"], "partial")
        self.assertIn("differs from current authenticated", result["error"]["message"])
        self.assertEqual(self.f.provider.calls, [])

    def test_sparse_role_receives_selected_policy_sources_bindings_and_disabled_advisor(self):
        f = self.f
        configuration = self.document("run_configuration", self.configuration())
        goal = self.document("goal", {"text": "Deliver the adopted outcome under owner constraints"})
        skill = self.document("skill", {"text": "Maintained delegation and operational-help guidance"})
        _manager, schedule, _request = self.role(sources=[configuration, goal, skill])
        due = f.app._read(schedule)
        self.assertEqual(due.context_refs, (due.context_refs[0], due.target["mandate_ref"], configuration, goal, skill))
        self.assertEqual(due.target["native_id"], "manager-session")
        self.assertEqual(due.target["execution_selection"]["model"], {"source": "selected_configuration", "ref": configuration})
        setup = self.setup({"manager": schedule})
        prepared = f.app.prepare_operating_setup(project_ref=f.project.ref.to_dict(), setup=setup, request_key="sparse-setup")
        self.assertEqual(prepared["outcome"], "prepared", prepared)
        self.assertEqual(f.provider.calls, [])

        intro = prepared["readiness"]["introductions"]["manager"]
        self.assertEqual(intro["current_task"]["ref"], f.task.ref.to_dict())
        self.assertEqual(intro["goal"]["title"], "Useful project")
        self.assertEqual(intro["tool_entrypoint"], "manager_ctl.py --help")
        result = f.app.activate_operating_setup(project_ref=f.project.ref.to_dict())
        self.assertEqual(result["outcome"], "succeeded", {k: result.get(k) for k in ("stage", "error", "next_action")})
        packet = self.packet()
        manager_context = packet["operating_core"]["introduction"]["manager_operating_context"]
        self.assertEqual(manager_context["project_ref"], f.project.ref.to_dict())
        self.assertEqual(manager_context["task_ref"], f.task.ref.to_dict())
        self.assertEqual(manager_context["tool_entrypoint"], "manager_ctl.py --help")
        self.assertIn("retain the issue and delivery receipt", manager_context["instructions"])
        self.assertIn("not submission", manager_context["instructions"])
        self.assertEqual(packet["operating_core"]["introduction"]["effective_context"]["manager_operating_context"], manager_context)
        self.assertIn("delegate implementation", packet["operating_core"]["operating_contract"])
        installed_evidence = packet["operating_core"]["introduction"]["operating_guidance"]["installed_evidence"]
        self.assertIn("criteria that explicitly require installed behavior", installed_evidence)
        self.assertIn("request operational help", installed_evidence)
        self.assertIn("ordinary REWORK finding", installed_evidence)
        self.assertEqual(packet["context"]["selected_configuration"]["ref"], configuration)
        self.assertEqual([s["ref"] for s in packet["context"]["supporting_context"]], [configuration, goal, skill])
        operating = packet["context"]["operating_setup"]
        self.assertEqual(operating["advisor_policy"], setup["advisor_policy"])
        self.assertFalse(operating["operational_help"]["ready"])
        self.assertEqual(operating["roles"]["manager"]["conversation_id"], "manager-session")


    def test_selected_role_pack_is_pinned_and_adopted_override_wins(self):
        """The canonical configuration adopts both pack bytes and project override."""
        selected = RolePackSelectorTests().native_role_pin()
        configuration = dict(self.configuration(), role_pack=selected,
                              role_policies={"manager": "Adopted project override wins."},
                              tool_entrypoints={"manager": "project-manager-tool"})
        source = self.document("run_configuration", configuration)
        _manager, schedule, _request = self.role(sources=[source])
        self.f.app.start(schedule_id=schedule)
        introduction = self.packet()["operating_core"]["introduction"]
        self.assertEqual(introduction["selected_policy"], "Adopted project override wins.")
        self.assertEqual(introduction["tool_entrypoint"], "project-manager-tool")
        self.assertEqual(introduction["role_pack"]["source_revision"], selected["source_revision"])

    def test_unadopted_role_pack_or_project_override_is_refused(self):
        selected = RolePackSelectorTests().native_role_pin()
        configuration = dict(self.configuration(), role_pack={**selected, "source_revision": "stale-source"})
        source = self.document("run_configuration", configuration)
        _manager, schedule, _request = self.role(sources=[source])
        result = self.f.app.start(schedule_id=schedule)
        self.assertNotEqual(result["outcome"], "succeeded")
        self.assertEqual(self.f.provider.calls, [])

    def test_explicit_overrides_retain_configuration_and_provenance(self):
        config = self.configuration()
        config["roles"]["coordinator"] = {"model": "configured-model", "reasoning": "low"}
        ref = self.document("run_configuration", config)
        _manager, schedule, _request = self.role(sources=[ref], overrides={"model": "gpt-test", "reasoning": "high"})
        due = self.f.app._read(schedule)
        self.assertEqual(due.requested_model, "gpt-test")
        self.assertEqual(due.target["execution_selection"]["model"]["source"], "explicit_override")
        result = self.f.app.start(schedule_id=schedule)
        self.assertEqual(result["outcome"], "succeeded", {k: result.get(k) for k in ("stage", "error", "next_action")})
        self.assertEqual(self.packet()["context"]["selected_configuration"]["ref"], ref)
        self.assertEqual(self.packet()["context"]["operating_setup"]["current_execution"]["model"], "gpt-test")

    def test_selected_manager_policy_is_provenance_bearing_and_not_a_core_default(self):
        for selected in ("Megado: delegate normal implementation to worker_normal and justified XHARD to worker_xhard.",
                         "Other pack: the manager implements directly under this project's policy."):
            with self.subTest(policy=selected):
                case = RoleContextTests(); case.setUp(); self.addCleanup(case.doCleanups)
                config = case.configuration(); config["role_policies"] = {"manager": selected}
                ref = case.document("run_configuration", config)
                _manager, schedule, _request = case.role(sources=[ref])
                result = case.f.app.start(schedule_id=schedule)
                self.assertEqual(result["outcome"], "succeeded", result.get("error"))
                intro = case.packet()["operating_core"]["introduction"]
                self.assertEqual(intro["selected_policy"], selected)
                self.assertEqual(intro["selected_policy_source"], ref)
                self.assertNotIn("worker_normal", intro["responsibility"])
                self.assertNotIn("worker_xhard", intro["responsibility"])
        _manager, schedule, _request = self.role()
        self.assertEqual(self.f.app.start(schedule_id=schedule)["outcome"], "succeeded")
        self.assertIsNone(self.packet()["operating_core"]["introduction"]["selected_policy"])

    def test_ordinary_worker_inherits_current_adopted_configuration_and_installed_command(self):
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        config = self.configuration()
        config["role_bindings"]["worker"] = "worker_normal"
        config["roles"]["worker_normal"] = {"model": "gpt-test", "reasoning": "high"}
        command = "/verified/python3 /verified/controller/manager_ctl.py help --format text"
        config["tool_entrypoints"]["worker"] = command
        ref = self.document("run_configuration", config)
        manager, _schedule, _request = self.role(sources=[ref])
        f = self.f; root = Path(f.temporary.name).resolve()
        (root / "run.yaml").write_text(json.dumps({"roles": {
            "worker_normal": {"model": "gpt-test", "reasoning": "high"},
            "worker_xhard": {"model": "gpt-xhard-test", "reasoning": "high"}}}))
        state = {"project_ref": f.project.ref.to_dict(), "task_refs": {"S06": f.task.ref.to_dict()},
            "assignment_ref": manager.ref.to_dict(), "manager_generation": manager.generation, "manager": "manager"}
        host = SimpleNamespace(_closing=False, submit=lambda _: {"outcome": "admitted"})
        server = SimpleNamespace(owner=f.owner, portfolio=f.app.portfolio, state=state,
            due_port=f.port, _execution=lambda **_: f.app, _save_state=lambda: None)
        service = ManagerJourneyService(server=server, host=host, workspace=root, run_path=root)
        request = {"command": "run-worker", "task": "S06", "route": "normal", "principal": "worker",
            "request_key": "selected-worker", "focus": "Read the delivered installed command"}
        prepared = service._submit_worker(request)
        self.assertEqual(prepared["outcome"], "admitted", prepared)
        self.assertEqual(f.provider.calls, [])
        self.assertEqual(f.app._read(prepared["schedule_id"]).context_refs[2:], (ref,))
        self.assertEqual(f.app.start(schedule_id=prepared["schedule_id"])["outcome"], "succeeded")
        intro = self.packet()["operating_core"]["introduction"]
        self.assertEqual(intro["tool_entrypoint"], command)
        self.assertEqual(intro["tool_entrypoint_source"], ref)
        # A selected default worker slot does not replace the explicit XHARD
        # route. Both receive the same adopted policy/host command provenance.
        f.app.runtime.adapter.requested_model = "gpt-xhard-test"
        xhard = service._submit_worker({**request, "route": "xhard", "request_key": "xhard-worker", "principal": "xhard"})
        due = f.app._read(xhard["schedule_id"])
        self.assertEqual(due.requested_model, "gpt-xhard-test")
        self.assertEqual(due.target["execution_selection"]["model"],
            {"source": "explicit_override", "selected_configuration_ref": ref})
        self.assertEqual(f.app.start(schedule_id=due.schedule_id)["outcome"], "succeeded")
        self.assertEqual(self.packet()["operating_core"]["introduction"]["tool_entrypoint"], command)
        self.assertEqual(self.packet()["context"]["operating_setup"]["current_execution"]["model"], "gpt-xhard-test")
        calls = len(f.provider.calls)
        retained = service._submit_worker({**request, "route": "xhard", "request_key": "xhard-worker", "principal": "xhard"})
        self.assertEqual(retained["outcome"], "replayed")
        self.assertEqual(len(f.provider.calls), calls)
        before = len(f.port.list_due())
        self.revise(ref, {**config, "changed": "new command requires readoption"})
        with self.assertRaisesRegex(ValueError, "stale"):
            service._submit_worker({**request, "request_key": "new-worker", "principal": "next-worker"})
        self.assertEqual(len(f.port.list_due()), before)
        self.assertEqual(len(f.provider.calls), 2)

    def test_required_source_missing_rejects_sparse_preparation_without_due_or_provider(self):
        missing = {"authority": self.f.actor.authority, "kind": "dat.content.document", "id": "missing-goal", "revision": "rev-1"}
        with self.assertRaisesRegex(ValueError, "supporting context.*missing"):
            self.role(sources=[missing])
        self.assertEqual(self.f.provider.calls, [])
        self.assertFalse(any(d["role"] == "manager" for d in self.f.port.list_due()))

    def test_missing_config_has_no_silent_model_or_instruction_fallback(self):
        with self.assertRaisesRegex(ValueError, "adopted role configuration"):
            self.role(sources=[])
        self.assertEqual(self.f.provider.calls, [])

    def test_goal_plan_skill_or_run_revision_rejects_future_delivery_before_claim(self):
        for kind in ("goal", "plan", "skill", "run_configuration"):
            with self.subTest(kind=kind):
                # Each variant has a separate fixture because role identities
                # are durable, not disposable retries of the same request key.
                case = RoleContextTests()
                case.setUp()
                self.addCleanup(case.doCleanups)
                ref = case.document(kind, case.configuration())
                _manager, schedule, _request = case.role(sources=[ref])
                case.revise(ref, {**case.configuration(), "changed": kind})
                result = case.f.app.start(schedule_id=schedule)
                self.assertEqual(result["outcome"], "partial", result)
                self.assertIn("stale", result["error"]["message"])
                self.assertIsNone((case.f.port.read_due(schedule)["host_evidence"] or {}).get("gateway_attempt"))
                self.assertEqual(case.f.provider.calls, [])

    def test_current_binding_cannot_be_overridden_by_admission_or_recipient_prose(self):
        _manager, schedule, _request = self.role()
        due = self.f.app._resources(self.f.app._read(schedule))
        changed = replace(due, target={**due.target, "native_id": "foreign-session"},
                          host_evidence={**(due.host_evidence or {}), "gateway_attempt": {"delivery_admission": {"physical_session_id": "foreign-session"}}})
        self.f.port.save_due(schedule, changed.to_dict(), request_id="wrong-native", expected_version=due.version)
        decision = evaluate_setup(self.f.app.runtime, self.f.project.ref.to_dict(), self.setup({"manager": schedule}))
        self.assertFalse(decision["ready"])
        self.assertIn("current assignment binding", json.dumps(decision["blockers"]))
        due = self.f.app._read(schedule)
        self.f.port.save_due(schedule, replace(due, target={**due.target, "native_id": "manager-session"},
            recipient="name-in-prose").to_dict(), request_id="wrong-recipient", expected_version=due.version)
        decision = evaluate_setup(self.f.app.runtime, self.f.project.ref.to_dict(), self.setup({"manager": schedule}))
        self.assertFalse(decision["ready"])
        self.assertIn("canonical principal", json.dumps(decision["blockers"]))
        self.assertEqual(self.f.provider.calls, [])

    def test_enabled_advisor_pairing_and_all_role_packets_use_actual_conversations(self):
        f = self.f
        configuration = self.document("run_configuration", self.configuration())
        manager, manager_schedule, _ = self.role(sources=[configuration])
        orchestrator, help_schedule, _ = self.role("orchestrator", sources=[configuration])
        advisor, advisor_schedule, _ = self.role("project_advisor", sources=[configuration])
        pool = LimitService(f.store).create_pool(ResourceRef(f.actor.authority, "limit", "context-advisor"),
            capacity_units=1, cumulative_allowance_units=2, logical_request_key="context-advisor-pool", actor=f.actor)
        due = f.app._read(advisor_schedule)
        f.port.save_due(advisor_schedule, replace(due, allowance_ref=pool.ref.to_dict()).to_dict(),
                       request_id="bind-advisor-allowance", expected_version=due.version)
        setup = self.setup({"manager": manager_schedule, "orchestrator": help_schedule,
                            "project_advisor": advisor_schedule}, advisor=True)
        prepared = f.app.prepare_operating_setup(project_ref=f.project.ref.to_dict(), setup=setup, request_key="all-roles")
        self.assertEqual(prepared["outcome"], "prepared", prepared)
        pairing = prepared["readiness"]["advisor_pairing"]
        self.assertEqual(pairing["manager_ref"], manager.ref.to_dict())
        self.assertEqual(pairing["advisor_ref"], advisor.ref.to_dict())
        for role, schedule in setup["roles"].items():
            result = f.app.start(schedule_id=schedule)
            self.assertEqual(result["outcome"], "succeeded", {k: result.get(k) for k in ("stage", "error", "next_action")})
            packet = self.packet()
            self.assertEqual(packet["operating_core"]["introduction"]["role"], role)
            context = packet["context"]["operating_setup"]
            self.assertEqual(context["advisor_pairing"], pairing)
            self.assertEqual(context["roles"][role]["conversation_id"], role + "-session")
        self.assertEqual(len(f.provider.calls), 3)
        f.app.assignments.assign(f.project.ref, role="manager", principal="replacement",
            manager="manager", session="replacement-session", logical_request_key="duplicate-manager", actor=f.actor)
        decision = evaluate_setup(f.app.runtime, f.project.ref.to_dict(), setup)
        self.assertFalse(decision["ready"])
        self.assertIn("exactly one active manager", json.dumps(decision["blockers"]))

    def test_continuation_receives_same_adopted_policy_and_current_occurrence(self):
        f = self.f
        config = self.document("run_configuration", self.configuration())
        assignment, schedule, _ = self.role(sources=[config])
        first = f.app.start(schedule_id=schedule)
        self.assertEqual(first["outcome"], "succeeded", first.get("error"))
        first_packet = self.packet()
        before = f.port.read_due(schedule)
        f.app.assignments.append_report(assignment.ref,
            {"schema": "otto.manager-progress.v1", "project_ref": f.project.ref.to_dict(),
             "task_alias": "task", "continue_requested": True, "next_action": "Review the next worker result",
             "logical_request_key": "context-next", "recorded_at": f.app._now()},
            expected_generation=1, logical_request_key="context-progress", actor=f.actor)
        continued = f.app.continue_manager(schedule_id=schedule)
        self.assertEqual(continued["outcome"], "succeeded", continued.get("error"))
        packet = self.packet()
        self.assertEqual(packet["operating_core"]["operating_contract"], first_packet["operating_core"]["operating_contract"])
        self.assertEqual(packet["context"]["selected_configuration"]["ref"], config)
        self.assertEqual(packet["context"]["operating_setup"]["current_execution"]["selection"],
                         first_packet["context"]["operating_setup"]["current_execution"]["selection"])
        self.assertEqual(f.port.read_due(schedule), before)
        self.assertEqual(continued["result"]["physical_session_id"], "manager-session")
        self.assertEqual(len(f.provider.calls), 2)

    def test_explicit_source_adoption_refreshes_future_packet_and_preserves_admitted_turn(self):
        f = self.f
        config = self.document("run_configuration", self.configuration())
        goal = self.document("goal", {"text": "Original adopted goal"})
        assignment, schedule, request = self.role(sources=[config, goal])
        first = f.app.start(schedule_id=schedule)
        self.assertEqual(first["outcome"], "succeeded", first.get("error"))
        original_packet = self.packet()
        original_due = f.port.read_due(schedule)
        goal = self.revise(goal, {"text": "Amended adopted goal"})
        guide = original_due["context_refs"][0]
        content = f.app.portfolio.operations.content_port.read(ResourceRef.from_dict(guide))["content"]
        content = {**content, "supporting_refs": [config, goal]}
        guide = self.revise(guide, content)
        assignment = f.app.assignments.adopt_resources(assignment.ref,
            resources=[{"resource_ref": guide, "resource_name": content["name"],
                        "content_digest": validate_instruction_content(content), "required": True}],
            expected_revision=assignment.revision, expected_generation=1, logical_request_key="adopt-amended-goal", actor=f.actor)
        old_mandate = f.app.portfolio.operations.content_port.read(ResourceRef.from_dict(request["mandate_ref"]))["content"]
        mandate = self.document("mandate", {**old_mandate, "assignment_ref": assignment.ref.to_dict()})
        prepared = f.app.prepare_role(**{**request, "assignment_ref": assignment.ref.to_dict(),
            "mandate_ref": mandate, "request_key": "amended-future-turn"})
        self.assertEqual(prepared["outcome"], "committed", prepared)
        future = f.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(future["outcome"], "succeeded", future.get("error"))
        packet = self.packet()
        self.assertEqual(packet["context"]["supporting_context"][1]["content"]["text"], "Amended adopted goal")
        self.assertEqual(packet["operating_core"]["introduction"]["mandate_ref"], mandate)
        self.assertEqual(f.port.read_due(schedule), original_due)
        self.assertEqual(self.packet(0), original_packet)
        self.assertEqual(len(f.provider.calls), 2)

    def test_task_goal_mandate_and_assignment_changes_reject_unadmitted_turn(self):
        for kind in ("task", "project", "mandate", "assignment"):
            with self.subTest(kind=kind):
                case = RoleContextTests()
                case.setUp()
                self.addCleanup(case.doCleanups)
                f = case.f
                assignment, schedule, request = case.role()
                if kind in {"task", "project"}:
                    record = getattr(f, kind)
                    f.owner.graph.revise(record.ref, title="Amended canonical " + kind,
                                         logical_request_key="amend-" + kind, actor=f.actor)
                elif kind == "mandate":
                    raw = f.app.portfolio.operations.content_port.read(ResourceRef.from_dict(request["mandate_ref"]))["content"]
                    case.revise(request["mandate_ref"], {**raw, "brief": {"role": "manager", "mandate": "Amended mandate"}})
                else:
                    f.app.assignments.reassign(assignment.ref, principal="replacement", session="replacement-session",
                        expected_generation=1, logical_request_key="replace-manager", actor=f.actor)
                result = f.app.start(schedule_id=schedule)
                self.assertEqual(result["outcome"], "partial", result.get("error"))
                self.assertEqual(f.provider.calls, [])
                self.assertIsNone((f.port.read_due(schedule)["host_evidence"] or {}).get("gateway_attempt"))

    def test_replacement_packet_uses_current_generation_principal_and_conversation(self):
        f = self.f
        config = self.document("run_configuration", self.configuration())
        assignment, schedule, request = self.role(sources=[config])
        first = f.app.start(schedule_id=schedule)
        self.assertEqual(first["outcome"], "succeeded", first.get("error"))
        before = f.port.read_due(schedule)
        replacement = f.app.assignments.reassign(assignment.ref, principal="replacement",
            session="replacement-session", expected_generation=1, logical_request_key="current-replacement", actor=f.actor)
        old = f.app.portfolio.operations.content_port.read(ResourceRef.from_dict(request["mandate_ref"]))["content"]
        contract = old["instruction_contract"]
        mandate = self.document("mandate", {**old, "assignment_ref": replacement.ref.to_dict(),
            "generation": replacement.generation, "instruction_contract": {**contract,
                "authority": {**contract["authority"], "owner_actor": "replacement"}}})
        prepared = f.app.prepare_role(**{**request, "assignment_ref": replacement.ref.to_dict(),
            "generation": replacement.generation, "mandate_ref": mandate, "request_key": "replacement-packet"})
        self.assertEqual(prepared["outcome"], "committed", prepared)
        result = f.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(result["outcome"], "succeeded", result.get("error"))
        intro = self.packet()["operating_core"]["introduction"]
        self.assertEqual(intro["principal"], "replacement")
        self.assertEqual(intro["generation"], 2)
        self.assertEqual(intro["assignment_ref"], replacement.ref.to_dict())
        self.assertEqual(result["result"]["physical_session_id"], "replacement-session")
        self.assertEqual(f.port.read_due(schedule), before)

    def test_context_race_rejects_packet_even_when_reader_reuses_a_mutable_mapping(self):
        from otto.agents.orchestrator_route import prepare_canonical_assignment_role_brief
        f = self.f
        _assignment, schedule, _request = self.role()
        due = f.app._read(schedule)
        target, runtime = due.target, f.app.runtime
        observed = {"revision": 0}
        def context():
            observed["revision"] += 1
            return observed
        with self.assertRaisesRegex(ValueError, "role context changed"):
            prepare_canonical_assignment_role_brief(role="manager", project_ref=target["project_ref"],
                task_ref=target["task_ref"], assignment_ref=due.assignment_ref, mandate_ref=target["mandate_ref"],
                expected_generation=1, lifecycle="resume", as_of=due.anchor,
                project_reader=runtime._project_reader(target["project_ref"]),
                task_reader=runtime._task_reader(target["project_ref"], target["task_ref"]),
                assignment_reader=runtime._assignment_reader(due.assignment_ref),
                mandate_reader=runtime._mandate_reader(target["project_ref"], target["mandate_ref"]),
                resource_reader=runtime.operations.content_port, operating_context_reader=context)
        self.assertEqual(f.provider.calls, [])

    def test_existing_explicit_preparation_identity_replays_without_new_provenance(self):
        f = self.f
        _assignment, schedule, request = self.role()
        due = f.app._read(schedule)
        original = [due.role, due.target["project_ref"], due.target["task_ref"], due.assignment_ref,
                    due.generation, due.target["mandate_ref"], due.context_refs, due.instruction,
                    due.requested_model, due.requested_reasoning, due.profile, due.target["native_id"],
                    due.timeout_seconds, due.allowance_ref]
        digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(due.invocation_identity, request["request_key"] + ":" + digest)
        # A pre-S02 occurrence has the same semantic identity and no selection
        # projection. Replaying it must preserve that existing target.
        target = {key: value for key, value in due.target.items() if key != "execution_selection"}
        f.port.save_due(schedule, replace(due, target=target).to_dict(), request_id="legacy-role-target", expected_version=due.version)
        replay = f.app.prepare_role(**{**request, "instruction": due.instruction,
            "context_refs": due.context_refs, "native_session_id": due.target["native_id"]})
        self.assertEqual(replay["schedule_id"], schedule)
        self.assertNotIn("execution_selection", f.app._read(schedule).target)
        self.assertEqual(f.provider.calls, [])

    def test_pre_s02_retained_worker_packet_settles_without_provider_replay(self):
        from unittest.mock import patch
        from otto.agents import orchestrator_route
        f = self.f
        prepared = f.app.assign_worker(**f.request())
        current = orchestrator_route.prepare_canonical_assignment_role_brief
        def legacy_packet(**kwargs):
            return current(**{**kwargs, "include_role_context": False, "operating_context_reader": None})
        with patch.object(orchestrator_route, "prepare_canonical_assignment_role_brief", legacy_packet):
            first = f.app.start(schedule_id=prepared["schedule_id"], settle=False)
        self.assertEqual(first["outcome"], "succeeded", first.get("error"))
        self.assertNotIn("introduction", self.packet()["operating_core"])
        self.assertNotIn("supporting_context", self.packet()["context"])
        before = ((f.port.read_due(prepared["schedule_id"])["host_evidence"] or {})["gateway_attempt"])
        settled = f.app.recover(schedule_id=prepared["schedule_id"], execute=False)
        self.assertEqual(settled["outcome"], "succeeded", settled.get("error"))
        after = ((f.port.read_due(prepared["schedule_id"])["host_evidence"] or {})["gateway_attempt"])
        self.assertEqual(after["result"], before["result"])
        self.assertEqual(after["delivery_authorization"], before["delivery_authorization"])
        self.assertEqual(len(f.provider.calls), 1)


if __name__ == "__main__":
    unittest.main()
