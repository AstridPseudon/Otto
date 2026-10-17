"""The one owner service end to end on a synthetic project (no provider, no real CLI).

The owner service runs in-process (a thread) and holds a disposable Store.
The orchestrator is a client: its commands travel through its host lane and
the service relays owner-custody manager commands to the attached project.
Activation is exercised only here, on a synthetic project: operating-setup
apply, then an explicit start-manager. The "Claude" launcher is a local
script that speaks the pinned stream-json shape; it runs under the real
macOS write fence and, as the manager's Bash steps, calls `ottoctl manager`
over its own lanes: the caller socket for identity-bearing commands (the
owner authenticates it by kernel ancestry) and its file lane for the rest.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from otto.hostctl import config as host_config
from otto.hostctl import manager_client

from test_hostctl_cli import HostctlFixture

SRC = str(Path(__file__).resolve().parents[1] / "src")

LAUNCHER = r'''#!{python} -B
import json, os, subprocess, sys, uuid
sys.path.insert(0, {src!r})
if "--version" in sys.argv:
    print("2.1.293 (Claude Code)"); sys.exit(0)
argv = sys.argv
tools = argv[argv.index("--tools") + 1].split(",") if argv[argv.index("--tools") + 1] else []
model = argv[argv.index("--model") + 1]
resumed = argv[argv.index("--resume") + 1] if "--resume" in argv else None
frame = json.loads(sys.stdin.readline())
prompt = frame["message"]["content"][0]["text"]
session = resumed or frame.get("session_id") or "synthetic-" + uuid.uuid4().hex[:12]
emit = lambda event: print(json.dumps(event), flush=True)
emit({{"type": "system", "subtype": "init", "session_id": session, "cwd": os.getcwd(), "model": model,
      "permissionMode": "bypassPermissions", "tools": tools, "mcp_servers": [], "plugins": [], "skills": [],
      "slash_commands": []}})
emit({{"type": "user", "uuid": "input-" + uuid.uuid4().hex[:8], "session_id": session,
      "message": {{"role": "user", "content": [{{"type": "text", "text": prompt}}]}}}})
def finish(text):
    emit({{"type": "result", "subtype": "success", "is_error": False, "session_id": session,
          "uuid": "r-" + uuid.uuid4().hex[:8], "result": text, "usage": {{"input_tokens": 3, "output_tokens": 2}}}})
    sys.exit(0)
def bash(name, command):
    emit({{"type": "assistant", "uuid": "a-" + name, "session_id": session, "message": {{"role": "assistant",
          "model": model, "content": [{{"type": "tool_use", "id": name, "name": "Bash",
          "input": {{"command": " ".join(command)}}}}]}}}})
    done = subprocess.run(command, capture_output=True, text=True)
    emit({{"type": "user", "uuid": "t-" + name, "session_id": session, "message": {{"role": "user", "content": [
          {{"type": "tool_result", "tool_use_id": name, "is_error": done.returncode not in (0, 1),
            "content": done.stdout[-2000:]}}]}}}})
    return done.stdout
if not tools:
    finish("READY")
cwd = os.getcwd()
if "Bash" not in tools:
    path = os.path.join(cwd, "answer-" + model + ".txt")
    content = "Worker artifact from " + model + "\\n"
    emit({{"type": "assistant", "uuid": "a-w", "session_id": session, "message": {{"role": "assistant", "model": model,
          "content": [{{"type": "tool_use", "id": "write-1", "name": "Write",
          "input": {{"file_path": path, "content": content}}}}]}}}})
    with open(path, "w") as stream:
        stream.write(content)
    emit({{"type": "user", "uuid": "t-w", "session_id": session, "message": {{"role": "user", "content": [
          {{"type": "tool_result", "tool_use_id": "write-1", "is_error": False, "content": "written"}}]}}}})
    finish("Worker delivered answer.txt for T1.")
ottoctl = [sys.executable, "-B", "-c", "import sys; sys.path.insert(0, {src!r}); "
           "from otto.hostctl.cli import main; sys.exit(main(sys.argv[1:]))", "--home", {home!r}, "manager"]
# The first work turn also resumes the initializer's session; count work
# turns per session to tell the first turn from owner continuations.
marker = os.path.join(cwd, ".turns-" + session)
open(marker, "a").write("turn\n")
turn = len(open(marker).read().splitlines())
open(os.path.join(cwd, "manager-turn-%d.txt" % turn), "w").write(prompt)
if turn == 1:
    open(os.path.join(cwd, "whoami.json"), "w").write(bash("bash-1", ottoctl + ["whoami"]))
    open(os.path.join(cwd, "documents.json"), "w").write(bash("bash-docs", ottoctl + ["project-documents"]))
    open(os.path.join(cwd, "brief-T1.json"), "w").write(bash("bash-brief", ottoctl + [
        "project-documents", "--operation", "read", "--path", "briefs/T1.md"]))
if {escalate!r}:
    if turn == 1:
        out = bash("bash-help", ottoctl + ["request-help", "--request-key", "help-1", "--issue-key", "ruling-1",
            "--problem", "Two valid designs for T1", "--impact", "Blocks T1", "--requested-decision",
            "Pick design A or B", "--return-condition", "A ruling is recorded", "--evidence", "[\"design note\"]"])
        open(os.path.join(cwd, "request-help.json"), "w").write(out)
        finish("Manager turn 1: escalated to the oracle and yielding.")
    if turn == 2:
        issue = json.load(open(os.path.join(cwd, "request-help.json")))["issue_id"]
        out = bash("bash-resolve", ottoctl + ["resolve-help", "--request-key", "resolve-1", "--issue-id", issue,
            "--evidence", "[\"applied the oracle ruling\"]", "--next-action", "Continue T1 with design A"])
        open(os.path.join(cwd, "resolve-help.json"), "w").write(out)
        finish("Manager turn 2: applied the ruling.")
    finish("Manager turn %d: done." % turn)
if {dispatch!r} and turn in (1, 2):
    if turn == 2:
        review = json.loads(bash("bash-review-input", ottoctl + ["review-input", "--task", "T1"]))
        judgments = {{alias: {{"verdict": "PASS", "rationale": "inspected_fixture_artifact",
            "evidence_refs": review["evidence_refs"]}} for alias in review["criterion_aliases"]}}
        review_args = ottoctl + ["review-task", "--task", "T1", "--request-key", "T1-review",
            "--candidate-ref", json.dumps(review["candidate_ref"]), "--judgments", json.dumps(judgments),
            "--inspection", json.dumps({{"observed": "Inspected the retained T1 worker artifact"}})]
        for source_ref in review["source_refs"]:
            review_args += ["--source-ref", json.dumps(source_ref)]
        bash("bash-review", review_args)
        bash("bash-finish", ottoctl + ["finish-task", "--task", "T1",
            "--request-key", "T1-review:finish", "--review-key", "T1-review"])
        finish("Manager turn 2: accepted T1 and yielding for owner settlement.")
if {dispatch!r} and turn in (1, 3):
    dispatch_number = 1 if turn == 1 else 2
    task, route = ("T1", "normal") if turn == 1 else ("T2", "xhard")
    out = bash("bash-run-%d" % dispatch_number, ottoctl + ["run-worker", "--task", task, "--route", route, "--principal",
                                               "demo-run-worker-%d" % dispatch_number, "--request-key", task + "-worker",
                                               "--focus", "Write the " + task + " answer"])
    open(os.path.join(cwd, "run-worker-%d.json" % dispatch_number), "w").write(out)
    finish("Manager turn %d: dispatched %s (%s) and yielding for its result." % (turn, task, route))
finish("Manager turn %d: done." % turn)
'''


BRIEF_T1 = "# Brief: T1\n\nBuild the first outcome. Proof: tests pass.\n"


class WorkerWorkspaceCompositionTests(unittest.TestCase):
    def test_fresh_project_view_loads_owner_policy_and_exact_criterion_aliases(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from herzchen.contracts import ResourceRef
        from otto.hostctl.serve import HostOwnerService

        project = ResourceRef("owner", "work.project", "project-a", "project-r2")
        prior_task = ResourceRef("owner", "work.task", "task-a", "task-r2")
        task = ResourceRef("owner", "work.task", "task-a", "task-r3")
        criterion = ResourceRef("owner", "assessment.criterion", "criterion-a", "criterion-r1")
        identities = {ref.id: SimpleNamespace(ref=ref, payload=payload)
                      for ref, payload in ((project, {"tasks": [prior_task.to_dict()]}),
                                           (task, {"alias": "T1"}),
                                           (criterion, {"definition": {"source_alias": "C01"}}))}
        reader = SimpleNamespace(get_identity=lambda ref: identities.get(ref.id))
        scope = SimpleNamespace(parent_obligation_ref=prior_task, criterion_refs=(criterion,))
        assessed = SimpleNamespace(coverage=lambda parent: {"scopes": [{"ref": {"id": "scope-a"}}]
                                   if parent.id == task.id else []},
                                   get_scope=lambda _ref: scope)
        service = object.__new__(HostOwnerService)
        service.state = {"authority": "owner", "project_ref": project.to_dict(),
                         "task_refs": {"T1": prior_task.to_dict()}, "manager": "manager"}
        service.owner = SimpleNamespace(
            binding=SimpleNamespace(authenticated_actor=lambda principal: principal),
            graph=SimpleNamespace(reader=reader, current=lambda _ref: identities[project.id]),
            evidence_payload_resolver=object())
        service.store = object()
        service._documents = lambda _project: [{"path": "run.json", "text": json.dumps({
            "assessment_accounting": {"kind": "owner_local_bookkeeping", "purpose": "local checks",
                "local_only": True, "pool_id": "fleet-checks", "capacity_units": 1,
                "cumulative_allowance_units": 1, "scope_mode": "check-accepted",
                "task_criterion_pairs": ["T1/C01"]}})}]

        with patch("otto.portfolio.assessment.OttoAssessment", return_value=assessed), \
             patch("herzchen.domains.assessment.AssessmentModule"):
            service._hydrate_assessment_policy(SimpleNamespace(payload={"tasks": [prior_task.to_dict()]}))

        self.assertEqual(service.state["assessment_policy"]["scope_mode"], "check-accepted")
        self.assertEqual(service.state["task_refs"], {"T1": task.to_dict()})
        self.assertEqual(service.state["criterion_refs"], {"C01": criterion.to_dict()})
        self.assertIsNone(service.assert_assessment_policy_current())
        policy = __import__("otto.portfolio.local_assessment_policy", fromlist=["LocalAssessmentPolicy"])
        parsed = policy.LocalAssessmentPolicy.from_run_config(service.state["assessment_policy"], state=service.state)
        self.assertEqual(parsed.task_criterion_pairs, ((task, criterion),))

        hydrated_state = json.loads(json.dumps(service.state))
        service._documents = lambda _project: [{"path": "run.json", "text": json.dumps({
            "assessment_accounting": {"kind": "owner_local_bookkeeping", "purpose": "changed owner policy",
                "local_only": True, "pool_id": "fleet-checks", "capacity_units": 1,
                "cumulative_allowance_units": 1, "scope_mode": "check-accepted",
                "task_criterion_pairs": ["T1/C01"]}})}]
        with self.assertRaisesRegex(RuntimeError, "changed after owner view hydration"):
            service.assert_assessment_policy_current()
        self.assertEqual(service.state, hydrated_state, "freshness check must not mutate trusted service state")

        service._documents = lambda _project: [{"path": "run.json", "text": json.dumps({
            "assessment_accounting": {"kind": "owner_local_bookkeeping", "purpose": "local checks",
                "local_only": True, "pool_id": "fleet-checks", "capacity_units": 1,
                "cumulative_allowance_units": 1, "task_criterion_pairs": ["T1/C01"]}})}]
        with patch("otto.portfolio.assessment.OttoAssessment", return_value=assessed), \
             patch("herzchen.domains.assessment.AssessmentModule"):
            service._hydrate_assessment_policy(SimpleNamespace(payload={"tasks": [prior_task.to_dict()]}))
        parsed = policy.LocalAssessmentPolicy.from_run_config(service.state["assessment_policy"], state=service.state)
        self.assertEqual(parsed.scope_mode, "review-required")

        service._documents = lambda _project: [{"path": "run.json", "text": json.dumps({
            "assessment_accounting": {"kind": "owner_local_bookkeeping", "purpose": "local checks",
                "local_only": True, "pool_id": "fleet-checks", "capacity_units": 1,
                "cumulative_allowance_units": 1, "task_criterion_pairs": ["T1/C99"]}})}]
        with patch("otto.portfolio.assessment.OttoAssessment", return_value=assessed), \
             patch("herzchen.domains.assessment.AssessmentModule"):
            with self.assertRaisesRegex(RuntimeError, "does not bind current owner records"):
                service._hydrate_assessment_policy(SimpleNamespace(payload={"tasks": [prior_task.to_dict()]}))

    def _service(self, due, workspace):
        from types import SimpleNamespace
        from otto.hostctl.serve import HostOwnerService
        service = object.__new__(HostOwnerService)
        service.due_port = SimpleNamespace(read_due=lambda schedule: due if schedule == due["schedule_id"] else None)
        service.worker_mcp_provider = lambda _due: {"token": "owner grant"}
        service.worker_context_provider = lambda _due: {"workspace": workspace}
        service.worker_lab_provider = lambda _project, _task: {"workspace": workspace}
        service._default_adapter_factory = False
        def adapter_factory(*, principal, model, reasoning, service, worker_mcp=None, workspace=None):
            return {"principal": principal, "model": model, "reasoning": reasoning,
                    "worker_mcp": worker_mcp, "workspace": workspace}
        service.adapter_factory = adapter_factory
        service.session = SimpleNamespace(execution_application=lambda adapter, **_kwargs: adapter)
        service.state = {"manager": "manager"}
        return service

    @staticmethod
    def _fleet_registry_for_due():
        import threading
        from types import SimpleNamespace
        from herzchen.contracts import ResourceRef
        from herzchen.domains.work.admission import authoring_stamp
        from herzchen.fleet.tools.tokens import TokenBook
        from otto.hostctl.product_service import OwnerFleetRegistry

        task_ref = ResourceRef("owner", "work.task", "task-a", "task-r1")
        payload = {"kind": "task", "fields": {}, "metadata_namespaces": {}}
        payload["metadata_namespaces"]["work.admission"] = authoring_stamp("task-r1", payload, "reviewer")
        task = SimpleNamespace(ref=task_ref, payload=payload)
        assignment_ref = ResourceRef("owner", "wrk.assignment", "assignment-a", "assignment-r2")
        assignment = SimpleNamespace(ref=assignment_ref, generation=2, role="executor",
                                      principal="worker-a", scope=task_ref)
        owner = SimpleNamespace(graph=SimpleNamespace(current=lambda _ref: task),
                                assignments=SimpleNamespace(get=lambda _ref: assignment))
        tokens = TokenBook()
        token = tokens.issue("assignment-a", "worker")
        record = SimpleNamespace(assignment="assignment-a", task=task, admitted_revision="task-r1",
                                 state="launched", role="worker", token=token)
        registry = object.__new__(OwnerFleetRegistry)
        registry.owner = owner
        registry.config = {"python": sys.executable}
        registry.tokens = tokens
        registry.records = {"assignment-a": record}
        registry.dispatcher = SimpleNamespace()
        registry._due_keys, registry._due_bindings = {}, {}
        registry._lock = threading.RLock()
        registry.facade_server = object()
        registry.facade_socket = "/tmp/otto-worker.sock"
        registry.assignment_context = lambda assignment_id, token=None: {
            "assignment_id": assignment_id, "token": token}
        due = {"schedule_id": "worker-run", "role": "worker", "recipient": "worker-a",
               "assignment_ref": assignment_ref.to_dict(), "generation": 2,
               "target": {"task_ref": task_ref.to_dict(), "assignment_ref": assignment_ref.to_dict()}}
        return registry, due

    def test_prepared_worker_workspace_is_verified_and_passed_to_adapter(self):
        service = self._service({"schedule_id": "pre-dispatch", "role": "manager"}, "/owner/labs/task-a")
        captured = service._execution(principal="worker", model="m", reasoning="high",
            evidence_id="pre-dispatch", project_ref={"id": "p"}, task_ref={"id": "t"},
            workspace="/owner/labs/task-a")
        self.assertEqual(captured["workspace"], "/owner/labs/task-a")

    def test_exact_worker_due_binds_lab_and_mcp_and_rejects_project_workspace_spoof(self):
        due = {"schedule_id": "worker-run", "role": "worker", "recipient": "worker-a",
               "assignment_ref": {"id": "assignment-a"}, "generation": 1,
               "target": {"task_ref": {"id": "task-a"}}}
        service = self._service(due, "/owner/labs/task-a")
        execution = service._execution(principal="worker-a", model="m", reasoning="high",
                                       evidence_id="worker-run")
        self.assertEqual(execution["workspace"], "/owner/labs/task-a")
        self.assertEqual(execution["worker_mcp"], {"token": "owner grant"})
        with self.assertRaises(PermissionError):
            service._execution(principal="worker-a", model="m", reasoning="high",
                               evidence_id="worker-run", workspace="/project/workspace")

    def test_non_manager_without_worker_due_cannot_fall_back_to_project_workspace(self):
        service = self._service({"schedule_id": "manager-run", "role": "manager"}, "/owner/labs/task-a")
        with self.assertRaises(PermissionError):
            service._execution(principal="worker-a", model="m", reasoning="high", evidence_id="missing-worker")

    def test_exact_project_advisor_help_due_keeps_non_worker_execution_available(self):
        from types import SimpleNamespace
        from herzchen.contracts import ResourceRef
        assignment_ref = ResourceRef("owner", "wrk.assignment", "advisor-a", "rev-3")
        assignment = SimpleNamespace(ref=assignment_ref, generation=2, role="project_advisor",
                                     principal="advisor-a")
        due = {"schedule_id": "help-run", "role": "project_advisor", "recipient": "advisor-a",
               "assignment_ref": assignment_ref.to_dict(), "generation": 2}
        service = self._service(due, "/owner/labs/task-a")
        service.owner = SimpleNamespace(assignments=SimpleNamespace(get=lambda _ref: assignment))
        execution = service._execution(principal="advisor-a", model="m", reasoning="high",
                                       evidence_id="help-run")
        self.assertEqual(execution["principal"], "advisor-a")

    def test_caller_context_keeps_the_exact_help_due_identity(self):
        from types import SimpleNamespace
        from herzchen.contracts import ResourceRef
        assignment_ref = ResourceRef("owner", "wrk.assignment", "advisor-a", "rev-3")
        assignment = SimpleNamespace(ref=assignment_ref, generation=2, role="project_advisor",
                                     principal="advisor-a")
        due = {"schedule_id": "help-run", "role": "project_advisor", "recipient": "advisor-a",
               "assignment_ref": assignment_ref.to_dict(), "generation": 2,
               "requested_model": "m", "requested_reasoning": "high"}
        service = self._service(due, "/owner/labs/task-a")
        service.owner = SimpleNamespace(assignments=SimpleNamespace(get=lambda _ref: assignment))
        service.session = SimpleNamespace(execution_application=lambda adapter, **_kwargs:
            SimpleNamespace(caller_context=lambda _caller: {"identity": "advisor"}))
        context = service._caller_context(SimpleNamespace(schedule_id="help-run",
            actor=SimpleNamespace(actor="advisor-a")))
        self.assertEqual(context, {"identity": "advisor"})
        due["generation"] = 3
        with self.assertRaises(PermissionError):
            service._caller_context(SimpleNamespace(schedule_id="help-run",
                actor=SimpleNamespace(actor="advisor-a")))

    def test_dispatcher_due_requires_exact_owner_generation_principal_and_task_revision(self):
        registry, due = self._fleet_registry_for_due()
        grant = registry.grant_for_due(due)
        self.assertEqual(grant.token, registry.records["assignment-a"].token)
        for key, value in (("generation", 1), ("recipient", "other")):
            registry, forged = self._fleet_registry_for_due()
            forged[key] = value
            with self.subTest(key=key), self.assertRaises(PermissionError):
                registry.grant_for_due(forged)
        registry, stale_task = self._fleet_registry_for_due()
        stale_task["target"]["task_ref"] = {**stale_task["target"]["task_ref"], "revision": "task-old"}
        with self.assertRaises(PermissionError):
            registry.grant_for_due(stale_task)


@unittest.skipUnless(sys.platform == "darwin" and os.path.exists("/usr/bin/sandbox-exec"), "macOS fence")
class ServeTests(HostctlFixture):
    dispatch = False
    escalate = False

    def setUp(self):
        super().setUp()
        # A Unix socket address is limited to 103 bytes: use a short home.
        short = os.path.realpath(tempfile.mkdtemp(prefix="ohs-", dir="/tmp"))
        self.addCleanup(lambda: shutil.rmtree(short, ignore_errors=True))
        self.home = os.path.join(short, "h")
        Path(self.launcher).write_text(LAUNCHER.format(python=sys.executable, src=SRC, home=self.home,
                                                       dispatch=self.dispatch, escalate=self.escalate))
        os.chmod(self.launcher, 0o755)
        os.makedirs(os.path.join(self.bundle, "briefs"))
        Path(self.bundle, "briefs", "T1.md").write_text(BRIEF_T1)
        self._ready()
        self.config = host_config.load(Path(self.home))

    def orchestrator(self, *argv, wait="120"):
        """The orchestrator's owner-custody manager command, relayed through its host lane."""
        code, out = self._ottoctl("--wait-seconds", wait, "manager", "--project", "demo-run", *argv)
        return out

    def attached(self):
        code, status = self._ottoctl("service", "status")
        return status["attached_project"]

    def test_editing_generated_view_does_not_change_owner_show(self):
        from otto.hostctl.serve import HostOwnerService

        code, before = self._ottoctl("project", "status", "--project", "demo-run")
        self.assertEqual(code, 0, before)
        root = Path(tempfile.mkdtemp(prefix="hostctl-view-", dir="/tmp"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))

        class Content:
            @staticmethod
            def read(_ref):
                return {"content": {"roles": {"coordinator": {"model": "model", "reasoning": "medium"}}}}

        service = object.__new__(HostOwnerService)
        service.state = {"project_ref": {"authority": "test", "kind": "work.project", "id": "demo-run"}}
        service.paths = {"run_view": root / "run"}
        service.run_id = "demo-run"
        service.config = {}
        service.owner = SimpleNamespace(content=Content())
        service._documents = lambda _project: [
            {"path": name, "text": Path(self.bundle, name).read_text()}
            for name in ("tasklist.md", "run.json")
        ]
        with patch("otto.hostctl.serve._registration", return_value={"steps": {"role_configuration": {
                "authority": "test", "kind": "dat.content.document", "id": "role-config"}}}):
            view = service.render_run_view()
        run_path = view / "run.json"
        generated = json.loads(run_path.read_text())
        marker = generated["otto_generated_view"]
        self.assertEqual(marker["authority"], "read-only projection")
        self.assertIn("owner records", marker["note"])

        run_path.write_text(json.dumps({"run_id": "forged", "roles": {}}))
        (view / "tasklist.md").write_text("## Forged tasks\n| id | outcome |\n|---|---|\n| BAD | forged |\n")

        code, after = self._ottoctl("project", "status", "--project", "demo-run")
        self.assertEqual(code, 0, after)
        self.assertEqual(after["tasks"], before["tasks"])
        self.assertEqual(sorted(task["id"] for task in after["tasks"]), ["T1", "T2"])

    def test_service_starts_no_due_relays_status_and_denies_a_foreign_socket_caller(self):
        code, before = self._ottoctl("schedules", "--project", "demo-run")
        status = self.orchestrator("status")
        self.assertEqual(status["outcome"], "ok", status)
        self.assertEqual(status["relayed"]["from"], "manager lane")
        self.assertEqual(status["manager"], "demo-run-manager")
        self.assertEqual(sorted(status["task_refs"]), ["T1", "T2"])
        attached = self.attached()
        self.assertEqual(attached["run_id"], "demo-run")
        self.assertTrue(os.path.exists(attached["caller_socket"]))
        # This test process was not launched by the owner: the socket refuses it.
        foreign = manager_client.run_launched(["whoami"], {"OTTO_CALLER_SOCKET": attached["caller_socket"]})
        self.assertEqual(foreign["outcome"], "error", foreign)
        self.assertFalse(foreign["provider_called"])
        # An identity-bearing command cannot be relayed for the orchestrator either.
        refused = self.orchestrator("whoami")
        self.assertEqual(refused["outcome"], "error", refused)
        code, busy = self._ottoctl("service", "run")
        self.assertEqual((code, busy["error"]["code"]), (3, "owner_service_running"))
        code, after = self._ottoctl("schedules", "--project", "demo-run")
        self.assertEqual(after["schedules"], before["schedules"])
        self.assertTrue(all(row["host_state"] == "paused" for row in after["schedules"]
                            if row.get("purpose") == "orchestrator-check"))

    def test_activation_launches_the_manager_which_authenticates_and_reads_its_documents(self):
        code, applied = self._ottoctl("operating-setup", "--project", "demo-run", "--operation", "apply")
        self.assertEqual((code, applied["outcome"], applied["started"]), (0, "replayed", False), applied)
        schedule = applied["setup"]["roles"]["manager"]
        # The journey assertions cover owner authentication and document reads;
        # the nested OS fence is independently exercised by the scope tests.
        with patch("otto.agents.claude_cli.MacWriteScope.preflight", autospec=True,
                   side_effect=lambda scope: {**scope.pin, "verified": True}), \
             patch("otto.agents.claude_cli.MacWriteScope.wrap", autospec=True,
                   side_effect=lambda scope, command, **options: command):
            started = self.orchestrator("start-manager", "--schedule-id", schedule)
        self.assertEqual(started.get("outcome"), "succeeded", started)
        root = Path(self.worktree)
        whoami = json.loads((root / "whoami.json").read_text())
        self.assertEqual(whoami["outcome"], "read", whoami)
        context = whoami["caller_context"]
        self.assertEqual((context["role"], context["principal"]), ("manager", "demo-run-manager"), context)
        # The manager reads its project's documents THROUGH Otto, over its own caller socket.
        listed = json.loads((root / "documents.json").read_text())
        self.assertEqual(listed["outcome"], "listed", listed)
        self.assertIn("briefs/T1.md", {row["path"] for row in listed["documents"]})
        self.assertEqual(listed["caller_context"]["principal"], "demo-run-manager")
        brief = json.loads((root / "brief-T1.json").read_text())
        self.assertEqual((brief["outcome"], brief["content"]), ("read", BRIEF_T1), brief)
        # The orchestrator's lane still answers while the manager is settled; a replay starts nothing.
        self.assertEqual(self.orchestrator("status")["outcome"], "ok")
        replay = self.orchestrator("start-manager", "--schedule-id", schedule)
        self.assertEqual(replay.get("outcome"), "replayed", replay)
        # Files created in the source directory after registration are not mirrored into Otto.
        os.makedirs(os.path.join(self.bundle, "reviews"), exist_ok=True)
        Path(self.bundle, "reviews", "after-start.md").write_text("# A review written during the run\n")
        code, status = self._ottoctl("project", "status", "--project", "demo-run")
        self.assertEqual(code, 0, status)
        self.assertNotIn("reviews/after-start.md", {row["path"] for row in status["documents"]})
        code, schedules = self._ottoctl("schedules", "--project", "demo-run")
        checks = [row for row in schedules["schedules"] if row.get("purpose") == "orchestrator-check"]
        self.assertEqual([row["host_state"] for row in checks], ["paused", "paused"])


