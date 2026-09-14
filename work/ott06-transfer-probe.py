from __future__ import annotations

import json
from pathlib import Path
import tempfile

from herzchen.authoring import register_authoring
from herzchen.content import domain_contribution
from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.domains.work import register_work
from herzchen.kernel.store import Store
from otto.portfolio import HerzchenBindingConfig, PortfolioOwnerBootstrap


def owner(path: Path, authority: str):
    store = Store.create(path, authority=authority)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    bootstrap = PortfolioOwnerBootstrap(
        store,
        binding=HerzchenBindingConfig(authority, authority + "-credential"),
        owner_actor="manager",
    )
    return store, bootstrap, bootstrap.consumer_operations()


with tempfile.TemporaryDirectory(prefix="ott06-transfer-") as raw:
    root = Path(raw)
    source_path = root / "source.sqlite"
    target_path = root / "target.sqlite"
    source_store, source_bootstrap, source = owner(source_path, "ott06-source")
    target_store, target_bootstrap, target = owner(target_path, "ott06-target")
    created = source.execute(
        "work.pending.create",
        {"edit": {"title": "Exported pending project", "outcome": "retain"}},
        request_id="source-create",
        actor="manager",
    )
    source_ref = ResourceRef.from_dict(created["project_ref"])
    # Seed a non-empty supported public project sheet.  The dependency is
    # authored in the same ProjectSheet command, so export can compare the
    # real task payloads rather than a fixture-shaped list.
    seeded = source_bootstrap.sheet.apply(
        source_ref,
        {
            "tasks": [
                {"id": "prerequisite", "title": "Prepare transfer", "body": "durable prerequisite", "order": 1},
                {"id": "dependent", "title": "Verify transfer", "body": "depends on prerequisite", "dependencies": ["prerequisite"], "order": 2},
            ],
            "metadata": {"seed": "ott06-transfer-probe", "nonempty": True},
        },
        logical_request_key="source-sheet",
        actor=source_bootstrap.owner_actor,
    )
    doc = source.execute(
        "work.pending.document.create",
        {"project_ref": created["project_ref"], "role": "brief", "content": {"body": "durable transfer brief", "revision": 1}, "document_id": "transfer-brief"},
        request_id="source-document",
        actor="manager",
    )
    linked = source.execute(
        "work.pending.document.link",
        {"project_ref": created["project_ref"], "document_ref": doc["document_ref"], "namespace": "project.documents", "key": "brief"},
        request_id="source-document-link",
        actor="manager",
    )
    exported = source.execute(
        "work.project.export", {"project_ref": created["project_ref"], "document_refs": [doc["document_ref"]]}, request_id="export", actor="manager"
    )
    imported = target.execute(
        "work.project.import", {"snapshot": exported["snapshot"]}, request_id="import", actor="manager"
    )
    replay = target.execute(
        "work.project.import", {"snapshot": exported["snapshot"]}, request_id="import", actor="manager"
    )
    changed = json.loads(json.dumps(exported["snapshot"]))
    changed["project"]["payload"]["title"] = "Changed same-key transfer"
    changed_without_digest = dict(changed)
    changed_without_digest.pop("snapshot_digest", None)
    import hashlib
    changed["snapshot_digest"] = hashlib.sha256(json.dumps(changed_without_digest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    conflict = target.execute(
        "work.project.import", {"snapshot": changed}, request_id="import", actor="manager"
    )
    parent = source.execute(
        "work.pending.create", {"edit": {"title": "Parent obligation"}}, request_id="parent", actor="manager"
    )
    assigned = source.execute(
        "work.responsibility.assign",
        {"project_ref": created["project_ref"], "roles": {"parent": parent["project_ref"], "manager": "manager-old", "executor": ["executor-a"]}},
        request_id="roles", actor="manager",
    )
    fenced = source.execute(
        "work.responsibility.fence",
        {"manager_assignment_ref": assigned["manager_assignment_ref"], "expected_generation": 1},
        request_id="fence", actor="manager",
    )
    # Handoff to a new manager, close the owner, then reopen the same durable
    # store in a fresh owner process.  A stale old-generation dispatch must be
    # a typed rejection with zero events, rather than merely dispatch:false.
    manager_ref = assigned["manager_assignment_ref"]
    consumption_ref = assigned["roles"]["roles:executor"]["ref"] if "roles:executor" in assigned.get("roles", {}) else next(
        item["ref"] for item in assigned.get("roles", {}).values() if item.get("role") == "executor"
    )
    handoff = source.execute(
        "work.responsibility.handoff",
        {
            "project_ref": created["project_ref"],
            "manager_assignment_ref": manager_ref,
            "from_manager": "manager-old",
            "to_manager": "manager-new",
            "evidence_refs": [parent["project_ref"]],
            "consumption_refs": [consumption_ref],
            "parent_obligation": parent["project_ref"],
        },
        request_id="handoff", actor="manager",
    )
    registered_domains = source_store.registered_domains()
    source_store.close()
    reopened_store = Store.open(source_path, authority="ott06-source", expected_domains=registered_domains)
    reopened_bootstrap = PortfolioOwnerBootstrap(
        reopened_store,
        binding=HerzchenBindingConfig("ott06-source", "ott06-source-credential"),
        owner_actor="manager",
    )
    reopened = reopened_bootstrap.consumer_operations()
    stale_dispatch = reopened.execute(
        "work.responsibility.dispatch",
        {"manager_assignment_ref": manager_ref, "expected_generation": 1, "action": "old-manager-dispatch", "input_refs": []},
        request_id="old-manager-dispatch-after-reopen",
        actor="manager-old",
    )
    reopened_counts = reopened.reader.snapshot_counts()
    print(json.dumps({
        "source_project": created["project_ref"],
        "export_digest": exported["snapshot_digest"],
        "seeded_sheet": {"mappings": str(getattr(seeded, "mappings", {})), "project_tasks": len(exported["snapshot"].get("tasks", [])), "project_documents": len(exported["snapshot"].get("documents", []))},
        "source_document": doc,
        "source_document_link": linked,
        "imported": imported,
        "replay": replay,
        "changed_request": conflict,
        "fenced": fenced,
        "handoff": handoff,
        "stale_dispatch_after_reopen": stale_dispatch,
        "reopened_counts": reopened_counts,
        "target_counts": target.reader.snapshot_counts(),
        "transfer_limits": exported["snapshot"].get("transfer_limits"),
        "origins": {"otto": __import__("otto").__file__, "herzchen": __import__("herzchen").__file__},
    }, sort_keys=True, default=str))
    reopened_store.close()
    target_store.close()
