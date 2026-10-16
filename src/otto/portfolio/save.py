"""``otto save``: one project from a file in the template seed shape (A2).

A save file is a template seed (``project``, ``tasks``, ``criteria``,
``documents``: packs/templates.py:390-395) plus, for an existing project, the
``project_ref`` it was read at. Its ``revision`` is the base the save applies
to, so a save written against an older revision is refused, never applied over
newer work. Without a ``project_ref`` the save creates the project.

Tasks are inert: a save file can add, edit or explicitly withdraw tasks, but it
never makes work runnable (A1). Omitting a task keeps it. A task may name the
``revision`` it was read at, which is a per-task base: a task edited since is
refused, and naming one needs the file's ``project_ref``.
"""

import hashlib
import json
from typing import Any, Mapping, Sequence

SAVE_TEMPLATE_ID = "otto.save"
SAVE_KEYS = frozenset({"project_ref", "project", "tasks", "criteria", "documents"})
PROJECT_KEYS = frozenset({"title", "name", "outcome", "scope", "approach", "acceptance", "protocol", "custom", "metadata"})
TASK_KEYS = frozenset({"id", "alias", "aliases", "kind", "title", "name", "body", "instructions", "outcome", "acceptance", "fields", "metadata", "metadata_namespace", "custom", "order", "lifecycle", "dependencies", "depends_on", "documents", "document_links", "revision", "withdraw"})
DIFF_SKIP = frozenset({"id", "local_id", "key", "dependencies", "depends_on", "metadata_namespace", "documents", "document_links", "revision"})


class SaveFileError(ValueError):
    """The file is not a valid save; nothing reached the owner."""


def parse_save_file(document: Any) -> dict[str, Any]:
    """Validate a save file and return ``{"project_ref": dict | None, "seed": dict}``."""
    if not isinstance(document, Mapping):
        raise SaveFileError("save file must be a JSON object")
    unknown = sorted(str(key) for key in set(document) - SAVE_KEYS)
    if unknown:
        raise SaveFileError("unknown save-file fields: " + ", ".join(unknown))
    if document.get("documents"):
        raise SaveFileError("documents are not saved by otto save yet; author them through the document route")
    project_ref = document.get("project_ref")
    if project_ref is not None:
        if not isinstance(project_ref, Mapping) or not isinstance(project_ref.get("id"), str) or not project_ref["id"].strip():
            raise SaveFileError("project_ref must be a durable reference with an id")
        if not isinstance(project_ref.get("revision"), str) or not project_ref["revision"].strip():
            raise SaveFileError("project_ref needs the revision the file was read at; that is the base the save applies to")
        project_ref = dict(project_ref)
    project = document.get("project", {})
    if not isinstance(project, Mapping):
        raise SaveFileError("project must be an object")
    unknown_project = sorted(str(key) for key in set(project) - PROJECT_KEYS)
    if unknown_project:
        raise SaveFileError("unknown project fields: " + ", ".join(unknown_project))
    tasks = document.get("tasks", [])
    if not isinstance(tasks, list):
        raise SaveFileError("tasks must be an array")
    criteria = document.get("criteria", [])
    if not isinstance(criteria, list):
        raise SaveFileError("criteria must be an array")
    ids: list[str] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, Mapping):
            raise SaveFileError(f"task[{index}] must be an object")
        unknown_task = sorted(str(key) for key in set(task) - TASK_KEYS)
        if unknown_task:
            raise SaveFileError(f"task[{index}] has unsupported fields: " + ", ".join(unknown_task))
        if task.get("kind", "task") not in ("task", "work.task"):
            raise SaveFileError(f"task[{index}] has unsupported kind")
        local_id = task.get("id")
        if not isinstance(local_id, str) or not local_id.strip():
            raise SaveFileError(f"task[{index}] needs a non-blank id")
        if local_id in ids:
            raise SaveFileError(f"task id {local_id!r} appears twice")
        if task.get("lifecycle", "pending") != "pending":
            raise SaveFileError(f"task {local_id!r} must be pending: a save never makes work runnable; activation starts work")
        if "revision" in task and (not isinstance(task["revision"], str) or not task["revision"].strip()):
            raise SaveFileError(f"task {local_id!r} revision must be a non-blank string")
        ids.append(local_id)
    if project_ref is None and any("revision" in task for task in tasks):
        raise SaveFileError("a task revision needs the project_ref it was read at; a new project has no earlier revision")
    dependencies = {task["id"]: _dependency_ids(task) for task in tasks}
    if project_ref is None:
        # A new project holds only this file's tasks, so an unknown dependency is refused before anything is created.
        for local_id, deps in dependencies.items():
            for dep in deps:
                if dep not in ids:
                    raise SaveFileError(f"task {local_id!r} depends on unknown task {dep!r}")
    _refuse_cycles(dependencies)
    # The file's id is the task's durable alias, so a later save finds the same task.
    seed = {"project": dict(project), "tasks": [dict(task, alias=task.get("alias", task["id"])) for task in tasks], "criteria": list(criteria)}
    return {"project_ref": project_ref, "seed": seed}


