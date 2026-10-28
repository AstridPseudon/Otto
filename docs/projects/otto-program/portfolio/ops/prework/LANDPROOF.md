## 1. Design, in implementation order

1. [tests/test_fleet_custody.py:891](${TRANSFER_ROOT}/source/otto/tests/test_fleet_custody.py:891) → Refactor the existing real-owner fixture to expose the service, owner, Git line, runner, and worker assignment before it calls `done()`. Let it supply a Git callable through `LandingService`’s existing injection point. Write the regression below first.

2. [src/herzchen/fleet/labs.py:365](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/labs.py:365) → Extend the existing marker into a versioned **intent** containing the old line tip, checked commit, task and assignment pins, sealed run ID, candidate ref, and accepted decision refs. It must never itself mean “landed.” Continue reading legacy two-line markers for cleanup, but refuse to infer acceptance from them.

3. [src/herzchen/fleet/landing.py:68](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:68) → Before checkpoint, rebase, or check, detect an exact retained intent. Verify its sealed runner record and owner assessment refs. If the commit is already on the configured line, finish recording proof. If the line is still at the recorded predecessor, retry only the fast-forward. Refuse a changed lab, admission, or divergent line. Neither path reruns the check, provider, or acceptance.

4. [src/herzchen/fleet/landing.py:194](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:194) → Keep acceptance before merge. At [line 216](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:216), write the intent with the exact accepted refs; after Git advances, verify the configured ref and exact commit, then call a required owner proof writer. Use a deterministic key so recovery writes one proof. Return `landed: true` only after proof is retained.

5. [src/otto/hostctl/fleet_landing.py:283](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/fleet_landing.py:283) → Bind the candidate’s existing commit, repo, line, task, assignment, and runner fields to an append-only `wrk.report` line-advance proof on that assignment. The owner writer checks Git ancestry against the configured repository and line; the report records the observed line tip and accepted refs. Pass this writer into landing at [line 371](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/fleet_landing.py:371). A crash after merge but before report is recoverable from Git plus the retained intent.

6. [src/otto/hostctl/owner.py:221](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/owner.py:221) → Supply the trusted repository map to the owner’s completion verifier. Resolve the line from the task’s admitted `otto.plan`, as the fleet registry does at [product_service.py:596](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:596); never accept a completion request’s path or line as authority. Wire it through [owner_bootstrap.py:710](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/owner_bootstrap.py:710).

7. [src/herzchen/domains/work/assignments.py:694](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/assignments.py:694) → After the existing accepted-decision and exact-citation checks, require code-task line proof for that **same candidate commit and configured line**. Reject an intent marker, absent proof, mismatched decision, or unverified repository. Add the verified commit, line ref, line tip, and proof ref to the existing completion observation and task completion at [line 759](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/assignments.py:759). Keep the current manager authority, revision fences, and one-transaction completion path.

## 2. Failing test to write first

Add `test_accepted_unlanded_commit_cannot_complete_and_reconciles_once` to [tests/test_fleet_custody.py:1029](${TRANSFER_ROOT}/source/otto/tests/test_fleet_custody.py:1029). The fixture refactor in step 1 provides `_real_landing_case(tmp_path, git=...)` as a context manager with the attributes used here; it uses the existing owner setup and does not patch a product method.

