"""Owner composition for Herzchen's fleet runner and landing mechanism.

The fleet owns the git/check protocol.  Otto supplies the task admission and the
project view.  Assessment completion remains deliberately fail closed until the
view has an exact candidate and frozen-input binding for the task.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from herzchen.contracts import ResourceRef
from herzchen.domains.work.admission import admitted_revision
from herzchen.fleet.capacity import CapacityPolicy, CapacityPool
from herzchen.fleet.landing import LandingError, LandingService
from herzchen.fleet.runner.runner import Runner
from herzchen.fleet.runner.store import ResultStore


class RunnerCallAdapter:
    """Expose the small JSON call protocol consumed by ``LandingService``."""

    def __init__(self, runner: Runner) -> None:
        self._runner = runner

    def call(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            return {"ok": False, "error": "bad_request"}
        op = request.get("op")
        if op == "submit":
            return self._runner.submit(request)
        if op == "await":
            return self._runner.await_run(request.get("run_id"), request.get("timeout"))
        return {"ok": False, "error": "bad_request", "detail": "unsupported runner operation"}


class RunnerLifecycle:
    """One owner runner and its adapter, with an explicit service lifecycle."""

    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        self.client = RunnerCallAdapter(runner)
        self._started = False

    def start(self) -> None:
        if not self._started:
            self.runner.start()
            self._started = True

    def close(self) -> None:
        if self._started:
            self.runner.stop()
            self._started = False


def compose_runner(home: Any, result_store: ResultStore,
                   capacity_policy: CapacityPolicy) -> RunnerLifecycle:
    """Compose one direct runner over the owner's shared result store.

    The caller starts this once for the owner and closes it during owner
    shutdown.  No runner socket or second ResultStore is created.
    """
    if not isinstance(result_store, ResultStore):
        raise TypeError("owner ResultStore is required")
    if not isinstance(capacity_policy, CapacityPolicy):
        raise TypeError("owner CapacityPolicy is required")
    runner = Runner(CapacityPool(capacity_policy), result_store,
                    state_dir=Path(home) / "runner-state")
    return RunnerLifecycle(runner)


def make_landing_service(*, fleet: Any, result_store: ResultStore,
                         repo_name: str, repo_path: Any, branch: str, owner: Any,
                         runner: Any, views_provider: Callable[[], Mapping[str, Any]],
                         task_lookup: Callable[[str], Mapping[str, Any]] | None = None,
                         timeout: float = 3600) -> LandingService:
    """Build a repo/branch landing service from owner-issued dependencies.

    ``views_provider`` is read at call time because owner project views are
    attached after the fleet registry is composed.  The resolver never reads
    worker request fields.  ``task_lookup`` may be supplied by the dispatch
    registry to additionally bind a task read to its retained assignment
    record; otherwise the task is re-read from the owner graph.
    """
    if not isinstance(repo_name, str) or not repo_name.strip():
        raise ValueError("repo name is required")
    if not isinstance(branch, str) or not branch.strip():
        raise ValueError("branch is required")
    if not isinstance(result_store, ResultStore):
        raise TypeError("owner ResultStore is required")
    if not callable(views_provider):
        raise TypeError("owner views provider is required")
    if not callable(getattr(runner, "call", None)):
        raise TypeError("owner runner call adapter is required")

    def current_task(task_id: str) -> Mapping[str, Any]:
        if task_lookup is not None:
            task = task_lookup(task_id)
            if not isinstance(task, Mapping):
                raise LandingError("dispatch-bound task lookup returned no current task")
            return task
        authority = owner.config["store"]["authority"]
        current = owner.graph.current(ResourceRef(authority, "work.task", task_id))
        return {"revision": current.ref.revision,
                "current_revision": current.ref.revision,
                "payload": current.payload}

    def view_for(task_id: str) -> tuple[Any, Mapping[str, Any]]:
        views = views_provider()
        if not isinstance(views, Mapping):
            raise LandingError("owner project views are unavailable")
        current = owner.graph.current(ResourceRef(owner.config["store"]["authority"],
                                                   "work.task", task_id))
        task_ref = current.ref.to_dict()
        project_id = None
        project_ref = current.payload.get("project_ref") if isinstance(current.payload, Mapping) else None
        if isinstance(project_ref, Mapping):
            project_id = project_ref.get("id")
        if project_id in views:
            view = views[project_id]
            state = getattr(getattr(view, "server", None), "state", None)
            if isinstance(state, Mapping):
                return view, state
        for view in views.values():
            state = getattr(getattr(view, "server", None), "state", None)
            if not isinstance(state, Mapping):
                continue
            refs = state.get("task_refs")
            if isinstance(refs, Mapping) and any(value == task_ref for value in refs.values()):
                return view, state
        raise LandingError("task has no exact active Otto project view")

    def assessment_context(record: Mapping[str, Any], task: Mapping[str, Any], **pins: Any) -> Mapping[str, Any]:
        task_id = str(task.get("id") or "")
        if not task_id:
            # LandingService intentionally passes the task payload projection;
            # retain task identity from the admitted check record.
            task_id = str(record.get("task") or "")
        _view, state = view_for(task_id)
        exact = state.get("fleet_assessment")
        exact = exact.get(task_id) if isinstance(exact, Mapping) else None
        required = {"scope_ref", "candidate_ref", "criterion_ref", "input_packet_ref", "limit_pool_ref"}
        if not isinstance(exact, Mapping) or not required.issubset(exact):
            raise LandingError(
                "owner project view lacks exact fleet assessment candidate, criterion, scope, input packet and pool pins"
            )
        raise LandingError(
            "owner fleet assessment pins are present but no trusted Otto assessment adapter is composed"
        )

    def no_criterion(pinned: Any) -> Any:
        # A complete assessment adapter is intentionally required before done
        # can accept work.  Returning a caller's pin here would make it look
        # current without an owner-side identity read.
        raise LandingError("owner project view has no trusted current criterion resolver")

    def no_completion(*_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
        raise LandingError("owner completion predicates are not composed for fleet landing")

    def no_gate(*_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
        raise LandingError("owner completion gate is not composed for fleet landing")

    return LandingService(
        fleet=fleet, runner=runner, task_lookup=current_task,
        line_ref="refs/heads/" + branch,
        assessment=None, assessment_context=assessment_context,
        criterion_lookup=no_criterion,
        completion_blockers=no_completion, completion_gate=no_gate,
        result_lookup=result_store.get, timeout=timeout,
    )

