Implemented the D19 Restore in the LANDPROOF lab. All four assessment refusal cases again assert that the configured line is unchanged and no decision was accepted. The post-merge test now locks the real store after Git advances; it leaves the production proof writer unchanged and confirms absent proof before recovery, unchanged runner and acceptance counts, and exactly one proof afterward.

**Invariant review:** Acceptance remains before merge. The retained intent is not landing proof; recovery verifies the accepted commit on the configured line and retains owner proof before returning landed. Manager completion requires proof for that same commit and line.

**Checks:** The accepted-but-unlanded regression was red on canon. In the lab, the six focused LANDPROOF cases passed; landing coverage passed (22); completion coverage passed (24 tests, 20 subtests). The full required command finished with **28 passed, 8 failed**. One failure requires nested `sandbox-exec`; seven require process census or `ps`, which this worker sandbox denies. These remain for the landing gate outside the sandbox. `git diff --check` and `git diff HEAD --check` passed.

Changed files: [labs.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/src/herzchen/fleet/labs.py), [landing.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/src/herzchen/fleet/landing.py), [fleet_landing.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/src/otto/hostctl/fleet_landing.py), [owner.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/src/otto/hostctl/owner.py), [owner_bootstrap.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/src/otto/portfolio/owner_bootstrap.py), [assignments.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/src/herzchen/domains/work/assignments.py), [test_fleet_custody.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/tests/test_fleet_custody.py), and [test_landing.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/tests/test_landing.py). The extra `test_landing.py` edit supplies proof callbacks to its real `LabFleet` fixture; the prework’s interrupted advance is also exercised through a SQLite storage lock.

| Luna sub-agent | Work and review |
| --- | --- |
| `regression` | Wrote the original regression; D19 omissions were corrected by the restore agents. |
| `intent_recovery` | Implemented retained intent and recovery; its landing-file conflict was reconciled. |
| `proof_owner` | Implemented owner proof and wiring; no further correction this turn. |
| `completion_gate` | Implemented completion verification; no further correction this turn. |
| `storage_design` | Identified the SQLite interruption approach; adopted. |
| `restore_assertions` | Restored all four refusal assertions; no correction needed. |
| `restore_postmerge` | Replaced the proof-writer wrapper with a real store interruption; no correction needed. |
| `resolve_landing_conflict` | Resolved the landing-file text conflict; its focused run exposed the fixture issue. |
| `landing_fixture` | Fixed that fixture; 22 landing tests passed without further correction. |

No commit or push was made. Git still marks `landing.py` unmerged in the **index**, although its working-tree conflict markers are resolved; the launcher must stage the lab changes.