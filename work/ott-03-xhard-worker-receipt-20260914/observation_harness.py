"""Installed-package durable observation harness for the OTT-03 XHARD receipt."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import os

import herzchen
import otto
from herzchen.authoring import register_authoring
from herzchen.content import domain_contribution
from herzchen.contracts import ResourceRef
from herzchen.domains.work import register_work
from herzchen.kernel.store import Store
from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap


ROOT = Path(__file__).resolve().parent
AUTHORITY = "ott03-xhard-observation"
CREDENTIAL = "ott03-xhard-observation-credential"


def safe(value):
    if hasattr(value, "to_dict"):
        return safe(value.to_dict())
    if is_dataclass(value):
        return safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(item) for item in value]
    return value


def create_store(path, authority):
    store = Store.create(path, authority=authority)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    return store


def bootstrap(store, authority, *, materializer=None):
    owner = PortfolioOwnerBootstrap(
        store,
        binding=HerzchenBindingConfig(authority, CREDENTIAL),
        owner_actor="manager",
        materializer=materializer,
    )
    return owner, OttoPortfolio(owner.consumer_operations())


def snapshot(store, keys, refs=()):
    return safe(
        {
            "event_count": len(store.list_events()),
            "events": [
                {
                    "event_id": item.event_id,
                    "event_type": item.event_type,
                    "operation": item.operation,
                    "subject": item.subject,
                }
                for item in store.list_events()
            ],
            "receipts": {key: store.get_receipt(key) for key in keys},
            "records": {name: store.get_identity(ref) for name, ref in refs},
        }
    )


started = datetime.now(timezone.utc).isoformat()
proof_path = ROOT / "durable-proof.sqlite"
store = create_store(proof_path, AUTHORITY)
owner, api = bootstrap(store, AUTHORITY)
consumer = owner.consumer_operations()
surface = {
    "retained": {name: type(value).__name__ for name, value in vars(consumer).items()},
    "create_open_endpoints": list(consumer.create_open_port.endpoints),
    "authoring_endpoints": list(consumer.authoring_port.endpoints),
    "create_open_transport": {
        key: value
        for key, value in consumer.create_open_port.transport.to_dict().items()
        if key != "token"
    },
}

keys = (
    "observation-create-open",
    "observation-create-open:project",
    "observation-create-open:actor",
    "observation-create-open:project-created",
    "observation-create-open:materialized",
)
before = snapshot(store, keys)
created = api.create_and_open(
    actor="manager",
    request_id="observation-create-open",
    edit={
        "title": "Observed owner bridge",
        "outcome": "durable proof",
        "why_pending": "await admission",
        "custom": {"preserved": [1, 2]},
    },
)
project_ref = ResourceRef.from_dict(created["project_ref"])
scope_ref = ResourceRef(AUTHORITY, "authoring-scope", project_ref.id)
after = snapshot(store, keys, (("project", project_ref), ("authoring_scope", scope_ref)))

occupied_before = snapshot(store, ("observation-occupied", "observation-occupied:project"))
occupied = api.create_and_open(
    actor="manager",
    request_id="observation-occupied",
    edit={"title": "Must remain absent"},
)
occupied_after = snapshot(store, ("observation-occupied", "observation-occupied:project"))

domains = store.registered_domains()
store.close()
fresh_store = Store.open(proof_path, authority=AUTHORITY, expected_domains=domains)
fresh_owner, fresh_api = bootstrap(fresh_store, AUTHORITY)
fresh_before_replay = snapshot(
    fresh_store, keys, (("project", project_ref), ("authoring_scope", scope_ref))
)
replay = fresh_api.create_and_open(
    actor="manager",
    request_id="observation-create-open",
    edit={
        "title": "Observed owner bridge",
        "outcome": "durable proof",
        "why_pending": "await admission",
        "custom": {"preserved": [1, 2]},
    },
)
fresh_after_replay = snapshot(
    fresh_store, keys, (("project", project_ref), ("authoring_scope", scope_ref))
)
conflict_before = snapshot(fresh_store, keys)
conflict = fresh_api.create_and_open(
    actor="manager",
    request_id="observation-create-open",
    edit={"title": "Changed logical request"},
)
conflict_after = snapshot(fresh_store, keys)
fresh_store.close()

failure_authority = AUTHORITY + "-failure"
failure_path = ROOT / "materialization-failure-proof.sqlite"
failure_calls = []


def fail_materialization(*, project, **_kwargs):
    failure_calls.append(project.to_dict())
    raise RuntimeError("receipt-forced materialization failure")


failure_store = create_store(failure_path, failure_authority)
_failure_owner, failure_api = bootstrap(
    failure_store, failure_authority, materializer=fail_materialization
)
failure_keys = (
    "observation-materialize",
    "observation-materialize:project",
    "observation-materialize:project-created",
    "observation-materialize:materialize-failure",
    "observation-materialize:materialize-failure:actor",
)
failure_before = snapshot(failure_store, failure_keys)
failed = failure_api.create_and_open(
    actor="manager",
    request_id="observation-materialize",
    edit={"title": "Saved materialization recovery"},
)
failure_project_ref = ResourceRef.from_dict(failed["project_ref"])
failure_scope_ref = ResourceRef(failure_authority, "authoring-scope", failure_project_ref.id)
failure_after = snapshot(
    failure_store,
    failure_keys,
    (("project", failure_project_ref), ("authoring_scope", failure_scope_ref)),
)
failure_replay = failure_api.create_and_open(
    actor="manager",
    request_id="observation-materialize",
    edit={"title": "Saved materialization recovery"},
)
failure_after_replay = snapshot(
    failure_store,
    failure_keys,
    (("project", failure_project_ref), ("authoring_scope", failure_scope_ref)),
)
reopened = failure_api.reopen(
    failed["project_ref"],
    actor="manager",
    request_id="observation-materialize-reopen",
)
failure_after_reopen = snapshot(
    failure_store,
    failure_keys + ("observation-materialize-reopen",),
    (("project", failure_project_ref), ("authoring_scope", failure_scope_ref)),
)
failure_store.close()

result = {
    "process": {
        "pid": os.getpid(),
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "cwd": os.getcwd(),
        "otto_origin": otto.__file__,
        "herzchen_origin": herzchen.__file__,
    },
    "consumer_surface": surface,
    "success": {
        "before": before,
        "action": safe(created),
        "after": after,
        "occupied_before": occupied_before,
        "occupied_action": safe(occupied),
        "occupied_after": occupied_after,
        "fresh_before_replay": fresh_before_replay,
        "replay_action": safe(replay),
        "fresh_after_replay": fresh_after_replay,
        "conflict_before": conflict_before,
        "conflict_action": safe(conflict),
        "conflict_after": conflict_after,
    },
    "materialization_failure": {
        "before": failure_before,
        "action": safe(failed),
        "after": failure_after,
        "materializer_calls": failure_calls,
        "replay_action": safe(failure_replay),
        "after_replay": failure_after_replay,
        "reopen_action": safe(reopened),
        "after_reopen": failure_after_reopen,
    },
}
print(json.dumps(result, indent=2, sort_keys=True))
