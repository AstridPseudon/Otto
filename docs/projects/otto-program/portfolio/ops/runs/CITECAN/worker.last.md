Implemented and left the changes uncommitted at base commit `97f5f97`.

- `assignments.py` validates each digest against its cited ref, then stores a canonical `kind:id:revision → digest` map while keeping the incoming hash shape in the replay payload.
- `attention_binding.py` reads the worker result’s canonical ref key and compares the completion source digest directly with the retained manifest digest.
- `test_operating_setup.py` covers list, labelled-map, and canonical-map inputs through real task completions, replay matching, historical setup reads, and corrective-reader hash corruption.

The requested focused command reported **43 passed, 1 failed**. `test_manager_journey_command.py` passed; the remaining failure is `test_ordinary_review_finishes_adopted_scope_without_owner_ratification`, which expected `manager_assessment` to raise `PermissionError("revision changed")` but it did not. I left that unrelated behavior unchanged. `git diff --check` passed. No commit was created.