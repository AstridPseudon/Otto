# D19 decision: OPERATOR-ADMIT, tests/test_admit.py (the orchestrator, 17 Oct 2026)

**Decision: LAND.** No Opus call was made; the behaviour change is the one the Opus oracle decided (`ops/reviews/ORACLE-ADMIT.md`).

- **What changes:**
  - `AdmitVerbTests`: the generic `portfolio admit` verb used to admit (pin, replay) and refuse a changed sheet with its diff. Its three tests now assert it is denied with `owner_presence_required` and writes nothing.
  - `ReviewedActivationAdmitsTests`: reviewed activation used to admit an agent-written task as the owner. The test now asserts activation is refused, with no writes, until the revision was admitted, and then activates.
  - `tests/test_hostctl_cli.py` only adds the new required `install --operator` argument; no expectation changes.
- **Why it's right:** the oracle's invariant is that only the operator admits, through the owner command after the owner's own presence check. The generic verb and activation's automatic admission were two admission paths without presence, so removing them is the outcome of the row, not a regression.
- **Coverage kept:** pinning, replay without duplicate writes and the changed-sheet diff are still asserted at the graph level (`AdmissionTests`, test_admit.py:130 and :147). Admission through the owner, as the operator, after presence, with one log line, is asserted in `tests/test_operator_admission.py:145`; refusals leave the Store byte-identical (:172, :185).
- **Cost noted:** activating a reviewed plan now needs each agent-written task admitted first, so one presence check per task. If that's too much at stage 2, a batch admission (one presence check for one reviewed plan revision) is the follow-up; it isn't part of this row.
- **Nit, not blocking:** `test_admit_verb_refuses_a_changed_sheet_with_the_diff` keeps its old name while asserting the denial.
