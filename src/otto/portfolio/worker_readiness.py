"""Finite current metadata, not new admission/accounting policy or recovery."""
from collections.abc import Mapping
from herzchen.contracts import ResourceRef

MAX_SLOTS = 32
MAX_RECORD_BYTES = 32768


def read_worker_readiness(service, request, *, context=None):
    service.commands._authorize()
    if set(request) != {"command"}:
        raise ValueError("worker-readiness is bound to the current manager; no actor/project/pool selectors")
    state = service.server.state
    reader = service.server.store.consumer()
    workers = state.get("workers") or {}
    if not isinstance(workers, Mapping) or len(workers) > MAX_SLOTS:
        raise ValueError("worker-readiness requires at most 32 owner-known current slots; no hidden roster clipping")
    project = ResourceRef.from_dict(state["project_ref"])
    same = lambda a, b: all(a.get(k) == b.get(k) for k in ("authority", "kind", "id"))
    if context is not None:
        service.authorize_caller(context, request)
        if not same(context.get("project_ref", {}), state["project_ref"]):
            raise PermissionError("worker-readiness caller is outside the current owner project")
    rows, pools = [], {}
    complete = True
    active = 0
    for alias, slot in workers.items():
        if (alias not in state["task_refs"] or not isinstance(slot, Mapping)
                or not isinstance(slot.get("schedule_id"), str) or not slot["schedule_id"]):
            raise PermissionError("worker slot has no current owner task/handle")
        assignment_pin = ResourceRef.from_dict(slot["assignment_ref"])
        if assignment_pin.authority != project.authority or assignment_pin.kind != "wrk.assignment":
            raise PermissionError("worker slot names a foreign assignment")
        pin = ResourceRef(project.authority, "otto.due-record", slot["schedule_id"])
        observed = reader.get_identity_bounded(pin, max_record_bytes=MAX_RECORD_BYTES)
        row = {"task_alias": alias, "schedule_id": slot["schedule_id"],
               "expected_assignment_ref": slot["assignment_ref"], "expected_generation": slot.get("generation"),
               "metadata_state": observed["state"], "metadata_bytes_parsed": observed["bytes_parsed"]}
        record = observed["record"]
        if record is None:
            complete = False
            row["next_action"] = "Inspect the exact retained occurrence through supported owner recovery; absent metadata is not absent effects."
            rows.append(row)
            continue
        due = record.payload
        target = due.get("target") or {}
        assignment = reader.get_identity_bounded(assignment_pin, max_record_bytes=MAX_RECORD_BYTES)
        assigned = assignment["record"]
        if assigned is None:
            row["assignment_state"] = assignment["state"]
            complete = False
            rows.append(row)
            continue
        body = assigned.payload
        if (not same(target.get("project_ref", {}), state["project_ref"])
                or not same(target.get("task_ref", {}), state["task_refs"][alias])
                or due.get("role") != "worker" or due.get("recipient") != slot.get("principal")
                or due.get("assignment_ref") != slot["assignment_ref"]
                or due.get("generation") != slot.get("generation")
                or assigned.ref != assignment_pin or body.get("principal") != slot.get("principal")
                or body.get("role") != "executor" or body.get("status") == "cancelled"
                or body.get("generation") != slot.get("generation")
                or body.get("manager") != state["manager"]
                or not same(body.get("scope", {}), state["task_refs"][alias])):
            raise PermissionError("worker-readiness slot/assignment/project/task pins are stale or foreign")
        row.update(occurrence_ref=record.ref.to_dict(), occurrence_version=record.version,
                   observed_at=record.updated_at, assignment_ref=assigned.ref.to_dict(),
                   assignment_version=assigned.version, principal=slot["principal"], generation=slot["generation"],
                   target_task_ref=target.get("task_ref"), current_task_ref=state["task_refs"][alias])
        for key in ("stop_state", "completion_state", "delivery_state", "host_state", "in_flight_request"):
            row[key] = due.get(key)
        # Counts are conservative unresolved current-slot metadata, NOT a
        # physical native roster or an admission verdict. A failed/stopped or
        # prepared occurrence may still hold custody until exact reconciliation.
        succeeded = due.get("completion_state") == "succeeded"
        uncertain = not (due.get("stop_state") == "completed" and succeeded
                         and due.get("in_flight_request") is None)
        row["active_or_uncertain"] = uncertain
        row["same_task_succeeded_predicate"] = succeeded
        row["custody_release"] = "not evaluated by this metadata read"
        row["native_liveness"] = "not established by this metadata read"
        row["state_semantics"] = "Due stop/completion metadata only; dispatch:false means this read launched nothing and is not an admission denial. Pending/unassigned/not-evaluated defaults and empty blocker lists are not admission verdicts. Generic host_state unknown is not itself a native identity hold. The canonical run-worker operation revalidates current task, custody, configuration and capacity."
        active += int(uncertain)
        allowance = due.get("allowance_ref")
        if allowance is not None:
            pool_ref = ResourceRef.from_dict(allowance)
            if pool_ref.authority != project.authority or pool_ref.kind != "limit":
                raise PermissionError("worker Due names a foreign allowance pool")
            row["allowance_ref"] = allowance
            stable = ResourceRef(pool_ref.authority, pool_ref.kind, pool_ref.id)
            pool_read = reader.get_identity_bounded(stable, max_record_bytes=MAX_RECORD_BYTES)
            pool = pool_read["record"]
            pools[pool_ref.id] = {"pool_ref": stable.to_dict(), "availability": pool_read["state"],
                "binding_source": "explicit current worker Due allowance_ref",
                "held_units": None, "used_units": None, "remaining_allowance_units": None,
                "balance_availability": "not computed by finite metadata reader; existing pool totals hydrate reservation history"}
            if pool is not None:
                if pool.payload.get("record_type") != "limit":
                    raise PermissionError("worker Due allowance is not a neutral pool")
                if pool_ref.revision is not None and pool_ref.revision != pool.ref.revision:
                    raise PermissionError("worker Due allowance pin is stale")
                pools[pool_ref.id].update(version=pool.version, current_revision=pool.ref.revision,
                    observed_at=pool.updated_at, capacity_units=pool.payload.get("capacity_units"),
                    cumulative_allowance_units=pool.payload.get("cumulative_allowance_units"))
        rows.append(row)
    return {"schema": "otto.worker-readiness-read.v1", "outcome": "read", "as_of": service._as_of(),
            "project_ref": state["project_ref"], "manager_assignment_ref": state["assignment_ref"],
            "manager_generation": state["manager_generation"], "current_worker_slots": rows,
            "read_bounds": {"current_slots": MAX_SLOTS, "record_bytes": MAX_RECORD_BYTES},
            "coverage": {"basis": "current owner-known slots only; not other projects or all historical worker turns",
                         "complete": complete, "slot_count": len(workers),
                         "count_semantics": "unresolved Due slots, including prepared, in-flight and failed without evaluated release; not physical native count or admission authorization"},
            "active_or_uncertain_current_slots": active if complete else None,
            "named_due_pool_snapshots": list(pools.values()),
            "ordinary_normal_allowance": {"state": "undeclared-by-this-reader", "remaining": None, "held": None,
                "reason": "No ordinary NORMAL numerical admission contract is derived here; explicit Due pool snapshots are observed accounting only. Assessment bookkeeping does not grant worker allowance."},
            "read_only": True, "provider_called": False, "effects_started": False,
            "dispatch": False, "retry": False}
