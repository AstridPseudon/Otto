## Design

Line numbers are from `canon/main`. Make these changes in order:

1. Add the real Store canary below to [tests/test_hostctl_serve.py:132](${TRANSFER_ROOT}/source/otto/tests/test_hostctl_serve.py:132). It should fail on canon: hydration currently accepts a current, retained criterion from T2 as `T1/C01`, although no T1 scope contains it.
2. At [src/otto/hostctl/serve.py:353](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/serve.py:353), accept a retained alias only when its **exact criterion revision** also appears in `scoped_criteria`, which was collected from the project and requested tasks. Keep the current-record check. At line 280, stage refreshed task refs locally and commit them with criterion refs and policy only after validation succeeds, so refusal leaves trusted state intact.
3. Rebuild `test_fresh_project_view_loads_owner_policy_and_exact_criterion_aliases` at [tests/test_hostctl_serve.py:133](${TRANSFER_ROOT}/source/otto/tests/test_hostctl_serve.py:133) with a disposable Store, owner, canonical run document, and declared assessment scope. Preserve its positive alias, policy freshness, default mode, and unknown alias checks.
4. At [tests/test_ask_socket_wait.py:73](${TRANSFER_ROOT}/source/otto/tests/test_ask_socket_wait.py:73), create a real Due, assignment, durable wait, and cursor on a disposable Store. Let `_wait_for_answer`, `authorize_caller`, `DecisionsModule`, `require_asking_session`, and `EventCursorReader` run. Use a zero-second wait for the drain case. Add a foreign-principal case against the real `authorize_caller`; it must raise `PermissionError` before cursor work.
5. At [src/otto/portfolio/tests/test_execution_continuity.py:159](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/tests/test_execution_continuity.py:159), obtain blocked and ready states through real operating-setup records, then keep the resume and replay assertions. At [tests/test_hostctl_portfolio.py:50](${TRANSFER_ROOT}/source/otto/tests/test_hostctl_portfolio.py:50), let override activation call real `_compose_setup`, using the existing model launcher stand-in.
6. Rebuild the registry fixture at [tests/test_fleet_custody.py:172](${TRANSFER_ROOT}/source/otto/tests/test_fleet_custody.py:172) around a real owner, `LabFleet`, owner ports, and facade server. Exercise token-bound task context and `worker-done` settlement through the actual facade. The program’s rule against patching product methods rules out leaving the four stubs in place under a “wiring” test name alone.

## Failing test to write first

Add this class to `tests/test_hostctl_serve.py` (which already imports `json` and `HostctlFixture`):

```python
class AssessmentHydrationCanaryTests(HostctlFixture):
    def test_retained_criterion_without_t1_scope_is_rejected(self):
        from hashlib import sha256

        from herzchen.content import ContentDocument, ContentRevision
        from herzchen.contracts import ResourceRef, TransactionContext
        from herzchen.domains.assessment import AssessmentModule
        from otto.portfolio.assessment import OttoAssessment

        self._ready()

        def check():
            view = self.owner_service._attach(
                "demo-run", host_kind="claude-code")
            project = view.owner.graph.current(
                ResourceRef.from_dict(view.state["project_ref"]))
            t1 = ResourceRef.from_dict(view.state["task_refs"]["T1"])
            t2 = ResourceRef.from_dict(view.state["task_refs"]["T2"])
            actor = view.owner.owner_actor
            assessment = OttoAssessment(
                AssessmentModule(view.store, actor=actor), actor)
            t2_scope = assessment.coverage(t2)["scopes"][0]
            criterion = assessment.get_scope(
                t2_scope["ref"]).criterion_refs[0]
            self.assertNotIn(
                criterion.to_dict(),
                [ref for scope in assessment.coverage(t1)["scopes"]
                 for ref in scope["criteria"]])

            row = next(row for row in view._documents(project.ref)
                       if row["path"] == "run.json")
            head = ResourceRef.from_dict(row["revision_ref"])
            document = ContentDocument.from_dict(
                view.owner.content.read(head)["document"])
            run = json.loads(row["text"])
            run["assessment_accounting"] = {
                "kind": "owner_local_bookkeeping",
                "purpose": "scope canary",
                "local_only": True,
                "pool_id": "scope-canary",
                "capacity_units": 1,
                "cumulative_allowance_units": 1,
                "task_criterion_pairs": ["T1/C01"],
            }
            writer = view.binding.authenticated_actor(
                view.config["hosts"]["claude-code"]["principal"])
            key = "testpatch-scope-canary"
            revision = ContentRevision(
                document.ref, "rev-testpatch-canary", json.dumps(run),
                writer, parent_revision=head.revision)
            context = TransactionContext(
                writer, key, sha256(key.encode()).hexdigest(),
                expected_revision=head.revision)
            view.owner.content.execute(
                view.owner.content.build_append_revision(
                    context, document, revision))

            view.state["criterion_refs"] = {
                "C01": criterion.to_dict()}
            with self.assertRaisesRegex(
                    RuntimeError, "does not bind current owner records"):
                view._hydrate_assessment_policy(project)

        self.owner_service.call(check)
```

The T2 criterion is a real, current owner record; its absence from T1 coverage is the canary. This uses real document revision and assessment methods. Canon has no scope deletion API, so a criterion scoped only to T2 supplies the missing-T1-scope case.

## Delete

Remove the invented identity, reader, scope, and assessment replacements at `tests/test_hostctl_serve.py:139–168, 192–203`; the authorization, decisions, asking-session, and cursor patches at `tests/test_ask_socket_wait.py:93–98`; the readiness patches at `test_execution_continuity.py:162–165`; the `_compose_setup` patch at `test_hostctl_portfolio.py:60`; and the `FleetStub`, `FacadeServerStub`, and owner-port patches at `test_fleet_custody.py:195–214`. Retain only person or model stand-ins.

## Mistake the tests catch

A plausible fix checks that the retained criterion **exists**, as the current code at `serve.py:363–367` does, without checking that a relevant scope contains it. The canary’s T2 criterion still exists, so that fix fails the test. A similarly incomplete ask test can accept a foreign principal because its mocked `authorize_caller` never checks the Due and assignment binding.

## D19 expectations

The rebuilt ask drain test must replace the invented `cursor-after-drain` expectation with the real cursor result. Fleet tests should compare owner record refs rather than `first["task"] is task` where the real owner returns a fresh projection. The missing-scope hydration case changes from acceptance to refusal. Those assertion decisions need written D19 coverage for the affected files; the program rule also applies to `src/otto/portfolio/tests/test_execution_continuity.py` if an assertion changes, even though the current `land.sh` detector at [ops/bootstrap/land.sh:133](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:133) scans only `tests/*.py`. The blocked/succeeded/replayed, prepared/override, and other positive expectations need no change solely to remove patches.

## Stale row details

The hydration test begins at line 133, not 143. The fleet fixture replaces **four** product components, not just `LabFleet`. The row’s literal scope-removal step has no owner API on canon; the equivalent real Store canary above leaves `T1/C01` without a matching scope.

This was a read-only review. I did not run tests or start an owner.