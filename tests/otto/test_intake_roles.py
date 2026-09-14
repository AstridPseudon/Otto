"""OTT-03 public-operation tests with a disposable canonical work port."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from otto.portfolio import HerzchenBindingConfig, HerzchenWorkOperations, OttoPortfolio, PortfolioError
from otto.portfolio.cli import main as portfolio_cli


def _copy(value):
    return json.loads(json.dumps(value, sort_keys=True))


class DisposableCanonicalWork:
    """Small public-port fixture; no Otto/private DB or raw SQL is used."""

    def __init__(self):
        self.projects = {}
        self.requests = {}
        self.attention = []
        self.calls = []
        self.open_by_actor = {}

    def _ref(self, project_id):
        return {"authority": "fixture-work", "kind": "work.project", "id": project_id, "revision": "rev-1"}

    def _receipt(self, request_id, operation):
        return {"authority": "fixture-work", "kind": "work.receipt", "id": f"receipt-{request_id}", "operation": operation}

    def _remember(self, operation, payload, request_id, actor, result):
        key = json.dumps([operation, payload], sort_keys=True)
        self.requests[request_id] = {"key": key, "actor": actor, "result": _copy(result)}
        self.calls.append((operation, request_id))
        return result

    def execute(self, operation, payload, *, request_id, actor):
        existing = self.requests.get(request_id)
        key = json.dumps([operation, payload], sort_keys=True)
        if existing:
            if existing["key"] != key or existing["actor"] != actor:
                return {"outcome": "error", "error": {"code": "request_reuse_conflict", "message": "request inputs changed"}}
            return _copy(existing["result"] | {"replayed": True})

        if operation == "work.pending.create":
            if payload["open"] and actor in self.open_by_actor:
                return self._remember(operation, payload, request_id, actor, {
                    "outcome": "occupied", "open": {"status": "occupied", "holder": self.open_by_actor[actor]},
                    "project_ref": None, "receipt": self._receipt(request_id, operation),
                })
            project_id = "project-" + hashlib.sha256(request_id.encode()).hexdigest()[:12]
            ref = self._ref(project_id)
            project = {
                "project_ref": ref,
                "state": "pending",
                "title": payload["edit"].get("title", "Untitled project"),
                "outcome": payload["edit"].get("outcome", ""),
                "manager": None,
                "parent": None,
                "executor": [],
                "allowance": None,
                "sessions": [],
                "accepted_results": [],
                "tasks": [],
                "template": payload["template"],
                "fields": payload["edit"],
                "unknown_fields": {k: v for k, v in payload["edit"].items() if k not in {"title", "outcome"}},
            }
            self.projects[project_id] = project
            status = "not_requested"
            if payload["open"]:
                self.open_by_actor[actor] = project_id
                status = "opened"
            result = {"outcome": "created", "project_ref": ref, "receipt": self._receipt(request_id, operation),
                      "open": {"status": status}, "executable": False, "project": project}
            return self._remember(operation, payload, request_id, actor, result)

        project_id = payload.get("project_ref", {}).get("id")
        project = self.projects.get(project_id)
        if project is None:
            return self._remember(operation, payload, request_id, actor, {"outcome": "error", "error": {"code": "not_found"}})

        if operation == "work.pending.edit":
            project["fields"].update(payload["edit"])
            project["unknown_fields"].update(payload["edit"])
            project["title"] = project["fields"].get("title", project["title"])
            project["outcome"] = project["fields"].get("outcome", project["outcome"])
            result = {"outcome": "edited", "project_ref": project["project_ref"], "receipt": self._receipt(request_id, operation), "project": project}
        elif operation == "work.pending.open":
            if actor in self.open_by_actor and self.open_by_actor[actor] != project_id:
                result = {"outcome": "occupied", "project_ref": project["project_ref"], "open": {"status": "occupied", "holder": self.open_by_actor[actor]}}
            else:
                self.open_by_actor[actor] = project_id
                result = {"outcome": "opened", "project_ref": project["project_ref"], "open": {"status": "opened"}, "project": project}
        elif operation in {"work.pending.revisit", "work.pending.prerequisite-satisfied"}:
            item = {"project_ref": project["project_ref"], "operation": operation, "payload": payload, "attention_id": f"attention-{len(self.attention) + 1}"}
            self.attention.append(item)
            result = {"outcome": "attention-created", "project_ref": project["project_ref"], "attention": item,
                      "readiness": {"status": "attention", "dispatch": False}, "executable": False}
        elif operation == "work.pending.admission":
            project["admission"] = {"choice": payload["choice"], "frame": payload["frame"]}
            if payload.get("roles"):
                project.update(payload["roles"])
            project["state"] = "active" if payload["choice"] in {"admit", "investigate"} else payload["choice"] + "ed"
            result = {"outcome": "admitted", "project_ref": project["project_ref"], "admission": project["admission"],
                      "roles": payload.get("roles"), "executable": payload["choice"] in {"admit", "investigate"}}
        elif operation == "work.responsibility.assign":
            project.update(payload["roles"])
            result = {"outcome": "assigned", "project_ref": project["project_ref"], "roles": payload["roles"], "executable": False}
        elif operation == "work.responsibility.handoff":
            if project.get("manager") != payload["from_manager"]:
                return self._remember(operation, payload, request_id, actor, {"outcome": "error", "error": {"code": "stale_manager"}})
            project["manager"] = payload["to_manager"]
            project["handoff"] = {k: payload[k] for k in ("evidence_refs", "consumption_refs", "parent_obligation")}
            result = {"outcome": "handed-off", "project_ref": project["project_ref"], "safe_handoff": True, "project": project}
        else:
            return self._remember(operation, payload, request_id, actor, {"outcome": "error", "error": {"code": "unsupported"}})
        return self._remember(operation, payload, request_id, actor, result)

    def read(self, operation, payload, *, actor):
        if operation == "work.pending.list":
            return {"outcome": "read", "projects": [_copy(p) for p in self.projects.values() if p["state"] in {"pending", "active", "investigated"}]}
        project = self.projects.get(payload["project_ref"]["id"])
        return {"outcome": "read", "project": _copy(project) if project else None}


@pytest.fixture
def portfolio():
    canonical = DisposableCanonicalWork()
    return OttoPortfolio(canonical), canonical


def create(api, *, request_id="create-1", actor="curator", open_project=False, edit=None, template=None):
    return api.create_pending(actor=actor, request_id=request_id, edit=edit, template=template, open_project=open_project)


def test_blank_and_create_and_open_preserve_sparse_unknown_fields_and_stay_inert(portfolio):
    api, canonical = portfolio
    created = create(api, request_id="blank-1", open_project=True, edit={"title": "Rough idea", "custom_unknown": {"keep": [1, 2]}})
    assert created["outcome"] == "created"
    assert created["open"]["status"] == "opened"
    assert created["executable"] is False
    assert created["project"]["state"] == "pending"
    assert created["project"]["manager"] is None
    assert created["project"]["tasks"] == []
    ref = created["project_ref"]
    fresh_api = OttoPortfolio(canonical)
    observed = fresh_api.read_pending(ref, actor="curator")
    assert observed["project"]["unknown_fields"]["custom_unknown"] == {"keep": [1, 2]}
    assert len(canonical.projects) == 1
    assert [call[0] for call in canonical.calls] == ["work.pending.create"]


def test_invalid_or_protected_edit_rejects_before_canonical_call(portfolio):
    api, canonical = portfolio
    with pytest.raises(PortfolioError):
        create(api, edit={"manager": "invented-manager"})
    with pytest.raises(PortfolioError):
        create(api, edit="malformed")
    with pytest.raises(PortfolioError):
        create(api, template={"id": object()})
    assert canonical.calls == []
    assert canonical.projects == {}


def test_same_request_replays_and_changed_request_has_no_partial_delta(portfolio):
    api, canonical = portfolio
    first = create(api, request_id="replay-1", edit={"title": "One"})
    replay = create(api, request_id="replay-1", edit={"title": "One"})
    changed = create(api, request_id="replay-1", edit={"title": "Changed"})
    assert replay["replayed"] is True
    assert replay["project_ref"] == first["project_ref"]
    assert changed["error"]["code"] == "request_reuse_conflict"
    assert len(canonical.projects) == 1
    assert canonical.projects[first["project_ref"]["id"]]["title"] == "One"


def test_occupied_create_does_not_hide_a_second_project_and_reopen_keeps_id(portfolio):
    api, canonical = portfolio
    first = create(api, request_id="open-1", actor="same-manager", open_project=True)
    occupied = create(api, request_id="open-2", actor="same-manager", open_project=True)
    reopened = api.reopen(first["project_ref"], actor="other-editor", request_id="reopen-1")
    assert occupied["outcome"] == "occupied"
    assert occupied["project_ref"] is None
    assert reopened["open"]["status"] == "opened"
    assert reopened["project_ref"] == first["project_ref"]
    assert len(canonical.projects) == 1


def test_revisit_and_satisfied_prerequisite_create_attention_only(portfolio):
    api, canonical = portfolio
    created = create(api, request_id="attention-project")
    ref = created["project_ref"]
    revisit = api.revisit(ref, {"after_receipt": "receipt-7", "purpose": "reconsider"}, actor="curator", request_id="attention-1")
    prerequisite = api.satisfied_prerequisite(ref, {"id": "dependency-1"}, actor="curator", request_id="attention-2")
    assert revisit["outcome"] == "attention-created"
    assert prerequisite["readiness"]["dispatch"] is False
    assert prerequisite["executable"] is False
    assert canonical.projects[ref["id"]]["state"] == "pending"
    assert canonical.projects[ref["id"]]["manager"] is None
    assert len(canonical.attention) == 2


def test_admission_is_separate_and_binds_parent_manager_executor(portfolio):
    api, canonical = portfolio
    ref = create(api, request_id="admission-project")["project_ref"]
    frame = {"outcome": "investigate feasibility", "recipient": "parent-owner", "route": "normal", "authority": "manager-mandate-1"}
    roles = {"parent": {"id": "parent-1"}, "manager": "manager-1", "executor": "executor-1", "profile": "otto.ast-manager"}
    admitted = api.admit(ref, choice="investigate", frame=frame, roles=roles, actor="manager-1", request_id="admit-1")
    assert admitted["outcome"] == "admitted"
    assert admitted["executable"] is True
    assert canonical.projects[ref["id"]]["parent"] == {"id": "parent-1"}
    assert canonical.projects[ref["id"]]["manager"] == "manager-1"
    assert canonical.projects[ref["id"]]["executor"] == ["executor-1"]
    with pytest.raises(PortfolioError):
        api.admit(ref, choice="automatic", frame=frame, actor="manager-1", request_id="bad-choice")


def test_roles_are_bounded_and_handoff_preserves_evidence_consumption_and_parent(portfolio):
    api, canonical = portfolio
    ref = create(api, request_id="handoff-project")["project_ref"]
    assigned = api.assign_roles(ref, {"parent": {"id": "parent-2"}, "manager": "manager-old", "executor": ["exec-a", "exec-b"]}, actor="parent-owner", request_id="roles-1")
    handed = api.handoff(ref, from_manager="manager-old", to_manager="manager-new",
                         evidence_refs=[{"id": "evidence-1"}], consumption_refs=[{"id": "allowance-ref-1"}],
                         parent_obligation={"id": "parent-2"}, actor="parent-owner", request_id="handoff-1")
    assert assigned["roles"]["executor"] == ["exec-a", "exec-b"]
    assert handed["safe_handoff"] is True
    assert canonical.projects[ref["id"]]["manager"] == "manager-new"
    assert canonical.projects[ref["id"]]["handoff"]["evidence_refs"] == [{"id": "evidence-1"}]
    assert canonical.projects[ref["id"]]["handoff"]["consumption_refs"] == [{"id": "allowance-ref-1"}]
    with pytest.raises(PortfolioError):
        api.assign_roles(ref, {"parent": {"id": "parent-2"}, "manager": "m", "executor": []}, actor="x", request_id="bad-roles")


def test_explicit_template_and_unavailable_binding_are_truthful(portfolio):
    api, canonical = portfolio
    created = create(api, request_id="template-1", template="investigation", edit={"why_pending": "await evidence"})
    assert created["project"]["template"] == "investigation"
    assert created["project"]["state"] == "pending"
    unavailable = OttoPortfolio()
    result = create(unavailable, request_id="no-binding")
    assert result["outcome"] == "unavailable"
    assert result["error"]["code"] == "canonical_work_port_unavailable"


def test_shipped_help_and_cli_diagnose_missing_host_binding(capsys):
    help_result = OttoPortfolio.help()
    assert "create_and_open" in help_result["operations"]
    assert "admit" in help_result["operations"]
    assert portfolio_cli(["help"]) == 0
    assert "canonical" in capsys.readouterr().out
    assert portfolio_cli(["create-pending", "--actor", "manager", "--request-id", "cli-1"]) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["error"]["code"] == "canonical_work_port_unavailable"


def _real_portfolio(tmp_path):
    """Build the accepted public Store/WorkGraph path for one disposable file."""

    from herzchen.domains.work import WorkGraph, register_work
    from herzchen.kernel.store import Store
    from herzchen.contracts import AuthenticatedActor

    path = tmp_path / "ott03-work.sqlite"
    store = Store.create(path, authority="ott03-test-authority")
    register_work(store)
    authenticated = AuthenticatedActor("ott03-test-authority", "manager", "ott03-test-credential")
    graph = WorkGraph(store, actor=authenticated)
    binding = HerzchenBindingConfig("ott03-test-authority", "ott03-test-credential")
    port = graph.command_port
    reader = graph.reader
    api = OttoPortfolio(HerzchenWorkOperations(port=port, reader=reader, binding=binding))
    return store, graph, api, path


def _public_counts(store, request_id, ref=None):
    from herzchen.contracts import ResourceRef

    receipt = store.get_receipt(request_id)
    identity = store.get_identity(ResourceRef.from_dict(ref)) if ref is not None else None
    return {
        "events": len(list(store.list_events())),
        "receipt": receipt.to_dict() if receipt is not None else None,
        "identity_present": identity is not None,
    }


def test_real_workgraph_create_read_reopen_and_replay_are_durable(tmp_path):
    from herzchen.domains.work import WorkGraph, contributions
    from herzchen.kernel.store import Store
    from herzchen.contracts import AuthenticatedActor

    store, graph, api, path = _real_portfolio(tmp_path)
    finite = api.operations
    assert finite.port is graph.command_port
    assert finite.reader is graph.reader
    assert "store" not in vars(finite) and "graph" not in vars(finite)
    first = api.create_pending(
        actor="manager",
        request_id="real-create-1",
        edit={"title": "Canonical idea", "outcome": "evidence", "why_pending": "await review", "unknown_field": {"keep": [1, 2]}},
    )
    assert first["outcome"] == "created"
    assert first["replayed"] is False
    assert first["event_ids"] == first["receipt"]["event_ids"]
    assert first["record"]["payload"]["lifecycle"] == "pending"
    assert first["record"]["payload"]["readiness"]["dispatch"] is False
    assert first["record"]["payload"]["metadata"]["unknown_field"] == {"keep": [1, 2]}
    assert first["record"]["payload"]["metadata"]["otto_request"]["logical_request_key"] == "real-create-1"
    ref = first["project_ref"]
    before = _public_counts(store, "real-create-1", ref)

    replay = api.create_pending(
        actor="manager",
        request_id="real-create-1",
        edit={"title": "Canonical idea", "outcome": "evidence", "why_pending": "await review", "unknown_field": {"keep": [1, 2]}},
    )
    after_replay = _public_counts(store, "real-create-1", ref)
    assert replay["outcome"] == "replayed"
    assert replay["project_ref"] == ref
    assert after_replay["events"] == before["events"]
    assert after_replay["receipt"] == before["receipt"]

    changed = api.create_pending(
        actor="manager",
        request_id="real-create-1",
        edit={"title": "Changed logical payload"},
    )
    after_conflict = _public_counts(store, "real-create-1", ref)
    assert changed["error"]["code"] == "replay_conflict"
    assert after_conflict == before

    store.close()
    reopened = Store.open(
        path,
        authority="ott03-test-authority",
        expected_domains=tuple(sorted(contributions(), key=lambda descriptor: descriptor.domain_id)),
    )
    reopened_graph = WorkGraph(reopened, actor=AuthenticatedActor("ott03-test-authority", "manager", "ott03-test-credential"))
    reopened_api = OttoPortfolio(HerzchenWorkOperations(
        port=reopened_graph.command_port,
        reader=reopened_graph.reader,
        binding=HerzchenBindingConfig("ott03-test-authority", "ott03-test-credential"),
    ))
    observed = reopened_api.read_pending(ref, actor="manager")
    assert observed["outcome"] == "read"
    assert observed["project_ref"] == ref
    assert observed["record"]["payload"]["metadata"]["unknown_field"] == {"keep": [1, 2]}
    assert observed["record"]["payload"]["lifecycle"] == "pending"
    reopened.close()


def test_real_binding_rejects_protected_or_malformed_edit_before_store_mutation(tmp_path):
    store, _graph, api, _path = _real_portfolio(tmp_path)
    with pytest.raises(PortfolioError):
        api.create_pending(actor="manager", request_id="real-invalid-1", edit={"manager": "forged"})
    with pytest.raises(PortfolioError):
        api.create_pending(actor="manager", request_id="real-invalid-2", edit="not-an-object")
    assert list(store.list_events()) == []
    assert store.get_receipt("real-invalid-1") is None
    assert store.get_receipt("real-invalid-2") is None
    store.close()


def test_real_finite_port_revise_and_truthful_open_admission_assignment_gaps(tmp_path):
    store, _graph, api, _path = _real_portfolio(tmp_path)
    created = api.create_pending(actor="manager", request_id="real-edit-create", edit={"title": "Before"})
    ref = created["project_ref"]
    edited = api.edit_pending(
        ref,
        {"title": "After", "documents": [{"id": "doc-1"}], "unknown_edit": {"keep": True}},
        actor="manager",
        request_id="real-edit-1",
    )
    assert edited["outcome"] == "edited"
    assert edited["record"]["payload"]["title"] == "After"
    assert edited["record"]["payload"]["fields"]["documents"] == [{"id": "doc-1"}]
    assert edited["record"]["payload"]["fields"]["unknown_edit"] == {"keep": True}

    opened = api.create_and_open(actor="manager", request_id="real-open-1", edit={"title": "No host"})
    assert opened["outcome"] == "unavailable"
    assert opened["error"]["code"] == "canonical_open_endpoint_unavailable"
    assert opened["receipt"] is None
    assert opened["event_ids"] == []

    frame = {"outcome": "admit", "recipient": "owner", "route": "normal", "authority": "manager"}
    admission = api.admit(ref, choice="admit", frame=frame, actor="manager", request_id="real-admit-gap")
    assignment = api.assign_roles(ref, {"parent": {"id": "p"}, "manager": "m", "executor": "e"}, actor="manager", request_id="real-assignment-gap")
    assert admission["outcome"] == "unavailable"
    assert assignment["outcome"] == "unavailable"
    assert admission["error"]["code"] == "canonical_operation_unavailable"
    assert assignment["error"]["code"] == "canonical_operation_unavailable"
    assert admission["receipt"] is None and assignment["receipt"] is None
    assert len(list(store.list_events())) == 2
    store.close()
