"""Installed OTT-03 sequential handoff observations using public APIs only."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile


AUTHORITY = "ott03-harness-v2"
CREDENTIAL = "ott03-harness-v2-credential"


def make_api(store):
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import WorkGraph
    from herzchen.domains.work.assignments import ResponsibilityAssignments
    from herzchen.domains.work.sheet import ProjectSheet
    from otto.portfolio import HerzchenBindingConfig, HerzchenWorkOperations, OttoPortfolio

    actor = AuthenticatedActor(AUTHORITY, "parent", CREDENTIAL)
    graph = WorkGraph(store, actor=actor)
    assignments = ResponsibilityAssignments(store, actor=actor)
    sheet = ProjectSheet(store, actor=actor)
    operations = HerzchenWorkOperations(
        port=graph.command_port,
        reader=graph.reader,
        binding=HerzchenBindingConfig(AUTHORITY, CREDENTIAL),
        sheet_port=sheet.command_port,
        assignments_port=assignments.command_port,
    )
    return graph, assignments, OttoPortfolio(operations)


def assignment_snapshot(assignments, ref):
    value = assignments.get(ref)
    return {
        "ref": value.ref.to_dict(),
        "scope": value.scope.to_dict(),
        "role": value.role,
        "principal": value.principal,
        "stored_manager": value.payload.get("manager"),
        "generation": value.generation,
        "status": value.status.value,
        "history": [dict(item) for item in value.history],
        "payload": deepcopy(dict(value.payload)),
    }


def event_snapshot(store):
    return [event.to_dict() for event in store.list_events()]


def receipt_snapshot(store, key):
    receipt = store.get_receipt(key)
    return None if receipt is None else receipt.to_dict()


def project_snapshot(graph, ref):
    value = graph.get(ref)
    return {"ref": value.ref.to_dict(), "payload": deepcopy(dict(value.payload))}


def observation(graph, assignments, store, project_ref, manager_ref):
    event_values = event_snapshot(store)
    return {
        "project": project_snapshot(graph, project_ref),
        "assignment": assignment_snapshot(assignments, manager_ref),
        "event_count": len(event_values),
        "event_ids": [event["event_id"] for event in event_values],
    }


def delta(before, after):
    return {
        "event_count": after["event_count"] - before["event_count"],
        "new_event_ids": [value for value in after["event_ids"] if value not in before["event_ids"]],
        "assignment_identity_same": before["assignment"]["ref"]["id"] == after["assignment"]["ref"]["id"],
        "generation_delta": after["assignment"]["generation"] - before["assignment"]["generation"],
        "principal_before": before["assignment"]["principal"],
        "principal_after": after["assignment"]["principal"],
    }


def main(output_path):
    from herzchen.authoring import register_authoring
    from herzchen.content import domain_contribution
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import register_work
    from herzchen.kernel.store import Store

    db_path = Path(tempfile.mktemp(prefix="ott03-handoff-v2-", suffix=".sqlite"))
    store = Store.create(db_path, authority=AUTHORITY)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    graph, assignments, api = make_api(store)
    parent = api.create_pending(actor="parent", request_id="parent", edit={"title": "Parent obligation"})
    project = api.create_pending(actor="parent", request_id="project", edit={"title": "Sequential handoff project"})
    assigned = api.assign_roles(
        project["project_ref"],
        {"parent": parent["project_ref"], "manager": "old", "executor": ["executor"]},
        actor="parent",
        request_id="roles",
    )
    manager_ref_1 = assigned["manager_assignment_ref"]
    evidence = [parent["project_ref"]]
    consumption = [assigned["roles"]["roles:executor"]["ref"]]
    first_request = {
        "project_ref": project["project_ref"], "manager_assignment_ref": manager_ref_1,
        "from_manager": "old", "to_manager": "new", "evidence_refs": evidence,
        "consumption_refs": consumption, "parent_obligation": parent["project_ref"],
        "actor": "parent", "request_id": "handoff-v2-1",
    }
    before = observation(graph, assignments, store, project["project_ref"], manager_ref_1)
    first = api.handoff(**first_request)
    after_first = observation(graph, assignments, store, project["project_ref"], manager_ref_1)
    manager_ref_2 = first["manager_assignment_ref"]
    second_request = {
        "project_ref": project["project_ref"], "manager_assignment_ref": manager_ref_2,
        "from_manager": "new", "to_manager": "third", "evidence_refs": evidence,
        "consumption_refs": consumption, "parent_obligation": parent["project_ref"],
        "actor": "parent", "request_id": "handoff-v2-2",
    }
    second = api.handoff(**second_request)
    manager_ref_3 = second["manager_assignment_ref"]
    after_second = observation(graph, assignments, store, project["project_ref"], manager_ref_3)
    persisted_events = event_snapshot(store)
    domains = store.registered_domains()
    store.close()

    reopened = Store.open(db_path, authority=AUTHORITY, expected_domains=domains)
    fresh_graph, fresh_assignments, fresh_api = make_api(reopened)
    fresh_after_restart = observation(fresh_graph, fresh_assignments, reopened, project["project_ref"], manager_ref_3)
    second_retry = fresh_api.handoff(**second_request)
    after_second_retry = observation(fresh_graph, fresh_assignments, reopened, project["project_ref"], manager_ref_3)
    first_retry = fresh_api.handoff(**first_request)
    after_first_retry = observation(fresh_graph, fresh_assignments, reopened, project["project_ref"], manager_ref_3)
    conflicts = {}
    for label, changed in {
        "manager": {"to_manager": "other"},
        "evidence": {"evidence_refs": [{"id": "changed-evidence"}]},
        "consumption": {"consumption_refs": [{"id": "changed-consumption"}]},
        "parent": {"parent_obligation": {"id": "changed-parent"}},
    }.items():
        result = fresh_api.handoff(**dict(second_request, **changed))
        conflicts[label] = {"result": result, "after": observation(fresh_graph, fresh_assignments, reopened, project["project_ref"], manager_ref_3)}
    rejections = {}
    for label, changed in {
        "wrong_from_manager": dict(first_request, request_id="reject-wrong-from", from_manager="wrong", manager_assignment_ref=manager_ref_3, to_manager="fourth"),
        "stale_old_target": dict(first_request, request_id="reject-stale-old", to_manager="fourth"),
        "unknown_target": dict(first_request, request_id="reject-unknown", manager_assignment_ref={"authority": AUTHORITY, "kind": "wrk.assignment", "id": "missing"}),
        "wrong_role": dict(first_request, request_id="reject-wrong-role", manager_assignment_ref=assigned["roles"]["roles:executor"]["ref"]),
    }.items():
        result = fresh_api.handoff(**changed)
        rejections[label] = {"result": result, "after": observation(fresh_graph, fresh_assignments, reopened, project["project_ref"], manager_ref_3)}
    final_events = event_snapshot(reopened)
    observations = {
        "metadata": {"pid": os.getpid(), "python": sys.version, "db_path": str(db_path), "authority": AUTHORITY},
        "before": before,
        "first_action": {"result": first, "receipt": receipt_snapshot(reopened, first_request["request_id"])},
        "after_first": after_first,
        "second_action": {"result": second, "receipt": receipt_snapshot(reopened, second_request["request_id"])},
        "after_second": after_second,
        "fresh_after_restart": fresh_after_restart,
        "second_exact_retry": {"result": second_retry, "after": after_second_retry},
        "first_exact_retry_after_second": {"result": first_retry, "after": after_first_retry},
        "conflicts": conflicts,
        "rejections": rejections,
        "deltas": {
            "first": delta(before, after_first),
            "second": delta(after_first, after_second),
            "restart": {"event_count": fresh_after_restart["event_count"] - after_second["event_count"], "assignment_identity_same": fresh_after_restart["assignment"]["ref"]["id"] == after_second["assignment"]["ref"]["id"]},
            "second_exact_retry": delta(after_second, after_second_retry),
            "first_exact_retry_after_second": delta(after_second_retry, after_first_retry),
            "post_replay_event_count": len(final_events) - len(persisted_events),
        },
        "receipt_event_linkage": {
            "first": {"receipt_event_ids": first["receipt"]["event_ids"], "result_event_ids": first["event_ids"], "result_ref": first["receipt"]["result_ref"]},
            "second": {"receipt_event_ids": second["receipt"]["event_ids"], "result_event_ids": second["event_ids"], "result_ref": second["receipt"]["result_ref"]},
        },
    }
    Path(output_path).write_text(json.dumps(observations, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "first": first["outcome"], "second": second["outcome"], "second_retry": second_retry["outcome"], "first_retry": first_retry["outcome"], "final_event_count": len(final_events)}, sort_keys=True))
    reopened.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) == 2 else "handoff-observations.json")
