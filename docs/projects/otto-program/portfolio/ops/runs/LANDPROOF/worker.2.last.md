The round-2 conflicts are resolved in the **working tree**. D19’s four refusal cases retain `pytest.raises(LandingError)` and now check, inside the fixture, that the line stays at `case.base` and no assessment decision exists. The post-merge test leaves the production proof writer unchanged and verifies recovery after a real store interruption.

Acceptance still precedes merge. A retained intent alone cannot return `landed`; owner proof must establish that the exact accepted commit reached the configured line. Recovery keeps the runner and acceptance counts unchanged.

**Checks:** The earlier canon regression was red when accepted but unlanded work could complete. After this rebase, the focused regressions are green (**6 passed**); landing coverage passed (**22**), and completion coverage passed (**24 tests, 20 subtests**). The required full check ran to completion: **31 passed, 8 failed**. One failure is `sandbox_apply: Operation not permitted`; the other seven depend on process census or `ps`, which this sandbox denies. `git diff --check` and `git diff HEAD --check` passed.

Changed files: [assignments.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/src/herzchen/domains/work/assignments.py), [labs.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/src/herzchen/fleet/labs.py), [landing.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/src/herzchen/fleet/landing.py), [fleet_landing.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/src/otto/hostctl/fleet_landing.py), [owner.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/src/otto/hostctl/owner.py), [owner_bootstrap.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/src/otto/portfolio/owner_bootstrap.py), [test_fleet_custody.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/tests/test_fleet_custody.py), and [test_landing.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDPROOF/tests/test_landing.py). This round removed conflict markers and replaced an unowned assessment-module construction with the owner-managed module. The D19 `interrupted_proof` wrapper and proof-writer reassignment remain absent.

| Luna sub-agent | Work; correction |
| --- | --- |
| `rebase_landing` | Merged landing flow and ran landing tests; none. |
| `rebase_owner_proof` | Merged owner proof context; I changed intent verification to use the owner-managed assessment module. |
| `rebase_bootstrap` | Merged repository wiring with owner lifecycle; I restored one missing first-use command-port binding. |
| `lifecycle_audit` | Found the unowned assessment module; none to its read-only review. |
| `round2_checks` | Ran the full check, completion checks, and diff checks; none. |
| `final_recheck` | Repeated the full check and diff checks after the lifecycle fix; none. |
| `regression_green` | Ran the six focused regressions; none. |

**No commit was made.** Git still marks the three resolved source files `UU` in the index, and the rebase remains in progress. Codex cannot write `.git`; the launcher must stage the resolved files and continue the rebase.