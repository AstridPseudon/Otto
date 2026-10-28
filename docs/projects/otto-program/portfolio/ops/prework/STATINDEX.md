## STATINDEX design

Line numbers are from `canon/main` (`b635c93`). I inspected the code but did not run a query plan or tests; the worker should run the test below on the unchanged branch first and retain its failing plan output.

1. [tests/test_portfolio_status.py:19](${TRANSFER_ROOT}/source/otto/tests/test_portfolio_status.py:19) → Add the test below first. It captures the **SQL and bound parameters actually executed** by status, explains all four child-record queries, and compares the result before and after index preparation. On current code, it should fail because the project selector is a bound JSON path.
2. [src/herzchen/kernel/schema.py:182](${TRANSFER_ROOT}/source/otto/src/herzchen/kernel/schema.py:182) → Declare three optional expression indexes on `(authority, kind, project expression)`: `work.task` / `$.project_ref.id`, `wrk.assignment` / `$.scope.id`, and `wrk.report` / `$.value.project_ref.id`, each with its literal `kind` partial predicate. Reuse the existing due-record project index at line 184. Keep exact DDL admission through `verify_physical_schema`; do not change canonical rows or the schema revision.
3. [src/herzchen/kernel/store.py:1574](${TRANSFER_ROOT}/source/otto/src/herzchen/kernel/store.py:1574) → After validating every path and value, recognize only those four `(kind, match_path)` pairs. When the declared index is present, emit its fixed literal `kind` and JSON expression, bind project IDs and other filter values, and use its `INDEXED BY` name. Keep the present generic parameterized query for other selectors and stores without the optional index. Keep `ORDER BY id` and all matches, including multiple selected projects.
4. [src/otto/hostctl/product_service.py:1224](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:1224) → Call the existing explicit `prepare_identity_lookup_indexes()` after admitted `Store.open`, while startup holds the exclusive owner lock and before serving status. This activates the declared indexes on existing installations; ordinary `Store.open` and status reads still perform no maintenance.
5. [src/otto/portfolio/status.py:54](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/status.py:54) → Keep its single shared reader and four batch calls. No new status SQL or second projection path is needed.

## Failing test to write first

Add this method to `PortfolioStatusTests` in [tests/test_portfolio_status.py:19](${TRANSFER_ROOT}/source/otto/tests/test_portfolio_status.py:19):

```python
def test_status_project_selectors_use_indexed_project_keys(self):
    import json

    self.owner.graph.create_task(self.projects[0].ref, logical_request_key="indexed-task-0")
    self.owner.graph.create_task(self.projects[1].ref, logical_request_key="indexed-task-1")
    manager = self.manager()
    self.due()
    self.owner.assignments.append_report(manager.ref, {
        "schema": "otto.issue.v1", "issue_id": "indexed-issue",
        "issue_version": 1, "project_ref": self.projects[1].ref.to_dict(),
        "problem": "Need a decision", "awaiting": "orchestrator",
        "observed_at": self.now.isoformat(),
    }, logical_request_key="indexed-report")

    foreign_ref = {"authority": "owner", "kind": "work.project", "id": "foreign"}
    templates = (
        ("work.task", {"project_ref": foreign_ref, "lifecycle": "pending"}),
        ("wrk.assignment", {"scope": foreign_ref, "role": "manager",
                            "status": "queued"}),
        ("otto.due-record", {"project_ref": "foreign", "role": "manager"}),
        ("wrk.report", {"value": {"project_ref": foreign_ref,
                                 "schema": "otto.issue.v1"}}),
    )
    stamp = self.now.isoformat()
    payloads = [
        (kind, json.dumps({**payload, "noise": "x" * 256},
                          sort_keys=True, separators=(",", ":")))
        for kind, payload in templates
    ]
    with self.store.transaction() as tx:
        tx.executemany(
            "INSERT INTO identities "
            "(authority, kind, id, current_revision, version, edit_token, "
            "payload_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [("owner", payloads[n % 4][0], f"foreign-{n:05d}", "rev-1",
              1, None, payloads[n % 4][1], stamp, stamp)
             for n in range(10_000)],
        )

    reference = self.status()  # Generic reader, before optional indexes exist.
    self.store.prepare_identity_lookup_indexes()

    class PlanningConnection:
        def __init__(self, base):
            self.base = base
            self.plans = []

        def execute(self, sql, parameters=()):
            if sql.startswith(
                "SELECT authority, kind, id, current_revision, "
                "updated_at, json_object("
            ):
                details = tuple(
                    row[3] for row in self.base.execute(
                        "EXPLAIN QUERY PLAN " + sql, parameters
                    )
                )
                self.plans.append((sql, tuple(parameters), details))
            return self.base.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self.base, name)

    original = self.store._connection
    planning = PlanningConnection(original)
    self.store._connection = planning
    try:
        actual = self.status()
    finally:
        self.store._connection = original

    self.assertEqual(actual, reference)
    self.assertEqual(
        {row["project_ref"]["id"] for row in actual["projects"]},
        {project.id for project in self.projects},
    )
    indexes = {
        "work.task": "identities_status_task_project_lookup",
        "wrk.assignment": "identities_status_assignment_project_lookup",
        "otto.due-record": "identities_due_project_lookup",
        "wrk.report": "identities_status_report_project_lookup",
    }
    self.assertEqual(len(planning.plans), 4, planning.plans)
    for sql, parameters, details in planning.plans:
        kind = next(k for k in indexes if k in sql or k in parameters)
        self.assertTrue(
            any("SEARCH identities USING INDEX " + indexes[kind] in detail
                and "<expr>=?" in detail for detail in details),
            (kind, details),
        )
```

The connection wrapper observes SQL execution; it does not replace a product method. The assertion requires an expression-key **search**, so merely forcing an index scan cannot pass.

## Deletion, mistake, and decisions

- **Delete:** In the four indexed cases, replace the bound-path selector at [store.py:1587](${TRANSFER_ROOT}/source/otto/src/herzchen/kernel/store.py:1587). Retain it only as the generic fallback. Delete no file or status reader.
- **Plausible mistake:** Add indexes and `INDEXED BY` but leave `json_extract(payload_json, ?)` or `kind = ?`. SQLite can scan an index without seeking a project key. The plan assertion rejects that; comparison with the pre-index result catches dropped rows or changed filters.
- **Existing test expectations:** None should change. The four-projection assertion at [tests/test_portfolio_status.py:100](${TRANSFER_ROOT}/source/otto/tests/test_portfolio_status.py:100) remains four, and the index-set assertion at [tests/test_indexed_identity_lookup.py:30](${TRANSFER_ROOT}/source/otto/tests/test_indexed_identity_lookup.py:30) derives its expectation from the declaration. Any edit to an existing assertion needs a written D19 decision.
- **Stale row details:** The due project index is already declared at [schema.py:184](${TRANSFER_ROOT}/source/otto/src/herzchen/kernel/schema.py:184), but status cannot seek it with its current bound path. No production caller currently invokes index preparation. The initial `work.project` discovery is portfolio-scoped and remains separate from these four project-key child queries. `STOREGROWTH C` is not present in `canon/main`, so its content could not be verified here.