"""Trusted controller policy for bounded local assessment accounting."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from herzchen.contracts import ResourceRef


@dataclass(frozen=True)
class LocalAssessmentPolicy:
    purpose: str
    local_only: bool
    pool_ref: ResourceRef
    capacity_units: int
    cumulative_allowance_units: int
    scope_project_ref: ResourceRef
    task_criterion_pairs: tuple[tuple[ResourceRef, ResourceRef], ...]

    def __post_init__(self) -> None:
        project, pool = self.scope_project_ref, self.pool_ref
        if (not isinstance(self.purpose, str) or not self.purpose.strip() or len(self.purpose) > 512
                or self.local_only is not True or not isinstance(project, ResourceRef)
                or project.kind != "work.project" or not project.revision
                or not isinstance(pool, ResourceRef) or pool.kind != "limit" or pool.revision is not None
                or pool.authority != project.authority):
            raise ValueError("local assessment policy requires purpose, local_only and exact owner pool/project refs")
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
        if not isinstance(configured, Mapping) or configured.get("kind") != "owner_local_bookkeeping":
            raise ValueError("assessment_accounting must declare owner local bookkeeping")
        pool_id, rows = configured.get("pool_id"), configured.get("task_criterion_pairs")
        if not isinstance(pool_id, str) or not pool_id.strip() or not isinstance(rows, list):
            raise ValueError("assessment_accounting requires a pool identity and pair aliases")
        pairs = []
        for row in rows:
            if not isinstance(row, str) or row.count("/") != 1:
                raise ValueError("assessment_accounting pairs must be task/criterion aliases")
            task, criterion = row.split("/")
            pairs.append({"task": task, "criterion": criterion})
        return cls.from_config({"purpose": configured.get("purpose"), "local_only": configured.get("local_only"),
            "pool_ref": ResourceRef(state["authority"], "limit", pool_id).to_dict(),
            "capacity_units": configured.get("capacity_units"),
            "cumulative_allowance_units": configured.get("cumulative_allowance_units"),
            "scope_project_ref": state["project_ref"], "task_criterion_pairs": pairs},
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
                   tuple(pairs))

    def validate_binding(self, project: ResourceRef, task: ResourceRef, reader: Any) -> None:
        if project != self.scope_project_ref or not any(pair[0] == task for pair in self.task_criterion_pairs):
            raise PermissionError("local assessment policy is outside the exact current project/task")
        refs = (project, task, *(criterion for member, criterion in self.task_criterion_pairs if member == task))
        for ref in refs:
            current = reader.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
            if current is None or current.ref != ref:
                raise PermissionError("local assessment policy project/task/criterion is stale")

    def require_pair(self, task: ResourceRef, criterion: ResourceRef) -> None:
        if (task, criterion) not in self.task_criterion_pairs:
            raise PermissionError("criterion is outside the configured local assessment task/criterion pairs")
