"""Emit bounded real-product observations for OTT-04 amendment recovery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile


def safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(item) for item in value]
    convert = getattr(value, "to_dict", None)
    if callable(convert):
        return safe(convert())
    if hasattr(value, "value"):
        return safe(value.value)
    return str(value)


def receipt_summary(value):
    if value is None:
        return None
    value = safe(value)
    return {
        key: value.get(key)
        for key in (
            "logical_request_key", "request_digest", "status", "event_ids",
            "result_ref", "transaction_id",
        )
    }


def stage_summary(stages):
    result = {}
    for name, stage in stages.items():
        receipts = stage.get("receipts")
        if receipts is None:
            receipts = [stage.get("receipt")]
        result[name] = {
            "status": stage.get("status"),
            "replayed": stage.get("replayed"),
            "receipts": [receipt_summary(receipt) for receipt in receipts],
        }
    return result


def view_summary(value):
    return {
        "plan": value.get("plan"),
        "next_dispatch": value.get("next_dispatch"),
        "attention": [
            {
                "event_id": item.get("event_id"),
                "recipient": item.get("recipient"),
                "state": item.get("state"),
            }
            for item in value.get("attention", ())
        ],
        "assignment": value.get("assignment"),
        "current_owner": value.get("current_owner"),
        "usage": value.get("usage"),
        "running_input_pins": value.get("running_input_pins"),
    }


def create_environment(path: Path, authority: str, owner: str):
    from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision
    from herzchen.content.model import domain_contribution as content_contribution
    from herzchen.content.packets import domain_contribution as packet_contribution
    from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
    from herzchen.domains.work import WorkGraph
    from herzchen.domains.work.assignments import ResponsibilityAssignments
    from herzchen.kernel import Store

    store = Store.create(path, authority=authority)
    actor = AuthenticatedActor(authority, "manager", "credential-manager")
    store.register_domain_handler((content_contribution(), packet_contribution()))
    graph = WorkGraph(store, actor=actor)
    graph.register()
    project = graph.create_project(
        title="amendment recovery plan",
        metadata={"ott04_usage_budget": {"spent": 4, "limit": 12}},
        logical_request_key="setup-project",
    )
    task = graph.create_task(project, title="amendment task", logical_request_key="setup-task")
    assignments = ResponsibilityAssignments(store, actor=actor)
    assignment = assignments.assign(
        task, role="execution", principal=owner, agent="agent-1", session="session-1",
        pins=(task.ref,), logical_request_key="setup-assignment",
    )
    content = ContentCommandHandler(store)
    subject = ContentDocument(
        ResourceRef(authority, "document", "amendment-subject"),
        "brief", "public", "read", owner,
    )
    revision = ContentRevision(subject.ref, "rev-1", {"title": "amendment subject"}, actor, initial=True)
    content.execute(content.build_create_document(
        TransactionContext(actor, "setup-subject", hashlib.sha256(b"setup-subject").hexdigest()),
        subject, revision,
    ))
    return store, actor, project, assignment, subject, revision


def first_retry_changed(root: Path):
    from herzchen.command_ports import close_consumer_facade
    from otto.attention import ImprovementPropagation, InputChangedError, issue_store_amendment_port

    store, actor, project, assignment, subject, revision = create_environment(
        root / "first-retry.sqlite", "ott04-xhard-first", "owner-1",
    )
    port = issue_store_amendment_port(store, actor, project, assignment, subject.ref, revision.ref)
    propagation = ImprovementPropagation(port)
    request = {
        "instruction": "apply the replay-safe amendment",
        "next_dispatch": "owner-review",
        "route": "owner-review-route",
    }
    before = port.read_views()
    before_events = len(store.list_events())
    first = propagation.apply(
        "review-xhard", decision_id="manager-decision-xhard",
        amendment=request, request_id="amendment-xhard",
    )
    after_first_events = len(store.list_events())
    retry = propagation.apply(
        "review-xhard", decision_id="manager-decision-xhard",
        amendment=request, request_id="amendment-xhard",
    )
    after_retry_events = len(store.list_events())
    before_changed_views = port.read_views()
    changed_error = None
    try:
        propagation.apply(
            "review-xhard", decision_id="manager-decision-xhard",
            amendment={**request, "route": "changed-route"}, request_id="amendment-xhard",
        )
    except InputChangedError as exc:
        changed_error = {"type": type(exc).__name__, "message": str(exc)}
    after_changed_events = len(store.list_events())
    after_changed_views = port.read_views()
    event_types = [event.event_type for event in store.list_events()]
    result = {
        "boundary": {
            "client_dir": dir(port),
            "has_store": hasattr(port, "store"),
            "has_callback": hasattr(port, "_apply"),
            "transport_endpoints": list(port.transport.endpoints),
            "transport_has_connection": hasattr(port.transport, "connection"),
            "transport_path_is_db": str(port.transport.socket_path).endswith((".sqlite", ".sqlite3", ".db")),
        },
        "before": view_summary(before),
        "first": {
            "event_delta": after_first_events - before_events,
            "outcome": first["outcome"],
            "action": first["action"],
            "stages": stage_summary(first["response"]["stages"]),
            "fresh_after": view_summary(first["fresh_after"]),
            "preserved": first["preserved"],
            "manager_decision": first["action"]["manager_decision"],
            "dispatch": first["dispatch"],
            "automatic_action": first["automatic_action"],
        },
        "exact_retry": {
            "event_delta": after_retry_events - after_first_events,
            "outcome": retry["outcome"],
            "replayed": retry["replayed"],
            "required_changes": retry["required_changes"],
            "requirements_satisfied": retry["requirements_satisfied"],
            "stages": stage_summary(retry["response"]["stages"]),
            "fresh_after": view_summary(retry["fresh_after"]),
            "dispatch": retry["dispatch"],
            "automatic_action": retry["automatic_action"],
        },
        "changed_input": {
            "error": changed_error,
            "event_delta": after_changed_events - after_retry_events,
            "state_delta": before_changed_views != after_changed_views,
        },
        "event_types": event_types,
        "dispatch_event_present": "work.assignment.dispatched" in event_types,
    }
    close_consumer_facade(port.transport)
    store.close()
    return safe(result)


def interrupted_recovery(root: Path):
    from herzchen.command_ports import close_consumer_facade
    from herzchen.kernel import Store
    from otto.attention import AmendmentInterruptedError, ImprovementPropagation, issue_store_amendment_port

    path = root / "interrupted.sqlite"
    store, actor, project, assignment, subject, revision = create_environment(
        path, "ott04-xhard-interrupted", "owner-2",
    )
    port = issue_store_amendment_port(
        store, actor, project, assignment, subject.ref, revision.ref,
        interrupt_after_stage="plan",
    )
    propagation = ImprovementPropagation(port)
    request = {
        "instruction": "resume the interrupted amendment",
        "next_dispatch": "owner-2-review",
        "route": "owner-2-route",
    }
    before = port.read_views()
    before_events = len(store.list_events())
    interruption = None
    try:
        propagation.apply(
            "review-interrupted", decision_id="manager-decision-interrupted",
            amendment=request, request_id="amendment-interrupted",
        )
    except AmendmentInterruptedError as exc:
        interruption = {"type": type(exc).__name__, "message": str(exc)}
    partial_events = len(store.list_events())
    partial = port.read_views()
    partial_receipts = {
        key: receipt_summary(store.get_receipt("amendment-interrupted:" + suffix))
        for key, suffix in {
            "decision": "decision",
            "plan": "plan",
            "assignment": "route",
            "attention": "attention:owner-2",
        }.items()
    }
    domains = store.registered_domains()
    close_consumer_facade(port.transport)
    store.close()

    reopened = Store.open(path, authority="ott04-xhard-interrupted", expected_domains=domains)
    resumed_port = issue_store_amendment_port(
        reopened, actor, project, assignment, subject.ref, revision.ref,
    )
    recovery_before_events = len(reopened.list_events())
    recovered = ImprovementPropagation(resumed_port).apply(
        "review-interrupted", decision_id="manager-decision-interrupted",
        amendment=request, request_id="amendment-interrupted",
    )
    recovery_after_events = len(reopened.list_events())
    event_types = [event.event_type for event in reopened.list_events()]
    result = {
        "interruption": interruption,
        "partial_event_delta": partial_events - before_events,
        "partial_receipts": partial_receipts,
        "partial_views": view_summary(partial),
        "recovery": {
            "event_delta": recovery_after_events - recovery_before_events,
            "outcome": recovered["outcome"],
            "recovered": recovered["recovered"],
            "replayed": recovered["replayed"],
            "required_changes": recovered["required_changes"],
            "requirements_satisfied": recovered["requirements_satisfied"],
            "stages": stage_summary(recovered["response"]["stages"]),
            "fresh_after": view_summary(recovered["fresh_after"]),
            "preserved_from_initial": {
                key: before[key] == recovered["fresh_after"][key]
                for key in ("current_owner", "usage", "running_input_pins")
            },
            "dispatch": recovered["dispatch"],
            "automatic_action": recovered["automatic_action"],
        },
        "stage_event_counts": {
            event_type: event_types.count(event_type)
            for event_type in (
                "work.project-sheet.applied",
                "work.assignment.route-pinned",
                "dat.context.attention.created",
                "work.assignment.dispatched",
            )
        },
    }
    close_consumer_facade(resumed_port.transport)
    reopened.close()
    return safe(result)


with tempfile.TemporaryDirectory(prefix="ott04-amendment-replay-") as directory:
    import herzchen
    import herzchen.command_ports
    import otto
    import otto.attention

    root = Path(directory)
    print(json.dumps({
        "origins": {
            "otto": otto.__file__,
            "otto_attention": otto.attention.__file__,
            "herzchen": herzchen.__file__,
            "herzchen_command_ports": herzchen.command_ports.__file__,
        },
        "first_retry_changed": first_retry_changed(root),
        "interrupted_recovery": interrupted_recovery(root),
        "expected_cas_base": {
            "source_commit": "54c3776b1dc466656df527724db5daa0b60f9dca",
            "installed_observation": "work/ott-04-correction-20260914/observation-installed-final2.json",
            "installed_observation_sha256": "6adf116477e4e4795ea148962a44f3d894ecaf94e142814ed0201be098cea5ec",
        },
    }, sort_keys=True, indent=2))
