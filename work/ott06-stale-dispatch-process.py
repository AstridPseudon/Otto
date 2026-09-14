from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from herzchen.authoring import register_authoring
from herzchen.content import domain_contribution
from herzchen.contracts import DomainContribution
from herzchen.domains.work import register_work
from herzchen.kernel.store import Store
from otto.portfolio import HerzchenBindingConfig, PortfolioOwnerBootstrap


def bootstrap(path: Path, authority: str):
    store = Store.create(path, authority=authority)
    register_work(store)
    store.register_domain_handler((domain_contribution(),))
    register_authoring(store)
    owner = PortfolioOwnerBootstrap(
        store,
        binding=HerzchenBindingConfig(authority, authority + "-credential"),
        owner_actor="manager",
    )
    return store, owner, owner.consumer_operations()


def child(path: Path) -> dict[str, object]:
    manager_ref = json.loads(path.with_suffix(".manager.json").read_text())
    domains = tuple(DomainContribution.from_dict(item) for item in json.loads(path.with_suffix(".domains.json").read_text()))
    store = Store.open(path, authority="ott06-process", expected_domains=domains)
    owner = PortfolioOwnerBootstrap(
        store,
        binding=HerzchenBindingConfig("ott06-process", "ott06-process-credential"),
        owner_actor="manager",
    )
    operations = owner.consumer_operations()
    before = operations.reader.snapshot_counts()
    result = operations.execute(
        "work.responsibility.dispatch",
        {"manager_assignment_ref": manager_ref, "expected_generation": 1, "action": "stale-old-owner", "input_refs": []},
        request_id="process-stale-dispatch",
        actor="manager-old",
    )
    after = operations.reader.snapshot_counts()
    output = {
        "pid": __import__("os").getpid(),
        "result": result,
        "counts_before": before,
        "counts_after": after,
        "event_delta": after["events"] - before["events"],
        "origins": {"otto": __import__("otto").__file__, "herzchen": __import__("herzchen").__file__},
    }
    store.close()
    return output


if len(sys.argv) == 3 and sys.argv[1] == "--child":
    print(json.dumps(child(Path(sys.argv[2])), sort_keys=True))
    raise SystemExit(0)


root = Path(sys.argv[1]) if len(sys.argv) == 2 else Path("ott06-stale-dispatch.sqlite")
store, owner, operations = bootstrap(root, "ott06-process")
created = operations.execute("work.pending.create", {"edit": {"title": "process stale dispatch"}}, request_id="create", actor="manager")
parent = operations.execute("work.pending.create", {"edit": {"title": "parent"}}, request_id="parent", actor="manager")
assigned = operations.execute(
    "work.responsibility.assign",
    {"project_ref": created["project_ref"], "roles": {"parent": parent["project_ref"], "manager": "manager-old", "executor": ["executor-a"]}},
    request_id="roles", actor="manager",
)
manager_ref = assigned["manager_assignment_ref"]
executor_ref = next(item["ref"] for item in assigned["roles"].values() if item.get("role") == "executor")
handoff = operations.execute(
    "work.responsibility.handoff",
    {
        "project_ref": created["project_ref"],
        "manager_assignment_ref": manager_ref,
        "from_manager": "manager-old",
        "to_manager": "manager-new",
        "evidence_refs": [parent["project_ref"]],
        "consumption_refs": [executor_ref],
        "parent_obligation": parent["project_ref"],
    },
    request_id="handoff", actor="manager",
)
domains_path = root.with_suffix(".domains.json")
domains_path.write_text(json.dumps([item.to_dict() for item in store.registered_domains()], sort_keys=True))
root.with_suffix(".manager.json").write_text(json.dumps(manager_ref, sort_keys=True))
store.close()
completed = subprocess.run([sys.executable, __file__, "--child", str(root)], capture_output=True, text=True, check=False)
if completed.returncode:
    raise SystemExit(completed.returncode)
child_result = json.loads(completed.stdout)
print(json.dumps({"parent_pid": __import__("os").getpid(), "manager_ref": manager_ref, "handoff": handoff, "child": child_result}, sort_keys=True))
