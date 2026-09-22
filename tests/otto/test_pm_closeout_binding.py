"""Otto transport coverage for the bounded PM closeout port."""

from pathlib import Path

from herzchen.contracts import AuthenticatedActor
from herzchen.content import domain_contribution
from herzchen.domains.work import register_work
from herzchen.kernel import Store
from otto.portfolio import HerzchenBindingConfig, OttoPortfolio, PortfolioOwnerBootstrap


def test_owner_binding_forwards_pm_closeout_fields_without_root_impersonation(tmp_path: Path):
    from herzchen.authoring import register_authoring

    authority = "otto-pm-closeout-owner"
    store = Store.create(tmp_path / "pm-closeout-binding.sqlite", authority=authority)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    owner = PortfolioOwnerBootstrap(
        store,
        binding=HerzchenBindingConfig(authority, "credential"),
        owner_actor="owner",
    )
    api = OttoPortfolio(owner.consumer_operations())
    created = api.create_pending(actor="owner", request_id="project", edit={"title": "PM closeout"})
    project = owner.graph.get(created["project_ref"])
    project = owner.sheet.apply(project, {"tasks": [{"id": "pm01", "title": "PM01"}]}, logical_request_key="tasks", actor=owner.owner_actor).project
    task = owner.graph.list(project=project)[0]
    manager = owner.assignments.assign(project.ref, role="manager", principal="owner", logical_request_key="manager", actor=owner.owner_actor)
    owner.assignments.complete(
        task.ref,
        project=project.ref,
        assignment=manager.ref,
        expected_generation=1,
        expected_project_revision=project.ref.revision,
        expected_task_revision=task.ref.revision,
        disposition="completed",
        evidence_refs=(project.ref,),
        evidence_hashes=["pm01-evidence"],
        gate_refs=(project.ref,),
        logical_request_key="pm01-complete",
        actor=owner.owner_actor,
    )
    task = owner.graph.get(task.ref)
    project = owner.graph.get(project.ref)
    operations = owner.consumer_operations()
    result = operations.execute(
        "work.lifecycle.transition",
        {
            "project_ref": project.ref.to_dict(),
            "action": "pm-bind-existing",
            "expected_project_revision": project.ref.revision,
            "expected_project_version": project.version,
            "generation": 1,
            "manager_assignment": manager.ref.to_dict(),
            "orchestrator_principal": "01a09c66-a6df-7140-a7b4-63dad5082d45",
            "task_refs": [task.ref.to_dict()],
            "owner_attribution": {"orchestrator": {"principal": "01a09c66-a6df-7140-a7b4-63dad5082d45"}},
            "schedule_observation": {"ignored": True},
            "effect_packet": {"ignored": True},
            "settlement": {"ignored": True},
        },
        request_id="otto-project-management-followup-20260922:closeout:20260922T0642Z-v1:bind-existing-root",
        actor="owner",
    )
    assert result["outcome"] == "transitioned"
    assert result["read"]["lifecycle"] == "pending"
    assert result["attribution_digest"]
    assert owner.lifecycle.delegation_issuer == AuthenticatedActor(authority, "owner", "credential")
    store.close()
