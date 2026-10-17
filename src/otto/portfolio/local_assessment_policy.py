"""Trusted controller policy for bounded local assessment accounting."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping
from herzchen.contracts import ResourceRef


_PROJECT_CONTENT_KEYS = (
    "title", "name", "outcome", "scope", "approach", "acceptance",
    "protocol", "custom", "criteria",
)


def _project_content(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Stable authored project fields; owner metadata and linked refs can advance."""
    result = {key: payload.get(key) for key in _PROJECT_CONTENT_KEYS}
    tasks = payload.get("tasks", ())
    if isinstance(tasks, (list, tuple)):
        result["tasks"] = tuple(
            (item.get("authority"), item.get("kind"), item.get("id"))
            if isinstance(item, Mapping) else
            (item.authority, item.kind, item.id) if isinstance(item, ResourceRef) else item
            for item in tasks
        )
    else:
        result["tasks"] = tasks
    return result


@dataclass(frozen=True)
class LocalAssessmentPolicy:
    purpose: str
    local_only: bool
    pool_ref: ResourceRef
    capacity_units: int
    cumulative_allowance_units: int
    scope_project_ref: ResourceRef
    task_criterion_pairs: tuple[tuple[ResourceRef, ResourceRef], ...]
    scope_mode: str = "review-required"

    def __post_init__(self) -> None:
        project, pool = self.scope_project_ref, self.pool_ref
        if (not isinstance(self.purpose, str) or not self.purpose.strip() or len(self.purpose) > 512
                or self.local_only is not True or not isinstance(project, ResourceRef)
                or project.kind != "work.project" or not project.revision
                or not isinstance(pool, ResourceRef) or pool.kind != "limit" or pool.revision is not None
                or pool.authority != project.authority):
            raise ValueError("local assessment policy requires purpose, local_only and exact owner pool/project refs")
        if (not isinstance(self.scope_mode, str)
                or self.scope_mode not in {"review-required", "check-accepted"}):
            raise ValueError("local assessment scope_mode must be review-required or check-accepted")
        pairs = self.task_criterion_pairs
        if not isinstance(pairs, tuple) or not 1 <= len(pairs) <= 256:
            raise ValueError("local assessment policy requires 1..256 task/criterion pairs")
        for pair in pairs:
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or any(not isinstance(ref, ResourceRef) or not ref.revision
                           or ref.authority != project.authority for ref in pair)
                    or pair[0].kind != "work.task" or pair[1].kind != "assessment.criterion"):
                raise ValueError("local assessment policy pairs must pin owner task/criterion revisions")
        if len(set(pairs)) != len(pairs):
            raise ValueError("duplicate local assessment task/criterion pair")
        if (type(self.capacity_units) is not int or type(self.cumulative_allowance_units) is not int
                or not 1 <= self.capacity_units <= self.cumulative_allowance_units <= len(pairs)):
            raise ValueError("local assessment capacity/allowance must be bounded by configured pairs")

    @classmethod
    def from_run_config(cls, configured: Mapping[str, Any], *, state: Mapping[str, Any]) -> "LocalAssessmentPolicy":
        """Normalize declarative run aliases using trusted owning-controller state."""
        project = ResourceRef.from_dict(state["project_ref"])
        if state["authority"] != project.authority:
            raise ValueError("trusted controller project and authority differ")
        return cls.from_config(configured, project_ref=state["project_ref"],
                               task_refs=state["task_refs"], criterion_refs=state["criterion_refs"])

    @classmethod
    def from_config(cls, configured: Mapping[str, Any], *, task_refs: Mapping[str, Any],
                    criterion_refs: Mapping[str, Any], project_ref: Any = None) -> "LocalAssessmentPolicy":
        """Resolve the small declarative run policy through trusted current state.

        The run file may name the pool as ``pool_id`` and pairs as ``PA01/C01``
        for readability.  The controller supplies the current project and
        exact task/criterion maps before this constructor is called.  No
        transport caller can supply or alter this policy.
        """
        if not isinstance(configured, Mapping):
            raise ValueError("assessment_accounting must be an object")
        required = {"kind", "purpose", "local_only", "capacity_units",
                    "cumulative_allowance_units", "task_criterion_pairs"}
        if not required.issubset(configured):
            raise ValueError("assessment_accounting is missing required local policy fields")
        if configured["kind"] != "owner_local_bookkeeping" or configured["local_only"] is not True:
            raise ValueError("assessment_accounting must be local-only owner bookkeeping")
        project_value = configured.get("scope_project_ref", project_ref)
        if project_value is None:
            raise ValueError("assessment_accounting requires the trusted current project")
        project = ResourceRef.from_dict(project_value)
        pool_value = configured.get("pool_ref")
        if pool_value is None:
            pool_id = configured.get("pool_id")
            if not isinstance(pool_id, str) or not pool_id.strip():
                raise ValueError("assessment_accounting requires a pool_id or pool_ref")
            pool_value = {"authority": project.authority, "kind": "limit", "id": pool_id}
        elif configured.get("pool_id") is not None and configured["pool_id"] != pool_value.get("id"):
            raise ValueError("assessment_accounting pool_id and pool_ref disagree")
        pairs_value = configured["task_criterion_pairs"]
        rows = []
        if not isinstance(pairs_value, list):
            raise ValueError("assessment_accounting requires bounded task/criterion aliases")
        for raw in pairs_value:
            if isinstance(raw, str) and raw.count("/") == 1:
                task_alias, criterion_alias = raw.split("/")
                raw = {"task": task_alias, "criterion": criterion_alias}
            rows.append(raw)
        if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
            raise ValueError("assessment_accounting requires bounded task/criterion aliases")
        pairs = []
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {"task", "criterion"}:
                raise ValueError("assessment_accounting pairs require task and criterion aliases")
            if row["task"] not in task_refs or row["criterion"] not in criterion_refs:
                raise ValueError("assessment_accounting alias is not in trusted controller state")
            pairs.append((ResourceRef.from_dict(task_refs[row["task"]]),
                          ResourceRef.from_dict(criterion_refs[row["criterion"]])))
        return cls(configured["purpose"], configured["local_only"],
                   ResourceRef.from_dict(pool_value), configured["capacity_units"],
                   configured["cumulative_allowance_units"], project,
                   tuple(pairs), configured.get("scope_mode", "review-required"))

    def validate_binding(self, project: ResourceRef, task: ResourceRef, reader: Any) -> None:
        project_pin = self.scope_project_ref
        task_pins = tuple(member for member, _ in self.task_criterion_pairs)
        same_identity = lambda left, right: (
            left.authority, left.kind, left.id
        ) == (right.authority, right.kind, right.id)
        if (not isinstance(project, ResourceRef) or not isinstance(task, ResourceRef)
                or not same_identity(project, project_pin)
                or not any(same_identity(task, pin) for pin in task_pins)):
            raise PermissionError("local assessment policy is outside the configured project/task")

        current_project = reader.get_identity(
            ResourceRef(project.authority, project.kind, project.id)
        )
        current_task = reader.get_identity(
            ResourceRef(task.authority, task.kind, task.id)
        )
        if (current_project is None or current_task is None
                or current_project.ref != project):
            raise PermissionError("local assessment policy project/task is missing")

        if not isinstance(current_task.payload, Mapping):
            raise PermissionError("local assessment policy task content is stale")

        if project != project_pin:
            retained_project = reader.get_revision(project_pin)
            if (retained_project is None or retained_project.ref != project_pin
                    or not isinstance(retained_project.payload, Mapping)
                    or not isinstance(current_project.payload, Mapping)
                    or _project_content(retained_project.payload) != _project_content(current_project.payload)):
                raise PermissionError("local assessment policy project content is stale")

        # The retained task content also pins its project parent. Require that
        # parent to remain in the configured project identity, while allowing
        # the stored parent ref to name an earlier project metadata revision.
        # Some trusted owner task views omit the parent ref entirely. In that
        # case the task's identity is already anchored by the configured
        # policy and the current project/task identity checks above. If a
        # parent is present, however, it must be well formed and name this
        # project identity.
        task_has_project = "project_ref" in current_task.payload
        task_project = current_task.payload.get("project_ref")
        if task_has_project and isinstance(task_project, Mapping):
            try:
                task_project = ResourceRef.from_dict(task_project)
            except (TypeError, ValueError):
                task_project = None
        if task_has_project and (
                not isinstance(task_project, ResourceRef)
                or not same_identity(task_project, project_pin)):
            raise PermissionError("local assessment policy task is outside the configured project")

        # Task revisions may advance for admission or other metadata writes,
        # while authored content remains pinned to the policy's retained ref.
        from herzchen.domains.work.admission import task_content_matches

        matching_pins = tuple(pin for pin in task_pins if same_identity(task, pin))
        try:
            content_matches = all(task_content_matches(reader, pin, current_task.payload,
                                                       current_ref=current_task.ref)
                                  for pin in matching_pins)
        except (AttributeError, KeyError, LookupError, TypeError, ValueError):
            content_matches = False
        if not content_matches:
            raise PermissionError("local assessment policy task content is stale")

        # Criteria remain exact revision bindings. Preserve the existing
        # criterion fence even when the task pin survives metadata revisions.
        for member, criterion in self.task_criterion_pairs:
            if not same_identity(member, task):
                continue
            current_criterion = reader.get_identity(
                ResourceRef(criterion.authority, criterion.kind, criterion.id)
            )
            if current_criterion is None or current_criterion.ref != criterion:
                raise PermissionError("local assessment policy criterion is stale")

    def require_pair(self, task: ResourceRef, criterion: ResourceRef) -> None:
        if (task, criterion) not in self.task_criterion_pairs:
            raise PermissionError("criterion is outside the configured local assessment task/criterion pairs")


def compose_manager_assessment_state(state: Mapping[str, Any], *, config_path: Any) -> dict[str, Any]:
    """Load the owning controller's trusted run policy without storing live objects.

    Both service entrypoints can call this before issuing commands. Keep only
    JSON policy in state, since the operational controller persists that state;
    resolve current task/criterion pins again for each finite command.
    """
    configured = json.loads(Path(config_path).read_text())["assessment_accounting"]
    LocalAssessmentPolicy.from_run_config(configured, state=state)
    return {**state, "assessment_policy": configured}