class ManagerLoopTests(ServeTests):
    """The manager dispatches a Claude worker over the socket, yields, and is resumed."""
    dispatch = True

    def setUp(self):
        # This integration test exercises the canonical worker lab resolver,
        # which requires an owner-local checkout and admitted otto.plan data.
        # Give only this fixture a disposable repo and add plan metadata at
        # activation, where the real register/materialize path creates tasks.
        from unittest.mock import patch
        from otto.hostctl import register
        from otto.hostctl import serve
        from otto.hostctl.product_service import OwnerFleetRegistry
        import test_hostctl_cli

        # The manager loop now follows the same explicit review path as a
        # real manager. Give this fixture owner-declared criteria and a local
        # assessment allowance so the retained worker result can be judged.
        run = dict(test_hostctl_cli.RUN)
        run["assessment_accounting"] = {
            "kind": "owner_local_bookkeeping", "purpose": "manager loop fixture",
            "local_only": True, "pool_id": "manager-loop-checks", "capacity_units": 2,
            "cumulative_allowance_units": 2,
            "task_criterion_pairs": ["T1/C01", "T2/C02"]}
        run_patcher = patch.object(test_hostctl_cli, "RUN", run)
        run_patcher.start()
        self.addCleanup(run_patcher.stop)

        materialize = register.materialize
        task_refs = register._task_refs
        def materialize_with_worker_plans(session, record, registration, **kwargs):
            registration = dict(registration)
            planned = []
            for task in registration["tasks"]:
                task = dict(task)
                task["metadata_namespace"] = {"otto.plan": {
                    "route": "xhard" if task["id"] == "T2" else "normal",
                    "size": 1, "repo": "manager-loop-fixture", "branch": "main"}}
                planned.append(task)
            registration["tasks"] = planned

            def admitted_task_refs(session, project_record):
                from herzchen.contracts import ResourceRef
                project_ref = ResourceRef.from_dict(project_record.ref.to_dict())
                project = session.owner.graph.current(project_ref)
                creator = project.payload["provenance"]["creator"]
                project_user = session.binding.authenticated_actor(creator["actor"])
                refs = task_refs(session, project)
                for alias, raw in refs.items():
                    task = session.owner.graph.current(ResourceRef.from_dict(raw))
                    review = session.owner.graph.create_effort(project_ref, title="Fixture admission for " + alias,
                        logical_request_key="manager-loop-review:" + alias, actor=project_user)
                    admitted = session.owner.graph.admit(task.ref, revision=task.ref.revision,
                        review_ref=review.ref, logical_request_key="manager-loop-admit:" + alias,
                        actor=project_user)
                    refs[alias] = admitted["task_ref"].to_dict()
                    from herzchen.domains.assessment import AssessmentModule
                    AssessmentModule(session.owner.store, actor=project_user).declare_scope(
                        "manager-loop-scope:" + alias,
                        parent_obligation=ResourceRef.from_dict(refs[alias]), protocol="fixture",
                        criteria=[{"id": "C01" if alias == "T1" else "C02"}],
                        logical_request_key="manager-loop-scope:" + alias)
                return refs

            with patch.object(register, "_task_refs", admitted_task_refs):
                return materialize(session, record, registration, **kwargs)

        patcher = patch.object(register, "materialize", materialize_with_worker_plans)
        patcher.start()
        self.addCleanup(patcher.stop)

        attach = serve.attach

        def attach_with_worker_providers(*args, **kwargs):
            import hashlib
            import threading
            from herzchen.fleet.labs import LabFleet
            from types import MethodType

            journey = attach(*args, **kwargs)
            fleets = {}
            registry = object.__new__(OwnerFleetRegistry)
            registry.owner = journey.owner
            registry.config = journey.config
            registry._pair_lock = threading.RLock()

            def pair(_registry, key, repo, branch):
                if key not in fleets:
                    branch_key = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:20]
                    labs_root = repo.parent / (repo.name + ".otto-labs") / branch_key
                    fleets[key] = LabFleet(repo, labs_root, checkpoint=lambda *_args, **_kwargs: None)
                return fleets[key], None

            registry._pair = MethodType(pair, registry)

            def prepare(project_ref, task_ref):
                return OwnerFleetRegistry.prepare_worker_lab(registry, project_ref, task_ref)

            def context_for_due(due):
                if not isinstance(due, dict) or due.get("role") != "worker":
                    raise PermissionError("fixture lab context requires a worker Due")
                target = due.get("target")
                if not isinstance(target, dict) or not isinstance(target.get("project_ref"), dict) \
                        or not isinstance(target.get("task_ref"), dict):
                    raise PermissionError("fixture worker Due has no exact project and task references")
                assignment = due.get("assignment_ref")
                if not isinstance(assignment, dict) or not assignment.get("id"):
                    raise PermissionError("fixture worker Due has no assignment reference")
                if target.get("assignment_ref") != assignment:
                    raise PermissionError("fixture worker Due assignment target does not match")
                return prepare(target["project_ref"], target["task_ref"])

            journey.worker_lab_provider = prepare
            journey.worker_context_provider = context_for_due
            journey.worker_mcp_provider = lambda due: {"fixture_grant": due["assignment_ref"]["id"]}
            return journey

        attach_patcher = patch.object(serve, "attach", attach_with_worker_providers)
        attach_patcher.start()
        self.addCleanup(attach_patcher.stop)

        start_service = self._start_service

        def start_service_with_fixture_repository():
            import subprocess
            repo = Path(self.bundle).parent / "manager-loop-line"
            repo.mkdir()
            self.worker_repo = repo
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True,
                           capture_output=True, text=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Fixture"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "fixture@example.invalid"], check=True)
            (repo / "README.md").write_text("Disposable manager loop fixture repository.\n")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "fixture base"], check=True,
                           capture_output=True, text=True)
            installation_path = Path(self.home, "installation.json")
            installation = json.loads(installation_path.read_text())
            installation["repositories"] = {"manager-loop-fixture": str(repo)}
            installation_path.write_text(json.dumps(installation, indent=2))
            return start_service()

        self._start_service = start_service_with_fixture_repository
        super().setUp()

    def test_service_starts_no_due_relays_status_and_denies_a_foreign_socket_caller(self):
        self.skipTest("covered by ServeTests")

    def test_activation_launches_the_manager_which_authenticates_and_reads_its_documents(self):
        self.skipTest("covered by ServeTests")

    @staticmethod
    def service_adapter_factory(*, principal, model, reasoning, service, worker_mcp=None, workspace=None, **_):
        """Synthetic manager scope (children allowed); the worker leaf skips sandbox-exec.

        A scripted launcher is an interpreter script, which the leaf fence's
        single-executable exec rule correctly refuses; the leaf fence itself is
        proven in test_claude_binding and test_claude_manager_admission. The
        manager journey tests exercise owner routing and continuation, so their
        scope preflight is synthetic and independent of nested sandbox support.
        """
        from otto.agents.claude_adapter import ClaudeWorkerAdapter
        from otto.agents.claude_cli import ClaudeCliTransport, LauncherPin, MANAGER_TOOLS, MacWriteScope
        from otto.hostctl.adapters import claude_settings, native_state_root
        pin = LauncherPin.inspect(claude_settings(service.config)["launcher"])
        state = str(native_state_root(service.config))
        launch = service.manager_launch()
        worktree = workspace or service.worktree()
        unfenced = type("UnfencedScope", (), {"identity": MacWriteScope.identity, "workspace": worktree,
            "state_root": state, "allow_subprocesses": False,
            "pin": {"identity": MacWriteScope.identity, "workspace": worktree, "state_root": state,
                    "evidence_kind": "SYNTHETIC-UNFENCED-LEAF"},
            "preflight": lambda self: {**self.pin, "verified": True}, "wrap": lambda self, command, **o: command})()
        worker = ClaudeCliTransport(pin, unfenced, model=model, reasoning=reasoning, timeout_seconds=60)
        class SyntheticManagerScope(MacWriteScope):
            def preflight(self):
                return {**self.pin, "verified": True}

            def wrap(self, command, **options):
                return command

        manager_scope = SyntheticManagerScope(worktree, state, allow_subprocesses=True,
                                               extra_write_roots=launch["write_roots"])
        manager = ClaudeCliTransport(pin, manager_scope,
            model=model, reasoning=reasoning, timeout_seconds=120, tools=MANAGER_TOOLS, max_turns=200,
            extra_env=launch["env"])
        return ClaudeWorkerAdapter(owner=principal, source=worktree, worktree=worktree, launcher_pin=pin,
            state_root=state, requested_model=model, requested_reasoning=reasoning, transport=worker,
            roles=("worker", "manager"), manager_transport=manager, native_caller_socket=launch["env"]["OTTO_CALLER_SOCKET"],
            native_process_observer=service.native_callers.observe)

    def test_manager_dispatches_normal_and_xhard_workers_and_is_resumed_with_results(self):
        code, applied = self._ottoctl("operating-setup", "--project", "demo-run", "--operation", "apply")
        self.assertEqual(applied["outcome"], "replayed", applied)
        schedule = applied["setup"]["roles"]["manager"]
        root = Path(self.worktree)
        started = self.orchestrator("start-manager", "--schedule-id", schedule)
        self.assertEqual(started.get("outcome"), "succeeded", started)
        first_receipt = root / "run-worker-1.json"
        second_receipt = root / "run-worker-2.json"
        required = (first_receipt, second_receipt, root / "manager-turn-4.txt")
        deadline = time.monotonic() + 180
        last_read_error = None
        while time.monotonic() < deadline:
            if all(path.exists() for path in required):
                try:
                    first = json.loads(first_receipt.read_text())
                    second = json.loads(second_receipt.read_text())
                except (FileNotFoundError, json.JSONDecodeError) as exc:
                    last_read_error = exc
                else:
                    break
            time.sleep(0.2)
        else:
            missing = [path.name for path in required if not path.exists()]
            self.fail("manager dispatch/resume timed out; missing: " + ", ".join(missing) +
                      "; last receipt read error: " + repr(last_read_error))
        # Routing is proven from run.json (Otto's generated view): normal -> Haiku, xhard -> Sonnet.
        self.assertEqual((first["outcome"], first["selection"]["model"], first["selection"]["reasoning"]),
                         ("admitted", "claude-haiku-5-5", "high"), first)
        self.assertEqual((second["outcome"], second["selection"]["model"]), ("admitted", "claude-sonnet-5-5"), second)
        self.assertEqual(first["caller_context"]["role"], "manager")
        status = self.orchestrator("status")
        self.assertEqual(status["outcome"], "ok", status)
        lab_root = self.worker_repo.parent / (self.worker_repo.name + ".otto-labs")
        task_ids = {alias: ref["id"] for alias, ref in status["task_refs"].items()}
        self.assertEqual(len(list(lab_root.glob("**/" + task_ids["T1"] + "/answer-claude-haiku-5-5.txt"))), 1,
                        "normal-route worker did not write its assignment lab")
        self.assertEqual(len(list(lab_root.glob("**/" + task_ids["T2"] + "/answer-claude-sonnet-5-5.txt"))), 1,
                        "xhard-route worker did not write its assignment lab")
        self.assertFalse((root / "answer-claude-haiku-5-5.txt").exists(),
                         "normal-route worker wrote the manager workspace")
        self.assertFalse((root / "answer-claude-sonnet-5-5.txt").exists(),
                         "xhard-route worker wrote the manager workspace")
        # Each worker result was delivered back by resuming the same manager session.
        self.assertTrue((root / "manager-turn-2.txt").exists(), "manager not resumed after T1")
        self.assertTrue((root / "manager-turn-4.txt").exists(), "manager not resumed after T2")
        self.assertEqual(len(list(root.glob(".turns-*"))), 1, "the manager continued one session")


