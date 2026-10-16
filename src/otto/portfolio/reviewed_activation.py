"""The narrow reviewed-plan to activation composition.

This module deliberately does not introduce a lifecycle or a second journal.
It reads the existing Work and DAT/assessment identities, validates the pins
that make a review applicable, and then uses the existing WorkGraph,
AssessmentModule and setup ports at the one explicit activation boundary.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping

from herzchen.contracts import ResourceRef
from herzchen.domains.assessment import AssessmentModule
from herzchen.kernel import LimitService


SCHEMA = "otto.reviewed-activation.v1"
READINESS_SCHEMA = "otto.reviewed-activation-readiness.v1"
MAX_TASKS = 256


def _json(value: Any) -> Any:
    if isinstance(value, ResourceRef):
        return value.to_dict()
    if hasattr(value, "to_dict"):
        return _json(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    return value


def _digest(value: Any) -> str:
    return sha256(json.dumps(_json(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _ref(value: Any, field: str, *, pinned: bool = True) -> ResourceRef:
    try:
        result = value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError(f"{field} must be a resource reference") from exc
    if result.revision is None and pinned:
        raise ValueError(f"{field} must pin an exact revision")
    if not result.authority or not result.kind or not result.id:
        raise ValueError(f"{field} is incomplete")
    return result


def _same(left: Any, right: Any) -> bool:
    try:
        a, b = _ref(left, "left", pinned=False), _ref(right, "right", pinned=False)
    except ValueError:
        return False
    return (a.authority, a.kind, a.id) == (b.authority, b.kind, b.id)


def _pinned_equal(left: Any, right: Any) -> bool:
    try:
        a, b = _ref(left, "left", pinned=False), _ref(right, "right", pinned=False)
    except ValueError:
        return False
    return a == b


class ReviewedActivationError(ValueError):
    """A reviewed activation input is not admissible."""


class ReviewedPlanActivation:
    """Owner-bound, provider-free activation over existing domain ports.

    ``owner`` is the already-authenticated ``PortfolioOwnerBootstrap``.  The
    optional setup application is the existing ``ExecutionApplication``; it is
    only consulted for setup read/prepare and never used to dispatch a role.
    """

    def __init__(self, owner: Any, *, setup_application: Any = None,
                 owner_policy: Mapping[str, Any] | None = None) -> None:
        if not hasattr(owner, "graph") or not hasattr(owner, "content"):
            raise TypeError("reviewed activation requires the trusted owner ports")
        self.owner = owner
        self.setup_application = setup_application
        if owner_policy is None:
            self._adopted_policy = None
            self._adopted_policy_digest = None
        else:
            if not isinstance(owner_policy, Mapping) or not owner_policy:
                raise ReviewedActivationError("owner_policy must be the current adopted policy")
            try:
                self._adopted_policy = json.loads(json.dumps(_json(owner_policy), sort_keys=True))
            except (TypeError, ValueError) as exc:
                raise ReviewedActivationError("owner_policy must contain JSON values") from exc
            self._adopted_policy_digest = _digest(self._adopted_policy)

    def _policy_binding(self, project: Any) -> dict[str, Any]:
        """Read the current owner grant that authorizes this policy."""
        grant = getattr(self.owner, "project_read_grant", None)
        actor = getattr(self.owner, "owner_actor", None)
        if grant is None or actor is None or grant.principal != actor or not grant.allows(project.ref):
            raise ReviewedActivationError("current adopted owner policy binding is unavailable")
        return {"owner": {"authority": actor.authority, "actor": actor.actor},
                "project_ref": project.ref.to_dict(),
                "policy_source": grant.policy_source,
                "policy_revision": grant.policy_revision}

    def _policy(self, project: Any, value: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._adopted_policy is None or self._adopted_policy_digest is None:
            raise ReviewedActivationError("reviewed activation requires an owner-bound adopted policy")
        if value is not None and (not isinstance(value, Mapping) or _digest(value) != self._adopted_policy_digest):
            raise ReviewedActivationError("owner_policy is not the current adopted policy binding")
        return dict(self._adopted_policy), self._policy_binding(project)

    def _current_work(self, value: Any, field: str) -> Any:
        ref = _ref(value, field, pinned=False)
        record = self.owner.graph.reader.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
        if record is None or (ref.revision is not None and record.ref != ref):
            raise ReviewedActivationError(f"{field} is missing or stale")
        return record

    def _read_pin(self, value: Any, field: str) -> tuple[ResourceRef, Any, Mapping[str, Any]]:
        ref = _ref(value, field)
        # Work reports/results and other owner records are read through the
        # normal finite Work reader. DAT pins are read through the existing
        # content port, including their immutable revision content.
        if ref.kind.startswith("work.") or ref.kind in {"wrk.report", "wrk.result"}:
            identity = self.owner.graph.reader.get_identity(ref)
            if identity is None or identity.ref != ref:
                raise ReviewedActivationError(f"{field} is missing or stale")
            payload = identity.payload
            value_payload = payload.get("value", payload)
            return ref, value_payload, payload
        if ref.kind == "dat.content.document":
            head = self.owner.content.read(ResourceRef(ref.authority, ref.kind, ref.id))
            current = head.get("current_revision") if isinstance(head, Mapping) else None
            try:
                current_revision = ResourceRef.from_dict(current) if isinstance(current, Mapping) else None
            except (TypeError, ValueError, KeyError):
                current_revision = None
            if current_revision is None or current_revision.revision != ref.revision:
                raise ReviewedActivationError(f"{field} is not the current document revision")
        observed = self.owner.content.read(ref)
        if not isinstance(observed, Mapping) or observed.get("identity") != ref:
            raise ReviewedActivationError(f"{field} is missing or stale")
        content = observed.get("content")
        if content is None and isinstance(observed.get("revision"), Mapping):
            content = observed["revision"].get("content")
        if content is None:
            content = observed.get("payload", {})
        return ref, content, observed

    @staticmethod
    def _extract_plan_ref(value: Any) -> Any:
        if not isinstance(value, Mapping):
            return None
        for key in ("plan_ref", "plan", "reviewed_plan_ref", "reviewed_plan"):
            candidate = value.get(key)
            if isinstance(candidate, Mapping) and "ref" in candidate:
                candidate = candidate["ref"]
            if candidate is not None:
                return candidate
        return None

    @staticmethod
    def _extract_plan_digest(value: Any) -> str | None:
        if not isinstance(value, Mapping):
            return None
        for key in ("plan_digest", "reviewed_plan_digest", "digest"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        return None

    @staticmethod
    def _task_specs(plan: Any, policy: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        candidates = policy.get("task_specs") if isinstance(policy, Mapping) else None
        if candidates is None and isinstance(plan, Mapping):
            candidates = plan.get("deliverables", plan.get("tasks"))
        if candidates is None:
            return []
        if not isinstance(candidates, list) or not candidates or len(candidates) > MAX_TASKS:
            raise ReviewedActivationError("activation task_specs must contain 1..256 objects")
        if not all(isinstance(item, Mapping) for item in candidates):
            raise ReviewedActivationError("activation task_specs must contain objects")
        return [dict(item) for item in candidates]

    @staticmethod
    def _pair_specs(policy: Mapping[str, Any]) -> list[tuple[ResourceRef, ResourceRef]]:
        raw = policy.get("task_criterion_pairs")
        if raw is None:
            return []
        if not isinstance(raw, list) or len(raw) > MAX_TASKS:
            raise ReviewedActivationError("task_criterion_pairs must be a bounded list")
        pairs: list[tuple[ResourceRef, ResourceRef]] = []
        for item in raw:
            if isinstance(item, Mapping):
                task, criterion = item.get("task_ref"), item.get("criterion_ref")
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                task, criterion = item
            else:
                raise ReviewedActivationError("task_criterion_pairs must contain task_ref and criterion_ref")
            pairs.append((_ref(task, "task_ref"), _ref(criterion, "criterion_ref")))
        if len({(task, criterion) for task, criterion in pairs}) != len(pairs):
            raise ReviewedActivationError("task_criterion_pairs must be distinct")
        return pairs

    def _predecessor(self, value: Any, project: Any) -> dict[str, Any]:
        if value is None:
            return {"ref": None, "eligible": True, "state": "not-required"}
        ref = _ref(value, "predecessor_ref", pinned=False)
        if _same(ref, project.ref):
            raise ReviewedActivationError("predecessor cannot be the activating project")
        predecessor = self._current_work(ref, "predecessor_ref")
        lifecycle = getattr(predecessor.payload.get("lifecycle"), "value", predecessor.payload.get("lifecycle"))
        control = predecessor.payload.get("lifecycle_control")
        reconciled = isinstance(control, Mapping) and isinstance(control.get("reconciliation"), Mapping) and control["reconciliation"].get("status") == "reconciled"
        # A lifecycle label alone is not a genuine predecessor disposition;
        # the existing lifecycle control/readback must prove final
        # reconciliation before the successor may activate.
        eligible = lifecycle in {"completed", "closed", "terminal"} and reconciled
        return {"ref": predecessor.ref.to_dict(), "eligible": eligible, "state": lifecycle,
                "terminal_disposition": predecessor.payload.get("terminal_disposition"),
                "reconciled": reconciled}

    def read(self, *, project_ref: Any, plan_ref: Any, review_ref: Any,
             owner_policy: Mapping[str, Any] | None = None, predecessor_ref: Any = None,
             setup: Mapping[str, Any] | None = None) -> dict[str, Any]:
        project = self._current_work(project_ref, "project_ref")
        if project.ref.kind != "work.project":
            raise ReviewedActivationError("project_ref must identify a Work project")
        policy, policy_binding = self._policy(project, owner_policy)
        plan, plan_content, _ = self._read_pin(plan_ref, "plan_ref")
        review, review_content, _ = self._read_pin(review_ref, "review_ref")
        linked_plan = self._extract_plan_ref(review_content)
        applicable = linked_plan is not None and _pinned_equal(linked_plan, plan)
        plan_digest = _digest(plan_content)
        review_digest = self._extract_plan_digest(review_content)
        if review_digest is not None and review_digest != plan_digest:
            applicable = False
        policy_plan = policy.get("plan_ref") or policy.get("required_plan_ref")
        if policy_plan is not None and not _pinned_equal(policy_plan, plan):
            applicable = False
        disposition = review_content.get("disposition", review_content.get("status")) if isinstance(review_content, Mapping) else None
        approved = str(disposition).lower() in {"approved", "accept", "accepted", "pass", "passed"}
        predecessor = self._predecessor(predecessor_ref, project)
        pairs = self._pair_specs(policy)
        specs = self._task_specs(plan_content, policy)
        current_tasks = [task for task in self.owner.graph.list(project=project.ref, kind="task")]
        activation = project.payload.get("fields", {}).get("reviewed_activation")
        active = project.payload.get("lifecycle") == "active"
        ready = bool(approved and applicable and predecessor["eligible"] and not active)
        blockers = []
        if not approved:
            blockers.append({"code": "review_not_approved"})
        if not applicable:
            blockers.append({"code": "review_plan_pin_stale"})
        if not predecessor["eligible"]:
            blockers.append({"code": "predecessor_not_terminal", "predecessor": predecessor})
        return {"schema": READINESS_SCHEMA, "outcome": "read", "state": "ready" if ready else ("activated" if active else "held"),
                "ready": ready, "project_ref": project.ref.to_dict(),
                "plan": {"ref": plan.to_dict(), "digest": plan_digest},
                "review": {"ref": review.to_dict(), "disposition": disposition, "applicable": applicable},
                "owner_policy": {"digest": self._adopted_policy_digest, "binding": policy_binding,
                                 "plan_ref": _json(policy_plan), "pair_count": len(pairs)},
                "predecessor": predecessor, "setup": _json(setup),
                "materialization": {"task_spec_count": len(specs), "existing_task_count": len(current_tasks), "pairs": [_json(pair) for pair in pairs], "activation": _json(activation)},
                "blockers": blockers, "inert": not ready and not active, "dispatch": False,
                "terminal_acceptance": False, "provider_called": False}

    def _pool(self, policy: Mapping[str, Any], request_key: str) -> Any:
        pool_id = policy.get("pool_id")
        if not isinstance(pool_id, str) or not pool_id:
            return None
        capacity = policy.get("capacity_units", 1)
        cumulative = policy.get("cumulative_allowance_units", capacity)
        if type(capacity) is not int or type(cumulative) is not int or not 1 <= capacity <= cumulative:
            raise ReviewedActivationError("owner policy allowance is invalid")
        ref = ResourceRef(self.owner.owner_actor.authority, "limit", pool_id)
        limits = LimitService(self.owner.store)
        existing = limits.get_pool(ref)
        if existing is None:
            return limits.create_pool(ref, capacity_units=capacity, cumulative_allowance_units=cumulative,
                                      logical_request_key=request_key + ":pool", actor=self.owner.owner_actor)
        if existing.capacity_units != capacity or existing.cumulative_allowance_units != cumulative:
            raise ReviewedActivationError("existing owner allowance differs from the adopted policy")
        return existing

    def activate(self, *, project_ref: Any, plan_ref: Any, review_ref: Any,
                 owner_policy: Mapping[str, Any] | None = None, request_key: str,
                 predecessor_ref: Any = None, manager: Any = None,
                 setup: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(request_key, str) or not request_key.strip():
            raise ValueError("request_key is required")
        try:
            existing_project = self._current_work(project_ref, "project_ref")
        except ReviewedActivationError:
            # A marker is written before the final activation call.  If its
            # reply is lost, the caller's original project pin is necessarily
            # stale on retry.  Reconcile only that exact request's retained
            # marker; an arbitrary stale caller still fails closed.
            requested_project = _ref(project_ref, "project_ref", pinned=False)
            current = self.owner.graph.reader.get_identity(
                ResourceRef(requested_project.authority, requested_project.kind, requested_project.id)
            )
            marker = current.payload.get("fields", {}).get("reviewed_activation") if current is not None else None
            if (current is None or not isinstance(marker, Mapping)
                    or marker.get("request_key") != request_key):
                raise
            existing_project = current
        policy, _policy_binding = self._policy(existing_project, owner_policy)
        expected_manager = {"principal": self.owner.owner_actor.actor,
                            "authority": self.owner.owner_actor.authority}
        if manager is None:
            manager_value = expected_manager
        elif isinstance(manager, str):
            if manager != expected_manager["principal"]:
                raise ReviewedActivationError("activation manager is outside the current owner policy binding")
            manager_value = expected_manager
        elif isinstance(manager, Mapping) and dict(manager) == expected_manager:
            manager_value = expected_manager
        else:
            raise ReviewedActivationError("activation manager is outside the current owner policy binding")
        existing_marker = existing_project.payload.get("fields", {}).get("reviewed_activation")
        requested_plan = _ref(plan_ref, "plan_ref").to_dict()
        requested_review = _ref(review_ref, "review_ref").to_dict()
        if existing_project.payload.get("lifecycle") == "active" and isinstance(existing_marker, Mapping):
            if (existing_marker.get("plan_ref") != requested_plan
                    or existing_marker.get("review_ref") != requested_review):
                raise ReviewedActivationError("project already has a different reviewed activation")
            return {"schema": SCHEMA, "outcome": "replayed", "project_ref": existing_project.ref.to_dict(),
                    "task_refs": list(existing_marker.get("task_refs", ())),
                    "criterion_refs": list(existing_marker.get("criterion_refs", ())),
                    "pool_ref": existing_marker.get("pool_ref"), "activation": _json(existing_marker),
                    "dispatch": False, "terminal_acceptance": False, "provider_called": False,
                    "readiness": self.read(project_ref=existing_project.ref, plan_ref=plan_ref,
                        review_ref=review_ref, owner_policy=policy,
                        predecessor_ref=predecessor_ref, setup=setup)}
        readiness = self.read(project_ref=existing_project.ref, plan_ref=plan_ref, review_ref=review_ref,
                              owner_policy=policy, predecessor_ref=predecessor_ref, setup=setup)
        if not readiness["ready"]:
            return {"schema": SCHEMA, "outcome": "held", "readiness": readiness,
                    "effects_started": False, "provider_called": False, "dispatch": False,
                    "terminal_acceptance": False, "retry": False}
        project = self._current_work(existing_project.ref, "project_ref")
        plan_content = self._read_pin(plan_ref, "plan_ref")[1]
        pairs = self._pair_specs(policy)
        specs = self._task_specs(plan_content, policy)
        if not pairs and not specs:
            raise ReviewedActivationError("activation requires task_specs or exact task_criterion_pairs")
        if pairs and specs and len(pairs) != len(specs):
            raise ReviewedActivationError("task_specs and task_criterion_pairs differ")
        setup_result = None
        if setup is not None and self.setup_application is not None:
            # Prepare the existing setup before creating any activation
            # children. A held setup therefore remains a genuinely inert
            # activation attempt and is safe to retry with the same input.
            setup_result = self.setup_application.prepare_operating_setup(
                project_ref=project.ref.to_dict(), setup=setup, request_key=request_key + ":setup")
            if setup_result.get("outcome") not in {"prepared", "replayed"}:
                return {"schema": SCHEMA, "outcome": "held", "readiness": readiness,
                        "setup": setup_result, "effects_started": False,
                        "provider_called": False, "dispatch": False,
                        "terminal_acceptance": False, "retry": False}
        tasks = []
        criteria = []
        if pairs:
            for task_ref, criterion_ref in pairs:
                task = self._current_work(task_ref, "task_ref")
                criterion = self.owner.store.consumer().get_identity(criterion_ref)
                if task.payload.get("project_ref") != project.ref.to_dict() or criterion is None or criterion.ref != criterion_ref:
                    raise ReviewedActivationError("owner policy task/criterion pair is stale or foreign")
                tasks.append(task.ref.to_dict()); criteria.append(criterion_ref.to_dict())
        else:
            assessment = AssessmentModule(self.owner.store, actor=self.owner.owner_actor,
                payload_resolver=self.owner.evidence_payload_resolver)
            for index, spec in enumerate(specs):
                title = spec.get("title", spec.get("name"))
                if not isinstance(title, str) or not title.strip():
                    raise ReviewedActivationError("each task spec requires a title")
                stable = str(spec.get("id", index + 1)).strip()
                task = self.owner.graph.create_task(project.ref, title=title,
                    fields={"activation_key": request_key, "activation_index": index,
                            "acceptance": spec.get("acceptance", spec.get("criteria", []))},
                    logical_request_key=f"{request_key}:task:{stable}", actor=self.owner.owner_actor)
                criterion_spec = spec.get("criterion", {"id": f"{stable}-criterion", "definition": spec.get("acceptance", title)})
                scope = assessment.declare_scope(f"{request_key}:scope:{stable}", parent_obligation=task.ref,
                    protocol="otto-reviewed-plan", criteria=[criterion_spec], review_required=True,
                    designated_approver=manager_value["principal"], authority=self.owner.owner_actor.authority,
                    policy={"required_for_completion": True}, logical_request_key=f"{request_key}:scope:{stable}", actor=self.owner.owner_actor)
                tasks.append(task.ref.to_dict()); criteria.append(scope.criterion_refs[0].to_dict())
        pool = self._pool(policy, request_key)
        activation_marker = {"schema": SCHEMA, "request_key": request_key,
            "plan_ref": _ref(plan_ref, "plan_ref").to_dict(), "review_ref": _ref(review_ref, "review_ref").to_dict(),
            "task_refs": tasks, "criterion_refs": criteria, "pool_ref": None if pool is None else pool.ref.to_dict(),
            "setup_prepared": setup_result is not None, "dispatch": False, "terminal_acceptance": False}
        current = self._current_work(project.ref, "project_ref")
        existing_marker = current.payload.get("fields", {}).get("reviewed_activation")
        if isinstance(existing_marker, Mapping):
            if existing_marker.get("plan_ref") != activation_marker["plan_ref"] or existing_marker.get("review_ref") != activation_marker["review_ref"]:
                raise ReviewedActivationError("project already has a different reviewed activation")
            activation_marker = dict(existing_marker)
        else:
            fields = dict(current.payload.get("fields", {}))
            fields["reviewed_activation"] = activation_marker
            current = self.owner.graph.revise(current.ref, fields=fields,
                logical_request_key=request_key + ":marker", actor=self.owner.owner_actor)
        activated = self.owner.sheet.batches.activate_project(current.ref, manager=manager_value,
            logical_request_key=request_key + ":activate", actor=self.owner.owner_actor,
            base_revision=current.ref.revision)
        return {"schema": SCHEMA, "outcome": "activated", "project_ref": activated.ref.to_dict(),
                "task_refs": tasks, "criterion_refs": criteria,
                "pool_ref": activation_marker.get("pool_ref"), "setup": _json(setup),
                "dispatch": False, "terminal_acceptance": False, "provider_called": False,
                "activation": activation_marker, "readiness": self.read(project_ref=activated.ref,
                    plan_ref=plan_ref, review_ref=review_ref, owner_policy=policy,
                    predecessor_ref=predecessor_ref, setup=setup)}


__all__ = ["READINESS_SCHEMA", "SCHEMA", "ReviewedActivationError", "ReviewedPlanActivation"]
