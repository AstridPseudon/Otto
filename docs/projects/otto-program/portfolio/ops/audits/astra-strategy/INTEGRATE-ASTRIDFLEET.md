**The study delivers its substantive goal. Land a corrected report through the gate; do not merge `proj/astridfleet` wholesale.** No task warrants dropping.

Reviewed `proj/astridfleet=f8d46ee` against base `163925e`, with canon at `eb9b6cd`. Three Luna reviewers supplied evidence; I independently checked the key claims. No tests, owners, staging runs, or Otto commands were executed.

The report makes both requested decisions: conditional support for fleet-hosted agents, and rejection of ledger convergence on the available evidence. It supplies a separate, four-task, 2.5-day follow-up. Its distinction between agent turns, capability execution, and durable receipt authority is supported by the cited source. This completes a **study**, not an integration demonstration. See [decisions and proposal](${TRANSFER_ROOT}/source/projects/astridfleet/.project/study.md:70).

| Merged task | Assessment | Recommendation |
|---|---|---|
| **AF1 — `450d783`, +18/−0** | Useful mapping of execution, authority, workspace, and process custody. No substantive defect found in the mapping. [Evidence](${TRANSFER_ROOT}/source/projects/astridfleet/.project/study.md:5) | **Merge now**, as report content. |
| **AF2 — `84b33a9`, +14/−0** | Correctly distinguishes command identity, process-local reconciliation traces, Runtime authority, and Runner persistence. Explicitly leaves storage/retention facts unverified. [Evidence](${TRANSFER_ROOT}/source/projects/astridfleet/.project/study.md:22) | **Merge now**, retaining those limits. |
| **AFUX — `6e8e959`, +32/−0** | Useful static walkthrough; it explicitly acknowledges that the proposed tool does not exist. Minor error: line 56 attributes “the owner supplies a stable request reference” to the compact brief, but line 42 contains no such statement. [Comparison](${TRANSFER_ROOT}/source/projects/astridfleet/.project/study.md:42) | **Merge after a small correction:** say the brief *assumes* a returned reference; owner minting is the proposal. |
| **AF3 — `fad4a1d`, +29/−0**, plus final corrections | Decisions, dependencies, and zero safe-deletion budget are reasonable. The final caller-reference correction is factually reversed, detailed below. [Evidence](${TRANSFER_ROOT}/source/projects/astridfleet/.project/study.md:93) | **Merge after correcting the caller evidence.** |

The concrete defects and integration requirements are:

- **Wrong caller classification.** [Study line 93](${TRANSFER_ROOT}/source/projects/astridfleet/.project/study.md:93) and [tasklist line 14](${TRANSFER_ROOT}/source/projects/astridfleet/.project/tasklist.md:14) say `run-task.sh:68` invokes `otto-lab.sh`, while the test merely prints instructions. Source shows the reverse: [run-task.sh:68](${TRANSFER_ROOT}/source/otto/ops/bootstrap/run-task.sh:68) prints a diagnostic; [test_bootstrap_gate.py:88](${TRANSFER_ROOT}/source/otto/tests/test_bootstrap_gate.py:88) executes it through `subprocess.run`. `land.sh:479` is the other invocation. A cleanup worker following the report would classify the wrong dependency as executable. Correct the report, tasklist, and review record. **The zero-deletion conclusion remains valid.**

- **The documented checks cannot pass the current gate alone.** All four [task checks](${TRANSFER_ROOT}/source/projects/astridfleet/.project/tasklist.md:7) are heading searches. A successful, silent `rg -q` is refused by [land.sh:279–282](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:279), which requires a test-result summary. The handoff’s assertion that [no gate-only tests were needed](${TRANSFER_ROOT}/portfolio/ops/projects-run/ASTRIDFLEET.last.md:14) is therefore incorrect **for canon integration**. Give the import task document checks plus a real invocation of the existing boundary test; retain staging. No new document-testing framework is needed.

- **Source provenance needs recording.** The report uses `Astrid/...` citations without identifying the supplied checkout. The matching source is `${ORIGINAL_HOME}/Developer/astrid-video/astrid-local/live-main/Astrid`, revision `f42eaa6db62d989fc869da7219d76493e932869c`. Add that and Otto baseline `163925e`. Otherwise a reviewer using another Astrid checkout gets mismatched lines. Date the EFFECTS comparison too: it compares the program plan, while the separate EFFECTS branch subsequently recorded EF1–EF4 implementation work. [EFFECTS record](${TRANSFER_ROOT}/source/projects/effects/.project/PROJECT.md:8)

**Test honesty:** the branch changes no test files, assertions, or timed-test mechanisms—only nine `.project/` files, **+202/−0**. The historical transcript records successful post-change heading checks; those establish section presence, not correctness. I found no evidence of fabricated runtime-test success. Fail-first execution is not established by the parent transcript inspected. AFUX supports a static proposed-path assessment, not measured behavior of a working integration. [Recorded validation](${TRANSFER_ROOT}/source/projects/astridfleet/.project/PROJECT.md:7)

**Cleanup:** there is no new runtime machinery to delete. I independently confirmed `process_group.py` has **678 lines and 13 importing modules**, and `otto-lab.sh` has **46 lines** with active invocations. Neither is safely removable on this evidence.

Since `163925e`, canon contains only:

```text
1b1159d READYPIN: the worker's changes (worker.jsonl)
eb9b6cd Land READYPIN: READYPIN
```

Those commits touch:

```text
src/otto/portfolio/owner_bootstrap.py
src/otto/portfolio/owner_readers.py
src/otto/portfolio/tests/test_operating_setup.py
tests/test_completed_occurrence_readiness.py
```

**Files touched by both branches: none.** Expected textual merge difficulty is trivial—an inference from the disjoint diffs, not an attempted merge.

There is a separate packaging conflict: ASTRIDFLEET, EFFECTS, and PACKS independently add the same eight generic `.project/` control-file paths. Merging those packages sequentially creates add/add conflicts and conflates project records. Preserve the packages in their project clones; import the report into a project-specific documentation path.

Recommended landing order:

1. **Prepare one `ASTRIDFLEET-REPORT` integration task**, containing the accumulated AF1 → AF2 → AFUX → AF3 report and final corrections, for example at `docs/astrid-fleet-study.md`. Preserve original task SHAs as provenance; exclude the generic `.project/` package.
2. **Land that task through the normal gate:** current-canon rebase, explicit document checks and existing boundary test, required sweep, staging on the tested revision, then recorded merge/push. The gate requires a task lab and brief and merges the entire prepared branch. [Gate requirements](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:50), [program procedure](${TRANSFER_ROOT}/portfolio/RUNBOOK.md:62)
3. **Keep implementation separate:** after the stated edition-1 and EFFECTS-contract prerequisites, integrate contract → adapter → real-tool UX and custody review. Reassess the EFFECTS comparison against its landed implementation first. Those dependencies are already explicit in the [proposal](${TRANSFER_ROOT}/source/projects/astridfleet/.project/study.md:84).