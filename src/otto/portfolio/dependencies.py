"""Portfolio dependency policy over the existing work graph and supervision.

A work.gate uses the work lifecycle: its terminal success is ``completed``.
Assessment PASS decisions are separate assessment records, not work.gates;
a readiness observation or an arbitrary ``passed`` field cannot pass a gate.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from herzchen.contracts import ResourceRef
from herzchen.domains.work.model import GraphCycleError, WorkValidationError


def identity(value: Any) -> ResourceRef:
    ref = getattr(value, "ref", value)
    if isinstance(ref, Mapping):
        ref = ResourceRef.from_dict(ref)
    return ResourceRef(ref.authority, ref.kind, ref.id)


def supervision(record: Any) -> Mapping[str, Any]:
    return record.payload.get("metadata", {}).get("otto_orchestrator", {})


def same(left: Any, right: Any) -> bool:
    try:
        return identity(left) == identity(right)
    except (AttributeError, TypeError, ValueError, KeyError):
        return False


class PortfolioDependencies:
    """Finite owner helper; callers supply an authenticated principal."""

    def __init__(self, graph: Any, reader: Any, *, actor: Any, owner_actor: Any = None,
                 portfolio_ref: Any = None) -> None:
        self.graph, self.reader = graph, reader
        self.actor, self.owner_actor = actor, owner_actor
        self.portfolio_ref = portfolio_ref

    def _current(self, value: Any, cache: Optional[dict] = None) -> Any:
        ref = identity(value)
        key = (ref.authority, ref.kind, ref.id)
        if cache is not None and key in cache:
            return cache[key]
        result = self.reader.get_record(ref)
        if result is None:
            raise WorkValidationError("dependency record is not readable: " + ref.id)
        if cache is not None:
            cache[key] = result
        return result

    def authorize(self, project: Any, cache: Optional[dict] = None) -> Any:
        project = self._current(project, cache)
        if project.ref.kind != "work.project":
            raise WorkValidationError("dependency_scope_mismatch: dependent must be a project")
        relation = supervision(project)
        portfolio = relation.get("portfolio_ref")
        if (not portfolio or identity(portfolio).kind != "wrk.portfolio"
                or not same(relation.get("project_ref"), project)
                or (self.portfolio_ref is not None and not same(portfolio, self.portfolio_ref))):
            raise WorkValidationError("dependency_scope_mismatch: project is outside this portfolio")
        if self.owner_actor is not None and self.actor == self.owner_actor:
            return project
        assignment = self._current(relation.get("assignment_ref"), cache)
        principal = assignment.payload.get("principal")
        principal = principal.get("actor") if isinstance(principal, Mapping) else principal
        if (principal != self.actor.actor or self.actor.authority != project.ref.authority
                or assignment.payload.get("role") != "orchestrator"
                or not same(assignment.payload.get("scope"), portfolio)
                or assignment.payload.get("generation") != relation.get("generation")):
            raise PermissionError("only the portfolio orchestrator or owner may change project dependencies")
        return project

    def resolve_prerequisite(self, project_ref: Any, gate_id_or_alias: Optional[str] = None) -> Any:
        project = self._current(project_ref)
        if project.ref.kind != "work.project":
            raise WorkValidationError("prerequisite must name a project")
        if gate_id_or_alias is None:
            return project.ref
        matches = [record for record in self.graph.list(project=identity(project), kind="gate")
                   if gate_id_or_alias == record.id or gate_id_or_alias in record.aliases]
        if len(matches) != 1:
            raise WorkValidationError("gate ID or alias must resolve to exactly one gate in the prerequisite project")
        return matches[0].ref

    def _validate_link(self, project: Any, prerequisite: Any, cache: Optional[dict] = None) -> Any:
        prerequisite = self._current(prerequisite, cache)
        if prerequisite.ref.kind not in {"work.project", "work.gate"}:
            raise WorkValidationError("dependency_scope_mismatch: projects may depend only on projects or gates")
        upstream = prerequisite if prerequisite.ref.kind == "work.project" else self._current(prerequisite.payload.get("project_ref"), cache)
        if (upstream.ref.kind != "work.project" or not same(supervision(upstream).get("project_ref"), upstream)
                or not same(supervision(project).get("portfolio_ref"), supervision(upstream).get("portfolio_ref"))):
            raise WorkValidationError("dependency_scope_mismatch: projects must share a portfolio")
        if prerequisite.ref.kind == "work.gate" and same(project, upstream):
            raise WorkValidationError("dependency_scope_mismatch: gate must belong to another project")
        return prerequisite

    def change(self, project: Any, prerequisite: Any, *, request_id: str, remove: bool = False) -> dict:
        project = self.authorize(project)
        # An upstream project may have been detached since the link was made.
        # Its former dependents must still be able to remove the blocked edge.
        prerequisite = self._current(prerequisite) if remove else self._validate_link(project, prerequisite)
        if prerequisite.ref.kind not in {"work.project", "work.gate"}:
            raise WorkValidationError("dependency_scope_mismatch: projects may depend only on projects or gates")
        before = self.reader.get_receipt(request_id)
        if not remove and before is None:
            self._check_project_cycle(project, prerequisite)
        command = self.graph.unlink_dependency if remove else self.graph.link_dependency
        updated = command(identity(project), identity(prerequisite), logical_request_key=request_id, actor=self.actor)
        receipt = self.reader.get_receipt(request_id)
        receipt = receipt.to_dict() if receipt is not None else None
        return {"outcome": "replayed" if before is not None else ("removed" if remove else "linked"),
                "project_ref": updated.ref.to_dict(), "dependency_ref": prerequisite.ref.to_dict(),
                "receipt": receipt, "replayed": before is not None,
                "event_ids": [] if receipt is None else list(receipt.get("event_ids", ())) }

    def _check_project_cycle(self, project: Any, prerequisite: Any) -> None:
        """Gate membership is also an activation prerequisite on its project.

        The work graph still checks the canonical dependency edges. This
        additional policy check catches A -> gate-in-B -> B -> A deadlocks,
        which cannot be represented by a work graph parent dependency.
        """
        cache, visited = {}, set()
        pending = [prerequisite]
        while pending:
            current = self._current(pending.pop(), cache)
            if current.ref.kind == "work.gate":
                current = self._current(current.payload["project_ref"], cache)
            if same(current, project):
                raise GraphCycleError("portfolio project dependency cycle rejected")
            key = identity(current)
            if key in visited:
                continue
            visited.add(key)
            pending.extend(current.payload.get("dependencies", ()))

    def readiness(self, project: Any, *, observe: bool = True, cache: Optional[dict] = None) -> dict:
        cache = {} if cache is None else cache
        project = self.authorize(project, cache)
        dependencies = []
        for value in project.payload.get("dependencies", ()):
            ref = identity(value)
            try:
                prerequisite = self._validate_link(project, ref, cache)
                lifecycle = prerequisite.payload.get("lifecycle")
                satisfied = lifecycle == "completed"
                upstream = prerequisite.ref if ref.kind == "work.project" else prerequisite.payload.get("project_ref")
                row = {"ref": prerequisite.ref.to_dict(), "project_ref": identity(upstream).to_dict(),
                       "title": prerequisite.payload.get("title"), "kind": prerequisite.ref.kind,
                       "lifecycle": lifecycle, "satisfied": satisfied,
                       "reason": None if satisfied else ("gate_not_passed" if ref.kind == "work.gate" else "project_not_completed")}
            except (WorkValidationError, AttributeError, TypeError, ValueError, KeyError) as error:
                row = {"ref": ref.to_dict(), "satisfied": False, "reason": str(error)}
            dependencies.append(row)
        # A declared external prerequisite is represented by an ordinary
        # project gate with portfolio_setup.external_prerequisite metadata.
        # It remains within the same project and therefore has no graph edge
        # (which would be a self dependency); its lifecycle is still the
        # canonical pass/fail signal.
        for gate in self.graph.list(project=identity(project), kind="gate"):
            setup = (gate.payload.get("fields") or {}).get("portfolio_setup") or {}
            external = setup.get("external_prerequisite")
            if not external:
                continue
            satisfied = gate.payload.get("lifecycle") == "completed"
            dependencies.append({"ref": gate.ref.to_dict(), "project_ref": identity(project).to_dict(),
                "title": gate.payload.get("title"), "kind": gate.ref.kind,
                "lifecycle": gate.payload.get("lifecycle"), "satisfied": satisfied,
                "external_prerequisite": external,
                "reason": None if satisfied else "external_prerequisite_not_passed"})
        blockers = [row for row in dependencies if not row["satisfied"]]
        observation = {"status": "blocked" if blockers else "ready", "ready": not blockers,
                       "dispatch": False, "blockers": blockers}
        # Preserve an activation override for status and audit; recomputation
        # must never erase the reason that admitted a blocked project.
        previous = project.payload.get("readiness", {})
        if previous.get("override"):
            observation["override"] = previous["override"]
        if observe and previous != observation:
            updated = self.graph.set_readiness(identity(project), observation, actor=self.actor)
            key = (project.ref.authority, project.ref.kind, project.ref.id)
            cache.pop(key, None)
            project = updated
        return {"project_ref": project.ref.to_dict(), **observation, "dependencies": dependencies}

    def activation_check(self, project: Any, *, override: bool = False,
                         reason: Optional[str] = None, request_id: str) -> dict:
        """Record the readiness decision before canonical activation proceeds."""
        if override and (not isinstance(reason, str) or not reason.strip()):
            raise WorkValidationError("readiness override requires a non-blank reason")
        result = self.readiness(project)
        if result["ready"]:
            return {"outcome": "ready", "readiness": result}
        if not override:
            return {"outcome": "error", "readiness": result,
                    "error": {"code": "project_readiness_blocked",
                              "message": "project activation blocked by: " + ", ".join(
                                  str(item.get("title") or item["ref"]["id"]) for item in result["blockers"]),
                              "blockers": result["blockers"]}}
        observation = {key: result[key] for key in ("status", "ready", "dispatch", "blockers")}
        observation["override"] = {"reason": reason.strip(), "actor": self.actor.actor,
                                   "request_id": request_id}
        updated = self.graph.set_readiness(identity(project), observation,
            logical_request_key=request_id + ":readiness-override", actor=self.actor)
        receipt = self.reader.get_receipt(request_id + ":readiness-override")
        return {"outcome": "overridden", "project_ref": updated.ref.to_dict(),
                "readiness": {**result, **observation},
                "receipt": None if receipt is None else receipt.to_dict()}
