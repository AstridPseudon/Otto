## Design, in implementation order

1. `tests/test_manager_journey_command.py:144` → add the failing real-owner test below. The fixture already has tasks PA01 and PA06; review PA01 with `finish: False`, edit PA06 through the owner’s project-sheet port, refresh the controller’s B and project refs, then finish the original review.
2. `src/otto/portfolio/manager_journey_command.py:773-835` → distinguish an already completed task from a still-pending task before choosing the replay path. Verify committed replays through `_committed_finish_for_review`; run the new content guard before writing a new `finish-intent`. This lets an edit to A report its changed field even when the controller has refreshed A’s ref.
3. `src/otto/portfolio/manager_journey_command.py:259-329,878-1009` → replace `_completion_project`’s event-chain bridge with an owner-reader check. Use `task_reader` (`src/otto/portfolio/owner_readers.py:117-157`) against the accepted task pin; it reads the current parent project and proves A’s authored content against the retained revision. Require A’s task revision to remain exact for this change, since the owner completion API still requires it (`src/herzchen/domains/work/assignments.py:674-677`). For changed content, use `admission.reviewed_content_diff` (`src/herzchen/domains/work/admission.py:63-74`) to report, for example, `task.instructions`.
4. `src/otto/portfolio/manager_journey_command.py:259-329,878-1009` → resolve the current trusted assessment policy and compare it with the manifest’s `assessment_policy_selection`. Compare the policy fields, pool, allocation, source, and **A’s** exact task/criterion pairs; treat the project ref by identity and omit other tasks’ pairs and the revision-dependent digest. Check A’s criterion revisions against the owner. A changed field must raise `PermissionError` naming, for example, `assessment_policy.purpose`, and direct the manager to `review-input --task PA01`, then `review-task --task PA01 --request-key <new-key>` with fresh inputs. Keep the existing manager-generation check and pass the retained evidence hashes and gates unchanged to completion.
5. `src/otto/portfolio/manager_journey_command.py:865-871` → pass the current project ref returned by that proof to `complete_task`. Its owner-side current-revision check remains the final race fence; a concurrent plan save can be handled by retrying the same finish key.
6. `tests/test_completion_project_refresh.py:89-149` → replace obsolete pin-chain tests with real-owner cases for an edit to A’s `instructions` and a change to A’s policy, each checking the named field, re-review command, and absence of a completion effect. Keep the successful same-root refresh coverage at `:63-72`.

## Failing test to write first

File: `tests/test_manager_journey_command.py`; name: `test_accepted_a_finishes_after_b_sheet_edit_with_current_policy_state`.

```python
def test_accepted_a_finishes_after_b_sheet_edit_with_current_policy_state(self):
    review = {**self.request(alias="PA01", key="completepin-review"),
              "finish": False}
    accepted = self.commands.review_task(review)
    self.assertEqual(accepted["outcome"], "accepted")

    state = self.fixture.state
    a_pin = state["task_refs"]["PA01"]
    b_pin = ResourceRef.from_dict(state["task_refs"]["PA06"])
    project_pin = ResourceRef.from_dict(state["project_ref"])
    retained_review = self.commands._journal("completepin-review", "review")
    pool_ref = ResourceRef(self.application.actor.authority, "limit",
                           "local-inspection")
    pool_before = LimitService(self.application.store).get_pool(pool_ref)

    edited = self.application.owner.sheet.batches.apply_project_sheet(
        project_pin,
        {"tasks": [{"id": b_pin.id, "title": "PA06 revised after A review"}]},
        logical_request_key="completepin-edit-b",
        actor=self.application.actor,
    )
    state["project_ref"] = edited.project.ref.to_dict()
    state["task_refs"]["PA06"] = edited.mappings[b_pin.id].to_dict()
    self.assertNotEqual(state["project_ref"], project_pin.to_dict())
    self.assertNotEqual(state["task_refs"]["PA06"], b_pin.to_dict())
    self.assertEqual(state["task_refs"]["PA01"], a_pin)

    finish = {"command": "finish-task", "task": "PA01",
              "request_key": "completepin-finish",
              "review_key": "completepin-review"}
    result = self.commands.finish_task(finish)
    self.assertEqual(result["outcome"], "completed", result)
    self.assertEqual(result["completion"]["project_ref"], state["project_ref"])
    self.assertEqual(self.commands._journal("completepin-review", "review"),
                     retained_review)
    self.assertEqual(LimitService(self.application.store).get_pool(pool_ref),
                     pool_before)

    state["task_refs"]["PA01"] = result["task_ref"]
    counts = self.application.store.consumer().snapshot_counts()
    self.assertEqual(self.commands.finish_task(finish)["outcome"], "replayed")
    self.assertEqual(self.application.store.consumer().snapshot_counts(),
                     counts)
```

## Delete

Delete the supervision-transfer ancestry walk and `finish-project-pin` proof writes in `manager_journey_command.py:888-1009`, plus its unused `HISTORY_SCHEMA` import at `:9`. Keep recognition of historical pin journal headers in `completion_intent_selection.py:15-23` so existing retained reports remain readable.

## Plausible mistake

An identity-only bridge would finish A after A’s instructions or assessment policy changed. The follow-on refusal tests must change A through the real owner sheet and change the trusted policy, then require `task.instructions` or `assessment_policy.purpose` in the refusal. The first test also catches an overbroad policy comparison: refreshing B’s task ref must not invalidate A’s acceptance.

## D19 decision needed

Changing or removing assertions in `tests/test_completion_project_refresh.py:89-149` needs a written D19 decision. The pending-pin proof expectations at `:89-125` become obsolete when that proof is deleted; unrelated project-edit refusals at `:103-108,126-130` must become successful completion cases. The stale-generation refusal at `:131-133` remains. The tests at `:109-125,134-149` also patch product methods or readers to manufacture ancestry failures, contrary to the stated test rule; replace their relevant coverage with real-owner edits. `ops/bootstrap/land.sh:131-186` requires the decision to name the changed test file and carry a verdict.

## Row corrections on `canon/main`

`finish_task` starts at `manager_journey_command.py:773`; `:827` is its call to `_completion_project`. `:1098` is the retained-intent settlement path, not the project-sheet batch path. The existing `project_reader` compares project setup content, including the task roster (`owner_readers.py:51-75`), so using its project-content match as the acceptance condition would still reject an edit to B. The useful PROJECTPIN proof here is its owner-backed **task** reader. No files were changed and no tests were run.