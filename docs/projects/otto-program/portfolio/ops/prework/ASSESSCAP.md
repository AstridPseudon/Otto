## Design, in build order

1. [tests/test_local_assessment_composition.py:19](${TRANSFER_ROOT}/source/otto/tests/test_local_assessment_composition.py:19) → Add the regression test below first. It uses real owner scope declarations and `Store.append_event`; it patches no product method.
2. [src/otto/portfolio/assessment.py:133](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/assessment.py:133) → Call `list_events(stream="assessment", assessment_parent=current_parent.ref)`. Keep the existing `> 10000` refusal at line 134 **after** that selection and keep the current-record checks. This makes the bound apply to the selected parent before event hydration.
3. [src/herzchen/kernel/store.py:2733](${TRANSFER_ROOT}/source/otto/src/herzchen/kernel/store.py:2733) → Complete the existing selector for events the coverage view consumes. Initial scope declarations store the parent at `before_refs[0]`; amended declarations store it at `[1]` ([module.py:421](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/assessment/module.py:421)). Correction creation stores it at `[1]` ([module.py:680](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/assessment/module.py:680)). For correction resolution, match the correction subject to its creation event, then check that creation’s parent slot; resolution has no direct parent slot ([module.py:871](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/assessment/module.py:871)). Keep the exact assessment stream, event type, subject kind, and authority predicates.
4. Add focused selector assertions for amended scopes and created/resolved corrections alongside the test above. Confirm that `coverage()["corrections"]` still returns the current correction. No change is needed at [manager_assessment_command.py:80](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/manager_assessment_command.py:80): required-scope lookup already calls `coverage()`.

## Failing test to write first

Add this method to `LocalAssessmentCompositionTests` in `tests/test_local_assessment_composition.py`. Its existing imports supply `replace`, `ResourceRef`, `AssessmentModule`, and `LocalAssessmentPolicy`.

```python
    def test_parent_coverage_bound_ignores_unrelated_assessment_history(self):
        from otto.portfolio.assessment import OttoAssessment, OttoAssessmentError

        store = self.f.store
        assessment = AssessmentModule(store, actor=self.f.actor)
        task = ResourceRef.from_dict(self.state["task_refs"]["PA01"])
        other = ResourceRef.from_dict(self.state["task_refs"]["PA06"])
        criterion = ResourceRef.from_dict(self.state["criterion_refs"]["C01"])
        other_criterion = ResourceRef.from_dict(self.state["criterion_refs"]["C09"])

        target_scope = assessment.declare_scope(
            "assecap-target", parent_obligation=task, protocol="inspection",
            criteria=[criterion], designated_approver="manager",
            authority=self.f.actor.authority,
            policy={"required_for_completion": True},
            logical_request_key="assecap-target",
        )
        other_scope = assessment.declare_scope(
            "assecap-other", parent_obligation=other, protocol="inspection",
            criteria=[other_criterion], designated_approver="manager",
            authority=self.f.actor.authority,
            policy={"required_for_completion": True},
            logical_request_key="assecap-other",
        )
        events = store.list_events(stream="assessment")
        target_event = next(
            event for event in events if event.subject.id == target_scope.ref.id
            and event.event_type == "assessment.scope.declared"
        )
        other_event = next(
            event for event in events if event.subject.id == other_scope.ref.id
            and event.event_type == "assessment.scope.declared"
        )
        sequence = events[-1].sequence + 1

        def add_history(template, label):
            nonlocal sequence
            with store.transaction() as transaction:
                for index in range(10_001):
                    store.append_event(
                        replace(
                            template,
                            event_id=f"assecap-{label}-{index}",
                            sequence=sequence,
                            effects={},
                        ),
                        transaction=transaction,
                    )
                    sequence += 1

        add_history(other_event, "other")
        view = OttoAssessment(assessment, self.f.actor)
        coverage = view.coverage(task)
        self.assertTrue(coverage["complete_scan"])
        self.assertEqual(coverage["scope_count"], 1)
        self.assertEqual(coverage["scopes"][0]["ref"], target_scope.ref.to_dict())
        self.assertEqual(coverage["coverage"][0]["state"], "uncovered")

        policy = LocalAssessmentPolicy.from_run_config(
            self.config, state=self.state
        )
        commands = self.f.owner.manager_assessment(
            project_ref=self.state["project_ref"],
            task_ref=self.state["task_refs"]["PA01"],
            manager_assignment_ref=self.state["assignment_ref"],
            manager_actor=self.state["manager"],
            manager_generation=self.state["manager_generation"],
            assessment_policy=policy,
        )
        self.assertEqual(commands.required_scope().ref, target_scope.ref)

        add_history(target_event, "target")
        with self.assertRaisesRegex(OttoAssessmentError, "complete-view bound"):
            view.coverage(task)
        with self.assertRaisesRegex(OttoAssessmentError, "complete-view bound"):
            commands.required_scope()
```

This fails on `canon/main` at the first `view.coverage(task)`: its global scan sees more than 10,000 events.

## Delete

Delete the global event-scan call at `assessment.py:133`; replace it with the parent-selected call. Add no second scan, cache, or separate required-scope lookup.

## Plausible mistake

Raising the bound or dropping it would let the first lookup pass while silently weakening oversized-parent refusal. The test’s second flood requires the same explicit exception. A plain switch to the current selector would also lose correction rows; the focused correction assertion in step 4 catches that.

## D19 and stale row evidence

No existing test assertion needs to change, so there is no D19 expectation decision for this design. The owner completion predicate already uses `assessment_parent` at [module.py:1115](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/assessment/module.py:1115); the fault is Otto’s separate global coverage scan. The row’s `STOREGROWTH A` label, and `ASSESSCAP` itself, are absent from `canon/main` text. The cited store selector exists, but currently omits corrections and misreads amended scope declarations. No files were changed and no tests were run.