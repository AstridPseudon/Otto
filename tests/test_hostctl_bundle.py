from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from otto.hostctl.bundle import BundleError, parse_tasklist, read_bundle

TASKLIST = """# Tasklist: test-run

Status is `todo` unless noted.

## Phase 0: activation (the orchestrator)
| id | outcome | deps | proof |
|---|---|---|---|
| Z-1 | D-SEQ settled by the user (A/B/C; C recommended) | — | recorded in status.md |
| Z-2 | **The paused work reconciled on one trunk:** decide held `30ba1369` | Z-3 | the gate suite |
| Z-3 | Freeze BOARD.md (history) | — | this file |

## Phase 1: pre-port (Astrid only; under C)
| id | repo | outcome | deps | route | proof |
|---|---|---|---|---|---|
| S0 | AS | **Safety-net fixtures** (step 0): a CLI film | Z-2 | normal | the fixtures FAIL today |
| A1 | AS | **Intent → `app.astrid`** on clips. *XHARD: data-loss risk.* | S0 | **xhard** | S0 fixtures flip to pass |
| L1 | AS | **Look fields** in change detection | Z-2, Codex packet | normal | a scenario passes |
| CK4 | AS | The `astrid-intent` schema | A1 and Z-9 | normal | round-trips the fixtures |

## Phase 2: the port (trigger: Codex's checkpoint packet)
| id | repo | outcome | deps | route | proof |
|---|---|---|---|---|---|
| PT-1 | AS | Port r2 + trunk + Phase 1 | Codex packet, Z-2, Phase 1 | **xhard** | their suite + ours |
| PT-2 | AS/RT | Move `almost-ready` | PT-1 | normal | FINAL-E2E stage 2 |
| PT-3 | all | Publish in Codex's order | PT-1/2 | — (orchestrator) | ls-remote verification |
"""

RUN_JSON = json.dumps({"run_id": "test-run", "mode": "setup_not_activated"}, indent=2)

REQUIRED_TEXT = {
    "northstar.md": "# North star\n",
    "agent_goal.md": "# Goal\n",
    "plan.md": "# Plan\n",
    "tasklist.md": TASKLIST,
    "status.md": "# Status\n",
}


