"""D01 through real disposable owner/DAT/Due ports; no provider dispatch."""
import argparse
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from herzchen.kernel.store import Store
from otto.portfolio.operating_composition import SCHEMA
from otto.portfolio.operating_setup import OperatingSetupError, setup_reference
from otto.portfolio.execution_host import _nested_capability
from otto.portfolio.manager_journey_client import add_manager_journey_parsers
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.tests import test_role_context as context_fixture
from tests import test_execution_application as owner_fixture


class PortProxy:
    def __init__(self, port, **overrides):
        self.port, self.overrides = port, overrides

    def __getattr__(self, name):
        return self.overrides.get(name, getattr(self.port, name))


class OperatingCompositionTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_fixture.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.manager, self.guide, self.mandate = self.f.role_handles("manager", "manager", "manager-session")

    def config(self):
        return {"schema": SCHEMA, "mode": "manual", "defaults": {"model": "gpt-test", "reasoning": "high"},
            "roles": {"manager": {"assignment_ref": self.manager.ref.to_dict(), "generation": 1,
                "task_ref": self.f.task.ref.to_dict(), "mandate_ref": self.mandate}},
            "advisor_policy": {"mode": "disabled", "reason": "Owner supervises this fixture"}, "acceptance_tasks": []}

    def call(self, operation="preview", setup=None, key="composition", expected=None):
        return self.f.app.compose_operating_setup(project_ref=self.f.project.ref.to_dict(), operation=operation,
            setup=setup or self.config(), request_key=key, expected_setup_ref=expected)

    def test_preview_apply_read_update_and_old_replay_preserve_canonical_records(self):
        f = self.f
        before = f.store.consumer().snapshot_counts()
        preview = self.call()
        self.assertEqual(preview["outcome"], "preview", preview)
        self.assertEqual(f.store.consumer().snapshot_counts(), before)
        role = preview["records"]["manager"]
        self.assertEqual(role["conversation_id"], "manager-session")
        self.assertEqual(role["assignment_ref"], self.manager.ref.to_dict())
        self.assertIsNone(f.port.read_due(role["schedule_id"]))
        applied = self.call("apply")
        self.assertEqual(applied["outcome"], "applied", applied)
        read = f.app.read_operating_setup(project_ref=f.project.ref.to_dict())
        self.assertEqual(read["setup"], applied["setup"])
        self.assertEqual(read["setup_ref"], applied["setup_ref"])
        counts = f.store.consumer().snapshot_counts()
        self.assertEqual(self.call("apply")["outcome"], "replayed")
        self.assertEqual(f.store.consumer().snapshot_counts(), counts)
        update = self.config()
        update["roles"]["manager"]["reasoning"] = "medium"
        checked = self.call(setup=update, key="change", expected=read["setup_ref"])
        self.assertEqual(checked["records"]["manager"]["execution"]["reasoning"], "medium")
        changed = self.call("update", update, "change", read["setup_ref"])
        self.assertEqual(changed["outcome"], "updated", changed)
        self.assertNotEqual(changed["setup_ref"], applied["setup_ref"])
        history = f.owner.content.read(ResourceRef.from_dict(applied["setup_ref"]))
        self.assertEqual(history["content"], applied["setup"])
        old = self.call("apply")
        self.assertEqual(old["setup_ref"], applied["setup_ref"])
        self.assertEqual(old["current_setup_ref"], changed["setup_ref"])
        self.assertEqual(f.provider.calls, [])

    def test_stale_update_and_changed_key_fail_without_writes(self):
        first = self.call("apply")
        setup = self.config()
        setup["advisor_policy"]["reason"] = "Changed reason"
        updated = self.call("update", setup, "change", first["setup_ref"])
        counts = self.f.store.consumer().snapshot_counts()
        with self.assertRaisesRegex(OperatingSetupError, "revision is stale"):
            self.call("update", setup, "stale", first["setup_ref"])
        with self.assertRaisesRegex(OperatingSetupError, "changed setup input"):
            self.call("apply", setup)
        with self.assertRaisesRegex(Exception, "setup already exists"):
            self.f.app.prepare_operating_setup(
                project_ref=self.f.project.ref.to_dict(), setup={**updated["setup"], "advisor_policy":
                    {"mode": "disabled", "reason": "overwrite"}}, request_key="overwrite")
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)

    def test_invalid_second_role_is_rejected_before_first_role_effect(self):
        setup = self.config()
        setup["roles"]["orchestrator"] = deepcopy(setup["roles"]["manager"])
        before = self.f.store.consumer().snapshot_counts()
        with self.assertRaisesRegex(ValueError, "role differs"):
            self.call("apply", setup)
        self.assertEqual(self.f.store.consumer().snapshot_counts(), before)
        bad = self.config()
        bad["roles"]["manager"]["generation"] = 2
        with self.assertRaisesRegex(ValueError, "generation is stale"):
            self.call("apply", bad)
        self.assertEqual(self.f.store.consumer().snapshot_counts(), before)

    def test_partial_due_resource_reconciliation_recovers_same_handles_after_restart(self):
        f = self.f
        def interrupt(*args, **kwargs):
            raise RuntimeError("fixture interruption")
        with patch.object(f.app, "due_port", PortProxy(f.port, reconcile_assignment_resources=interrupt)):
            partial = self.call("apply")
        self.assertEqual(partial["outcome"], "partial", partial)
        self.assertEqual(partial["stage"], "role:manager")
        schedule = partial["handles"]["manager"]["schedule_id"]
        self.assertIsNotNone(f.port.read_due(schedule))
        self.assertEqual(f.owner.content.read(setup_reference(f.project.ref.to_dict())), {})
        f.store.close()
        f.store = Store.open(f.path, authority="execution-owner", expected_domains=tuple(sorted(f.domains, key=lambda d: d.domain_id)))
        f.compose()
        before = f.store.consumer().snapshot_counts()
        preview = self.call()
        self.assertEqual(preview["outcome"], "preview", preview)
        self.assertEqual(f.store.consumer().snapshot_counts(), before)
        result = self.call("apply")
        self.assertEqual(result["outcome"], "applied", result)
        self.assertEqual(result["setup"]["roles"]["manager"], schedule)
        self.assertEqual(f.provider.calls, [])

    def test_committed_setup_response_loss_replays_exact_receipt(self):
        f = self.f
        execute = f.owner.content.command_port.execute
        def interrupted(envelope):
            receipt = execute(envelope)
            if envelope.context.logical_request_key == "composition:setup":
                raise RuntimeError("lost response after commit")
            return receipt
        with patch.object(f.app.portfolio.operations, "content_port", PortProxy(f.owner.content.command_port, execute=interrupted)):
            result = self.call("apply")
        self.assertEqual(result["outcome"], "partial", result)
        before = f.store.consumer().snapshot_counts()
        replay = self.call("apply")
        self.assertEqual(replay["outcome"], "replayed", replay)
        self.assertEqual(f.store.consumer().snapshot_counts(), before)
        self.assertEqual(replay["setup_ref"], f.app.read_operating_setup(project_ref=f.project.ref.to_dict())["setup_ref"])

    def test_unknown_paused_and_stopped_occurrences_are_read_only_holds(self):
        f = self.f
        request = {**self.config()["roles"]["manager"], "role": "manager", "project_ref": f.project.ref.to_dict(),
            "request_key": "existing", "profile": "workspace-write", "model": "gpt-test", "reasoning": "high"}
        prepared = f.app.prepare_role(**request)
        original = f.app._read(prepared["schedule_id"])
        setup = {**self.config(), "roles": {"manager": original.schedule_id}}
        for changes in ({"completion_state": "unknown", "host_evidence": {"gateway_attempt": {"result": {"outcome": "unknown"}}}},
                        {"host_state": "paused"}, {"stop_state": "stopped"}):
            due = replace(original, **changes)
            raw_read = f.port.read_due
            proxy = PortProxy(f.port, read_due=lambda schedule: due.to_dict()
                              if schedule == due.schedule_id else raw_read(schedule))
            with patch.object(f.app, "due_port", proxy), patch.object(f.app.runtime, "due_port", proxy):
                before = f.store.consumer().snapshot_counts()
                result = self.call("apply", setup)
                self.assertEqual(result["outcome"], "blocked", result)
                self.assertEqual(result["readiness"]["state"], "blocked")
                self.assertFalse(result["readiness"]["autonomous_ready"])
                self.assertEqual(result["readiness"]["blockers"][-1]["code"], "retained_effect_held")
                self.assertEqual(f.store.consumer().snapshot_counts(), before)
        self.assertEqual(f.provider.calls, [])

    def test_adopted_configuration_and_session_defaults_keep_provenance(self):
        context = context_fixture.RoleContextTests()
        context.setUp()
        self.addCleanup(context.doCleanups)
        configuration = context.document("run_configuration", context.configuration())
        _assignment, _schedule, role = context.role(sources=[configuration])
        spec = {k: v for k, v in role.items() if k not in {"role", "project_ref", "request_key"}}
        setup = {**self.config(), "roles": {"manager": spec}}
        setup.pop("defaults")
        preview = context.f.app.compose_operating_setup(project_ref=context.f.project.ref.to_dict(),
            operation="preview", setup=setup, request_key="adopted")
        self.assertEqual(preview["outcome"], "preview", preview)
        execution = preview["records"]["manager"]["execution"]
        self.assertEqual(execution["selection"]["model"], {"source": "selected_configuration", "ref": configuration})
        self.assertEqual(preview["records"]["manager"]["conversation_id"], "manager-session")
        self.assertEqual(context.f.provider.calls, [])

    def test_shared_command_help_and_host_lane_preserve_authority_boundary(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        add_manager_journey_parsers(sub)
        args = vars(parser.parse_args(["operating-setup", "--operation", "preview", "--setup", "{}", "--request-key", "preview"]))
        self.assertEqual(_nested_capability(args), "admitted")
        self.assertEqual(_nested_capability({**args, "operation": "apply"}), "held")
        self.assertEqual(_nested_capability({**args, "operation": "update"}), "held")
        read = vars(parser.parse_args(["operating-setup"]))
        self.assertEqual(_nested_capability(read), "admitted")

    def test_bound_service_composes_setup_and_rejects_foreign_or_stale_callers(self):
        f = self.f
        state = {"project_ref": f.project.ref.to_dict(), "assignment_ref": self.manager.ref.to_dict(),
            "manager_generation": 1, "manager": "manager", "requested_model": "gpt-test", "requested_reasoning": "high"}
        server = SimpleNamespace(state=state, owner=f.owner, portfolio=f.app.portfolio,
            due_port=f.port, _execution=lambda **kwargs: f.app)
        service = ManagerJourneyService(server=server, host=None, run_path=f.temporary.name, workspace=f.temporary.name)
        request = {"command": "operating-setup", "operation": "preview", "request_key": "service", "setup": self.config()}
        before = f.store.consumer().snapshot_counts()
        self.assertEqual(service(request)["outcome"], "preview")
        self.assertEqual(f.store.consumer().snapshot_counts(), before)
        with self.assertRaisesRegex(ValueError, "bound project"):
            service({**request, "project_ref": {**state["project_ref"], "id": "foreign"}})
        context = {"role": "manager", "principal": "manager", "assignment_ref": state["assignment_ref"], "generation": 1}
        service.authorize_caller(context, request)
        with self.assertRaises(PermissionError):
            service.authorize_caller({**context, "generation": 2}, request)
        result = service({**request, "operation": "apply"})
        self.assertEqual(result["outcome"], "applied", result)
        read = service({"command": "operating-setup", "operation": "read"})
        self.assertEqual(read["setup_ref"], result["setup_ref"])
        with self.assertRaises(PermissionError):
            f.app.portfolio.operations.read_document_receipt(project_ref=state["project_ref"],
                document_ref=setup_reference(state["project_ref"]).to_dict(), request_id="service:setup", actor="foreign")
        self.assertEqual(f.provider.calls, [])


if __name__ == "__main__":
    unittest.main()
