## Design

Line references are from `canon/main`.

1. [tests/test_admit.py:101](${TRANSFER_ROOT}/source/otto/tests/test_admit.py:101) — Write the regression test below first.
2. [src/herzchen/domains/work/module.py:535](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/module.py:535) — Keep the pinned `ResourceRef` requirement, then resolve the **supplied revision** before reaching the already-admitted check or stamp write. For ordinary stored identities, require `get_revision(review)` to return a record whose `ref == review`. For `dat.content.document`, resolve `revision_identity(unpinned_review, review.revision)` and verify the immutable `dat.content.revision` record names that document and revision. Refuse either missing or mismatched result with `TaskNotAdmittedError`.
3. [src/herzchen/domains/work/module.py:553](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/module.py:553) — Continue stamping the original exact review ref only after resolution. Add a focused DAT case using a real review document whose head advances: its retained earlier content revision must still admit. The existing current-head DAT case is [tests/test_manager_completion_command.py:144](${TRANSFER_ROOT}/source/otto/tests/test_manager_completion_command.py:144).

## Failing test to write first

Add to `AdmissionTests` in [tests/test_admit.py](${TRANSFER_ROOT}/source/otto/tests/test_admit.py:44):

```python
def test_admit_requires_stored_review_revision_after_review_advances(self):
    task = self.agent_revise("Agent plan", "agent-plan")
    retained_review = self.review.ref
    later_review = self.graph.revise(
        unpinned(retained_review), title="Review updated",
        logical_request_key="review-updated", actor=USER)
    self.assertNotEqual(later_review.revision, retained_review.revision)
    self.assertEqual(self.store.get_revision(retained_review).ref, retained_review)

    missing_review = ResourceRef(
        retained_review.authority, retained_review.kind,
        retained_review.id, "rev-999999")
    self.assertIsNone(self.store.get_revision(missing_review))
    before = self.graph.admission_state(self.task_ref())
    self.assertIsNone(before["admitted_revision"])
    writes = self.revised_event_ids()

    with self.assertRaisesRegex(TaskNotAdmittedError, "exact stored revision"):
        self.admit(task.revision, key="missing-review-revision",
                   review=missing_review)

    self.assertEqual(self.revised_event_ids(), writes)
    self.assertEqual(self.graph.admission_state(self.task_ref()), before)
    self.assertIsNone(self.store.get_receipt("missing-review-revision"))

    admitted = self.admit(
        task.revision, key="retained-review-revision",
        review=retained_review)
    self.assertEqual(admitted["outcome"], "admitted")
    self.assertEqual(admitted["stamp"]["review_ref"],
                     retained_review.to_dict())
```

## Delete

Delete the identity-only lookup at [module.py:536](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/module.py:536). Keep the owner lane’s local pinned-ref check; it runs before presence proof. No dispatch change is needed.

## Likely mistake

A `get_identity` check still accepts the nonexistent pin; the first refusal assertion catches that. A current-head-only check rejects the retained older pin; the final admission catches that. Using `get_revision(review)` for **all** kinds is also wrong: DAT content revisions have separate derived identities, so the additional DAT case must catch it.

## Existing expectations and D19

No existing test assertion needs to change, so no D19 assertion-change decision is needed. Existing work-effort review refs are stored pins, and the manager-completion test creates a real DAT `rev-1` review.

## Row correction

The reported gap and line numbers are accurate. Its implicit “exact revision lookup” needs the DAT distinction: [Store.get_revision:1721](${TRANSFER_ROOT}/source/otto/src/herzchen/kernel/store.py:1721) reads a document head’s FND history, while DAT stores content revisions under [revision_identity:290](${TRANSFER_ROOT}/source/otto/src/herzchen/content/model.py:290). The change establishes revision existence; it does not validate the review’s content or bind its approval to the task.

Read-only review; no files changed or tests run.