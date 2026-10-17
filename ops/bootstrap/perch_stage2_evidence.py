"""Copy stage-2 task events from the owner's Store into a portable raw receipt.

This reads the Store after the owner is down. It does not use the generic
assignment timeline projection, which omits observation bodies and task
completion effects needed to identify the event's actual task.
"""

import argparse
from collections.abc import Mapping
import json
import sys
from pathlib import Path


def plain(value):
    if hasattr(value, "to_dict"):
        return plain(value.to_dict())
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def capture(src, store_path, authority):
    sys.path.insert(0, str(src))
    from herzchen.contracts import ResourceRef
    from herzchen.domains.work.admission import admitted_revision, reviewed_content_digest
    from herzchen.kernel import Store
    from otto.hostctl.owner import host_domains

    store = Store.open(str(store_path), authority=authority, expected_domains=host_domains())
    try:
        reader = store.consumer()
        page = reader.read_identity_page(kind="work.task", limit=100)
        if page["next_cursor"] is not None or page["held"]:
            raise ValueError("work task page is incomplete")
        tasks = {row.ref.id: row.payload.get("alias") for row in page["records"]}
        assignment_page = reader.read_identity_page(kind="wrk.assignment", limit=100)
        if assignment_page["next_cursor"] is not None or assignment_page["held"]:
            raise ValueError("assignment page is incomplete")
        assignments = {}
        for row in assignment_page["records"]:
            scope = row.payload.get("scope") or {}
            if isinstance(scope, Mapping) and scope.get("kind") == "work.task":
                assignments[row.ref.id] = scope.get("id")
        revisions = {}
        for row in page["records"]:
            history = []
            for version in range(1, row.version + 1):
                record = store.get_revision(ResourceRef(authority, "work.task", row.ref.id, "rev-" + str(version)))
                if record is None:
                    raise ValueError("missing retained task revision " + row.ref.id + "@rev-" + str(version))
                history.append({"revision": record.ref.revision,
                    "instructions": record.payload.get("instructions"),
                    "reviewed_digest": reviewed_content_digest(record.payload),
                    "admitted_revision": admitted_revision(record.payload)})
            revisions[row.ref.id] = history
        result = {"error": None, "tasks": tasks, "assignments": assignments,
                  "revisions": revisions, "events": []}
        for event in store.list_events():
            if event.event_type not in {"work.assignment.dispatched", "work.result.appended",
                                        "work.revised", "work.project-sheet.applied"}:
                continue
            assignment_id = (event.stream.split(":", 1)[1]
                             if event.stream.startswith(("dispatch:", "result:")) else None)
            task_id = assignments.get(assignment_id)
            value = None
            if event.event_type == "work.result.appended" and task_id is not None:
                record = store.get_identity(event.subject)
                value = (record.payload.get("value") if record is not None else None)
            elif event.event_type == "work.revised":
                task_id = event.subject.id if event.subject.kind == "work.task" else None
            elif event.event_type == "work.project-sheet.applied":
                effects = plain(event.effects)
                child_refs = (effects or {}).get("child_refs") or ()
                if not any(isinstance(ref, Mapping) and ref.get("kind") == "work.task"
                           and ref.get("id") in tasks for ref in child_refs):
                    continue
                result["events"].append({"task_id": None, "alias": None, "assignment_id": None,
                    "event_type": event.event_type, "stream": event.stream,
                    "recorded_at": event.recorded_at, "subject": plain(event.subject),
                    "effects": effects, "value": None})
                continue
            if task_id not in tasks:
                continue
            result["events"].append({"task_id": task_id, "alias": tasks[task_id],
                "assignment_id": assignment_id, "event_type": event.event_type,
                "stream": event.stream, "recorded_at": event.recorded_at,
                "subject": plain(event.subject), "effects": plain(event.effects),
                "value": plain(value)})
        return result
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--store", required=True)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        result = capture(args.src, args.store, args.authority)
    except Exception as exc:
        result = {"error": str(exc), "tasks": {}, "assignments": {}, "events": []}
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if result["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
