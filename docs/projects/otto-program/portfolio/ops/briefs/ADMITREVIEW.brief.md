# Brief: ADMITREVIEW (normal, 0.25 focused days)

**Outcome:** An admission stamps only a review revision that exists.

**Why it matters:** Prevent an admission from recording a review pin that was never stored, while still allowing a retained review revision after its head advances.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen model for exact revision admission; Otto product keeps only the owner lane's local pinned-ref check.

**Files you own:** `src/herzchen/domains/work/module.py`, `tests/test_admit.py`.

**Other files:** Edit any other file the outcome directly requires, except files under Do not touch. Explain additions in your report.

**Do not touch:**
- `src/herzchen/command_ports.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/otto/hostctl/owner.py` and per-call owner facade sites (SESSIONFD);
- `ops/bootstrap/otto_gate_exit.py`, `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, `tests/test_manager_journey_service.py` (GATESKIP);
- `src/otto/hostctl/product_service.py`, `tests/test_fleet_custody.py` (DONESETTLE and MCPPATH);
- `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside your lab.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/ADMITREVIEW.md` first. Add the regression to `AdmissionTests` in `tests/test_admit.py`: an existing review identity with a nonexistent revision must be refused without a stamp; a retained exact revision must admit after the review head advances. In `WorkGraph.admit`, resolve the supplied exact revision before the already-admitted check or stamp write. Ordinary stored identities use `get_revision(review)` and require `record.ref == review`. DAT content reviews use `revision_identity(unpinned_review, review.revision)` and verify the immutable content record names that document and revision. Refuse missing or mismatched records with `TaskNotAdmittedError`. Keep the owner's local pinned-ref check and stamp the original exact review ref only after successful resolution. Do not add a dispatch change.

**Your check:** Run the focused admission tests and report canon red before the implementation and lab green after it. Include the DAT retained-revision case from the design.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_admit.py tests/test_manager_completion_command.py`

**Regression at the level the friction appears:** A nonexistent exact review pin is refused with no stamp, while a stored retained revision admits after the head advances.

**Working rules:** Never stash, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher. Keep long tests running to completion. On Codex, any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`. Never weaken a test to pass in the worker sandbox. Do not run tests that start a staging owner in the worker sandbox.

**When done:** Report the canon red and lab green runs, files changed, and blockers. Preserve existing assertions; list any changed assertion as file:line and explain it for D19.
