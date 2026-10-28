## 1. Implementation design

1. [tests/test_operator_admission.py:114](${TRANSFER_ROOT}/source/otto/tests/test_operator_admission.py:114) → Add the regression test below first. Then add cases for ordinary pending, template pending, orchestrated pending, new-project save, and canonical import. Each should check that refusal leaves no project or receipt, then retry the same key with an operator and verify one creation. Exercise both the facade and the direct orchestration command port.
2. [src/herzchen/domains/work/orchestration.py:187](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/orchestration.py:187) → Store `operator_actor` without falling back to `actor`. At `:397`, resolve and require it before the creation transaction; use that local actor as `creator` at `:461`. Keep attach and other existing-project operations available without an operator.
3. [src/otto/portfolio/herzchen_binding.py:531](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:531) → Require `_operator()` before calling orchestration. At `:1391`, require it before either create-and-open route. For ordinary pending (`:493`), template (`:1593`), new-project save (`:2373–2381`), and import (`:1092–1109`), resolve it before the first creation write and pass the resolved actor to the existing creator argument. Existing-project save must remain available.
4. [src/otto/portfolio/owner_bootstrap.py:455](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/owner_bootstrap.py:455) → Resolve `_operator_actor()` before calling authoring at `:534`; capture that actor in `create_project` and use it at `:479`. Keep template validation ahead of writes.
5. [src/herzchen/authoring/sessions.py:768](${TRANSFER_ROOT}/source/otto/src/herzchen/authoring/sessions.py:768) → No change. Its reservation and post-creation failure recovery remain valid once operator refusal occurs before entry.

## 2. Failing test to write first

Add `test_missing_operator_create_and_open_leaves_no_reservation_and_retries_same_key` in **new** `tests/test_missing_operator_creation.py`:

```python
import unittest

from herzchen.contracts import ResourceRef
from otto.portfolio.fixtures.project_authoring import ProjectAuthoringProof
from otto.portfolio.intake import OttoPortfolio
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap


class MissingOperatorCreationTests(unittest.TestCase):
    def test_missing_operator_create_and_open_leaves_no_reservation_and_retries_same_key(self):
        fixture = ProjectAuthoringProof()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        request = {
            "actor": "owner",
            "request_id": "missing-operator-open",
            "edit": {"title": "Operator required", "outcome": "Pending"},
        }
        reader = fixture.store.consumer()
        before = reader.snapshot_counts()

        missing = PortfolioOwnerBootstrap(
            fixture.store, binding=fixture.owner.binding,
            owner_actor="owner", materializer=fixture.materialize,
        )
        denied = OttoPortfolio(missing.consumer_operations()).create_and_open(**request)
        self.assertEqual(denied["outcome"], "error", denied)
        self.assertIn("operator", denied["error"]["message"])
        self.assertEqual(reader.snapshot_counts(), before)
        self.assertFalse(reader.find_identity_refs(kind="work.project"))
        self.assertFalse(reader.find_identity_refs(kind="authoring-scope"))
        for suffix in ("", ":actor", ":project", ":project-created",
                       ":materialized", ":materialize-failure"):
            self.assertIsNone(reader.get_receipt(request["request_id"] + suffix))

        configured = PortfolioOwnerBootstrap(
            fixture.store, binding=fixture.owner.binding,
            owner_actor="owner", operator_actor="fixture-operator",
            materializer=fixture.materialize,
        )
        portfolio = OttoPortfolio(configured.consumer_operations())
        created = portfolio.create_and_open(**request)
        self.assertEqual(created["outcome"], "created", created)
        self.assertEqual(
            configured.graph.current(ResourceRef.from_dict(created["project_ref"]))
            .payload["provenance"]["creator"]["actor"],
            "fixture-operator",
        )
        after = reader.snapshot_counts()
        replay = portfolio.create_and_open(**request)
        self.assertEqual(replay["project_ref"], created["project_ref"])
        self.assertEqual(reader.snapshot_counts(), after)
        self.assertEqual(len(reader.find_identity_refs(kind="work.project")), 1)
```

## 3. Delete

Delete the `or actor` fallback at `orchestration.py:187`. Do not add a second source of operator identity or a compensating authoring receipt path.

## 4. Plausible mistake

Guarding only the creation callback still lets EDT reserve the scope and consume the request key first. The test catches the authoring identity and receipt writes, then proves that the unchanged key succeeds after operator configuration. A separate direct-port test catches an orchestration fallback hidden by a facade-only guard.

## 5. Existing expectations and D19

I found **no existing test assertion that should change**. The missing-operator composition assertions in `tests/test_operator_admission.py:114–136` remain correct. The saved-edit status asserted in `src/otto/portfolio/fixtures/project_folder.py:384` describes a genuine failure *after* creation and should remain. Any proposed change to either expectation needs a written D19 decision.

## 6. Row corrections on `canon/main`

Ordinary pending, template pending, new-project save, and import already call `_operator()` before their creation write. Their missing-operator risk is coverage and consistent preflight placement. The two demonstrated defects are orchestration’s fallback at `orchestration.py:187` and create-and-open’s late callback check at `owner_bootstrap.py:479`. `sessions.py:768` is the reservation site, not an authority resolver. I did not run tests or alter files.