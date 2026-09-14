"""Installed-wheel public-port observation for selected create-and-open."""

from __future__ import annotations

from copy import deepcopy
import importlib.metadata
import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import herzchen
import otto
from herzchen.authoring import register_authoring
from herzchen.content import domain_contribution
from herzchen.contracts import ResourceRef
from herzchen.domains.work import register_work
from herzchen.kernel.store import Store
from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap


AUTHORITY = "ott03-selected-open-observation"
CREDENTIAL = "ott03-selected-open-observation-credential"


def template():
    return {
        "kind": "work_template",
        "id": "ott03.observed.selected-open",
        "revision": "observed-v1",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "body": {"type": "string", "minLength": 1},
            },
            "required": ["title", "body"],
            "additionalProperties": False,
        },
        "seed": {
            "project": {
                "title": {"$param": "title"},
                "outcome": "Observed selected outcome",
                "custom": {"observation": "selected-create-open"},
            },
            "tasks": [{
                "local_id": "observed-task",
                "title": "Observed typed task",
                "body": {"$param": "body"},
                "metadata": {"origin": "installed-observation"},
            }],
        },
    }


def event_values(store):
    return [event.to_dict() for event in store.list_events()]


def receipt_values(store, keys):
    return {
        key: None if store.get_receipt(key) is None else store.get_receipt(key).to_dict()
        for key in keys
    }


def identity_value(record):
    if record is None:
        return None
    return {
        "ref": record.ref.to_dict(),
        "version": record.version,
        "payload": dict(record.payload),
        "edit_token": record.edit_token,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


with TemporaryDirectory(prefix="ott03-selected-open-observation-") as directory:
    path = Path(directory) / "selected-open.sqlite"
    store = Store.create(path, authority=AUTHORITY)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    binding = HerzchenBindingConfig(AUTHORITY, CREDENTIAL)
    owner = PortfolioOwnerBootstrap(store, binding=binding, owner_actor="owner")
    api = OttoPortfolio(owner.consumer_operations())
    resource = template()
    parameters = {"title": "Observed selected project", "body": "Observed typed content"}
    keys = (
        "observation", "observation:actor", "observation:project",
        "observation:template", "observation:project-created", "observation:materialized",
    )
    before = {
        "events": event_values(store),
        "receipts": receipt_values(store, keys),
        "counts": dict(store.consumer().snapshot_counts()),
    }
    created = api.create_and_open(
        actor="owner",
        request_id="observation",
        template=resource,
        template_parameters=parameters,
    )
    after_create = {
        "events": event_values(store),
        "receipts": receipt_values(store, keys),
        "counts": dict(store.consumer().snapshot_counts()),
    }
    replay = api.create_and_open(
        actor="owner",
        request_id="observation",
        template=deepcopy(resource),
        template_parameters=deepcopy(parameters),
    )
    after_replay = {
        "events": event_values(store),
        "receipts": receipt_values(store, keys),
        "counts": dict(store.consumer().snapshot_counts()),
    }
    changed_resource = deepcopy(resource)
    changed_resource["seed"]["project"]["outcome"] = "Changed resource"
    resource_conflict = api.create_and_open(
        actor="owner",
        request_id="observation",
        template=changed_resource,
        template_parameters=parameters,
    )
    parameter_conflict = api.create_and_open(
        actor="owner",
        request_id="observation",
        template=resource,
        template_parameters=dict(parameters, title="Changed parameter"),
    )
    after_conflicts = {
        "events": event_values(store),
        "receipts": receipt_values(store, keys),
        "counts": dict(store.consumer().snapshot_counts()),
    }
    invalid_before = dict(store.consumer().snapshot_counts())
    invalid = api.create_and_open(
        actor="owner",
        request_id="invalid-observation",
        template={"id": "invalid"},
        template_parameters={},
    )
    invalid_after = dict(store.consumer().snapshot_counts())
    domains = store.registered_domains()
    store.close()

    reopened_store = Store.open(path, authority=AUTHORITY, expected_domains=domains)
    fresh_owner = PortfolioOwnerBootstrap(
        reopened_store, binding=binding, owner_actor="owner"
    )
    fresh_api = OttoPortfolio(fresh_owner.consumer_operations())
    fresh_record = fresh_api.read_pending(created["project_ref"], actor="owner")
    scope_ref = ResourceRef(AUTHORITY, "authoring-scope", created["project_ref"]["id"])
    fresh_scope = fresh_owner.consumer_operations().reader.get_record(scope_ref)
    fresh_replay = fresh_api.create_and_open(
        actor="owner",
        request_id="observation",
        template=deepcopy(resource),
        template_parameters=deepcopy(parameters),
    )
    final_events = event_values(reopened_store)
    result = {
        "schema": "ott03.selected-create-open.observation.v1",
        "origins": {
            "herzchen": herzchen.__file__,
            "herzchen_version": importlib.metadata.version("herzchen-contracts"),
            "otto": otto.__file__,
            "otto_version": importlib.metadata.version("otto-local-candidate"),
            "owner_bootstrap": inspect.getfile(PortfolioOwnerBootstrap),
        },
        "request": {
            "actor": "owner",
            "request_id": "observation",
            "template_resource": resource,
            "template_parameters": parameters,
        },
        "before": before,
        "created": created,
        "after_create": after_create,
        "exact_replay": replay,
        "after_replay": after_replay,
        "resource_conflict": resource_conflict,
        "parameter_conflict": parameter_conflict,
        "after_conflicts": after_conflicts,
        "invalid": invalid,
        "invalid_before_counts": invalid_before,
        "invalid_after_counts": invalid_after,
        "fresh_record": fresh_record,
        "fresh_scope": identity_value(fresh_scope),
        "fresh_replay": fresh_replay,
        "final_events": final_events,
        "observations": {
            "created_event_delta": len(after_create["events"]) - len(before["events"]),
            "exact_replay_zero_delta": after_replay == after_create,
            "conflicts_zero_delta": after_conflicts == after_create,
            "invalid_zero_delta": invalid_after == invalid_before,
            "fresh_replay_zero_delta": final_events == after_create["events"],
            "project_ref": created["project_ref"],
            "task_refs": created["task_refs"],
            "template_ref": created["template_ref"],
            "session_id": created["open"]["session_id"],
            "scope": created["open"]["scope"],
            "open_status": created["open"]["status"],
            "fresh_title": fresh_record["record"]["payload"]["title"],
            "fresh_tasks": fresh_record["record"]["payload"]["tasks"],
            "fresh_scope_state": fresh_scope.payload["checkout"]["state"],
            "event_types": [event["event_type"] for event in after_create["events"]],
            "inert": {
                "dispatch": created["dispatch"],
                "manager_launch": created["manager_launch"],
                "budget_reserved": created["budget_reserved"],
                "session_task_created": created["session_task_created"],
                "execution": created["execution"],
            },
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    reopened_store.close()
