Implemented only PERCH2C items (g)–(j), preserving commit `8c02a8b` and the ORPHANWORKER census lines.

- [perch_stage2_evidence.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2C/ops/bootstrap/perch_stage2_evidence.py) now captures C’s `work.project-sheet.applied` event, including its child revision and changed fields.
- [perch_report.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2C/ops/bootstrap/perch_report.py) reports a missing final status without calling Store completed tasks incomplete; matches the instruction edit to that project-sheet event; and distinguishes task labs from an empty branch namespace. It names a retained unknown C recovery lab using the killed-worker marker and final status.
- [perch.sh](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2C/ops/bootstrap/perch.sh) collects labs beneath the namespace and builds `config.json` before Store observations, while keeping fault seeding afterward.
- [test_perch.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2C/tests/test_perch.py) adds owner-free collection and doctored-input regressions for all four items.

**Checks:** 63 passed, 6 deselected, 68 subtests; shell syntax, Python compilation, and `git diff --check` passed. I did not start an owner or run stage 2. PERCH2C remains held for the Orchestrator’s rerun; I did not commit or land it.