def write_bundle(root: Path, *, run_name: str = "run.yaml", run_text: str = RUN_JSON,
                 omit: tuple = (), extra: dict | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    files = dict(REQUIRED_TEXT)
    files.update(extra or {})
    for name in omit:
        files.pop(name, None)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    if run_name:
        (root / run_name).write_text(run_text, encoding="utf-8")
    return root


class ReadBundleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_happy_path(self):
        root = write_bundle(self.base / "b", extra={"manager-brief.md": "# brief\n"})
        bundle = read_bundle(root)

        self.assertEqual(bundle["root"], str(root.resolve()))
        self.assertEqual(bundle["run_file"], "run.yaml")
        self.assertEqual(bundle["run"]["run_id"], "test-run")
        self.assertIn("manager-brief.md", bundle["files"])
        self.assertEqual(bundle["files"]["plan.md"], "# Plan\n")

        tasks = bundle["tasks"]
        self.assertEqual(len(tasks), 10)
        by_id = {t["id"]: t for t in tasks}

        # Phases: ordered, with the heading text and task ids.
        self.assertEqual([p["heading"] for p in bundle["phases"]], [
            "Phase 0: activation (the orchestrator)",
            "Phase 1: pre-port (Astrid only; under C)",
            "Phase 2: the port (trigger: Codex's checkpoint packet)",
        ])
        self.assertEqual([p["task_ids"] for p in bundle["phases"]], [
            ["Z-1", "Z-2", "Z-3"],
            ["S0", "A1", "L1", "CK4"],
            ["PT-1", "PT-2", "PT-3"],
        ])
        self.assertEqual(by_id["S0"]["phase"], "Phase 1: pre-port (Astrid only; under C)")

        # Routes.
        self.assertEqual(by_id["A1"]["route"], "xhard")
        self.assertEqual(by_id["A1"]["route_text"], "**xhard**")
        self.assertEqual(by_id["S0"]["route"], "normal")
        self.assertEqual(by_id["PT-1"]["route"], "xhard")
        self.assertIsNone(by_id["PT-3"]["route"])
        self.assertEqual(by_id["PT-3"]["route_text"], "— (orchestrator)")
        self.assertIsNone(by_id["Z-1"]["route"])
        self.assertIsNone(by_id["Z-1"]["route_text"])

        # Deps: em-dash means none; forward reference resolves; unknown tokens dropped.
        self.assertEqual(by_id["Z-1"]["deps"], [])
        self.assertEqual(by_id["Z-1"]["deps_text"], "—")
        self.assertEqual(by_id["Z-2"]["deps"], ["Z-3"])
        self.assertEqual(by_id["CK4"]["deps"], ["A1"])
        self.assertEqual(by_id["CK4"]["deps_text"], "A1 and Z-9")
        self.assertEqual(by_id["L1"]["deps"], ["Z-2"])
        self.assertEqual(by_id["L1"]["deps_text"], "Z-2, Codex packet")
        self.assertEqual(by_id["PT-1"]["deps"], ["Z-2"])
        self.assertEqual(by_id["PT-3"]["deps"], ["PT-1", "PT-2"])

        # Other columns.
        self.assertEqual(by_id["S0"]["repo"], "AS")
        self.assertEqual(by_id["S0"]["proof"], "the fixtures FAIL today")
        self.assertIsNone(by_id["S0"]["who"])
        self.assertEqual(by_id["S0"]["columns"]["route"], "normal")
        self.assertEqual(by_id["A1"]["title"], "Intent → app.astrid on clips")
        self.assertEqual(by_id["Z-2"]["title"], "The paused work reconciled on one trunk")

        # Raw hashes match exact bytes on disk.
        for name, digest in bundle["raw_sha256"].items():
            data = (root / name).read_bytes()
            self.assertEqual(digest, hashlib.sha256(data).hexdigest(), name)
        self.assertIn("run.yaml", bundle["raw_sha256"])

    def test_run_json_accepted(self):
        root = write_bundle(self.base / "b", run_name="run.json")
        bundle = read_bundle(root)
        self.assertEqual(bundle["run_file"], "run.json")
        self.assertEqual(bundle["run"]["mode"], "setup_not_activated")

    def test_tasklist_branch_column_is_parsed(self):
        task = next(task for task in parse_tasklist("""## Phase 1
| id | repo | branch | outcome |
|---|---|---|---|
| S0 | AS | feature/setup | Ship it |
""") if task["id"] == "S0")
        self.assertEqual(task["branch"], "feature/setup")

    def test_generated_run_view_cannot_be_registered_as_a_source_bundle(self):
        root = write_bundle(self.base / "generated")
        run = json.loads((root / "run.yaml").read_text(encoding="utf-8"))
        run["otto_generated_view"] = {
            "from": "otto records",
            "authority": "read-only projection",
        }
        (root / "run.yaml").write_text(json.dumps(run), encoding="utf-8")
        (root / "tasklist.md").write_text("| id | outcome |\n| not a separator |\n", encoding="utf-8")
        with self.assertRaisesRegex(BundleError, "generated run view.*source bundle"):
            read_bundle(root)

    def test_both_run_files_is_error(self):
        root = write_bundle(self.base / "b", run_name="run.yaml")
        (root / "run.json").write_text(RUN_JSON, encoding="utf-8")
        with self.assertRaises(BundleError):
            read_bundle(root)

    def test_missing_run_file_is_error(self):
        root = write_bundle(self.base / "b", run_name=None)
        with self.assertRaises(BundleError):
            read_bundle(root)

    def test_missing_required_file_is_error(self):
        root = write_bundle(self.base / "b", omit=("plan.md",))
        with self.assertRaisesRegex(BundleError, "plan.md"):
            read_bundle(root)

    def test_symlinked_file_is_error(self):
        root = write_bundle(self.base / "b", omit=("status.md",))
        target = self.base / "elsewhere-status.md"
        target.write_text("# Status\n", encoding="utf-8")
        os.symlink(target, root / "status.md")
        with self.assertRaisesRegex(BundleError, "symlink"):
            read_bundle(root)

    def test_symlinked_extra_md_is_error(self):
        root = write_bundle(self.base / "b")
        target = self.base / "elsewhere.md"
        target.write_text("x\n", encoding="utf-8")
        os.symlink(target, root / "extra.md")
        with self.assertRaises(BundleError):
            read_bundle(root)

    def test_non_json_run_file_is_error(self):
        root = write_bundle(self.base / "b", run_text="run_id: test-run\nmode: x\n")
        with self.assertRaisesRegex(BundleError, "JSON"):
            read_bundle(root)

    def test_duplicate_id_is_error(self):
        root = write_bundle(self.base / "b")
        (root / "tasklist.md").write_text(
            TASKLIST.replace("| PT-3 | all |", "| S0 | all |"), encoding="utf-8")
        with self.assertRaisesRegex(BundleError, "duplicate task id 'S0'"):
            read_bundle(root)

    def test_invalid_utf8_is_error(self):
        root = write_bundle(self.base / "b")
        (root / "plan.md").write_bytes(b"\xff\xfe bad\n")
        with self.assertRaisesRegex(BundleError, "UTF-8"):
            read_bundle(root)

    def test_too_many_files_is_error(self):
        root = write_bundle(self.base / "b")
        with self.assertRaises(BundleError):
            read_bundle(root, max_files=3)

    def test_nested_markdown_is_read_at_its_relative_path(self):
        root = write_bundle(self.base / "b")
        (root / "briefs" / "phase-1").mkdir(parents=True)
        (root / "briefs" / "M1.md").write_text("# M1\n")
        (root / "briefs" / "phase-1" / "M2.md").write_text("# M2\n")
        (root / "reviews").mkdir()
        (root / "reviews" / "notes.txt").write_text("a review note\n")
        (root / ".hidden").mkdir()
        (root / ".hidden" / "x.md").write_text("# hidden\n")
        bundle = read_bundle(root)
        self.assertEqual(bundle["files"]["briefs/M1.md"], "# M1\n")
        self.assertIn("briefs/phase-1/M2.md", bundle["files"])
        self.assertEqual(bundle["raw_sha256"]["briefs/M1.md"], hashlib.sha256(b"# M1\n").hexdigest())
        # The whole run dir is the record: any text file, not only Markdown.
        self.assertEqual(bundle["files"]["reviews/notes.txt"], "a review note\n")
        self.assertFalse(any(path.startswith(".hidden") for path in bundle["files"]))

    def test_nested_symlink_too_deep_and_binary_files_are_refused_not_skipped(self):
        root = write_bundle(self.base / "b")
        (root / "a" / "b" / "c" / "d" / "e").mkdir(parents=True)
        (root / "a" / "b" / "c" / "d" / "e" / "deep.md").write_text("# too deep\n")
        with self.assertRaisesRegex(BundleError, "deeper"):
            read_bundle(root)
        import shutil
        shutil.rmtree(root / "a")
        (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff")
        with self.assertRaisesRegex(BundleError, "UTF-8"):
            read_bundle(root)
        (root / "image.png").unlink()
        (root / "briefs").mkdir()
        os.symlink(root / "plan.md", root / "briefs" / "link.md")
        with self.assertRaisesRegex(BundleError, "symlink"):
            read_bundle(root)


class ParseTasklistTests(unittest.TestCase):
    def test_empty_id_rows_skipped_and_deps_expanded(self):
        md = (
            "## Phase A\n"
            "| id | outcome | deps |\n"
            "|---|---|---|\n"
            "| X-1 | first. Second sentence | — |\n"
            "|  | blank id row | — |\n"
            "| X-2 | `app.astrid` and more: tail | X-1 (done), Q-9 |\n"
        )
        tasks = parse_tasklist(md)
        self.assertEqual([t["id"] for t in tasks], ["X-1", "X-2"])
        self.assertEqual(tasks[0]["title"], "first")
        self.assertEqual(tasks[1]["title"], "app.astrid and more")
        self.assertEqual(tasks[1]["deps"], ["X-1"])
        self.assertIsNone(tasks[0]["repo"])

    def test_title_truncated_at_120(self):
        long = "w" * 200
        tasks = parse_tasklist(f"## P\n| id | outcome |\n|---|---|\n| T | {long} |\n")
        self.assertEqual(len(tasks[0]["title"]), 120)

    def test_non_task_tables_ignored(self):
        md = "## P\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        self.assertEqual(parse_tasklist(md), [])

    def test_id_keyed_log_without_outcome_is_not_a_task_table(self):
        # A manager's dispatch log is keyed by task id but defines no outcomes;
        # it must not create tasks (or duplicate-id errors) during registration.
        md = ("## Phase 1\n| id | outcome | deps |\n|---|---|---|\n| S0 | Fixtures | — |\n\n"
              "## Dispatch log\n| id | model | state |\n|---|---|---|\n| S0 | haiku | dispatched |\n"
              "| CK2, OPS1 | haiku | waiting |\n")
        self.assertEqual([task["id"] for task in parse_tasklist(md)], ["S0"])


class RegistrationProfileRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = write_bundle(Path(self.temporary.name) / "run")

    def test_registration_records_resolved_profile_pin_defaults_and_role_bindings(self):
        from otto.agents import host_profiles
        from otto.hostctl.register import plan

        bundle = read_bundle(self.root)
        selected = host_profiles.profile_for_run(bundle["run"], host_kind="codex", default_profile="codex")
        registration = plan(bundle, profile=selected, manager_principal="manager",
                            worktree=str(self.root), tool_entrypoint="ottoctl")
        selection = registration["custom"]["otto_host_registration"]["profile_selection"]
        self.assertEqual(selection["pin"], selected["pin"])
        self.assertEqual(selection["name"], selected["name"])
        self.assertEqual(selection["roles"], selected["roles"])
        self.assertEqual(selection["resolved_roles"], registration["configuration"]["roles"])
        self.assertEqual(registration["configuration"]["role_pack"], selection["role_pack"])
        self.assertEqual(set(selection["role_pack"]), {"pack_id", "pack_version", "source_revision",
            "source_inventory_identity", "resource_path", "resource_digest"})

    def test_registration_refuses_declared_or_retained_stale_role_pack(self):
        from otto.agents import host_profiles
        from otto.hostctl.register import plan, plan_retained

        bundle = read_bundle(self.root)
        selected = host_profiles.profile_for_run(bundle["run"], host_kind="codex", default_profile="codex")
        kwargs = {"manager_principal": "manager", "worktree": str(self.root), "tool_entrypoint": "ottoctl"}
        registration = plan(bundle, profile=selected, **kwargs)
        facts = registration["custom"]["otto_host_registration"]
        bad_pin = {**registration["configuration"]["role_pack"], "resource_digest": "stale"}
        declared = plan({**bundle, "run": {**bundle["run"],
            "role_pack": registration["configuration"]["role_pack"]}}, profile=selected, **kwargs)
        self.assertEqual(declared["configuration"]["role_pack"], registration["configuration"]["role_pack"])
        with self.assertRaisesRegex(ValueError, "role pack pin") as refused:
            plan({**bundle, "run": {**bundle["run"], "role_pack": bad_pin}}, profile=selected, **kwargs)
        from otto.hostctl.register import refusal_result
        serialized = refusal_result(refused.exception)
        self.assertEqual(serialized["error"], {"code": "ValueError", "message": str(refused.exception)})
        self.assertIs(serialized["provider_called"], False)
        self.assertIn("correct the stale or malformed pin", serialized["next_action"])
        from otto.hostctl import cli, service
        owner_serialized = service._owner_exception_result(refused.exception)
        self.assertEqual(owner_serialized, serialized)
        output = io.StringIO()
        with mock.patch.object(cli, "client_request", side_effect=refused.exception), \
                mock.patch("sys.stdout", output):
            exit_code = cli.main(["--home", str(self.root.parent), "project", "register",
                                  "--bundle", str(self.root)])
        self.assertEqual(exit_code, cli.EXIT_ERROR)
        self.assertEqual(json.loads(output.getvalue()), serialized)
        changed_facts = {**facts, "profile_selection": {**facts["profile_selection"], "role_pack": bad_pin}}
        host = {"kind": "codex", "adapters": {"codex": {"profiles": ["workspace-write"]}}}
        with self.assertRaisesRegex(ValueError, "role pack pin"):
            plan_retained(bundle, facts=changed_facts, host=host, **kwargs)
        with self.assertRaisesRegex(ValueError, "role pack pin"):
            plan_retained(bundle, facts={**facts, "profile_selection": {
                key: value for key, value in facts["profile_selection"].items() if key != "role_pack"}},
                host=host, **kwargs)
        with self.assertRaisesRegex(ValueError, "role pack pin"):
            plan({**bundle, "run": {**bundle["run"], "role_pack": None}}, profile=selected, **kwargs)
        from otto.portfolio import role_context
        newer_pin = {**registration["configuration"]["role_pack"], "source_revision": "new-edition"}
        with mock.patch.object(role_context, "_role_pack", return_value=({"pin": newer_pin}, {})):
            with self.assertRaisesRegex(ValueError, "role pack pin"):
                plan_retained(bundle, facts=facts, host=host, **kwargs)

    def test_pending_pre_role_pin_selection_is_persisted_before_activation(self):
        from otto.agents import host_profiles
        from otto.hostctl import register as registration_module

        bundle = read_bundle(self.root)
        selected = host_profiles.profile_for_run(bundle["run"], host_kind="codex", default_profile="codex")
        kwargs = {"manager_principal": "manager", "worktree": str(self.root), "tool_entrypoint": "ottoctl"}
        planned = registration_module.plan(bundle, profile=selected, **kwargs)
        prior = {key: value for key, value in
                 planned["custom"]["otto_host_registration"]["profile_selection"].items()
                 if key != "role_pack"}
        facts = {**planned["custom"]["otto_host_registration"], "profile_selection": prior}
        project = mock.Mock()
        project.ref = mock.Mock(authority="owner", kind="work.project", id="project", revision="rev-1")
        project.ref.to_dict.return_value = {"authority": "owner", "kind": "work.project", "id": "project", "revision": "rev-1"}
        project.lifecycle.value = "pending"
        project.payload = {"custom": {"otto_host_registration": facts}}
        graph = mock.Mock()
        graph.current.return_value = project
        session = mock.Mock()
        session.owner.graph = graph
        writes = []

        def check_in(_session, _ref, _principal, _key, edit, **_kwargs):
            draft = {"custom": {"otto_host_registration": dict(facts)}}
            edit(draft)
            writes.append(draft["custom"]["otto_host_registration"])
            project.payload = {"custom": {"otto_host_registration": dict(writes[-1])}}
            return {"outcome": "finished"}

        host = {"kind": "codex", "adapters": {"codex": {"profiles": ["workspace-write"]}}}
        with mock.patch.object(registration_module, "_check_in", side_effect=check_in):
            _project, retained = registration_module.ensure_profile_selection(
                session, project, bundle, host=host, **kwargs)
        self.assertEqual(len(writes), 1)
        self.assertEqual(retained["profile_selection"]["role_pack"], planned["configuration"]["role_pack"])
        self.assertEqual(registration_module.plan_retained(bundle, facts=retained, host=host,
            **kwargs)["configuration"]["role_pack"], planned["configuration"]["role_pack"])
        with mock.patch.object(registration_module, "_check_in", side_effect=AssertionError("must not rewrite")):
            registration_module.ensure_profile_selection(session, project, bundle, host=host, **kwargs)
        project.payload = {"custom": {"otto_host_registration": facts}}
        altered = {**bundle, "raw_sha256": {**bundle["raw_sha256"], bundle["run_file"]: "changed"}}
        with mock.patch.object(registration_module, "_check_in", side_effect=AssertionError("must not write")):
            with self.assertRaisesRegex(ValueError, "changed"):
                registration_module.ensure_profile_selection(session, project, altered, host=host, **kwargs)
        for invalid in (None, "otto-roles", {"pack_id": "otto-roles"}):
            project.payload = {"custom": {"otto_host_registration": {**facts,
                "profile_selection": {**prior, "role_pack": invalid}}}}
            with self.subTest(invalid=invalid), mock.patch.object(
                    registration_module, "_check_in", side_effect=AssertionError("must not write")):
                with self.assertRaisesRegex(ValueError, "role pack pin"):
                    registration_module.ensure_profile_selection(session, project, bundle, host=host, **kwargs)

    def test_registration_accepts_template_resource_pin_and_retains_full_selection(self):
        from otto.agents import host_profiles
        from otto.hostctl.bundle import parse_files
        from otto.hostctl.register import plan, plan_retained

        bundle = read_bundle(self.root)
        selected = host_profiles.profile_for_run(bundle["run"], host_kind="codex", default_profile="codex")
        files = dict(bundle["files"])
        files[bundle["run_file"]] = json.dumps({**bundle["run"],
            "profile_pack": host_profiles.profile_resource_pin(selected["pin"])})
        bundle = {**bundle, **parse_files(files), "root": bundle["root"]}
        registration = plan(bundle, profile=selected, manager_principal="manager",
                            worktree=str(self.root), tool_entrypoint="ottoctl")
        facts = registration["custom"]["otto_host_registration"]
        self.assertEqual(facts["profile_selection"]["pin"], selected["pin"])
        host = {"kind": "codex", "adapters": {"codex": {"profiles": ["workspace-write"]}}}
        replay = plan_retained(bundle, facts=facts, host=host, manager_principal="manager",
                               worktree=str(self.root), tool_entrypoint="ottoctl")
        self.assertEqual(replay["configuration"]["roles"], registration["configuration"]["roles"])

    def test_retained_activation_uses_registration_defaults_after_pack_defaults_change(self):
        from otto.agents import host_profiles
        from otto.hostctl.register import plan, plan_retained

        bundle = read_bundle(self.root)
        selected = host_profiles.profile_for_run(bundle["run"], host_kind="codex", default_profile="codex")
        registration = plan(bundle, profile=selected, manager_principal="manager",
                            worktree=str(self.root), tool_entrypoint="ottoctl")
        facts = registration["custom"]["otto_host_registration"]
        changed_pack = json.loads(json.dumps(host_profiles.load_profile_pack()))
        changed_pack["profiles"]["codex"]["roles"]["coordinator"]["model"] = "gpt-6-astra"
        joined_host = {"kind": "codex", "adapters": {"codex": {"profiles": ["workspace-write"]}}}
        with mock.patch.object(host_profiles, "load_profile_pack", return_value=changed_pack):
            retained = plan_retained(bundle, facts=facts, host=joined_host,
                                     manager_principal="manager", worktree=str(self.root),
                                     tool_entrypoint="ottoctl")
        self.assertEqual(retained["configuration"]["roles"], registration["configuration"]["roles"])

    def test_legacy_pending_registration_persists_reselection_before_retry(self):
        """A pre-selection draft is upgraded from its stored run exactly once."""
        from otto.agents import host_profiles
        from otto.hostctl import register as registration_module
        from otto.hostctl.bundle import parse_files

        bundle = read_bundle(self.root)
        # A run-level coordinator override must survive profile reselection.
        files = dict(bundle["files"])
        run = {**bundle["run"], "roles": {"coordinator": {
            "model": "gpt-6-astra", "reasoning": "high"}}}
        files[bundle["run_file"]] = json.dumps(run)
        bundle = {**bundle, **parse_files(files), "root": bundle["root"]}
        legacy_facts = {"run_id": "test-run", "mode": "setup_not_activated"}
        project = mock.Mock()
        project.ref = mock.Mock(authority="owner", kind="work.project", id="project", revision="rev-1")
        project.lifecycle.value = "pending"
        project.payload = {"custom": {"otto_host_registration": legacy_facts}}
        graph = mock.Mock()
        graph.current.return_value = project
        session = mock.Mock()
        session.owner.graph = graph

        persisted = {}
        def check_in(_session, _ref, _principal, _key, edit, **_kwargs):
            draft = {"custom": {"otto_host_registration": dict(legacy_facts)}}
            edit(draft)
            persisted.update(draft["custom"]["otto_host_registration"])
            project.payload = {"custom": {"otto_host_registration": dict(persisted)}}
            return {"outcome": "finished"}

        host = {"kind": "codex", "adapters": {"codex": {"profiles": ["workspace-write"]}}}
        restricted = {"kind": "codex", "adapters": {"codex": {"models": ["gpt-5.6-luna"]}}}
        with mock.patch.object(registration_module, "_check_in", side_effect=AssertionError("must not persist")):
            with self.assertRaisesRegex(ValueError, "manager model is unsupported"):
                registration_module.ensure_profile_selection(
                    session, project, bundle, host=restricted, manager_principal="manager",
                    worktree=str(self.root), tool_entrypoint="ottoctl")
        with mock.patch.object(registration_module, "_check_in", side_effect=check_in):
            updated, facts = registration_module.ensure_profile_selection(
                session, project, bundle, host=host, manager_principal="manager",
                worktree=str(self.root), tool_entrypoint="ottoctl")

        self.assertIs(updated, project)
        self.assertIn("profile_selection", persisted)
        self.assertEqual(facts["profile_selection"], persisted["profile_selection"])
        self.assertEqual(facts["profile_selection"]["resolved_roles"]["coordinator"]["model"], "gpt-6-astra")
        self.assertEqual(bundle["files"], files)

        # A retry reads the saved choice, even after the pack's defaults change.
        changed_pack = json.loads(json.dumps(host_profiles.load_profile_pack()))
        changed_pack["profiles"]["codex"]["roles"]["coordinator"]["model"] = "gpt-6-luna"
        with mock.patch.object(host_profiles, "load_profile_pack", return_value=changed_pack), \
             mock.patch.object(registration_module, "_check_in", side_effect=AssertionError("must not rewrite")):
            _same_project, retry_facts = registration_module.ensure_profile_selection(
                session, project, bundle, host=host, manager_principal="manager",
                worktree=str(self.root), tool_entrypoint="ottoctl")
        self.assertEqual(retry_facts["profile_selection"], facts["profile_selection"])

    def test_changed_stored_run_or_stale_source_pin_is_refused(self):
        from otto.agents import host_profiles
        from otto.hostctl.register import plan, plan_retained

        bundle = read_bundle(self.root)
        selected = host_profiles.profile_for_run(bundle["run"], host_kind="codex", default_profile="codex")
        registration = plan(bundle, profile=selected, manager_principal="manager",
                            worktree=str(self.root), tool_entrypoint="ottoctl")
        facts = registration["custom"]["otto_host_registration"]
        host = {"kind": "codex", "adapters": {"codex": {"profiles": ["workspace-write"]}}}
        changed_files = dict(bundle["files"])
        changed_files[bundle["run_file"]] = json.dumps({**bundle["run"], "roles": {
            "coordinator": {"model": "gpt-6-astra", "reasoning": "high"}}})
        with self.assertRaisesRegex(ValueError, "model choices changed"):
            plan_retained({**bundle, "files": changed_files}, facts=facts, host=host,
                          manager_principal="manager", worktree=str(self.root), tool_entrypoint="ottoctl")
        stale = {**bundle, "run": {**bundle["run"], "profile_pack": {"resource_digest": "stale"}}}
        with self.assertRaisesRegex(ValueError, "stale"):
            plan(stale, profile=selected, manager_principal="manager", worktree=str(self.root),
                 tool_entrypoint="ottoctl")

    def test_history_plan_preserves_unqualified_foreign_profile_declaration(self):
        from otto.hostctl.register import plan_history
        from otto.hostctl.bundle import parse_files

        bundle = read_bundle(self.root)
        files = dict(bundle["files"])
        files[bundle["run_file"]] = json.dumps({**bundle["run"], "model_profile": "profile-from-retired-host"})
        bundle = {**bundle, **parse_files(files), "root": bundle["root"]}
        history = plan_history(bundle)
        self.assertEqual(history["run_id"], bundle["run"]["run_id"])
        self.assertEqual(history["files"], bundle["files"])
        self.assertEqual(history["custom"]["otto_host_registration"]["mode"], "history")
        self.assertEqual(history["custom"]["otto_host_registration"]["model_profile"],
                         "profile-from-retired-host")

    def test_cli_history_import_does_not_qualify_archived_profile(self):
        from otto.agents import host_profiles
        from otto.hostctl import cli
        from otto.hostctl.bundle import parse_files
        from otto.hostctl import register as registration_module

        bundle = read_bundle(self.root)
        files = dict(bundle["files"])
        files[bundle["run_file"]] = json.dumps({**bundle["run"], "model_profile": "retired-host-only"})
        bundle = {**bundle, **parse_files(files), "root": bundle["root"]}
        receipt = {"outcome": "imported_history", "run_id": bundle["run"]["run_id"]}
        session = mock.MagicMock()
        session.__enter__.return_value = object()
        args = type("Args", (), {"note": "closed"})()
        with mock.patch.object(cli, "_home", return_value=Path(self.temporary.name)), \
             mock.patch.object(cli.host_config, "load", return_value={}), \
             mock.patch.object(cli, "_client_bundle", return_value=bundle), \
             mock.patch.object(cli, "_host", return_value={"kind": "codex", "model_profile": "codex"}), \
             mock.patch.object(cli, "HostSession", return_value=session), \
             mock.patch.object(cli, "_receipt"), \
             mock.patch.object(registration_module, "import_history", return_value=receipt) as imported, \
             mock.patch.object(host_profiles, "profile_for_run", side_effect=AssertionError("history is inert")):
            self.assertEqual(cli.cmd_import_history(args), receipt)
        self.assertEqual(imported.call_args.args[1]["custom"]["otto_host_registration"]["model_profile"],
                         "retired-host-only")


if __name__ == "__main__":
    unittest.main()
