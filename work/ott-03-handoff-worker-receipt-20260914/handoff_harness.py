"""Installed-wheel OTT-03 handoff observation harness."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile


AUTHORITY = "ott03-handoff-harness"
CREDENTIAL = "ott03-harness-credential"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def event_dicts(store):
    return [event.to_dict() for event in store.list_events()]


def receipt(store, key):
    value = store.get_receipt(key)
    return None if value is None else value.to_dict()


def assignment_dict(value):
    return {
        "ref": value.ref.to_dict(),
        "scope": value.scope.to_dict(),
        "role": value.role,
        "principal": value.principal,
        "generation": value.generation,
        "status": value.status.value,
        "history": [dict(item) for item in value.history],
        "payload": deepcopy(dict(value.payload)),
    }


def snapshot(store, graph, assignments, project_ref, manager_ref, request_key):
    project = graph.get(project_ref)
    manager = assignments.get(manager_ref)
    events = event_dicts(store)
    return {
        "captured_at": now(),
        "event_count": len(events),
        "event_ids": [event["event_id"] for event in events],
        "project": {
            "ref": project.ref.to_dict(),
            "lifecycle": project.payload["lifecycle"],
            "manager": project.payload["manager"],
            "tasks": deepcopy(project.payload["tasks"]),
            "payload": deepcopy(dict(project.payload)),
        },
        "assignment": assignment_dict(manager),
        "receipt": receipt(store, request_key),
    }


def delta(before, after):
    return {
        "events": after["event_count"] - before["event_count"],
        "new_event_ids": [item for item in after["event_ids"] if item not in before["event_ids"]],
        "receipt_changed": before.get("receipt") != after.get("receipt"),
    }


def make_api(store, actor):
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import WorkGraph
    from herzchen.domains.work.assignments import ResponsibilityAssignments
    from otto.portfolio import HerzchenBindingConfig, HerzchenWorkOperations, OttoPortfolio

    graph = WorkGraph(store, actor=actor)
    assignments = ResponsibilityAssignments(store, actor=actor)
    operations = HerzchenWorkOperations(
        port=graph.command_port,
        reader=graph.reader,
        binding=HerzchenBindingConfig(AUTHORITY, CREDENTIAL),
        assignments_port=assignments.command_port,
    )
    return graph, assignments, OttoPortfolio(operations)


def main(output: str) -> None:
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import register_work
    from herzchen.kernel.store import Store

    started = now()
    pid = os.getpid()
    path = Path(tempfile.mktemp(prefix="ott03-handoff-", suffix=".sqlite"))
    actor = AuthenticatedActor(AUTHORITY, "parent", CREDENTIAL)
    store = Store.create(path, authority=AUTHORITY)
    register_work(store)
    graph, assignments, api = make_api(store, actor)
    parent = api.create_pending(actor="parent", request_id="parent", edit={"title": "Parent obligation"})
    project = api.create_pending(actor="parent", request_id="project", edit={"title": "Pending project", "why_pending": "await manager"})
    assigned = api.assign_roles(
        project["project_ref"],
        {"parent": parent["project_ref"], "manager": "manager-old", "executor": ["executor-a"]},
        actor="parent",
        request_id="roles",
    )
    manager_ref = assigned["manager_assignment_ref"]
    handoff_args = {
        "project_ref": project["project_ref"],
        "manager_assignment_ref": manager_ref,
        "from_manager": "manager-old",
        "to_manager": "manager-new",
        "evidence_refs": [parent["project_ref"]],
        "consumption_refs": [assigned["roles"]["roles:executor"]["ref"]],
        "parent_obligation": parent["project_ref"],
        "actor": "parent",
        "request_id": "handoff",
    }
    before = snapshot(store, graph, assignments, project["project_ref"], manager_ref, "handoff")
    action = api.handoff(**handoff_args)
    after = snapshot(store, graph, assignments, project["project_ref"], manager_ref, "handoff")
    action_record = {"result": action, "after": after, "delta": delta(before, after)}
    persisted_events = event_dicts(store)
    domains = store.registered_domains()
    store.close()

    reopened = Store.open(path, authority=AUTHORITY, expected_domains=domains)
    fresh_graph, fresh_assignments, fresh_api = make_api(reopened, actor)
    fresh_after = snapshot(reopened, fresh_graph, fresh_assignments, project["project_ref"], manager_ref, "handoff")
    replay = fresh_api.handoff(**handoff_args)
    replay_after = snapshot(reopened, fresh_graph, fresh_assignments, project["project_ref"], manager_ref, "handoff")
    replay_record = {"result": replay, "after": replay_after, "delta": delta(fresh_after, replay_after)}

    conflict_records = []
    for label, changed in (
        ("manager", {"to_manager": "manager-other"}),
        ("evidence", {"evidence_refs": [{"id": "changed-evidence"}]}),
        ("consumption", {"consumption_refs": [{"id": "changed-consumption"}]}),
        ("parent", {"parent_obligation": {"id": "changed-parent"}}),
    ):
        conflict_before = snapshot(reopened, fresh_graph, fresh_assignments, project["project_ref"], manager_ref, "handoff")
        result = fresh_api.handoff(**dict(handoff_args, **changed))
        conflict_after = snapshot(reopened, fresh_graph, fresh_assignments, project["project_ref"], manager_ref, "handoff")
        conflict_records.append({"case": label, "result": result, "before": conflict_before, "after": conflict_after, "delta": delta(conflict_before, conflict_after)})

    rejection_records = []
    for label, changed in (
        ("wrong_from_manager", {"request_id": "reject-wrong-from", "from_manager": "wrong-manager"}),
        ("unknown_target", {"request_id": "reject-unknown", "manager_assignment_ref": {"authority": AUTHORITY, "kind": "wrk.assignment", "id": "missing"}}),
        ("wrong_role_target", {"request_id": "reject-wrong-role", "manager_assignment_ref": assigned["roles"]["roles:executor"]["ref"]}),
    ):
        rejection_before = snapshot(reopened, fresh_graph, fresh_assignments, project["project_ref"], manager_ref, changed["request_id"])
        result = fresh_api.handoff(**dict(handoff_args, **changed))
        rejection_after = snapshot(reopened, fresh_graph, fresh_assignments, project["project_ref"], manager_ref, changed["request_id"])
        rejection_records.append({"case": label, "result": result, "before": rejection_before, "after": rejection_after, "delta": delta(rejection_before, rejection_after)})
    final_events = event_dicts(reopened)
    reopened.close()
    observation = {
        "harness": {"pid": pid, "started": started, "ended": now(), "python": sys.version, "cwd": os.getcwd(), "otto_origin": importlib.import_module("otto").__file__, "herzchen_origin": importlib.import_module("herzchen").__file__, "sqlite_path": str(path)},
        "before": before,
        "action": action_record,
        "fresh_after": fresh_after,
        "replay": replay_record,
        "conflicts": conflict_records,
        "rejections": rejection_records,
        "event_persistence": {"before_close_count": len(persisted_events), "after_reopen_count": len(final_events), "equal": persisted_events == final_events},
    }
    Path(output).write_text(json.dumps(observation, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"action": action["outcome"], "action_delta": action_record["delta"], "replay_delta": replay_record["delta"], "conflict_count": len(conflict_records), "rejection_count": len(rejection_records), "event_persistence": observation["event_persistence"]}, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "handoff-observations.json")
