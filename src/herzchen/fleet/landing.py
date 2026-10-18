"""Verified lifecycle for landing one worker lab on its line.

The owner supplies task admission, assessment writes, and the runner connection.  This module owns
the git sequence and insists that runner evidence identifies the clean, rebased commit exactly.
"""
from __future__ import annotations

from contextlib import closing, contextmanager, nullcontext
import fcntl
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping, Optional, Sequence

from ..domains.work.admission import admitted_revision
from .labs import _paths_to_commit, _work
from .runner.commit import git_commit_identity
from .runner.store import ResultStore


class LandingError(RuntimeError):
    """Landing was refused or could not safely complete; the lab is retained."""

    code = "landing_refused"

    def __init__(self, message: str, *, settled: bool | None = None) -> None:
        super().__init__(message)
        self.message = message
        # Owner-only effect fact. A refusal code or worker-visible text is not
        # proof that the line was untouched after a failed merge/update.
        self.settled = settled


def assert_line_checkout_clean(repo: Any, line_ref: str, *,
                               git: Optional[Callable[..., Any]] = None) -> None:
    """Require the configured line to be checked out cleanly at its branch tip.

    Worker preparation and landing share this preflight so an unusable line is
    refused before a worker lab is created or reused, and again before landing.
    """
    def run(*args: str) -> str:
        if git is not None:
            value = git(repo, *args)
            return value.decode() if isinstance(value, bytes) else str(value)
        done = subprocess.run(["git", "-C", os.fspath(repo), *args], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if done.returncode:
            detail = done.stderr.decode("utf-8", "replace").strip()
            raise LandingError("git %s failed: %s" % (args[0], detail))
        return done.stdout.decode("utf-8", "surrogateescape")

    branch = run("symbolic-ref", "-q", "HEAD").strip()
    if branch != line_ref:
        raise LandingError("line checkout is not on the configured line branch")
    head = run("rev-parse", "HEAD").strip()
    ref = run("rev-parse", "--verify", line_ref).strip()
    status = run("status", "--porcelain", "-z", "--untracked-files=all")
    if head != ref or status:
        raise LandingError("line checkout must be clean and at its branch tip")


class LandingService:
    """Owner-injected lab landing service.

    ``task_lookup`` returns the current admitted projection and its exact ``check_argv`` list.
    ``assessment`` is the existing AssessmentModule. ``assessment_context`` supplies its scope,
    input packet, and pool pins for a runner result. ``completion_blockers`` and ``completion_gate`` are required read predicates
    supplied by the owning completion path. ``result_lookup`` is required and must read the sealed
    runner record from its ResultStore.
    """

    def __init__(self, fleet: Any, runner: Any, task_lookup: Callable[[str], Mapping[str, Any]],
                 line_ref: str, *, assessment: Any = None,
                 assessment_context: Optional[Callable[..., Mapping[str, Any]]] = None,
                 criterion_lookup: Optional[Callable[[Any], Any]] = None,
                 completion_blockers: Optional[Callable[..., Mapping[str, Any]]] = None,
                 completion_gate: Optional[Callable[..., Mapping[str, Any]]] = None,
                 result_lookup: Optional[Callable[[str], Mapping[str, Any]]] = None,
                 lab_lookup: Optional[Callable[[str], Any]] = None,
                 git: Optional[Callable[..., Any]] = None, timeout: float = 3600) -> None:
        if not isinstance(line_ref, str) or not line_ref.startswith("refs/heads/"):
            raise ValueError("line_ref must be a fully qualified branch ref")
        self.fleet, self.runner, self.task_lookup, self.line_ref = fleet, runner, task_lookup, line_ref
        self.assessment = assessment
        self.assessment_context = assessment_context
        self.criterion_lookup = criterion_lookup
        self.completion_blockers = completion_blockers
        self.completion_gate = completion_gate
        self.result_lookup = result_lookup
        if result_lookup is None:
            raise ValueError("authoritative sealed runner result lookup is required")
        self.lab_lookup = lab_lookup or fleet._lab
        self._git_hook = git
        self.timeout = timeout

    def check(self, lab_name: str, task_id: str) -> dict[str, Any]:
        """Run the current admitted check and return feedback. This never accepts or lands work."""
        task = self._task(task_id)
        lab = self.lab_lookup(lab_name)
        record = self._run_check(lab, task_id, task, require_clean=False)
        return {"ok": record["exit_code"] == 0, "feedback_only": True,
                "run_id": record["run_id"], "commit": record["commit"],
                "exit_code": record["exit_code"], "outcome": record["outcome"]}

    def done(self, lab_name: str, task_id: str, *, assignment_id: str | None = None,
             candidate: Any = None,
             criterion: Any = None, parent_obligation: Any = None, actor: Any = None,
             gate_refs: Sequence[Any] = ()) -> dict[str, Any]:
        """Checkpoint, rebase, verify, assess and atomically advance the line."""
        task = self._task(task_id)
        if (self.assessment is None or self.assessment_context is None or self.criterion_lookup is None
                or self.completion_blockers is None
                or self.completion_gate is None):
            raise LandingError("assessment, criterion lookup, completion blockers and completion gate are required")
        if criterion is not None:
            self._require_current_criterion(criterion)
        lab = self.lab_lookup(lab_name)
        repo = Path(self.fleet.repo)
        # Serialize the line worktree and branch update across landing services/processes.
        lock_path = Path(str(repo / ".git" / "landing.lock"))
        if not lock_path.parent.is_dir():
            # In a linked worktree .git is a file; place the lock beside the common git dir.
            common = self._git(repo, "rev-parse", "--git-common-dir").strip()
            lock_path = (repo / common / "landing.lock").resolve()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._assert_line_clean(repo)
            base = self._git(repo, "rev-parse", "--verify", self.line_ref).strip()
            with self._lab_lock(lab_name):
                prepared = self._prepare(lab_name, task_id, task, lab, repo, base)
        except LandingError as exc:
            if exc.settled is None:
                exc.settled = True  # No line advancement has been attempted.
            raise
        with _exclusive_lock(lock_path), self._lab_lock(lab_name):
            result = self._accept_and_advance(lab_name, task_id, lab, repo, base, prepared,
                                              assignment_id, candidate, criterion, parent_obligation, actor,
                                              tuple(gate_refs))
        # Landing and worker-turn capture are separate owner operations. Keep
        # the lab available until the enclosing native turn has returned and
        # its Write artifacts have been captured by the owner.
        return result

    def _prepare(self, lab_name: str, task_id: str, task: Mapping[str, Any], lab: Any,
                 repo: Path, old_line: str) -> tuple[Mapping[str, Any], dict[str, Any], tuple]:
        if self._rebase_in_progress(lab):
            # The owner deliberately reopened the refused rebase for this
            # bounded worker turn. The worker may edit conflict markers, but
            # only the owner stages and advances Git's rebase metadata.
            paths = _paths_to_commit(_work(Path(lab.path), getattr(self.fleet, "exempt", ())))
            if not paths:
                raise LandingError("rebase conflict has no worker resolution", settled=True)
            try:
                self._git(Path(lab.path), "diff", "--check")
            except LandingError as exc:
                raise LandingError("rebase conflict markers or whitespace errors remain",
                                   settled=True) from exc
            self._git(Path(lab.path), "add", "-A", "--", *paths)
            self._git(Path(lab.path), "-c", "core.editor=true", "rebase", "--continue")
        else:
            # Commit through the fleet's one checkpoint mechanism, preserving its path policy.
            self._checkpoint(lab, lab_name)
        # Rebase the lab commit before checking. A failed rebase leaves the worker's lab intact.
        self._git(Path(lab.path), "fetch", "--no-tags", "origin", self.line_ref)
        try:
            self._git(Path(lab.path), "rebase", old_line)
        except LandingError as exc:
            aborted = False
            try:
                self._git(Path(lab.path), "rebase", "--abort")
                aborted = True
            except LandingError:
                pass
            raise LandingError("rebase conflict; lab returned to worker: %s" % exc,
                               settled=aborted) from exc
        rebased = lab.head()
        if lab.dirty():
            raise LandingError("rebased lab is dirty; refusing to run check")
        record = self._run_check(lab, task_id, task)
        if record["commit"] != rebased:
            raise LandingError("runner result is for a different commit")
        if record["exit_code"] != 0:
            raise LandingError("admitted check failed; lab returned to worker")
        gate_records = []
        for index, gate in enumerate(task.get("gate_checks", ())):
            gate_task = dict(task, check_argv=list(gate["check_argv"]))
            gate_id = str(gate.get("id") or "%s-gate-%d" % (task_id, index))
            gate_record = self._run_check(lab, gate_id, gate_task)
            if gate_record["commit"] != rebased or gate_record["exit_code"] != 0:
                raise LandingError("completion gate check failed on the rebased commit")
            gate_records.append(gate_record)
        # Ensure the verified commit is available in the line object database before CAS.
        self._git(repo, "fetch", "--no-tags", str(lab.path), "HEAD:refs/labs/%s" % lab_name)
        if self._git(repo, "rev-parse", "refs/labs/" + lab_name).strip() != rebased:
            raise LandingError("line could not verify the rebased lab commit")
        # Admission is re-read after the check. A changed task cannot donate an older argv result.
        current_task = self._task(task_id)
        if (current_task.get("revision") != task.get("revision")
                or current_task.get("current_revision") != task.get("current_revision")
                or current_task.get("check_argv") != task.get("check_argv")
                or current_task.get("gate_checks") != task.get("gate_checks")
                or current_task.get("payload") != task.get("payload")):
            raise LandingError("task admission changed during landing")
        return current_task, record, tuple(gate_records)

    def _rebase_in_progress(self, lab: Any) -> bool:
        git_dir = self._git(Path(lab.path), "rev-parse", "--absolute-git-dir").strip()
        return any((Path(git_dir) / name).exists() for name in ("rebase-merge", "rebase-apply"))

    def prepare_rework(self, lab_name: str) -> None:
        """Reopen one settled conflict in the same lab for a bounded owner turn."""
        lab = self.lab_lookup(lab_name)
        repo = Path(self.fleet.repo)
        self._assert_line_clean(repo)
        with self._lab_lock(lab_name):
            if self._rebase_in_progress(lab):
                return
            line = self._git(repo, "rev-parse", "--verify", self.line_ref).strip()
            self._git(Path(lab.path), "fetch", "--no-tags", "origin", self.line_ref)
            try:
                self._git(Path(lab.path), "rebase", line)
            except LandingError:
                if not self._rebase_in_progress(lab):
                    raise

    def _accept_and_advance(self, lab_name: str, task_id: str, lab: Any, repo: Path, old_line: str,
                            prepared: tuple, assignment_id: str | None, candidate: Any, criterion: Any, parent: Any,
                            actor: Any, gate_refs: Sequence[Any]) -> dict[str, Any]:
        task, record, gate_records = prepared
        self._assert_line_clean(repo)
        if self._git(repo, "rev-parse", "--verify", self.line_ref).strip() != old_line:
            raise LandingError("line advanced during landing; lab returned to worker")
        if lab.head() != record["commit"] or lab.dirty():
            raise LandingError("lab changed after its verified check; refusing acceptance")
        context = self.assessment_context(record, task, candidate=candidate, criterion=criterion,
                                          parent_obligation=parent, actor=actor,
                                          assignment_id=assignment_id, gate_refs=tuple(gate_refs),
                                          gate_records=tuple(gate_records))
        if not isinstance(context, Mapping):
            raise LandingError("assessment context did not provide the admitted scope, input and pool")
        # Owner adapters may resolve identity pins only after the lab commit and
        # its sealed check result are known.  Caller pins remain a compatibility
        # input for existing injected services; the Otto owner adapter always
        # returns these four trusted values itself.
        candidate = context.get("candidate", candidate)
        criterion = context.get("criterion", criterion)
        parent = context.get("parent_obligation", parent)
        actor = context.get("actor", actor)
        assessment = context.get("assessment", self.assessment)
        request_owned = "assessment" in context and assessment is not self.assessment
        with (closing(assessment) if request_owned and callable(getattr(assessment, "close", None)) else nullcontext()):
            criteria = tuple(context.get("criteria", (criterion,)))
            if not criteria or len(set(criteria)) != len(criteria):
                raise LandingError("owner assessment criteria must be a nonempty distinct pinned set")
            results, decisions = [], []
            for selected in criteria:
                self._require_current_criterion(selected)
                assess_kwargs = dict(context.get("assess_kwargs", {}))
                request_key = assess_kwargs.get("logical_request_key")
                if isinstance(request_key, str) and len(criteria) > 1:
                    assess_kwargs["logical_request_key"] = request_key + ":criterion:" + str(getattr(selected, "id", ""))
                result = assessment.assess(
                    context["scope"], candidate=candidate, criterion=selected,
                    input_packet=context["input_packet"], verdict="PASS",
                    protocol_result={
                        "runner": _runner_identity(record),
                        "gate_runners": [_runner_identity(gate_record) for gate_record in gate_records],
                    },
                    limit_pool=context["limit_pool"], actor=actor,
                    **assess_kwargs)
                if (getattr(result, "verdict", None) != "PASS"
                        and getattr(getattr(result, "verdict", None), "value", None) != "PASS"):
                    raise LandingError("assessment did not record PASS for the verified runner result")
                runner_identity = result.protocol_result.get("runner") if isinstance(result.protocol_result, Mapping) else None
                if not isinstance(runner_identity, Mapping) or any(
                        runner_identity.get(key) != record.get(key)
                        for key in ("run_id", "commit", "binding", "argv", "cwd", "exit_code")):
                    raise LandingError("assessment result is not linked to the verified runner record")
                decision = assessment.accept(
                    result.ref, candidate=candidate, criterion=selected,
                    rationale="Admitted task check passed on rebased commit " + record["commit"], actor=actor)
                if (getattr(decision, "result_ref", None) != result.ref
                        or getattr(decision, "disposition", None) not in {"accept", "accept-with-risk"}):
                    raise LandingError("assessment did not accept the exact passing result")
                results.append(result)
                decisions.append(decision)
            result_ref_json = [_json_ref(result.ref) for result in results]
            decision_ref_json = [_json_ref(decision.ref) for decision in decisions]
            decision_gates = tuple(gate_refs) + tuple(decision.ref for decision in decisions)
            blockers = self.completion_blockers(parent, candidate=candidate, gate_refs=decision_gates, actor=actor)
            if not _clear_blockers(blockers, tuple(decision.ref for decision in decisions)):
                raise LandingError("completion blockers remain")
            gate = self.completion_gate(parent, candidate=candidate, gate_refs=decision_gates, actor=actor)
            if not _clear_gate(gate):
                raise LandingError("completion gate refused landing")
            # The line lock and fast-forward merge update the checked-out branch, index and tree together.
            self._assert_line_clean(repo)
            if self._git(repo, "rev-parse", "--verify", self.line_ref).strip() != old_line:
                raise LandingError("line advanced during landing; lab returned to worker")
            rebased = record["commit"]
            mark_landed = getattr(self.fleet, "_mark_landed_locked", None)
            if callable(mark_landed):
                # Persist exact verified intent before advancing the line. The
                # owner Due capture predicate and ancestry check are both required
                # before a later cleanup may remove this lab.
                mark_landed(lab_name, rebased, self.line_ref)
            self._git(repo, "merge", "--ff-only", rebased)
            if self._git(repo, "rev-parse", "HEAD").strip() != rebased:
                raise LandingError("line checkout did not advance to the verified lab commit")
            return {"ok": True, "landed": True, "task": task_id, "commit": rebased,
                    "runner_run_id": record["run_id"],
                    "assessment_results": result_ref_json,
                    "acceptances": decision_ref_json,
                    "assessment_result": result_ref_json[0] if len(results) == 1 else result_ref_json,
                    "acceptance": decision_ref_json[0] if len(decisions) == 1 else decision_ref_json}

    def _checkpoint(self, lab: Any, name: str) -> None:
        # LabFleet owns the checkpoint callback and verification. Match park's path discovery but
        # retain the lab until acceptance and line advancement have completed.
        self._git(Path(lab.path), "reset", "-q")
        records = _work(Path(lab.path), getattr(self.fleet, "exempt", ()))
        paths = _paths_to_commit(records)
        if paths:
            checkpoint = getattr(self.fleet, "checkpoint", None)
            if not callable(checkpoint):
                raise LandingError("LabFleet checkpoint callback is unavailable")
            checkpoint(str(lab.path), paths, message="land " + name)
        if lab.dirty():
            raise LandingError("checkpoint left uncommitted lab work")

    def _task(self, task_id: str) -> Mapping[str, Any]:
        if not isinstance(task_id, str) or not task_id:
            raise LandingError("task id is required")
        task = self.task_lookup(task_id)
        if not isinstance(task, Mapping):
            raise LandingError("owner task lookup returned no admitted task")
        payload = task.get("payload")
        if not isinstance(payload, Mapping):
            raise LandingError("owner task lookup must return the current task payload")
        admitted = admitted_revision(payload)
        revision = task.get("revision")
        if (admitted is None or not isinstance(revision, str)
                or revision not in {admitted, task.get("current_revision", revision)}):
            raise LandingError("task payload is not admitted at its current revision")
        fields = payload.get("fields")
        check = fields.get("check") if isinstance(fields, Mapping) else None
        argv = check.get("argv") if isinstance(check, Mapping) else None
        if not isinstance(argv, (list, tuple)) or not argv or not all(
                isinstance(part, str) and "\0" not in part for part in argv):
            raise LandingError("task has no admitted argv check; free-text checks are refused")
        task = dict(task)
        task["check_argv"] = list(argv)
        if "gate_checks" in task:
            gates = task["gate_checks"]
            if not isinstance(gates, (list, tuple)):
                raise LandingError("gate checks must be a typed list")
            normalized_gates = []
            for gate in gates:
                if not isinstance(gate, Mapping) or not isinstance(gate.get("payload"), Mapping):
                    raise LandingError("completion gate check lacks its admitted payload")
                gate_revision = admitted_revision(gate["payload"])
                gate_fields = gate["payload"].get("fields")
                gate_check = gate_fields.get("check") if isinstance(gate_fields, Mapping) else None
                gate_argv = gate_check.get("argv") if isinstance(gate_check, Mapping) else None
                if (gate_revision is None or gate.get("revision") not in
                        {gate_revision, gate.get("current_revision", gate.get("revision"))}
                        or not _valid_argv(gate_argv)):
                    raise LandingError("completion gate contains a free-text or untyped check")
                normalized_gates.append(dict(gate, check_argv=list(gate_argv)))
            task["gate_checks"] = tuple(normalized_gates)
        return task

    def _run_check(self, lab: Any, task_id: str, task: Mapping[str, Any], *,
                   require_clean: bool = True) -> dict[str, Any]:
        argv = list(task["check_argv"])
        cwd = os.path.realpath(os.fspath(lab.path))
        commit = git_commit_identity(cwd)
        if commit is None:
            raise LandingError("check tree has no runner commit identity")
        if require_clean and lab.dirty():
            raise LandingError("check tree must be clean")
        submitted = self.runner.call({"op": "submit", "argv": argv, "cwd": cwd,
                                      "task": task_id, "purpose": "admitted task check"})
        if not submitted.get("ok") or not isinstance(submitted.get("run_id"), str):
            raise LandingError("runner refused admitted check")
        reply = self.runner.call({"op": "await", "run_id": submitted["run_id"], "timeout": self.timeout})
        if not reply.get("ok") or not reply.get("done") or not isinstance(reply.get("record"), Mapping):
            raise LandingError("runner did not return a terminal sealed result")
        record = dict(reply["record"])
        authoritative = self.result_lookup(submitted["run_id"])
        if not isinstance(authoritative, Mapping) or dict(authoritative) != record:
            raise LandingError("runner reply differs from authoritative sealed result")
        record = dict(authoritative)
        expected_binding = ResultStore.binding(argv, cwd, commit)
        if (record.get("run_id") != submitted["run_id"] or record.get("argv") != argv
                or record.get("cwd") != cwd or record.get("commit") != commit
                or record.get("binding") != expected_binding
                or record.get("state") != "settled" or record.get("outcome") != "exited"
                or type(record.get("exit_code")) is not int):
            raise LandingError("runner result does not identify the admitted check on this exact commit")
        if git_commit_identity(cwd) != commit:
            raise LandingError("lab changed while its check was running")
        if require_clean and (lab.head() != commit or lab.dirty()):
            raise LandingError("landing check did not run on a stable clean rebased commit")
        return record

    def _assert_line_clean(self, repo: Path) -> None:
        assert_line_checkout_clean(repo, self.line_ref, git=self._git)

    def _require_current_criterion(self, pinned: Any) -> None:
        if pinned is None:
            raise LandingError("exact admitted criterion reference is required")
        current = self.criterion_lookup(pinned)
        if not _typed_ref(pinned) or not _typed_ref(current):
            raise LandingError("criterion must be a typed pinned resource reference")
        if _ref_identity(current) != _ref_identity(pinned):
            raise LandingError("criterion reference is stale")

    def _lab_lock(self, name: str):
        hold = getattr(self.fleet, "_hold", None)
        return (hold(name, fcntl.LOCK_EX, "lab %s is held by a writer" % name)
                if callable(hold) else nullcontext())

    def _git(self, cwd: Any, *args: str) -> str:
        if self._git_hook is not None:
            value = self._git_hook(cwd, *args)
            return value.decode() if isinstance(value, bytes) else str(value)
        done = subprocess.run(["git", "-C", os.fspath(cwd), *args], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if done.returncode:
            detail = done.stderr.decode("utf-8", "replace").strip()
            raise LandingError("git %s failed: %s" % (args[0], detail))
        return done.stdout.decode("utf-8", "surrogateescape")


@contextmanager
def _exclusive_lock(path: Path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LandingError("another landing currently owns this line") from exc
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _valid_argv(value: Any) -> bool:
    return (isinstance(value, (list, tuple)) and bool(value)
            and all(isinstance(part, str) and "\0" not in part for part in value))


def _runner_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in ("run_id", "commit", "binding", "argv", "cwd", "exit_code")}


def _clear_blockers(value: Any, decision_ref: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("blockers") != []:
        return False
    if value.get("required") is True:
        accepted = value.get("accepted_decision_refs")
        if not isinstance(accepted, (list, tuple)):
            return False
        decisions = decision_ref if isinstance(decision_ref, (tuple, list)) else (decision_ref,)
        return all(any(_ref_identity(ref) == _ref_identity(decision) for ref in accepted)
                   for decision in decisions)
    return value.get("required") is False


def _clear_gate(value: Any) -> bool:
    if not isinstance(value, Mapping) or value.get("blockers", []) != []:
        return False
    eligibility = value.get("eligibility")
    explicit_clear = value.get("clear")
    if eligibility is not None and eligibility != "clear":
        return False
    if explicit_clear is not None and explicit_clear is not True:
        return False
    return eligibility == "clear" or explicit_clear is True


def _ref_identity(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif hasattr(value, "ref"):
        value = value.ref
        if hasattr(value, "to_dict"):
            value = value.to_dict()
    if isinstance(value, Mapping):
        return (value.get("authority"), value.get("kind"), value.get("id"), value.get("revision"))
    return value


def _json_ref(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise LandingError("assessment returned a reference that cannot be serialized")


def _typed_ref(value: Any) -> bool:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif hasattr(value, "ref"):
        value = value.ref
        if hasattr(value, "to_dict"):
            value = value.to_dict()
    return (isinstance(value, Mapping) and value.get("kind") == "assessment.criterion"
            and all(isinstance(value.get(key), str) and value[key]
                    for key in ("authority", "id", "revision")))
