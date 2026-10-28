## Design

1. [src/otto/portfolio/owner_readers.py:51](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/owner_readers.py:51) → remove `"tasks"` from `_PROJECT_SETUP_FIELDS`. At [line 58](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/owner_readers.py:58), describe the projection as adopted project setup content; delete the roster normalization at lines 68–75. Keep the `reviewed_activation` exclusion.
2. [src/otto/portfolio/owner_readers.py:78](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/owner_readers.py:78) → retain the exact historical revision read and comparison for every remaining field. [operating_brief.py:207](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/operating_brief.py:207) and [line 217](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/operating_brief.py:217) need no change: they still enforce the individual task, mandate, assignment, and project content pins.
3. Add the test below first. Then add focused cases in the same new test file: revise A’s `instructions` through the sheet after preparing its worker; append changed content to its adopted mandate; and change project `acceptance` through the sheet. In each case, assert refusal before another provider call. Keep [operating_setup.py:424](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/operating_setup.py:424)’s exact `acceptance_tasks` validation.

## First failing test

New `tests/test_rosterpin.py`, `test_unrelated_unadmitted_sheet_task_preserves_admitted_a_launch`:

```python
import unittest

from otto.portfolio.tests.test_operating_setup import OperatingSetupTests


class RosterPinTests(unittest.TestCase):
    def setUp(self):
        fixture = OperatingSetupTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.f = fixture.f

    def test_unrelated_unadmitted_sheet_task_preserves_admitted_a_launch(self):
        f = self.f
        a = f.task
        seeded = f.owner.sheet.apply(
            f.project.ref,
            {"tasks": [{"id": a.id, "title": a.payload["title"]}]},
            logical_request_key="rosterpin-seed-a", actor=f.actor,
        )
        f.project = seeded.project
        f.task = f.owner.graph.current(a.ref)
        self.assertIsNotNone(
            f.owner.graph.admission_state(f.task.ref)["admitted_revision"]
        )

        setup = self.fixture.manual()
        activated_pin = f.project.ref.to_dict()
        self.assertEqual(
            f.app.prepare_operating_setup(
                project_ref=activated_pin, setup=setup,
                request_key="rosterpin-prepare"
            )["outcome"], "prepared"
        )
        self.assertEqual(
            f.app.activate_operating_setup(project_ref=activated_pin)["outcome"],
            "succeeded",
        )
        pending_a = next(
            due for due in f.port.list_due()
            if due["role"] == "worker"
            and due["target"]["task_ref"]["id"] == f.task.id
        )
        calls_before = len(f.provider.calls)

        added = f.owner.sheet.apply(
            f.project.ref,
            {"tasks": [{"id": "D", "title": "Unrelated D"}]},
            logical_request_key="rosterpin-add-d", actor=f.actor,
        )
        current_project = added.project.ref.to_dict()
        d_ref = added.mappings["D"]
        self.assertEqual(f.owner.graph.current(f.task.ref).ref, f.task.ref)
        self.assertIsNone(
            f.owner.graph.admission_state(d_ref)["admitted_revision"]
        )
        self.assertTrue(
            f.app.read_operating_setup(project_ref=current_project)["ready"]
        )

        launched = f.app.start(schedule_id=pending_a["schedule_id"])
        self.assertEqual(launched["outcome"], "succeeded", launched)
        self.assertEqual(len(f.provider.calls), calls_before + 1)

        request = f.request()
        request.update(
            project_ref=current_project, task_ref=d_ref.to_dict(),
            request_key="rosterpin-unadmitted-d",
        )
        request["instruction_contract"]["task_ref"] = d_ref.to_dict()
        denied = f.app.assign_and_start(**request)
        self.assertEqual(denied["outcome"], "partial", denied)
        self.assertEqual(denied["stage"], "admission", denied)
        self.assertEqual(len(f.provider.calls), calls_before + 1)
```

This uses `ProjectSheet.apply` and the real owner execution path. The fixture substitutes only the external provider.

## Delete

Delete the identity-only roster comparison block and its `"tasks"` field entry. Add no replacement roster mechanism. [batches.py:699](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:699) already retains A when the sheet adds D.

## Plausible mistake

Dropping the entire project comparison, or weakening the task and mandate checks along with roster membership, would let changed instructions or policy inherit old authorization. The follow-up refusal cases catch that; the first test also proves that D’s new roster entry cannot give unadmitted D a provider turn.

## D19 and stale row details

No existing test expectation needs changing. The existing C revision edit already passes at [tests/test_operating_setup_pin_content.py:42](${TRANSFER_ROOT}/source/otto/tests/test_operating_setup_pin_content.py:42); its scope-change refusal remains valid. No existing assertion needs a D19 decision.

On `canon/main`, task **revision pointers** are already ignored in project setup comparison; only roster identity changes cause this failure. The sheet retention path and operating-brief pin guard cited in the row already work as intended. `PROJECTPIN` and `ROSTERPIN` are not literal code identifiers in this tree.

Read-only review only; no files were changed and no tests were run.