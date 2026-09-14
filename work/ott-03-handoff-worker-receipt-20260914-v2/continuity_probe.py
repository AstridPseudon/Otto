"""Public-API continuity probe used before and after the v2 correction."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


AUTHORITY = "ott03-continuity-probe"
CREDENTIAL = "ott03-continuity-credential"


def snap(assignments, ref):
    value = assignments.get(ref)
    return {
        "ref": value.ref.to_dict(),
        "principal": value.principal,
        "generation": value.generation,
        "status": value.status.value,
        "history": [dict(item) for item in value.history],
        "payload": dict(value.payload),
    }


def events(store):
    return [event.to_dict() for event in store.list_events()]


def main():
    from herzchen.authoring import register_authoring
    from herzchen.content import domain_contribution
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import WorkGraph, contributions, register_work
    from herzchen.domains.work.assignments import ResponsibilityAssignments
    from herzchen.domains.work.sheet import ProjectSheet
    from herzchen.kernel.store import Store
    from otto.portfolio import HerzchenBindingConfig, HerzchenWorkOperations, OttoPortfolio

    path = Path(tempfile.mktemp(prefix="otto03-continuity-", suffix=".sqlite"))
    store = Store.create(path, authority=AUTHORITY)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
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
    api = OttoPortfolio(operations)
    parent = api.create_pending(actor="parent", request_id="parent", edit={"title": "Parent"})
    project = api.create_pending(actor="parent", request_id="project", edit={"title": "Project"})
    assigned = api.assign_roles(
        project["project_ref"],
        {"parent": parent["project_ref"], "manager": "old", "executor": ["executor"]},
        actor="parent",
        request_id="roles",
    )
    manager_ref_1 = assigned["manager_assignment_ref"]
    base_1 = dict(
        project_ref=project["project_ref"], manager_assignment_ref=manager_ref_1,
        from_manager="old", to_manager="new", evidence_refs=[parent["project_ref"]],
        consumption_refs=[assigned["roles"]["roles:executor"]["ref"]],
        parent_obligation=parent["project_ref"], actor="parent", request_id="handoff-1",
    )
    before = snap(assignments, manager_ref_1)
    first = api.handoff(**base_1)
    after_first = snap(assignments, manager_ref_1)
    manager_ref_2 = first.get("manager_assignment_ref")
    base_2 = dict(
        project_ref=project["project_ref"], manager_assignment_ref=manager_ref_2,
        from_manager="new", to_manager="third", evidence_refs=[parent["project_ref"]],
        consumption_refs=[assigned["roles"]["roles:executor"]["ref"]],
        parent_obligation=parent["project_ref"], actor="parent", request_id="handoff-2",
    )
    second = api.handoff(**base_2)
    after_second = snap(assignments, manager_ref_2)
    events_after_second = events(store)
    first_replay = api.handoff(**base_1)
    return_value = {
        "python": sys.version,
        "pid": os.getpid(),
        "project_ref": project["project_ref"],
        "before_first": before,
        "first": first,
        "after_first": after_first,
        "second": second,
        "after_second": after_second,
        "first_replay_after_second": first_replay,
        "events_after_second_count": len(events_after_second),
        "events_after_first_count": len(events(store)),
        "delta_after_first_to_second_replay": len(events(store)) - len(events_after_second),
    }
    print(json.dumps(return_value, ensure_ascii=False, sort_keys=True, default=str, indent=2))
    store.close()


if __name__ == "__main__":
    main()
