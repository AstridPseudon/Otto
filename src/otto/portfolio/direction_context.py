"""Read-only invocation composition over D01/D02 owner capabilities.

No head selection, scope adoption, caller authentication or new state lives here.
Every bound applicable scope is mandatory; unbound scopes remain optional.
"""
from __future__ import annotations

from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from .direction import owner_direction_subject


def read_direction_context(directions: Any, *, actor: Any, assignment_ref: Any,
                           generation: int | None, project_ref: Any, task_ref: Any = None) -> list[dict[str, Any]]:
    pin = ResourceRef.from_dict(assignment_ref) if isinstance(assignment_ref, Mapping) else assignment_ref
    # Assignment lookup recovers the enduring responsibility independently of
    # principal names, native sessions and generation changes.
    responsibility = None if pin is None else directions.read(pin, actor=actor)
    project = ResourceRef.from_dict(project_ref)
    def same_identity(left: Any, right: ResourceRef) -> bool:
        if not isinstance(left, Mapping):
            return False
        ref = ResourceRef.from_dict(left)
        return (ref.authority, ref.kind, ref.id) == (right.authority, right.kind, right.id)
    if responsibility is not None:
        if responsibility.get("portfolio_ref") is not None:
            # A read grant alone does not enroll a project. Use the canonical
            # join written by Work's authenticated attach/transfer operation.
            record = directions.reader.get_record(ResourceRef(project.authority, project.kind, project.id))
            relation = None if record is None else record.payload.get("metadata", {}).get("otto_orchestrator")
            current = responsibility["assignment_ref"]
            if (responsibility.get("role") != "orchestrator" or not isinstance(relation, Mapping)
                    or relation.get("schema") != "otto.orchestrator.supervision.v2"
                    or not same_identity(relation.get("portfolio_ref"), ResourceRef.from_dict(responsibility["portfolio_ref"]))
                    or not same_identity(relation.get("project_ref"), project)
                    or relation.get("assignment_ref") != current
                    or relation.get("assignment_revision") != current.get("revision")
                    or relation.get("generation") != generation
                    or responsibility.get("generation") != generation):
                raise PermissionError("assignment direction is outside the enrolled portfolio project")
        elif not same_identity(responsibility["project_ref"], project):
            raise PermissionError("assignment direction is outside the granted project")
    scopes = [owner_direction_subject(project.authority), project]
    if task_ref is not None:
        scopes.append(ResourceRef.from_dict(task_ref))
    if responsibility is not None:
        scopes.append(ResourceRef.from_dict(responsibility["subject_ref"]))
    result, seen = [], set()
    for scope in scopes:
        identity = ResourceRef(scope.authority, scope.kind, scope.id)
        if identity in seen:
            continue
        seen.add(identity)
        binding = directions.read(identity, actor=actor)
        if binding.get("project_ref") is not None and not same_identity(binding["project_ref"], project):
            raise PermissionError("direction subject belongs to another project")
        if binding["document_ref"] is None:
            continue
        resolved = directions.resolve(identity, actor=actor, assignment_ref=pin, expected_generation=generation)
        result.append(dict(resolved, source="canonical scope adoption and exact assignment BASE pin"))
    return result


def direction_inputs(context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate exact inputs while retaining every scope attribution."""
    result, seen = [], {}
    for scope in context:
        for item in scope["inputs"]:
            ref = item["ref"]
            identity = tuple(ref[key] for key in ("authority", "kind", "id"))
            if identity in seen:
                if seen[identity] != item:
                    raise ValueError("applicable direction scopes contain conflicting input pins")
                continue
            seen[identity] = item
            result.append(item)
    return result