def _dependency_ids(task: Mapping[str, Any]) -> list[str]:
    """A task's dependencies as local ids; a template's ``{"$local": id}`` form is accepted."""
    raw = task.get("dependencies", task.get("depends_on", []))
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SaveFileError(f"task {task['id']!r} dependencies must be an array")
    ids: list[str] = []
    for dep in raw:
        if isinstance(dep, Mapping) and set(dep) == {"$local"}:
            dep = dep["$local"]
        if not isinstance(dep, str) or not dep.strip():
            raise SaveFileError(f"task {task['id']!r} dependency must name a task id")
        ids.append(dep)
    return ids


def _refuse_cycles(dependencies: Mapping[str, Sequence[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise SaveFileError("task dependency cycle rejected at " + repr(node))
        if node in visited:
            return
        visiting.add(node)
        for dep in dependencies.get(node, ()):
            if dep in dependencies:
                visit(dep)
        visiting.remove(node)
        visited.add(node)

    for node in tuple(dependencies):
        visit(node)


def save_request_key(document: Any) -> str:
    """A deterministic logical request key: the same file replays, a changed file does not."""
    try:
        text = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SaveFileError("save file must be JSON-compatible") from exc
    return "save:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def diff_save(seed: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Name what a save file would change against the owner's current sheet view.

    ``current`` is ``ProjectSheet.export`` output. The diff lists each project
    and task field that differs from the file, each task the file adds, and each
    current task the file leaves out. Those are kept, never withdrawn.
    """
    authored_project = dict(current["project"].get("authored", {}))
    project_diff = {
        field: {"file": value, "current": authored_project.get(field)}
        for field, value in seed.get("project", {}).items()
        if field in ("title", "name", "outcome", "scope", "approach", "acceptance", "protocol")
        and authored_project.get(field) != value
    }
    by_key: dict[str, Mapping[str, Any]] = {}
    for view in current.get("tasks", ()):
        authored = view.get("authored", {})
        for key in {authored.get("alias"), *authored.get("aliases", ())} - {None}:
            by_key[str(key)] = authored
    file_ids = {str(task["id"]) for task in seed.get("tasks", ())}
    added: list[str] = []
    changed: list[dict[str, Any]] = []
    for task in seed.get("tasks", ()):
        local_id = str(task["id"])
        authored = by_key.get(local_id)
        if authored is None:
            added.append(local_id)
            continue
        fields = {
            field: {"file": value, "current": authored.get(field)}
            for field, value in task.items()
            if field not in DIFF_SKIP and authored.get(field) != value
        }
        if fields:
            changed.append({"id": local_id, "fields": fields})
    kept: list[str] = []
    for view in current.get("tasks", ()):
        authored = view.get("authored", {})
        names = {str(name) for name in {authored.get("alias"), *authored.get("aliases", ())} - {None}}
        if not names & file_ids:
            kept.append(str(authored.get("alias")))
    return {"project": project_diff, "tasks": {"added": added, "changed": changed, "kept": kept}}