class EscalationTests(ServeTests):
    """Manager -> oracle (help request) -> the orchestrator's reply -> the manager continues."""
    escalate = True

    def test_service_starts_no_due_relays_status_and_denies_a_foreign_socket_caller(self):
        self.skipTest("covered by ServeTests")

    def test_activation_launches_the_manager_which_authenticates_and_reads_its_documents(self):
        self.skipTest("covered by ServeTests")

    def test_manager_escalates_the_orchestrator_answers_and_the_manager_applies_it(self):
        code, applied = self._ottoctl("operating-setup", "--project", "demo-run", "--operation", "apply")
        schedule = applied["setup"]["roles"]["manager"]
        root = Path(self.worktree)
        with patch("otto.agents.claude_cli.MacWriteScope.preflight", autospec=True,
                   side_effect=lambda scope: {**scope.pin, "verified": True}), \
             patch("otto.agents.claude_cli.MacWriteScope.wrap", autospec=True,
                   side_effect=lambda scope, command, **options: command):
            started = self.orchestrator("start-manager", "--schedule-id", schedule)
        self.assertEqual(started.get("outcome"), "succeeded", started)
        # The manager's request-help went through its file lane during its own turn.
        requested = json.loads((root / "request-help.json").read_text())
        self.assertIn("issue_id", requested, requested)
        issue_id = requested["issue_id"]
        code, read = self._ottoctl("help", "read", "--project", "demo-run")
        issue = next(item for item in read["issues"] if item["issue_id"] == issue_id)
        self.assertEqual(issue["current_owner_ref"]["kind"], "wrk.assignment")
        attached = self.attached()
        fields = ["--issue-id", issue_id, "--authority-source", "x", "--response", "Use design B",
                  "--proposed-solution", "x", "--next-action", "x"]
        # A launched process cannot answer for the oracle: not over its file lane (no owner grant) ...
        forged = manager_client.run_launched(["--timeout-seconds", "30", "respond-help", "--request-key", "forged",
            *fields], {"OTTO_MANAGER_IPC": attached["manager_ipc"]})
        self.assertNotEqual(forged.get("outcome"), "responded", forged)
        self.assertIn("host lane", json.dumps(forged))
        # ... and the orchestrator cannot smuggle it through the manager relay.
        smuggled = self.orchestrator("respond-help", "--request-key", "smuggled", *fields)
        self.assertEqual(smuggled["outcome"], "error", smuggled)
        scope_patches = [
            patch("otto.agents.claude_cli.MacWriteScope.preflight", autospec=True,
                  side_effect=lambda scope: {**scope.pin, "verified": True}),
            patch("otto.agents.claude_cli.MacWriteScope.wrap", autospec=True,
                  side_effect=lambda scope, command, **options: command)]
        for scope_patch in scope_patches:
            scope_patch.start()
            self.addCleanup(scope_patch.stop)
        code, answered = self._ottoctl("--wait-seconds", "60", "help", "respond", "--project", "demo-run",
            "--issue-id", issue_id, "--request-key", "ruling-1-answer", "--response", "Use design A",
            "--proposed-solution", "Design A keeps one resolver", "--next-action", "Implement T1 with design A")
        self.assertEqual(code, 0, answered)
        self.assertNotIn(answered.get("outcome"), {"error", "pending"}, answered)
        deadline = time.monotonic() + 60
        while not (root / "resolve-help.json").exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        for scope_patch in reversed(scope_patches):
            scope_patch.stop()
        resolved = json.loads((root / "resolve-help.json").read_text())
        self.assertNotEqual(resolved.get("outcome"), "error", resolved)
        self.assertIn("Use design A", (root / "manager-turn-2.txt").read_text())
        self.assertNotIn("Use design B", (root / "manager-turn-2.txt").read_text())


if __name__ == "__main__":
    unittest.main()
