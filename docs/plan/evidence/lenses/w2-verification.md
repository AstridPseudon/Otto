## Lens: Verification, testing and evidence rules

### Findings

1. **“Done” became an approved, testable condition.**  
   **Observed:** A cold-start review found missing pass criteria across the UPD, GATE and COH plans. The process was changed so a worker proposes a “Done when” and test when a task lacks one, and the manager approves it before implementation [10-26 19:59–20:06; `data/main-full.txt`]. The manager brief later required checking the diff, test output, criterion and real callers before landing [`/home/user/repo/astrid-install/MANAGER.md`, lines 43–50].  
   **Inference:** This made task completion a checkable claim, rather than a worker’s status label.

2. **“Written, not run” prevented plans from masquerading as proof.**  
   **Observed:** The install plan said real Windows and macOS checks could not run locally and that review gates would not count them as passed [10-26 01:39; `data/main-full.txt`]. The manager brief formalized that “Written, not run is never a pass” and required a real-runner log for native OS, CI and Pinokio checks [`/home/user/repo/astrid-install/MANAGER-CODEX.md`, lines 69, 87–97].  
   **Observed:** This distinction mattered in practice: the private test-repo Actions jobs remained queued on all three runner types for about 15 minutes, so the orchestrator sent the integration zip with CI still unverified [10-28 16:13; `data/main-full.txt`].  
   **Inference:** The rule blocked a false green, though it could not make the unavailable CI run happen.

3. **Failure classification was wrong at first; “the base decides” corrected it.**  
   **Observed:** The original rule treated failures also seen on the UPD branch as pre-existing. That mislabeled 87 failures without checking the branch being rebased onto. The orchestrator corrected the baseline to `origin/main`; 82 failures then counted as pre-existing, 10 as regressions and 5 as environmental [10-28 13:04; `data/main-full.txt`; commit `8f22a35`, `data/plan-repo-gitlog.txt`].  
   **Observed:** A later edge case required another clarification: a new test absent from `origin/main` cannot establish a clean baseline. The two Pinokio switch tests were first called pre-existing because main could not run them, then treated as regressions while investigated [10-28 15:27–15:29; `data/main-full.txt`].  
   **Inference:** Baseline comparison needs an explicit “new test” branch in its logic; “fails on base” is not meaningful when the test cannot run there.

4. **Classification improved when it separated code regressions from test/setup and release effects.**  
   **Observed:** The R8 records used distinct labels: regression, pre-existing, environmental, release-pending, and not run. In the final report, 67 failures were release-pending because they reflected the pinned schema digest; 2 service-repair failures were traced to a test helper’s bare venv, not product behavior; and one new recovery test had a stale fixture [R8 `regression-triage.md`, `runtime-pinokio-classification.md`, and `REBASE-COMPLETE.md`].  
   **Observed:** Fixture-only fixes were accepted with safeguards: model the state the real installer creates, change test setup only, preserve assertions, and rerun focused tests. For R8-F3, the orchestrator explicitly required reverting if product code changed or assertions were loosened [10-28 16:04, 20:21; `data/main-full.txt`].  
   **Inference:** A failing test is a signal to investigate, not by itself proof that product code is wrong.

5. **Bounded runs made hangs visible, but left a real coverage gap.**  
   **Observed:** After R8 went silent, the manager was told to split integration tests into chunks, use a 600-second per-test timeout, cap each chunk at 30 minutes, use fresh basetemp directories, and record hung IDs as “not run” [10-28 16:58; `data/main-full.txt`]. Final evidence named the last test in each hung chunk and counted 1,021 tests as not run [R8 `agent-classification.md`; `REBASE-COMPLETE.md`].  
   **Inference:** This was honest closeout: the work could proceed, but the rebase was explicitly “not fully verified” until those tests ran [`REBASE-COMPLETE.md`].

6. **Direct isolation fixes beat expensive bisecting for order-dependent tests.**  
   **Observed:** Two failures passed individually but appeared in full-suite order. The manager was bisecting with runs of about 70 minutes; the orchestrator stopped that approach and requested targeted isolation fixes, quick reproducing probes, file-alone checks, and one final full run [10-28 14:16–14:17; `data/main-full.txt`]. The final completion record distinguishes the environment-leak fix from a genuine file-descriptor leak in `_materialize_export` [R7 evidence in `REBASE-COMPLETE.md`].  
   **Inference:** When a failure is proven order-dependent, isolate shared state first; use bisecting when it can identify a product change or dependency boundary.

