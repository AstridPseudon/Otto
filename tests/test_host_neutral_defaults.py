"""Host-neutral defaults: model profiles, adapter efforts, launcher versions and
the manager command port. Codex behaviour must be unchanged when no host
selection is made; a Claude host selects its own values explicitly."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from otto.agents import host_profiles
from otto.agents.claude_cli import ClaudeBindingError, LauncherPin, VERSION, file_digest, qualified_versions
from otto.agents.trusted_selection import TrustedAdapter, TrustedAdapterSelection
from otto import cli as gateway_cli

ROOT = Path(__file__).resolve().parents[1]


def load_manager_ctl(environ):
    spec = importlib.util.spec_from_file_location("manager_ctl_under_test", ROOT / "manager_ctl.py")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, environ, clear=False):
        for name in ("OTTO_MANAGER_CONFIG", "OTTO_MANAGER_IPC", "OTTO_MANAGER_SERVICE_SOCKET",
                     "OTTO_MANAGER_OFFLINE_READER", "OTTO_MANAGER_STATUS_OWNER", "OTTO_OWNER_PYTHON",
                     "OTTO_MANAGER_TASKS"):
            if name not in environ:
                os.environ.pop(name, None)
        spec.loader.exec_module(module)
    return module


class ModelProfileTests(unittest.TestCase):
    def test_codex_profile_is_the_unchanged_edition_default(self):
        roles = host_profiles.PROFILES["codex"]["roles"]
        self.assertEqual(roles["worker_normal"], {"model": "gpt-5.6-luna", "reasoning": "high"})
        self.assertEqual(roles["worker_xhard"], {"model": "gpt-5.6-sol", "reasoning": "high"})
        self.assertEqual(roles["oracle"], {"model": "gpt-6-astra", "reasoning": "high"})
        self.assertEqual(host_profiles.resolve_profile_name(environ={}), "codex")

    def test_claude_profile_selected_by_host_kind_or_explicitly(self):
        self.assertEqual(host_profiles.resolve_profile_name(environ={"OTTO_HOST_KIND": "claude-code"}), "claude")
        self.assertEqual(host_profiles.resolve_profile_name(host_kind="claude-code", environ={}), "claude")
        self.assertEqual(host_profiles.resolve_profile_name("codex", environ={"OTTO_HOST_KIND": "claude-code"}), "codex")
        binding = host_profiles.slot_binding("coordinator", "claude")
        self.assertEqual(binding, {"model": "claude-haiku-5-5", "reasoning": "medium", "adapter": "claude-code"})
        self.assertEqual(host_profiles.slot_binding("worker_xhard", "claude")["model"], "claude-sonnet-5-5")
        self.assertEqual(host_profiles.slot_binding("final_reviewer", "claude")["model"], "claude-opus-5-5")
        with self.assertRaises(ValueError):
            host_profiles.resolve_profile_name("gpt-everything", environ={})
        with self.assertRaises(ValueError):
            host_profiles.slot_binding("manager", "claude")

    def test_every_profile_binds_all_seven_slots(self):
        for name, value in host_profiles.PROFILES.items():
            self.assertEqual(set(value["roles"]), set(host_profiles.SLOTS), name)
            template = host_profiles.run_template(name)
            self.assertEqual(set(template["roles"]), set(host_profiles.SLOTS))

    def run_dry(self, environ):
        out = io.StringIO()
        with mock.patch.dict(os.environ, environ, clear=False), contextlib.redirect_stdout(out):
            for name in ("OTTO_MODEL_PROFILE", "OTTO_HOST_KIND"):
                if name not in environ:
                    os.environ.pop(name, None)
            self.assertEqual(gateway_cli.main(["dry-run"]), 0)
        return json.loads(out.getvalue())

    def test_gateway_dry_run_is_unchanged_for_codex_and_host_aware_for_claude(self):
        self.assertEqual(self.run_dry({}), {"mode": "dry-run", "effects": "none", "route": "normal",
            "requested_model": "gpt-5.6-luna", "requested_reasoning": "high",
            "operations": ["invoke", "resume", "send", "inspect", "cancel", "wait"]})
        claude = self.run_dry({"OTTO_HOST_KIND": "claude-code"})
        self.assertEqual((claude["requested_model"], claude["model_profile"], claude["adapter"]),
                         ("claude-haiku-5-5", "claude", "claude-code"))


class AdapterEffortTests(unittest.TestCase):
    def selection(self, reasonings):
        app = type("App", (), {"native_adapter_identity": lambda self: "fixture"})()
        return TrustedAdapterSelection({"claude-code": TrustedAdapter(
            "fixture", lambda **kw: app, frozenset({"claude-haiku-5-5"}), frozenset({"workspace-write"}),
            {"pin": 1}, reasonings)})

    def test_declared_effort_set_rejects_unsupported_effort_at_resolve(self):
        restricted = self.selection(frozenset({"low", "medium", "high", "xhigh", "max"}))
        role = {"adapter": "claude-code", "model": "claude-haiku-5-5"}
        self.assertEqual(restricted.resolve(role={**role, "reasoning": "high"})["reasoning"], "high")
        for effort in ("ultra", "minimal", "none"):
            with self.assertRaises(ValueError):
                restricted.resolve(role={**role, "reasoning": effort})

    def test_undeclared_effort_set_keeps_generic_vocabulary(self):
        generic = self.selection(None)
        role = {"adapter": "claude-code", "model": "claude-haiku-5-5", "reasoning": "ultra"}
        self.assertEqual(generic.resolve(role=role)["reasoning"], "ultra")


class LauncherVersionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def launcher(self, version):
        path = Path(self.temporary.name) / "claude"
        path.write_text("#!/bin/sh\necho '%s'\n" % version)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_default_pin_accepts_only_the_parser_version(self):
        self.assertEqual(LauncherPin.inspect(str(self.launcher(VERSION))).version, VERSION)
        with self.assertRaises(ClaudeBindingError) as raised:
            LauncherPin.inspect(str(self.launcher("2.1.296 (Claude Code)")))
        self.assertIn("2.1.296", str(raised.exception))

    def test_host_qualified_exact_version_is_accepted_and_still_drift_checked(self):
        path = self.launcher("2.1.296 (Claude Code)")
        pin = LauncherPin.inspect(str(path), qualified=(VERSION, "2.1.296 (Claude Code)"))
        self.assertEqual(pin.version, "2.1.296 (Claude Code)")
        pin.verify()
        path.write_text("#!/bin/sh\necho drifted\n")
        with self.assertRaises(ClaudeBindingError):
            pin.verify()

    def test_qualified_versions_are_exact_strings_and_keep_the_parser_version(self):
        for bad in ((), ("2.1.296 (Claude Code)",), (VERSION, "2.1.*"), (VERSION, VERSION)):
            with self.assertRaises(ClaudeBindingError):
                qualified_versions(bad)
        legacy = LauncherPin("/x", "/x", "0" * 64, VERSION)
        self.assertEqual(legacy.qualified, (VERSION,))


class LeafAdapterTests(unittest.TestCase):
    def test_declared_leaf_adapter_refuses_coordinating_operation(self):
        from otto.portfolio.manager_journey_service import compose_worker_operation
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root))
        adapter = type("Leaf", (), {"worktree": str(root), "writable_roots": (), "leaf_only": True,
                                    "adapter_identity": "otto.adapter.example-cli.leaf.v1"})()
        config = {"worker_operation_profiles": {"T1": "coordinating_implementation"}}
        task = {"authority": "a", "kind": "work.task", "id": "t", "revision": "rev-1"}
        with self.assertRaisesRegex(ValueError, "example-cli"):
            compose_worker_operation(config=config, task="T1", task_ref=task, principal="w", model="m",
                reasoning="high", focus="x", workspace=root.resolve(), run_path=root, adapter=adapter)
        _, contract, _ = compose_worker_operation(config={}, task="T1", task_ref=task, principal="w", model="m",
            reasoning="high", focus="x", workspace=root.resolve(), run_path=root, adapter=adapter)
        self.assertEqual(contract["read_targets"], [str(root.resolve())])


class RoleGuidanceTests(unittest.TestCase):
    def test_manager_guidance_is_host_neutral_and_can_name_the_installed_command(self):
        from otto.portfolio import operating_brief
        self.assertEqual(operating_brief._host_role_guidance({}), operating_brief._CODEX_ADAPTER_ROLE_BASE_GUIDANCE)
        self.assertNotIn("Documents/Codex", operating_brief._host_role_guidance({"OTTO_HOST_KIND": "codex"}))
        claude = operating_brief._host_role_guidance({"OTTO_HOST_KIND": "claude-code",
                                                      "OTTO_TOOL_ENTRYPOINT": "/home/u/.otto-claude/bin/ottoctl"})
        self.assertIn("`/home/u/.otto-claude/bin/ottoctl`", claude)
        self.assertNotIn("Documents/Codex", claude)
        self.assertNotIn("mechanical only", claude)
        self.assertIn("run-worker --task TASK", claude)


class ManagerPortConfigTests(unittest.TestCase):
    def test_defaults_are_the_original_codex_run_layout(self):
        module = load_manager_ctl({})
        run = ROOT.parent
        self.assertEqual(module.IPC, run / "controller" / "manager-ipc")
        self.assertEqual(module.SERVICE, Path("/tmp/otto-project-advisor-manager-ops.sock"))
        self.assertEqual(module.OFFLINE_READER, run / "controller" / "read_manager_status.py")
        self.assertEqual(module.STATUS_OWNER, run / "controller" / "manager-status-owner.json")
        self.assertTrue(str(module.OWNER_PYTHON).endswith("d97-successor-integration/env/bin/python"))
        self.assertEqual(module.TASKS, ["PA01", "PA02", "PA03", "PA04", "PA05", "PA06"])

    def test_config_file_and_variables_select_a_host_port(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "host.json"
            config.write_text(json.dumps({"schema": "ignored-outer", "manager_port": {
                "ipc_dir": directory + "/ipc", "service_socket": directory + "/svc.sock",
                "tasks": ["Z-2", "S0", "A1"]}}))
            module = load_manager_ctl({"OTTO_MANAGER_CONFIG": str(config),
                                       "OTTO_OWNER_PYTHON": "/opt/otto/bin/python"})
            self.assertEqual(module.IPC, Path(directory) / "ipc")
            self.assertEqual(module.SERVICE, Path(directory) / "svc.sock")
            self.assertEqual(module.OWNER_PYTHON, Path("/opt/otto/bin/python"))
            self.assertEqual(module.TASKS, ["Z-2", "S0", "A1"])
            module = load_manager_ctl({"OTTO_MANAGER_CONFIG": str(config), "OTTO_MANAGER_TASKS": "A,B"})
            self.assertEqual(module.TASKS, ["A", "B"])

    def test_unknown_config_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "port.json"
            config.write_text(json.dumps({"ipc_dir": directory, "store": "/elsewhere"}))
            with self.assertRaises(RuntimeError):
                load_manager_ctl({"OTTO_MANAGER_CONFIG": str(config)})

    def test_client_uses_the_configured_ipc_directory_and_task_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            ipc = Path(directory) / "ipc"
            ipc.mkdir()
            module = load_manager_ctl({"OTTO_MANAGER_IPC": str(ipc), "OTTO_MANAGER_TASKS": "S0,A1",
                                       "OTTO_MANAGER_SERVICE_SOCKET": directory + "/absent.sock",
                                       "OTTO_MANAGER_STATUS_OWNER": directory + "/owner.json"})
            (Path(directory) / "owner.json").write_text(json.dumps({"pid": os.getpid()}))
            seen = []

            def responder():
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    for request in ipc.glob("request-*.json"):
                        payload = json.loads(request.read_text())
                        seen.append(payload)
                        token = request.name[len("request-"):-len(".json")]
                        (ipc / ("response-" + token + ".json")).write_text(json.dumps({"outcome": "read"}))
                        request.unlink()
                        return
                    time.sleep(.01)

            thread = threading.Thread(target=responder)
            thread.start()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                module.main(["report", "--task", "A1", "--summary", "s", "--next-action", "n", "--request-key", "k"])
            thread.join()
            self.assertEqual(seen[0]["task"], "A1")
            self.assertEqual(json.loads(out.getvalue())["outcome"], "read")
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                module.main(["report", "--task", "PA01", "--summary", "s", "--next-action", "n", "--request-key", "k"])


if __name__ == "__main__":
    unittest.main()
