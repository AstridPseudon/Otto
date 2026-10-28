## 1. Design, in implementation order

1. `tests/test_manager_journey_command.py:144` → Write the failing test below. It uses three independent real owner tasks and accepted reviews, then checks the stored completion and exact replay for each input shape.
2. `src/herzchen/domains/work/assignments.py:750–769` → After every supplied digest has matched its exact evidence ref, build `canonical_hashes = {f"{ref.kind}:{ref.id}:{ref.revision or ''}": supplied_digests[ref] for ref in evidence_values}`. Store that map in `completion["evidence_hashes"]`. Keep `request_payload["evidence_hashes"] = hash_values` at line 612: replay must compare the submitted shape.
3. `src/otto/portfolio/attention_binding.py:135–142` → Read the worker result digest under the canonical key built from `proof["result_ref"]`. Compare `completion["source_set_digest"]` directly with the retained source manifest digest and proof. Remove the two labelled-hash lookups.
4. `src/otto/portfolio/tests/test_operating_setup.py:787–812` → Exercise list, labelled-map and canonical-map inputs across its three genuinely accepted historical tasks before the existing `acceptance_readiness` read. Keep its exact evidence and corruption checks.
5. `tests/test_manager_journey_service.py:476–541` → Add coverage that the genuine corrective completion reaches `_completed_task_corrections` with canonical candidate hash evidence. Use real owner completions; add no product-method patches.

## 2. Failing test to write first

Add this class to `tests/test_manager_journey_command.py`:

```python
class CanonicalCompletionHashesTests(unittest.TestCase):
    def test_accepted_hash_forms_store_canonical_pins_and_preserve_replay(self):
        for form in ("list", "label", "canonical"):
            with self.subTest(form=form):
                case = ManagerJourneyCommandTests()
                case.setUp()
                self.addCleanup(case.doCleanups)
                request = case.request(key="citecan-review")
                request["finish"] = False
                reviewed = case.commands.review_task(request)
                self.assertEqual(reviewed["outcome"], "accepted")

                canonical = dict(reviewed["evidence_hashes"])
                values = list(canonical.values())
                supplied = {
                    "list": values,
                    "label": {f"slot-{i}": digest
                              for i, digest in enumerate(values)},
                    "canonical": canonical,
                }[form]
                f = case.application
                state = case.fixture.state
                task = ResourceRef.from_dict(state["task_refs"]["PA01"])
                port = f.owner.assignments.command_port
                args = dict(
                    project=ResourceRef.from_dict(state["project_ref"]),
                    assignment=ResourceRef.from_dict(state["assignment_ref"]),
                    expected_generation=state["manager_generation"],
                    expected_project_revision=state["project_ref"]["revision"],
                    expected_task_revision=task.revision,
                    disposition="accepted",
                    evidence_refs=reviewed["evidence_refs"],
                    evidence_hashes=supplied,
                    gate_refs=reviewed["gate_refs"],
                    candidate_ref=reviewed["candidate_ref"],
                    logical_request_key="citecan-complete",
                    actor=f.actor,
                )
                wrong = (["0" * 64 for _ in values] if form == "list"
                         else {key: "0" * 64 for key in supplied})
                with self.assertRaisesRegex(Exception, "digest|mismatch"):
                    port.complete(task, **{**args, "evidence_hashes": wrong,
                                           "logical_request_key": "citecan-wrong"})

                completed = port.complete(task, **args)
                self.assertEqual(completed["outcome"], "completed")
                stored = f.owner.graph.reader.get_identity(
                    ResourceRef.from_dict(completed["task_ref"])
                ).payload["completion"]
                self.assertEqual(stored["evidence_hashes"], canonical)
                self.assertEqual(completed["completion"]["evidence_hashes"], canonical)

                counts = f.owner.graph.reader.snapshot_counts()
                replay = port.complete(task, **args)
                self.assertEqual(replay["outcome"], "replayed")
                self.assertEqual(replay["completion"]["evidence_hashes"], canonical)
                if form != "canonical":
                    with self.assertRaises(Exception):
                        port.complete(task, **{**args, "evidence_hashes": canonical})
                self.assertEqual(f.owner.graph.reader.snapshot_counts(), counts)
```

## 3. What to delete

Delete the raw-shape storage at `assignments.py:769` and the labelled-hash lookups at `attention_binding.py:139–140`. Keep the existing input parser and replay payload; add no reader fallback or second normalization path.

## 4. Plausible mistake

Canonicalizing `request_payload` as well as the completion would let a same-key replay with a different input shape match. The test’s changed-shape replay must refuse. Merely keeping the submitted list or labels in the stored completion fails its stored-map assertion.

## 5. Existing expectations and D19

No existing assertion needs to change, so no D19 decision is needed. Add assertions and vary the historical test’s completion inputs while retaining its current expected readbacks.

## 6. Row corrections on `canon/main`

The producer already accepts and verifies all three forms at `assignments.py:732–757`; the defect is storage at line 769. `owner_bootstrap.py:1319–1349` already requires canonical keys. The corrective reader at `manager_journey_command.py:595` calls `.get()` on hashes, so a stored list currently raises `AttributeError`. The row also omits `attention_binding.py:135–142`, which still reads labelled keys and must change with the producer.

This was read-only design work; no files were changed and no tests were run.