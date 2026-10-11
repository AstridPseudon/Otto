"""Apply a Megado portfolio root to an admitted Otto portfolio, by receipt."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from herzchen.contracts import ResourceRef

SETUP_SCHEMA = "otto.portfolio-setup.v1"


def read_portfolio_root(directory: str, *, history_directory: str | None = None) -> dict[str, Any]:
    """Read client-owned text files before sending them to the owner service."""
    from otto.portfolio.shared_documents import read_document_directory
    from .bundle import read_bundle
    root = Path(directory).resolve()
    shared = read_document_directory(root, exclude_prefixes=("projects/",))
    try:
        setup = json.loads(shared["files"]["portfolio-setup.json"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("portfolio root needs a valid portfolio-setup.json") from exc
    project_rows = []
    project_root = root / "projects"
    for item in setup.get("projects") or ():
        folder = item.get("folder") or item.get("directory")
        if not folder and isinstance(item.get("run_id"), str):
            folder = item["run_id"].split("/")[-1]
        if not isinstance(folder, str) or not folder or "/" in folder or "\\" in folder:
            raise ValueError("each portfolio-setup project needs a single-component folder")
        bundle = read_bundle(project_root / folder)
        project_rows.append({"id": item.get("id"), "folder": folder, "bundle": bundle})
    present = {p.name for p in project_root.iterdir() if p.is_dir()
               and any((p / name).is_file() for name in ('run.json', 'run.yaml'))}
    if present != {row['folder'] for row in project_rows}:
        raise ValueError('portfolio manifest must declare every project bundle directory exactly once')
    history = read_bundle(history_directory) if history_directory else None
    return {"schema": "otto.portfolio-apply-input.v1", "root": str(root), "setup": setup,
            "shared_bundle": shared, "projects": project_rows,
            "history": history, "history_root": str(Path(history_directory).resolve()) if history_directory else None}


def _worktree(bundle: Mapping[str, Any]) -> str:
    run = bundle["run"]
    root = run.get("control_root") or bundle.get("root")
    path = Path(root)
    if not path.is_absolute():
        path = Path(bundle.get("root") or ".") / path
    return str(path.resolve().parents[2])


def _run_id(bundle: Mapping[str, Any]) -> str:
    return bundle["run"].get("run_id") or Path(bundle.get("root") or "run").name


def _custom(record: Any) -> Mapping[str, Any]:
    return ((record.payload.get("custom") or {}).get("otto_host_registration") or {})


def _portfolio_key(record: Any) -> Mapping[str, Any]:
    return (record.payload.get("custom") or {}).get("otto_portfolio_setup") or {}


def _project_index(session: Any, rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    from .cli import _project_records
    by_run = {}
    for record in _project_records(session):
        run_id = _custom(record).get("run_id")
        if run_id:
            by_run[run_id] = record
    result = {}
    for row in rows:
        bundle = row["bundle"]
        run_id = _run_id(bundle)
        record = by_run.get(run_id)
        if record is not None:
            relation = (record.payload.get("metadata") or {}).get("otto_orchestrator") or {}
            expected = session.host.get("portfolio_ref") if session.host else None
            current_portfolio = relation.get("portfolio_ref")
            if relation and (not expected or not current_portfolio or
                             ResourceRef.from_dict(current_portfolio).id != ResourceRef.from_dict(expected).id):
                raise PermissionError("run " + run_id + " already exists outside the selected portfolio")
            retained_portfolio = _portfolio_key(record).get("portfolio_id")
            if retained_portfolio and retained_portfolio != session.host["portfolio_ref"]["id"]:
                raise PermissionError("detached run belongs to another portfolio")
        relation = (((record.payload.get("metadata") or {}).get("otto_orchestrator") or {}) if record else {})
        result[str(row["id"])] = {"row": row, "record": record, "run_id": run_id,
                                   "attached": bool(relation),
                                   "old_setup": dict(_portfolio_key(record)) if record else {}}
    return result


def _setup_rows(setup: Mapping[str, Any]) -> tuple[list[dict], list[dict], list[dict]]:
    if setup.get("schema") != SETUP_SCHEMA:
        raise ValueError("portfolio-setup.json schema must be " + SETUP_SCHEMA)
    projects = list(setup.get("projects") or ())
    if not projects or len({str(row.get("id")) for row in projects}) != len(projects):
        raise ValueError("portfolio-setup projects must be nonempty and uniquely identified")
    dependencies = []
    gates = list(setup.get("gates") or ())
    for project in projects:
        pid = project.get("id")
        if not isinstance(pid, str) or not pid:
            raise ValueError("portfolio project id is required")
        for gate in project.get("gates") or ():
            gates.append({**gate, "project": pid})
        for dep in project.get("dependencies") or ():
            dependencies.append({**dep, "project": pid})
    dependencies.extend(setup.get("dependencies") or ())
    external = list(setup.get("external_prerequisites") or ())
    return projects, gates, dependencies + [{"external_prerequisites": external}]


def _gate_specs(setup: Mapping[str, Any]) -> tuple[list[dict], list[dict], list[dict]]:
    projects = list(setup.get("projects") or ())
    gates = list(setup.get("gates") or ())
    dependencies = list(setup.get("dependencies") or ())
    external = list(setup.get("external_prerequisites") or ())
    for project in projects:
        pid = project.get("id")
        gates.extend({**gate, "project": pid} for gate in project.get("gates") or ())
        dependencies.extend({**dep, "project": pid} for dep in project.get("dependencies") or ())
        # An external entry names the gate that carries its canonical state.
        ext = project.get("external_prerequisite")
        if isinstance(ext, Mapping):
            external.append({**ext, "project": pid})
    for prerequisite in external:
        project_id = prerequisite.get("project")
        gate_id = prerequisite.get("gate") or prerequisite.get("milestone") or prerequisite.get("id")
        ident = prerequisite.get("id") or prerequisite.get("external_prerequisite")
        if project_id and gate_id and ident and not any(
                row.get("project") == project_id and row.get("id") == gate_id for row in gates):
            gates.append({"project": project_id, "id": gate_id, "title": prerequisite.get("title") or ident,
                          "owner": prerequisite.get("owner") or "portfolio orchestrator",
                          "proof": prerequisite.get("proof"), "external_prerequisite": ident})
    return gates, dependencies, external


def _gate_record(session: Any, project: Any, gate_id: str) -> Any:
    matches = [row for row in session.owner.graph.list(project=project.ref, kind="gate")
               if gate_id == row.ref.id or gate_id in row.aliases]
    if len(matches) != 1:
        raise LookupError("gate " + gate_id + " must resolve to exactly one milestone")
    return matches[0]


def _gate_fields(spec):
    external = spec.get('external_prerequisite')
    return {'portfolio_setup': {'project': spec['project'],
        'milestone': spec.get('milestone') or spec['id'], 'owner': spec['owner'], 'proof': spec['proof'],
        **({'external_prerequisite': external, 'evidence_required': True} if external else {})}}


def _ensure_gates(session: Any, index: Mapping[str, Any], gates: list[dict], *, dry_run: bool) -> list[dict]:
    result = []
    actor = session.binding.authenticated_actor(session.host["principal"])
    for spec in gates:
        project_id, gate_id = spec.get("project"), spec.get("id") or spec.get("milestone")
        if project_id not in index or not isinstance(gate_id, str) or not gate_id:
            raise ValueError("gate needs a known project and id")
        owner, proof = spec.get("owner"), spec.get("proof")
        if not isinstance(owner, str) or not owner.strip() or not isinstance(proof, str) or not proof:
            raise ValueError("gate " + gate_id + " needs an owner and proof file")
        fields = _gate_fields(spec)
        project_ref = ResourceRef.from_dict(index[project_id]["record"].ref.to_dict())
        try:
            existing = _gate_record(session, index[project_id]["record"], gate_id)
        except LookupError:
            existing = None
        if existing is not None:
            current_fields = dict(existing.payload.get("fields") or {})
            current_setup = dict(current_fields.get("portfolio_setup") or {})
            completion = current_setup.pop("completion", None)
            current_fields["portfolio_setup"] = current_setup
            if current_fields != fields:
                previous = next((g for g in index[project_id].get('old_setup', {}).get('gates', ())
                                 if g.get('id') == gate_id), None)
                if (previous is not None and current_fields == _gate_fields(previous)
                        and existing.lifecycle.value == 'pending' and completion is None):
                    if not dry_run:
                        session.owner.graph.revise(existing.ref, fields=fields, actor=actor,
                            logical_request_key='portfolio-gate-sync:' + existing.ref.id + ':' + str(existing.version))
                    result.append({'project': project_id, 'gate': gate_id,
                                   'outcome': 'would_update' if dry_run else 'updated'})
                    continue
                result.append({"project": project_id, "gate": gate_id, "outcome": "otto_edit_preserved",
                               "project_ref": project_ref.to_dict(), "gate_ref": existing.ref.to_dict(),
                               "drift": "declared owner/proof differs from retained Otto gate metadata",
                               "completion_preserved": completion})
            else:
                result.append({"project": project_id, "gate": gate_id, "outcome": "present",
                               "gate_ref": existing.ref.to_dict(), "lifecycle": existing.lifecycle.value})
            continue
        if dry_run:
            result.append({"project": project_id, "gate": gate_id, "outcome": "would_create"})
            continue
        created = session.owner.graph.create_gate(project=project_ref, alias=gate_id,
            title=spec.get("title") or gate_id, fields=fields,
            logical_request_key="portfolio-apply:gate:" + project_ref.id + ":" + gate_id, actor=actor)
        result.append({"project": project_id, "gate": gate_id, "outcome": "created",
                       "gate_ref": created.ref.to_dict(), "lifecycle": created.lifecycle.value})
    return result


def _sync_projects(session: Any, index: Mapping[str, Any], *, apply: bool) -> list[dict]:
    from .sync import sync_documents
    from .cli import _resolve_project
    rows = []
    for letter, item in index.items():
        record = item["record"]
        if record is None:
            rows.append({"project": letter, "run_id": item["run_id"], "outcome": "would_register"})
            continue
        current = _resolve_project(session, item["run_id"])
        result = sync_documents(session, current, item["row"]["bundle"], apply=apply)
        rows.append({"project": letter, "run_id": item["run_id"], **result})
    return rows


def _ensure_dependencies(session: Any, index: Mapping[str, Any], specs: list[dict], *, dry_run: bool) -> list[dict]:
    from .portfolio import dependency_service
    actor = session.binding.authenticated_actor(session.host["principal"])
    dependencies = dependency_service(session, type("Args", (), {"portfolio": session.host["portfolio_ref"]["id"],
                                                                    "owner_authorized": False})())
    result = []
    requested_by_project = {}
    for spec in specs:
        dependent, upstream, gate = spec.get("project"), spec.get("on"), spec.get("gate")
        if dependent not in index or upstream not in index or not gate:
            raise ValueError("project dependency requires project, on, and milestone gate")
        requested_by_project.setdefault(dependent, set()).add((upstream, gate))
        down_record, up_record = index[dependent]["record"], index[upstream]["record"]
        if down_record is None or up_record is None:
            result.append({"project": dependent, "on": upstream, "gate": gate, "outcome": "would_link"})
            continue
        dependencies.authorize(down_record.ref)
        try:
            prerequisite = dependencies.resolve_prerequisite(up_record.ref, gate)
        except ValueError:
            if not dry_run:
                raise
            result.append({"project": dependent, "on": upstream, "gate": gate, "outcome": "would_link"})
            continue
        key = "portfolio-apply:dependency:" + down_record.ref.id + ":" + prerequisite.id
        existing = any(ResourceRef.from_dict(ref).id == prerequisite.id
                       for ref in down_record.payload.get("dependencies") or ())
        if existing:
            result.append({"project": dependent, "on": upstream, "gate": gate, "outcome": "present",
                           "dependency_ref": prerequisite.to_dict()})
        elif (session.store.consumer().get_receipt(key) is not None and
              {"on": upstream, "gate": gate} in index[dependent].get("old_setup", {}).get("dependencies", ())):
            result.append({"project": dependent, "on": upstream, "gate": gate,
                           "outcome": "otto_edit_preserved", "dependency_ref": prerequisite.to_dict()})
        elif dry_run:
            result.append({"project": dependent, "on": upstream, "gate": gate, "outcome": "would_link",
                           "dependency_ref": prerequisite.to_dict()})
        else:
            if session.store.consumer().get_receipt(key) is not None:
                key += ':readd:' + str(down_record.version)
            receipt = dependencies.change(down_record.ref, prerequisite, request_id=key)
            result.append({"project": dependent, "on": upstream, "gate": gate, **receipt})
    # Remove only links explicitly recorded by this apply integration in the
    # previous manifest snapshot. Hand-authored Otto edges remain untouched.
    for dependent, item in index.items():
        old = item.get("old_setup", {}).get("dependencies") or ()
        for previous in old:
            upstream, gate = previous.get("on"), previous.get("gate")
            if not upstream or not gate or (upstream, gate) in requested_by_project.get(dependent, set()):
                continue
            down_record = item.get("record")
            up_record = index.get(upstream, {}).get("record")
            if down_record is None or up_record is None:
                result.append({"project": dependent, "on": upstream, "gate": gate,
                               "outcome": "managed_edge_removal_unavailable"})
                continue
            try:
                prerequisite = dependencies.resolve_prerequisite(up_record.ref, gate)
            except Exception:
                result.append({"project": dependent, "on": upstream, "gate": gate,
                               "outcome": "managed_edge_removal_unavailable"})
                continue
            if any(ResourceRef.from_dict(ref).id == prerequisite.id
                   for ref in down_record.payload.get("dependencies") or ()):
                key = "portfolio-apply:dependency-remove:" + down_record.ref.id + ":" + prerequisite.id + ":" + str(down_record.version)
                removed = ({"outcome": "would_remove"} if dry_run else
                           dependencies.change(down_record.ref, prerequisite, request_id=key, remove=True))
                result.append({"project": dependent, "on": upstream, "gate": gate, **removed})
    return result


def _readiness(session: Any, index: Mapping[str, Any], *, observe: bool) -> list[dict]:
    from .portfolio import dependency_service
    from .cli import _resolve_project
    args = type("Args", (), {"portfolio": session.host["portfolio_ref"]["id"], "owner_authorized": False})()
    service = dependency_service(session, args)
    return [{"project": letter, "run_id": item["run_id"],
             **service.readiness(_resolve_project(session, item["run_id"]).ref, observe=observe)}
            for letter, item in index.items() if item["record"] is not None]


def apply_portfolio(session: Any, portfolio_ref: Any, payload: Mapping[str, Any], *,
                    dry_run: bool = False, import_history: bool = False) -> dict[str, Any]:
    from .cli import _resolve_project
    from .register import import_history as register_history, plan, register
    from .portfolio import dependency_service
    from otto.portfolio.shared_documents import sync_portfolio_documents
    setup = payload["setup"]
    _setup_rows(setup)  # Validate before any durable operation.
    projects = list(setup.get("projects") or ())
    gates, dependencies, external = _gate_specs(setup)
    data_rows = {str(row["id"]): row for row in payload.get("projects") or ()}
    declared = {str(row["id"]): row for row in projects}
    if set(data_rows) != set(declared):
        raise ValueError("portfolio source folders and portfolio-setup project IDs differ")
    for letter, row in declared.items():
        if row.get("folder") and row["folder"] != data_rows[letter]["folder"]:
            raise ValueError("portfolio project folder mismatch for " + letter)
        if row.get("run_id") and row["run_id"] != _run_id(data_rows[letter]["bundle"]):
            raise ValueError("portfolio project run_id mismatch for " + letter)
    for gate in gates:
        pid, gid = gate.get("project"), gate.get("id") or gate.get("milestone")
        if pid not in declared or not isinstance(gid, str) or not gid:
            raise ValueError("every gate needs a known project and milestone id")
        if not isinstance(gate.get("owner"), str) or not gate.get("owner", "").strip():
            raise ValueError("gate " + gid + " needs an owner")
        if not isinstance(gate.get("proof"), str) or not gate.get("proof"):
            raise ValueError("gate " + gid + " needs a planned proof path")
        proof = gate['proof']
        bundle = data_rows[pid]['bundle']
        prefix = 'projects/' + data_rows[pid]['folder'] + '/'
        if proof not in payload['shared_bundle']['files'] and proof.removeprefix(prefix) not in bundle['files']:
            raise ValueError('missing declared gate proof file: ' + proof)
    gate_keys = {(g['project'], g['id']) for g in gates}
    if len(gate_keys) != len(gates):
        raise ValueError('duplicate gate declaration')
    edges = {pid: set() for pid in declared}
    for dep in dependencies:
        if dep.get('project') not in declared or (dep.get('on'), dep.get('gate')) not in gate_keys:
            raise ValueError('dependency names an undeclared project or milestone')
        edges[dep['project']].add(dep['on'])
    visiting, visited = set(), set()
    def visit(pid):
        if pid in visiting:
            raise ValueError('project activation dependency cycle')
        if pid in visited:
            return
        visiting.add(pid)
        for upstream in edges[pid]:
            visit(upstream)
        visiting.remove(pid)
        visited.add(pid)
    for pid in declared:
        visit(pid)
    index = _project_index(session, list(data_rows.values()))
    from otto.agents.host_profiles import profile as model_profile
    profile = model_profile(session.host["model_profile"])
    planned, registrations = [], {}
    actor = session.host_principal()
    for letter, item in index.items():
        bundle = item["row"]["bundle"]
        computed = plan(bundle, profile=profile, manager_principal=item["run_id"] + "-manager",
                        worktree=_worktree(bundle), tool_entrypoint=str(Path(session.config["home"]) / "bin" / "ottoctl"))
        computed["custom"]["otto_portfolio_setup"] = {"project_id": letter,
            "portfolio_id": str(portfolio_ref.id), "manifest_schema": setup.get("schema"),
            "gates": [g for g in gates if g['project'] == letter],
            "dependencies": [{"on": dep.get("on"), "gate": dep.get("gate")}
                             for dep in dependencies if dep.get('project') == letter]}
        registrations[letter] = computed
        record = item["record"]
        planned.append({"project": letter, "run_id": item["run_id"],
                        "outcome": "already_registered" if record else "would_register",
                        "project_ref": None if record is None else record.ref.to_dict(),
                        "document_count": len(bundle["files"]), "task_count": len(bundle["tasks"]),
                        "role_profile": computed["configuration"]["model_profile"]})
    if dry_run:
        docs = sync_portfolio_documents(session, portfolio_ref, payload["shared_bundle"], apply=False)
        project_sync = _sync_projects(session, index, apply=False)
        gate_rows = _ensure_gates(session, index, gates, dry_run=True) if all(
            item["record"] is not None for item in index.values()) else [
                {"project": gate.get("project"), "gate": gate.get("id"), "outcome": "would_create"} for gate in gates]
        dep_rows = _ensure_dependencies(session, index, dependencies, dry_run=True)
        return {"outcome": "plan", "portfolio_ref": portfolio_ref.to_dict(), "projects": planned,
                "project_sync": project_sync, "shared_documents": docs, "gates": gate_rows,
                "dependencies": dep_rows, "readiness": _readiness(session, index, observe=False),
                "external_prerequisites": external, "writes": False, "provider_called": False}

    shared_preview = sync_portfolio_documents(session, portfolio_ref, payload["shared_bundle"], apply=False)
    project_preview = _sync_projects(session, index, apply=False)
    conflicts = ["shared:" + path for path in shared_preview.get("not_overwritten", ())]
    conflicts.extend(item["run_id"] + ":" + path for item in project_preview
                     for path in item.get("not_overwritten", ()))
    if conflicts:
        return {"outcome": "held", "reason": "source differs from Otto-owned documents; review and reconcile before apply",
                "conflicts": conflicts, "portfolio_ref": portfolio_ref.to_dict(), "writes": False,
                "provider_called": False}

    for letter, item in index.items():
        bundle = item["row"]["bundle"]
        current = item["record"]
        key = "portfolio-apply:" + str(portfolio_ref.id) + ":" + letter + ":v1"
        if current is not None and not item.get("attached"):
            key += ":reattach:" + str(current.version)
        registration = registrations[letter]
        if current is not None:
            # Advance the managed manifest baseline only after its graph changes
            # succeed, so a held apply retains the previous comparison point.
            registration = {**registration, 'custom': {**registration['custom'],
                'otto_portfolio_setup': item.get('old_setup', {})}}
        receipt = register(session, registration, key=key)
        item["record"] = _resolve_project(session, item["run_id"])
        planned_row = next(row for row in planned if row["project"] == letter)
        planned_row.update(outcome=receipt.get("outcome"), project_ref=receipt.get("project_ref"), receipt=receipt)
    if import_history and payload.get("history"):
        history_bundle = payload["history"]
        run_id = _run_id(history_bundle)
        history_plan = plan(history_bundle, profile=profile, manager_principal=run_id + "-manager",
            worktree=str(Path(history_bundle.get("root") or payload.get("history_root")).resolve().parent),
            tool_entrypoint=str(Path(session.config["home"]) / "bin" / "ottoctl"))
        register_history(session, history_plan, note="Closed timeline-platform-r3 history; Phase 2 port moved to Codex.")
    project_sync = _sync_projects(session, index, apply=True)
    if any(row.get('outcome') not in {'synced', 'in_sync'} for row in project_sync):
        return {'outcome': 'held', 'project_sync': project_sync, 'provider_called': False,
                'reason': 'project document sync did not finish; inspect retained receipts before continuing'}
    shared = sync_portfolio_documents(session, portfolio_ref, payload["shared_bundle"], apply=True)
    gate_rows = _ensure_gates(session, index, gates, dry_run=False)
    dep_rows = _ensure_dependencies(session, index, dependencies, dry_run=False)
    from .register import _check_in
    for letter, item in index.items():
        current = _resolve_project(session, item['run_id'])
        desired = registrations[letter]['custom']['otto_portfolio_setup']
        if _portfolio_key(current) != desired and not any(
                row.get('outcome') in {'otto_edit_preserved', 'managed_edge_removal_unavailable'}
                for row in gate_rows + dep_rows if row.get('project') == letter):
            _check_in(session, current.ref.to_dict(), actor,
                'portfolio-manifest:' + current.ref.id + ':' + str(current.version),
                lambda draft, desired=desired: draft.update(custom={**(draft.get('custom') or {}),
                                                                    'otto_portfolio_setup': desired}))
    changed = (any(row.get("outcome") in {"created", "synced", "linked", "would_register"} for row in planned)
               or any(row.get("outcome") == "synced" for row in project_sync)
               or shared.get("outcome") == "synced"
               or any(row.get("outcome") in {"created", "updated"} for row in gate_rows)
               or any(row.get("outcome") in {"linked", "removed"} for row in dep_rows))
    drift = [row for row in gate_rows + dep_rows if row.get('outcome') in
             {'otto_edit_preserved', 'managed_edge_removal_unavailable'}]
    return {"outcome": "held" if drift else "applied" if changed else "in_sync", "drift": drift,
            "portfolio_ref": portfolio_ref.to_dict(), "projects": planned,
            "project_sync": project_sync, "shared_documents": shared, "gates": gate_rows,
            "dependencies": dep_rows, "readiness": _readiness(session, index, observe=False),
            "external_prerequisites": external, "writes": True, "provider_called": False}


def complete_gate(session: Any, portfolio_ref: Any, *, project: str, gate: str, evidence: str,
                  external_prerequisite: str | None = None) -> dict[str, Any]:
    from .cli import _resolve_project
    from .portfolio import dependency_service
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("gate completion requires non-empty --evidence")
    args = type("Args", (), {"portfolio": portfolio_ref.id, "owner_authorized": False})()
    dependencies = dependency_service(session, args)
    try:
        record = _resolve_project(session, project)
    except LookupError:
        matches = [item for item in session.owner.graph.list(kind="work.project")
                   if _portfolio_key(item).get("project_id") == project and
                   _portfolio_key(item).get("portfolio_id") == str(portfolio_ref.id)]
        if len(matches) != 1:
            raise LookupError("no unique portfolio project " + project)
        record = matches[0]
    dependencies.authorize(record.ref)
    milestone = _gate_record(session, record, gate)
    fields = dict(milestone.payload.get("fields") or {})
    setup = dict(fields.get("portfolio_setup") or {})
    if external_prerequisite and setup.get("external_prerequisite") != external_prerequisite:
        raise PermissionError("the requested external prerequisite does not own this gate")
    if external_prerequisite is None and setup.get("external_prerequisite"):
        raise PermissionError("complete this external prerequisite with `portfolio prerequisite complete`")
    lifecycle = getattr(milestone.lifecycle, "value", milestone.lifecycle)
    completion = setup.get("completion")
    if lifecycle == "completed":
        if completion and completion.get("evidence") == evidence:
            return {"outcome": "already_completed", "gate_ref": milestone.ref.to_dict(),
                    "completion": completion, "provider_called": False}
        raise ValueError("gate is already completed; Otto's evidence is retained")
    setup["completion"] = {"actor": dependencies.actor.actor, "evidence": evidence.strip(),
                           "completed_at": datetime.now(timezone.utc).isoformat()}
    fields["portfolio_setup"] = setup
    key = "portfolio-gate-complete:" + milestone.ref.id + ":" + hashlib.sha256(evidence.encode()).hexdigest()[:16]
    updated = session.owner.graph.revise(milestone.ref, fields=fields, lifecycle="completed",
        logical_request_key=key, actor=dependencies.actor)
    readiness = dependencies.readiness(record.ref)
    return {"outcome": "completed", "project_ref": record.ref.to_dict(), "gate_ref": updated.ref.to_dict(),
            "completion": setup["completion"], "readiness": readiness, "provider_called": False}