```python
def test_accepted_unlanded_commit_cannot_complete_and_reconciles_once(tmp_path):
    from herzchen.domains.assessment import AssessmentModule
    from herzchen.fleet.landing import LandingError
    from otto.portfolio.intake import OttoPortfolio
    from tests.test_landing import _run

    locks = []

    def git(cwd, *args):
        if args[0] == "merge" and not locks:
            lock = Path(cwd) / ".git" / "index.lock"
            lock.write_text("occupied\n")
            locks.append(lock)
        return _run(Path(cwd), *args)  # The real Git merge must fail.

    with _real_landing_case(tmp_path, git=git) as case:
        def land():
            return case.service.done(
                "one", case.task_ref.id, assignment_id=case.worker.ref.id)

        with pytest.raises((LandingError, subprocess.CalledProcessError)):
            land()

        assert len(locks) == 1
        assert _run(case.line, "rev-parse", "refs/heads/main") == case.base
        assert case.runner.n == 1
        assessment = AssessmentModule(case.f.store, actor=case.f.actor)
        decisions = assessment.list_decisions(parent_obligation=case.task_ref)
        assert len(decisions) == 1
        decision = decisions[0]
        assert decision.disposition == "accept"
        result = assessment.get_result(decision.result_ref)
        checked = result.protocol_result["runner"]["commit"]
        assert checked == case.fleet.get("one").head()
        assert checked != case.base
        candidate = case.f.store.get_identity(result.candidate_ref)
        assert candidate.payload["value"]["lab_commit"] == checked
        evidence, = decision.evidence_refs
        verified = case.handler.resolve(
            evidence, actor=case.f.binding.authenticated_actor("manager"),
            verify_full=True)
        digest = verified["manifest"]["byte_digest"]
        portfolio = OttoPortfolio(case.f.owner.consumer_operations())

        def complete():
            task = case.f.owner.graph.reader.get_identity(case.task_ref)
            pin = ResourceRef.from_dict(case.fixture.state["project_ref"])
            project = case.f.owner.graph.reader.get_identity(
                ResourceRef(pin.authority, pin.kind, pin.id))
            return portfolio.complete_task(
                project.ref.to_dict(), task.ref.to_dict(),
                case.fixture.manager.ref.to_dict(),
                actor="manager", request_id="landproof-complete",
                expected_generation=case.fixture.manager.generation,
                expected_project_revision=project.ref.revision,
                expected_task_revision=task.ref.revision,
                disposition="accepted", evidence_refs=[evidence.to_dict()],
                evidence_hashes=[digest], gate_refs=[decision.ref.to_dict()],
                candidate_ref=result.candidate_ref.to_dict(),
                result_ref=result.ref.to_dict())

        refused = complete()
        assert refused["outcome"] == "held"  # Fails on canon/main.
        assert "landing" in refused["error"]["message"].lower()
        assert case.f.owner.graph.reader.get_identity(
            case.task_ref).payload["lifecycle"] != "completed"

        locks[0].unlink()
        landed = land()
        assert landed["landed"] is True
        assert landed["commit"] == checked
        assert _run(case.line, "rev-parse", "refs/heads/main") == checked
        assert case.runner.n == 1
        assert len(assessment.list_decisions(
            parent_obligation=case.task_ref)) == 1

        completed = complete()
        assert completed["outcome"] == "completed"
        assert completed["completion"]["landed_commit"] == checked
        assert completed["completion"]["line_ref"] == "refs/heads/main"
        reports = case.f.owner.assignments.list_observations(
            case.fixture.manager.ref, kind="report")
        assert sum(row.value.get("kind") == "manager-completion"
                   for row in reports) == 1
```

Also add a sibling assessment-failure case: a failed admitted check or refused assessment leaves no accepted decision or advance proof, keeps the line at its base, and makes the same manager completion request return `held`. The existing failed-check test at [test_landing.py:321](${TRANSFER_ROOT}/source/otto/tests/test_landing.py:321) already covers the first half.

## 3. Delete

Remove the silent marker deletion in [labs.py:312](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/labs.py:312) and [labs.py:329](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/labs.py:329); create and resume must refuse an unsettled intent. Remove the optional “no marker is fine” branch at [landing.py:216](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:216) for owner-governed landing. Do not add a second completion ledger.

## 4. Plausible mistake

Moving acceptance after merge can land rejected work. Treating the pre-merge marker as proof can complete absent work. The test observes a real failed Git merge **after** an accepted decision, demands completion refusal, then proves recovery uses the same check and decision and produces one completion.

## 5. Existing expectations and D19

No existing assertion needs to change under this design. The successful landing and completion assertions at [test_fleet_custody.py:1033](${TRANSFER_ROOT}/source/otto/tests/test_fleet_custody.py:1033) should still pass after the fixture supplies configured-line proof; the assessment-only `completion_blockers` expectation there remains assessment-only. If implementation changes either existing assertion, record that test file and the reason in a D19 decision before landing.

## 6. Row corrections on `canon/main`

The cited landing and assignment lines are current. `landed` is presently written as **intent before merge** at [landing.py:216–222](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:216); no owner line-proof record or interrupted-advance reconciliation exists. The row’s `GITCUSTODY 2` and `COMPLETECITE` labels have no matching tracked implementation text on `canon/main`; they are program context, not APIs to call. Read-only review only: I did not edit files or run tests.