7. **A correct fixture fix can still be missed if test coverage is incomplete.**  
   **Observed:** The Pinokio switch failures exposed that the earlier UPD final run had not run the Pinokio integration suite [10-28 15:27; `data/main-full.txt`]. Once the fixture modeled a completed install, both switch tests passed; a separate `.pth`-only legacy-install refusal check was requested before closure [10-28 16:04; R8 evidence].  
   **Inference:** “The test passes after a fixture repair” is strongest when both the fixture’s realism and adjacent legacy cases are verified.

### What worked

- Task-level Done-when criteria, manager approval, and actual output made completion auditable [10-26 20:05; `MANAGER.md`].
- The base-branch correction caught failures hidden by comparing only with the old feature branch [10-28 13:04; `data/main-full.txt`].
- Separating release-pending pin differences from regressions avoided unnecessary code fixes [R8 `regression-triage.md`; `REBASE-COMPLETE.md`].
- Bounded chunks, named hung tests, and explicit not-run counts prevented silence from becoming an implied pass [10-28 16:58; R8 `agent-classification.md`].
- Fixture-only acceptance required fidelity to real installation state and unchanged assertions [10-28 16:04, 20:21; `data/main-full.txt`].

### What failed / friction

- The first baseline rule hid likely regressions; the corrected rule required re-sorting dozens of failures [10-28 13:04].
- New tests absent on the base exposed ambiguity: “fails on main” can mean “pre-existing” or “not runnable there” [10-28 15:27–15:29].
- CI jobs stuck queued, leaving real-runner evidence unavailable despite configured workflows [10-28 16:13].
- Full-suite bisecting of order-dependent tests spent roughly 70 minutes per run before the direct-isolation approach was mandated [10-28 14:16–14:17].
- The final rebase retained a large unrun test set: 1,021 IDs [R8 `agent-classification.md`; `REBASE-COMPLETE.md`].

### Candidate principles

- When a task lacks a Done-when criterion, have the worker propose one and a proving test; require manager approval before implementation, because the cold-start review found plans with no pass criteria [10-26 19:59–20:06].
- When a check depends on an OS, hosted CI, or external service, mark it “written, not run” until a real-runner log exists, because queued jobs provided no execution evidence [10-28 16:13; `MANAGER-CODEX.md`].
- When classifying a failure, compare it with the exact target base; label a new test separately if the base cannot run it, because the old-branch comparison misclassified 87 failures [10-28 13:04, 15:28].
- When a failure appears only with a pin mismatch, record it as release-pending with the pin and release action, because 67 R8 failures were digest mismatches rather than rebase defects [R8 `regression-triage.md`].
- When a test fails, inspect product behavior, environment and fixture realism before assigning a code fix, because R8-F1/F2/F3 were ultimately test-setup defects [10-28 16:04, 20:21; R8 cause files].
- When a run hangs, enforce per-test and per-chunk limits, preserve IDs and last output, and classify the remainder as not run, because R8 ended with 1,021 unexecuted tests [10-28 16:58; `REBASE-COMPLETE.md`].
- When failures are order-dependent but pass alone, fix isolation and use focused reproductions before a final full suite, because repeated 70-minute bisects were unnecessary [10-28 14:17].

### Structure implications

- **Task entity:** required `done_when`, proving command/test, approval state, approver, and approval timestamp. Block dispatch until approved.
- **Test-result record:** command, commit/base tuple, runner and OS, exit state, logs, test IDs, and one classification: regression, pre-existing, environmental, release-pending, skipped, or not run.
- **Baseline logic:** store exact base commit per repo. Require a “new test / absent on base” reason when no direct comparison is possible.
- **External-runner gate:** represent written workflow separately from run evidence. Only attach a passing status when a real runner reports success; queued, skipped, cancelled and missing results remain non-passing.
- **Hang handling:** configure timeout per test and per chunk, capture last test/output, preserve not-run IDs, and expose the remaining coverage gap in the completion summary.
- **Fixture-fix checklist:** require evidence that the fixture matches real setup, changed files are test-only, assertions remain intact, and focused tests pass. For risky flows, require one adjacent legacy-state case.
- **Failure triage cadence:** after the initial suite, rerun only failing IDs on the exact base; group confirmed failures by root cause; run focused checks after fixes and one full run at the end. This matches the documented R8 sequence and avoids repeated full-suite bisects [10-28 14:17; `data/main-full.txt`].