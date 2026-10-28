DEFECTS — COMPLETECITE delivers the core citation checks, but leaves a completion-format mismatch on `canon/main` (`eb9b6cd`).

1. **Valid completions can block subsequent setup acceptance. Route: normal.**
   - `src/herzchen/domains/work/assignments.py:732–749` validates list and labelled-map hashes, then persists the original format at `:769`.
   - Labelled maps are supported public input: `src/otto/portfolio/execution_operations.py:55–62` parses `label=sha256`.
   - **Failing scenario:** complete an accepted task using `[correct_digest]` or `{"review": correct_digest}`, then check operating-setup readiness with that completed task. `src/otto/portfolio/owner_bootstrap.py:1358` invokes historical verification, which rejects lists at `:1286` and noncanonical map keys at `:1303–1305`. Completion succeeded, but its stored proof cannot pass the reader.
   - Corrective-task validation has the same mismatch: `src/otto/portfolio/manager_journey_command.py:595` expects `.get(canonical_key)`; a label misses and a list raises `AttributeError`.
   - **Fix:** in `assignments.py`, persist the verified `supplied_digests` as a canonical `kind:id:revision → digest` mapping, preserving both supported input forms. Keep the original request payload for replay matching.
   - **Failing test:** on the real owner, complete equivalent tasks using list, labelled-map and canonical-map inputs, then exercise historical setup readiness and corrective-task coverage. All must accept the resulting proof. This defect remains present; the landing left it unfixed.

The row’s exact-evidence, digest and missing-scope checks are present at `assignments.py:709–757`. The stage-2 stand-in forwards accepted evidence and pins through product completion at `ops/bootstrap/perch_stage2_owner.py:41–68`.

**Tests, assessed statically:** the unrelated-evidence, wrong-map-digest and missing-scope tests distinguish the parent implementation. The wrong-list-digest test already passes before this change because assessment rejects that mismatch; the positive completion test also passes before it. The new domain tests exercise real completion without patching it, recreating its digest computation or waiting on timers. The perch test substitutes assessment and portfolio objects (`tests/test_perch.py:1378–1419`), so it proves forwarding, not product enforcement.

No material over-engineering finding. `land.out` reports passing checks and `perch --fake`, but does not separately identify stage-2 A/B completion. No tests or Otto commands were run during this review.