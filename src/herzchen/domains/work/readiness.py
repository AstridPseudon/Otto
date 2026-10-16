"""Pure readiness checks for dispatchable work.

The work domain owns task admission and task dependency rules. Integrations
provide record readers and any portfolio specific gate policy through
callbacks, keeping this module independent of Otto and persistence.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from . import admission


def ready(
    task: Any,
    *,
    read_record: Callable[[Any], Any],
    project_readiness: Optional[Callable[[Any], Any]] = None,
    gate_satisfied: Optional[Callable[[Any], bool]] = None,
    read_revision: Optional[Callable[[Any], Any]] = None,
    is_admitted: Optional[Callable[[Any], bool]] = None,
) -> dict:
    """Return whether a task may run and the reasons it is waiting.

    ``read_record`` resolves dependency references. ``project_readiness`` may
    apply host-specific project, portfolio gate, or external prerequisite
    rules. The admission stamp names a reviewed revision and remains valid
    across lifecycle/readiness revisions; it is never compared to the current
    identity revision.
    """
    blockers = []
    payload = _value(task, "payload", {})
    admitted_revision = admission.admitted_revision(payload) if isinstance(payload, Mapping) else None
    admitted = admitted_revision is not None
    if is_admitted is not None:
        try:
            admitted = admitted and bool(is_admitted(task))
        except Exception:
            admitted = False
    if admitted and read_revision is not None:
        pinned = _revision_ref(_value(task, "ref", None), admitted_revision)
        try:
            reviewed = read_revision(pinned) if pinned is not None else None
            admitted = reviewed is not None and not admission.reviewed_content_diff(
                _value(reviewed, "payload", {}), payload
            )
        except Exception:
            admitted = False
    if not admitted:
        blockers.append({"reason": "task_not_admitted", "ref": _safe_ref(_value(task, "ref", None))})

    task_lifecycle = _lifecycle(task)
    if task_lifecycle in {"completed", "withdrawn"}:
        blockers.append({"reason": "task_not_dispatchable", "ref": _safe_ref(_value(task, "ref", None)),
                         "lifecycle": task_lifecycle})

    dependencies = payload.get("dependencies", ()) if isinstance(payload, Mapping) else ()
    for value in dependencies or ():
        ref = _value(value, "ref", value)
        try:
            dependency = read_record(_current_ref(ref))
            if dependency is None:
                raise LookupError("dependency record is not readable")
            kind = _kind(_value(dependency, "ref", None))
            lifecycle = _lifecycle(dependency)
            if kind in {"work.gate", "gate"}:
                satisfied = (gate_satisfied(dependency) if gate_satisfied is not None
                             else lifecycle == "completed")
                reason = "gate_not_passed"
            elif kind in {"work.task", "task"}:
                satisfied = lifecycle == "completed"
                reason = "dependency_not_completed"
            else:
                satisfied, reason = False, "unsupported_dependency_kind"
            if not satisfied:
                blockers.append({"reason": reason, "ref": _safe_ref(_value(dependency, "ref", ref)),
                                 "lifecycle": lifecycle})
        except (LookupError, KeyError, TypeError, ValueError, AttributeError) as error:
            blockers.append({"reason": "dependency_unavailable", "ref": _safe_ref(ref),
                             "detail": str(error)})

    if project_readiness is not None:
        project_ref = _value(task, "project_ref", None)
        if project_ref is None and isinstance(payload, Mapping):
            project_ref = payload.get("project_ref")
        try:
            result = project_readiness(project_ref)
            is_ready = result.get("ready", False) if isinstance(result, Mapping) else bool(result)
            if not is_ready:
                blockers.append({"reason": "project_dependencies_blocked",
                                 "project_ref": _safe_ref(project_ref),
                                 "readiness": dict(result) if isinstance(result, Mapping) else None})
        except (LookupError, KeyError, TypeError, ValueError, AttributeError) as error:
            blockers.append({"reason": "project_readiness_unavailable",
                             "project_ref": _safe_ref(project_ref), "detail": str(error)})

    return {"ready": not blockers, "blockers": blockers,
            "admitted_revision": admitted_revision if admitted else None}


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _kind(ref: Any) -> Optional[str]:
    kind = _value(ref, "kind")
    return getattr(kind, "value", kind)


def _lifecycle(record: Any) -> Any:
    value = _value(record, "lifecycle")
    if value is None:
        value = _value(_value(record, "payload", {}), "lifecycle")
    return getattr(value, "value", value)


def _safe_ref(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict"):
        return value.to_dict()
    ref = _value(value, "ref")
    if ref is not None and ref is not value:
        return _safe_ref(ref)
    if isinstance(value, Mapping):
        return dict(value)
    return str(value)


def _revision_ref(ref: Any, revision: Optional[str]) -> Any:
    if ref is None or revision is None:
        return None
    if hasattr(ref, "authority"):
        try:
            return type(ref)(ref.authority, ref.kind, ref.id, revision)
        except (TypeError, ValueError):
            return None
    if isinstance(ref, Mapping):
        return {**ref, "revision": revision}
    return None


def _current_ref(ref: Any) -> Any:
    """Remove a historical revision pin before checking dependency state."""
    if hasattr(ref, "authority"):
        try:
            return type(ref)(ref.authority, ref.kind, ref.id)
        except (TypeError, ValueError):
            return ref
    if isinstance(ref, Mapping) and "authority" in ref and "kind" in ref and "id" in ref:
        return {"authority": ref["authority"], "kind": ref["kind"], "id": ref["id"], "revision": None}
    return ref


__all__ = ["ready"]
