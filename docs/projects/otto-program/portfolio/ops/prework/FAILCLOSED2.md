## 1. Design, in implementation order

1. `src/otto/portfolio/tests/test_reviewed_activation.py:43` → Add the failing test below. It uses real document creation and checks readiness, the named conflicting values, and absence of activation effects.
2. `src/otto/portfolio/reviewed_activation.py:179` → Replace the two first-match extractors with alias resolution that inspects every supplied review plan reference and digest. Unwrap legacy `{"ref": ...}` values, normalize references as exact pins, and accept equal aliases. Treat a supplied malformed alias as invalid rather than falling through to another.
3. `src/otto/portfolio/reviewed_activation.py:261` → Check *all* review aliases and both adopted-policy aliases against the requested plan. Conflicts must return `ready: false`, `state: "held"`, and a blocker containing both alias names and values. Use `ambiguous_plan_pin` with `source: "review"` or `"owner_policy"`; use `ambiguous_plan_digest` for contradictory digest aliases. Preserve the existing stale-pin behavior for a single wrong pin. `activate()` already gates effects through this read at `:365`.
4. `tests/test_authenticated_actor_decode.py` (new) → Test missing, `"false"`, and `1` claims, plus literal `True`.
5. `src/herzchen/contracts/model.py:380` and `:387` → Require `authenticated is True` in construction and require the field explicitly in `from_dict`; remove `bool(...)` and its missing-field default. The constructor check also closes the tagged wire decoder, which constructs dataclasses directly.

## 2. Failing test to write first

File: `src/otto/portfolio/tests/test_reviewed_activation.py`, inside `ReviewedActivationTests`. Name: `test_conflicting_review_and_policy_plan_aliases_hold_before_activation`.

```python
def test_conflicting_review_and_policy_plan_aliases_hold_before_activation(self):
    plan_a, clean_review = self._documents()
    other = self.portfolio.create_document(
        self.f.project.ref.to_dict(), actor="manager",
        request_id="d04-other-plan", role="plan",
        content={"schema": "otto.plan.v1",
                 "deliverables": [{"id": "other", "title": "Other"}]})
    plan_b = dict(other["document_ref"])
    plan_b["revision"] = "rev-1"

    conflicting = self.portfolio.create_document(
        self.f.project.ref.to_dict(), actor="manager",
        request_id="d04-conflicting-review", role="review",
        content={"plan_ref": plan_a, "reviewed_plan_ref": plan_b,
                 "disposition": "approved"})
    conflicting_review = dict(conflicting["document_ref"])
    conflicting_review["revision"] = "rev-1"

    specs = {"task_specs": [{"id": "one", "title": "First"}]}
    cases = (
        ("review", conflicting_review, specs,
         {"plan_ref": plan_a, "reviewed_plan_ref": plan_b}),
        ("owner_policy", clean_review,
         {**specs, "plan_ref": plan_a, "required_plan_ref": plan_b},
         {"plan_ref": plan_a, "required_plan_ref": plan_b}),
    )
    for source, review_ref, policy, values in cases:
        with self.subTest(source=source):
            activation = self.f.owner.reviewed_plan_activation(
                owner_policy=policy)
            arguments = dict(project_ref=self.f.project.ref.to_dict(),
                             plan_ref=plan_a, review_ref=review_ref,
                             owner_policy=policy)
            readiness = activation.read(**arguments)
            self.assertFalse(readiness["ready"], readiness)
            self.assertEqual(readiness["state"], "held")
            conflicts = [
                item for item in readiness["blockers"]
                if item.get("code") == "ambiguous_plan_pin"
                and item.get("source") == source
            ]
            self.assertEqual(len(conflicts), 1, readiness)
            self.assertEqual(conflicts[0]["values"], values)
            result = activation.activate(
                **arguments, request_key="d04-conflict-" + source)
            self.assertEqual(result["outcome"], "held", result)
            self.assertFalse(result["effects_started"])
            self.assertEqual(
                len(self.f.owner.graph.list(
                    project=self.f.project.ref, kind="task")), 1)
            self.assertEqual(len(self.f.provider.calls), 0)

    consistent = self.portfolio.create_document(
        self.f.project.ref.to_dict(), actor="manager",
        request_id="d04-consistent-review", role="review",
        content={"plan_ref": plan_a,
                 "reviewed_plan_ref": {"ref": plan_a},
                 "disposition": "approved"})
    consistent_review = dict(consistent["document_ref"])
    consistent_review["revision"] = "rev-1"
    policy = {**specs, "plan_ref": plan_a, "required_plan_ref": plan_a}
    activation = self.f.owner.reviewed_plan_activation(owner_policy=policy)
    self.assertTrue(activation.read(
        project_ref=self.f.project.ref.to_dict(), plan_ref=plan_a,
        review_ref=consistent_review, owner_policy=policy)["ready"])
```

The actor test should assert `AuthenticatedActor.from_dict(base)` and the same record with `"authenticated": "false"` or `1` raise `ContractError`; the record with literal `True` must decode. Add a tagged-wire case with `authenticated: 1` to verify the direct-constructor boundary.

## 3. Delete

Delete the first-present returns at `reviewed_activation.py:183-198`, the `plan_ref or required_plan_ref` selection at `:267`, and the actor decoder’s `bool(value.get("authenticated", True))` at `model.py:387`. Do not add another activation path.

## 4. Likely mistake

Checking only the review aliases leaves the adopted-policy conflict ready; checking aliases with truthiness skips malformed falsey values. Using `== True` for actors admits `1`. The test’s two independent readiness cases catch the first error, and the actor cases catch the latter; the wire case catches a decoder that bypasses `from_dict`.

## 5. Existing expectations and D19

No existing assertion should change, so no D19 decision is needed. The current happy path at `test_reviewed_activation.py:43`, recovery path at `:102`, and admitted-revision test at `tests/test_admit.py:296` use unambiguous pins. Add tests; do not rewrite those expectations.

## 6. Row corrections

The cited `ContractRecord.to_dict` method delegates serialization; dataclass fields are emitted by `_json_value` at `model.py:109-114`. “Every writer serializes the field” is too broad: SQLite event rows reconstruct actors from three columns at `src/herzchen/kernel/store.py:2761-2763`. Also, `decode_wire` constructs dataclasses directly at `src/herzchen/command_ports.py:130-137`, so fixing `from_dict` alone does not reject every truthy non-boolean actor record. The CUTOVER compatibility claim does not establish that all external JSON actor records contain the field.

This was a read-only review of `canon/main`; no tests were run.