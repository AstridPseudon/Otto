"""Record selected-template public-port observations for the amendment."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

AUTHORITY = "ott03-selected-template-harness"
CREDENTIAL = "ott03-selected-template-harness-credential"


def _template():
    return {
        "id": "ott03.selected.template",
        "revision": "template-rev-7",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "seed": {
            "project": {"title": "Selected template project", "outcome": "Template-defined outcome", "custom": {"selected": True}},
            "tasks": [{"local_id": "template-task", "title": "Template-defined task", "body": "Typed task content", "metadata": {"origin": "selected-template"}}],
        },
    }


def _owner_api(tmp_path):
    from herzchen.authoring import register_authoring
    from herzchen.content import domain_contribution
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import WorkGraph, register_work
    from herzchen.kernel.store import Store
    from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap

    path = tmp_path / "selected-template-harness.sqlite"
    store = Store.create(path, authority=AUTHORITY)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    binding = HerzchenBindingConfig(AUTHORITY, CREDENTIAL)
    owner = PortfolioOwnerBootstrap(store, binding=binding, owner_actor="owner")
    graph = WorkGraph(store, actor=AuthenticatedActor(AUTHORITY, "owner", CREDENTIAL))
    return store, owner, graph, OttoPortfolio(owner.consumer_operations()), path, binding


def _events(store):
    return [event.to_dict() for event in store.list_events()]


def _receipt(store, request_id):
    value = store.get_receipt(request_id)
    return None if value is None else value.to_dict()


def state(graph, store, project_ref):
    project = graph.get(project_ref)
    events = _events(store)
    return {
        "project_ref": project.ref.to_dict(),
        "project_payload": deepcopy(dict(project.payload)),
        "event_count": len(events),
        "event_ids": [event["event_id"] for event in events],
    }


def main(output):
    from herzchen.contracts import AuthenticatedActor
    from herzchen.domains.work import WorkGraph
    from herzchen.kernel.store import Store
    from otto.portfolio import PortfolioOwnerBootstrap

    store, owner, graph, api, path, binding = _owner_api(Path(tempfile.mkdtemp(prefix="ott03-selected-template-harness-")))
    template = _template()
    before = {"event_count": len(_events(store)), "event_ids": _events(store)}
    created = api.create_pending(actor="owner", request_id="harness-template", template=template)
    after_create = state(graph, store, created["project_ref"])
    edited = api.edit_pending(created["project_ref"], {"title": "Harness edited", "outcome": "Edited"}, actor="owner", request_id="harness-edit")
    after_edit = state(graph, store, created["project_ref"])
    reopened = api.reopen(created["project_ref"], actor="owner", request_id="harness-reopen")
    events_before_replay = _events(store)
    replay = api.create_pending(actor="owner", request_id="harness-template", template=deepcopy(template))
    replay_after = state(graph, store, created["project_ref"])
    changed = deepcopy(template)
    changed["parameters"] = {"type": "object", "properties": {"changed": {"type": "string"}}, "additionalProperties": False}
    conflict = api.create_pending(actor="owner", request_id="harness-template", template=changed)
    invalid_before = _events(store)
    invalid = api.create_pending(actor="owner", request_id="harness-invalid", template={"id": "unknown"})
    selected_open = api.create_and_open(actor="owner", request_id="harness-selected-open", template=template)
    after_all = _events(store)
    domains = store.registered_domains()
    persisted = after_all
    store.close()
    reopened_store = Store.open(path, authority=AUTHORITY, expected_domains=domains)
    fresh_graph = WorkGraph(reopened_store, actor=AuthenticatedActor(AUTHORITY, "owner", CREDENTIAL))
    fresh = state(fresh_graph, reopened_store, created["project_ref"])
    observations = {
        "before": before,
        "create": {"result": created, "after": after_create},
        "edit": {"result": edited, "after": after_edit},
        "reopen": reopened,
        "replay": {"result": replay, "after": replay_after, "event_delta": len(replay_after["event_ids"]) - len(events_before_replay)},
        "conflict": {"result": conflict, "event_delta": len(after_all) - len(events_before_replay)},
        "invalid": {"result": invalid, "event_delta": len(after_all) - len(invalid_before)},
        "selected_create_and_open": selected_open,
        "fresh_after_restart": fresh,
        "persisted_event_count": len(persisted),
        "receipt": _receipt(reopened_store, "harness-template"),
        "python": sys.version,
    }
    Path(output).write_text(json.dumps(observations, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"create": created["outcome"], "replay": replay["outcome"], "conflict": conflict["error"]["code"], "invalid": invalid["error"]["code"], "selected_open": selected_open["error"]["code"], "fresh_revision": fresh["project_ref"]["revision"]}, sort_keys=True))
    reopened_store.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) == 2 else "selected-template-observations.json")
