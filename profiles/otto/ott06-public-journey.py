"""Executable public OTT-06 example.

Run this file with an installed Otto + Herzchen environment.  It deliberately
uses the documented finite consumer APIs plus the host-owned semantic
check-in boundary; the owner Store and authoring lifecycle remain in host
custody and are reopened with ``Store.open`` for the final read/replay check.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path

from herzchen.authoring import AuthoringLifecycle, FileWriterLeaseAuthority, register_authoring
from herzchen.content import domain_contribution as content_contribution
from herzchen.contracts import ResourceRef
from herzchen.domains.work import register_work
from herzchen.kernel.store import Store
from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap


def public(value):
    """Convert typed public results to JSON without inspecting implementations."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): public(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [public(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return public(to_dict())
    if hasattr(value, "value"):
        return public(value.value)
    return str(value)


def bootstrap(path: Path, authority: str, credential_ref: str, actor: str, *, reopen: bool, domains=()):
    if reopen:
        store = Store.open(path, authority=authority, expected_domains=domains)
    else:
        store = Store.create(path, authority=authority)
        register_work(store)
        store.register_domain_handler((content_contribution(),))
        register_authoring(store)
    owner = PortfolioOwnerBootstrap(
        store,
        binding=HerzchenBindingConfig(authority, credential_ref),
        owner_actor=actor,
    )
    return store, owner, OttoPortfolio(owner.consumer_operations())


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Run the public OTT-06 manager journey")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("OTT06_EXAMPLE_DB", "/private/tmp/ott06-public-example.sqlite3")),
        help="disposable SQLite path (default: OTT06_EXAMPLE_DB or /private/tmp/ott06-public-example.sqlite3)",
    )
    parser.add_argument("--output", type=Path, help="write the complete JSON result to this file")
    args = parser.parse_args(argv)

    path = args.db
    if path.exists():
        raise RuntimeError(f"refusing an existing database path: {path}")
    authority = "ott06-public-example"
    credential_ref = "ott06-public-credential"
    actor = "ott06-public-manager"

    store, owner, portfolio = bootstrap(path, authority, credential_ref, actor, reopen=False)
    help_value = portfolio.help()
    before_list = portfolio.list_pending(actor=actor)
    created = portfolio.create_pending(
        actor=actor,
        request_id="ott06-example-create-1",
        edit={"title": "OTT-06 public example", "description": "Pending and inert"},
    )
    project_ref = created["project_ref"]
    edited = portfolio.edit_pending(
        project_ref,
        {"title": "OTT-06 public example edited"},
        actor=actor,
        request_id="ott06-example-edit-1",
    )
    read_after_edit = portfolio.read_pending(edited["project_ref"], actor=actor)
    edit_replay = portfolio.edit_pending(
        project_ref,
        {"title": "OTT-06 public example edited"},
        actor=actor,
        request_id="ott06-example-edit-1",
    )

    operations = owner.consumer_operations()
    task_batch = operations.sheet_port.apply(
        ResourceRef.from_dict(read_after_edit["project_ref"]),
        {
            "tasks": [
                {"id": "foundation", "title": "Capture the baseline", "order": 0},
                {
                    "id": "follow-up",
                    "title": "Review the baseline",
                    "order": 1,
                    "dependencies": ["foundation"],
                },
            ]
        },
        logical_request_key="ott06-example-task-batch-1",
        actor=operations.binding.authenticated_actor(actor),
        base_revision=read_after_edit["project_ref"]["revision"],
    )
    task_ref = task_batch.project.ref.to_dict()
    task_view = operations.sheet_port.export(ResourceRef.from_dict(task_ref)).to_dict()
    read_after_tasks = portfolio.read_pending(task_ref, actor=actor)
    # Direct task edits and whole-project check-in use the two supported
    # owner paths. The finite consumer receives only typed command ports; the
    # host keeps the authoring service, writer lease and semantic handler.
    direct_task = operations.port.revise(
        task_batch.mappings["follow-up"],
        title="Review the baseline directly edited",
        logical_request_key="ott06-example-direct-task-1",
        actor=operations.binding.authenticated_actor(actor),
    )
    checkout_root = path.parent / "ott06-project-checkout"
    checkout_root.mkdir()
    lifecycle = AuthoringLifecycle(
        owner.authoring,
        writer_leases=FileWriterLeaseAuthority(
            path.parent / "ott06-writer-locks",
            authority=authority + "-writer",
            secret=b"ott06-public-writer-authority-key-material",
            writer_identities=("ott06-editor",),
        ),
        writer_identity="ott06-editor",
    )
    opened_checkout = lifecycle.open(
        ResourceRef.from_dict(task_ref),
        operations.binding.authenticated_actor(actor),
        request_id="ott06-example-project-open-1",
        target_kind="project-sheet",
        base_revision=task_ref["revision"],
        initial_content=b"{}",
        pending=True,
    )
    (checkout_root / "project.json").write_text(
        json.dumps(
            {
                "title": "OTT-06 public example checked in",
                "tasks": [
                    {"id": "foundation", "title": "Capture the baseline", "order": 0},
                    {
                        "id": "follow-up",
                        "title": "Review the baseline checked in",
                        "order": 1,
                        "dependencies": ["foundation"],
                    },
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    checkin = lifecycle.finish(
        opened_checkout,
        request_id="ott06-example-project-checkin-1",
        mode="manual",
        checkout_root=checkout_root,
        registered_files=["project.json"],
        handler=owner.sheet.batches.lifecycle_handler(
            ResourceRef.from_dict(task_ref),
            authoring=owner.authoring,
            handle=opened_checkout.handle,
            request_id="ott06-example-project-domain-1",
        ),
        writer_check=lambda: True,
    )
    read_after_checkin = portfolio.read_pending(task_ref, actor=actor)
    task_ref = read_after_checkin["project_ref"]
    decision_frame = {
        "outcome": "Investigate the dependency before any admission or execution step",
        "recipient": actor,
        "route": "manual-review",
        "authority": authority,
    }
    admission = portfolio.admit(
        task_ref,
        choice="investigate",
        frame=decision_frame,
        actor=actor,
        request_id="ott06-example-admit-1",
    )
    domains = store.registered_domains()
    store.close()

    reopened_store, reopened_owner, reopened_portfolio = bootstrap(
        path, authority, credential_ref, actor, reopen=True, domains=domains
    )
    reopened = reopened_portfolio.reopen(
        admission["project_ref"], actor=actor, request_id="ott06-example-reopen-1"
    )
    reopen_replay = reopened_portfolio.reopen(
        admission["project_ref"], actor=actor, request_id="ott06-example-reopen-1"
    )
    reopened_read = reopened_portfolio.read_pending(admission["project_ref"], actor=actor)
    after_list = reopened_portfolio.list_pending(actor=actor)
    reopened_store.close()

    payload = {
        "help": help_value,
        "before_list": before_list,
        "created": created,
        "edited": edited,
        "read_after_edit": read_after_edit,
        "edit_replay": edit_replay,
        "task_batch": {
            "status": task_batch.status,
            "project_ref": task_ref,
            "mappings": public(task_batch.mappings),
            "receipt": public(task_batch.receipt),
            "view": public(task_view),
        },
        "direct_task": public(direct_task.ref),
        "project_checkout_checkin": {
            "opened": opened_checkout.opened.status,
            "status": checkin.status,
            "validated": checkin.finish.validation.valid if checkin.finish.validation else None,
            "receipt": public(checkin.receipt),
            "cleanup": None if checkin.cleanup is None else public(checkin.cleanup),
            "temporary_file_removed": not (checkout_root / "project.json").exists(),
            "read_after_checkin": read_after_checkin,
        },
        "read_after_tasks": read_after_tasks,
        "admission": admission,
        "reopened": reopened,
        "reopen_replay": reopen_replay,
        "reopened_read": reopened_read,
        "after_list": after_list,
    }
    serialized = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if args.output is None:
        print(serialized)
    else:
        args.output.write_text(serialized + "\n")


if __name__ == "__main__":
    main()
