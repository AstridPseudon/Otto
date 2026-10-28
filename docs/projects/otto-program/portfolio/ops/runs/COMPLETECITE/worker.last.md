Implemented COMPLETECITE in the lab, with changes left uncommitted.

[WorkAssignments.complete](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/COMPLETECITE/src/herzchen/domains/work/assignments.py:706) now requires a required assessment scope, exact citations from the accepted decisions, and matching digests in list and map form. The [regression tests](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/COMPLETECITE/tests/test_completed_worker_support_pins.py:65) use real governed completion with pinned DAT evidence.

The [stage-2 helper](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/COMPLETECITE/ops/bootstrap/perch_stage2_owner.py:62) now passes accepted decision pins to product completion instead of repeating byte verification. I updated its direct [test fixture](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/COMPLETECITE/tests/test_perch.py:1388) to supply those pins; fake lab cleanup was preserved.

Two Luna agents handled the product and stage edits. My review prompted the product agent to replace an observation-only regression with pinned DAT evidence and another task’s retained ref; I made the required stage fixture correction. Against canon, the new tests exposed three missing refusals; canon already refused the wrong list digest. The requested focused check passed: **12 passed, 3 subtests passed**. Four nearby completion regressions also passed.

I did not run staging-owner tests or stage-2 `--fake` A/B here. **A/B completion still requires the orchestrator run.**