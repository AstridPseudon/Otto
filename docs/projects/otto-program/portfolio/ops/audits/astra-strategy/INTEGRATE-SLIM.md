**Do not integrate SLIM wholesale or mark its goal complete.** Several changes are ready for individual landings; SL4, SL8 and SL9B need corrections, and SL2 remains incomplete.

Reviewed `proj/slim` **`2df7571`**, base **`163925e`**, against `canon/main` **`ec6bacf`**. I used three Luna reviewers and a Sol reviewer for friction semantics, then checked the findings against source and diffs. No tests, owners, staging or Otto commands were run; no files were changed.

**1. Goal delivery: partial.**

The independently measured top-level portfolio diff is **+346/−1,656: 1,310 net lines removed**, or **2.73%** of 47,920. The target is 11,980; **10,670 lines remain**. No controller files were removed. The project records these numbers correctly. [Evidence](${TRANSFER_ROOT}/source/projects/slim/.project/PROJECT.md:180)

SL2 has no production caller for `OwnerManagerReplacement`; SL6’s measured UX pass, SL7’s dependent guidance pass and SL9’s budget closure remain blocked. Keeping Vision/Native5 until controller retirement is justified, but does not satisfy the original deletion goal. [Task status](${TRANSFER_ROOT}/source/projects/slim/.project/tasklist.md:14)

**2. Findings that affect landing.**

- **SL8: real retained data does not match the successful test.** Issue fields live in `wrk.report.value`; the history projection omits them. The reducer expects those fields in its flattened summary, and its positive test supplies invented summary shapes. Actual questions, `next_action` and answer waits therefore cannot produce the demonstrated counts. This is a feature-delivery gap, not proof of intentional dishonesty. [Producer](${TRANSFER_ROOT}/source/projects/slim/src/otto/portfolio/issue_loop.py:761), [history projection](${TRANSFER_ROOT}/source/projects/slim/src/herzchen/kernel/history.py:19), [test](${TRANSFER_ROOT}/source/projects/slim/tests/test_status_friction.py:66).
- **SL8: unsupported zero and incorrect acceptance accounting.** An empty complete window reports all six categories as known zero despite missing category coverage. A completed task with disposition `approved`, `completed` or `verified` is omitted from `accepted_tasks`; only `accepted`/`passed` mappings count. Real usage facts contain task association and component metrics under `usage_fact`, on a `wrk.report` subject; the reducer instead requires a task subject and scalar `tokens`. Thus retained usage cannot yield the promised ratio. [Reducer](${TRANSFER_ROOT}/source/projects/slim/src/otto/portfolio/observability_views.py:315), [valid dispositions](${TRANSFER_ROOT}/source/projects/slim/src/herzchen/domains/work/assignments.py:105), [usage producer](${TRANSFER_ROOT}/source/projects/slim/src/herzchen/domains/work/usage.py:297). **Fix:** use actual retained schemas and existing usage accounting; keep unsupported categories unavailable even for empty pages; replace the synthetic acceptance evidence with real writer→reader→CLI regressions.
- **SL4: deletion removes tests of retained functionality.** In `163925e:src/otto/portfolio/tests/test_d05_events_candidate_proof.py`, the tests at **53, 64 and 83** exercise withdrawn history, foreign/snapshot/time-range refusal and per-page `grant_reader` reauthorization directly. They do not need the retired proof implementation. Remaining tests cover some adjacent cases, but not the dynamic grant-reader case or nonexistent Berlin local time. **Fix:** move those retained-behavior checks into `tests/test_project_history.py`, deduplicating genuinely equivalent coverage. This is a coverage regression, not a demonstrated runtime failure.
- **SL9B: retirement leaves an advertised orphan command.** Root `manager_ctl.py` still advertises `advisor-followup-bind-paused` and special-cases its `reconciled` result. No maintained handler remains in the inspected repository. This advertisement was already orphaned; the deletion did not newly break a working route. **Fix:** retire the parser branch and special exit handling, and extend the retirement check to cover the command. [Parser](${TRANSFER_ROOT}/source/projects/slim/manager_ctl.py:212), [exit handling](${TRANSFER_ROOT}/source/projects/slim/manager_ctl.py:297).

No new sleep-based or elapsed-time assertions appear in the test diff. SL2’s concurrency check is a deterministic reentrant model using permissive `setdefault`, not proof of production Store concurrency. SL3’s “installed” observability tests substitute `HostSession` and the history reader; they establish wiring, not a running-owner result. [SL2 fixture](${TRANSFER_ROOT}/source/projects/slim/tests/test_manager_replacement_unit.py:41), [SL3 fixture](${TRANSFER_ROOT}/source/projects/slim/tests/test_owner_observability_cli.py:57)

**3. Per-task recommendation.** “Merge now” still requires the program gate and applicable D19 approval.

| Task / project merge | Recommendation | Assessment |
|---|---|---|
| **SL0** `81abf5c`, fixes `b6f48f5`, `d435a11` | **Drop from canon; retain as project audit evidence** | Useful inventory, accurate baseline. Its test checks rendered constants rather than independently validating the pinned baseline. The fixed-baseline generator and `.project` execution metadata are project scaffolding, not product functionality. |
| **SL1** `cd4d611` | **Merge now** | Small canonical-direction projection; strengthened replacement test preserves exact adoption and excludes drafts/foreign direction. No confirmed source defect. Advisor-context removal has no retained in-repository caller. |
| **SL2** `64869e6`, `f0f7bc5` | **Merge after owner wiring is resolved** | Generation guard and acquisition fencing are useful, but the requested replacement route remains unentered. A separate landing of the live final-admission guard is reasonable now; do not close SL2 on that basis. Coordinate the rest with PROGRAM MGR. |
| **SL3** `29c6530`, repairs `a4c0a8f`, `ea52539` | **Merge now, excluding SL8-specific hunks** | Pagination/cursor forwarding and finite owner-grant composition are sound on inspection. Include the structured usage-error repair. |
| **SL4** `9fdc4be` | **Merge after test-preservation fix** | Source retirement is reasonable; preserve the retained-reader checks identified above before approving deleted assertions. |
| **SL7A** `52d23ff`, correction `079d492` | **Merge now, both together** | Corrected documentation distinguishes registration/metadata reconciliation from document synchronization. Keep PROGRAM A6 implementation ownership. |
| **SL8** `24eeda2`, `ee9a30d`, shared follow-ups | **Merge after real-schema/coverage fixes** | Current positive tests overstate delivered functionality. Delete unsupported speculative shape handling instead of expanding it. |
| **SL9A** `a7feacf` | **Merge now** | Dormant ORC modules/export removal; no retained named caller found. Preserve historical manifests. |
| **SL9B** `3053409` | **Merge after orphan-command cleanup** | Source deletion is reasonable; agent-facing retirement is incomplete. |
| **SL9C** `9b4a1eb` | **Merge now** | Installed parser narrows to existing lanes; owner allowlist remains finite. Generic admission denial tests require D19 retirement approval. |
| **SL9D** `f935261` | **Merge now** | Removes inert public gateway entrypoint while retaining internal `OttoGateway`. Intentional packaging-contract reversal needs D19. |
| **SL9E** `32e069e` | **Merge now** | Both spellings map to the same destination; transport request IDs remain distinct. Tests prove parsing/forwarding, not a complete mutation replay. |

SL5 is a retention decision, not a code landing. SL6, SL7 and SL9 remain open.

**4. Canon conflicts since `163925e`.**

**Files touched by both branches: none.** Canon’s delta contains 18 paths; its implementation commits are READYPIN `1b1159d`, OWNERCOMPLETION `ec7c1b9`, FACADEFD `874553c`, CTLRACE `3581821`, and CAPTUREEDIT `67af2ae`/`cb439b3`.

Consequently, textual integration should be easy **at these reviewed tips**. That is an inference from disjoint paths, not a performed merge.

| Canon area | SLIM interaction | Integration difficulty |
|---|---|---|
| OWNERCOMPLETION: manager journey, owner composition | SL1 context; SL2 replacement; SL3 owner routing | Low textual; meaningful owner-path regression testing |
| READYPIN: owner readers | SL1/SL2 consume current assignment/task state | Low textual; preserve exact-pin tests |
| CAPTUREEDIT: adapter and nested operating-setup tests | SL2 execution admission | Low textual; explicitly run nested operating-setup tests |
| FACADEFD: command ports | CLI owner transport | Low textual; retain lifecycle/owner-route sweep |
| CTLRACE: `install/controller/manager_ctl.py` | SL9B’s remaining advertisement is in **root** `manager_ctl.py` | Different files; inspect ownership before the cleanup |

Recompute this intersection at every landing; unlanded PROGRAM work is not part of this result.

**5. Gate checks and D19 inventory.**

Run each required file **alone, twice**, on its rebased candidate, plus the automatically computed importer sweep, boundary check and exact-candidate staging startup/current-stage canaries. This follows [RUNBOOK §4](${TRANSFER_ROOT}/portfolio/RUNBOOK.md:62).

The exact files with recorded sandbox-blocked evidence are:

```text
tests/test_admit.py
tests/test_execution_operations.py
tests/test_host_startup_composition.py
tests/test_manager_journey_service.py
tests/test_otto_open_release.py
tests/test_otto_show_status.py
tests/test_owner_lane.py
tests/test_owner_manager_replacement.py
tests/test_portfolio_status.py
tests/test_project_advisor_delivery.py
tests/test_project_history.py
src/otto/portfolio/tests/test_direction_invocation.py
src/otto/portfolio/tests/test_observability_views.py
```

Run the **whole files**, not the previously passing subsets. Particularly important are the execution-operations progress-stream case, advisor-delivery `OwnerAdmissionTests`, actual owner `OwnerRouteTests`, and both new owner-manager-replacement regressions. The project records these outstanding checks at [PROJECT.md:201](${TRANSFER_ROOT}/source/projects/slim/.project/PROJECT.md:201); this review does not convert them into passes.

The task checks also include:

| Landing | Explicit focused files, in addition to the above applicable files |
|---|---|
| SL1 | `tests/test_manager_journey_service.py` |
| SL2 | `tests/test_manager_replacement_unit.py`, `tests/test_manager_continuity.py`, `tests/test_manager_handoff.py` |
| SL3 / SL9C | `tests/test_cli_read_routes.py`, `tests/test_owner_observability_cli.py` |
| SL4 | `tests/test_usage_contract.py`, restored reader regressions |
| SL7A | `tests/test_docs_supported_routes.py` |
| SL8 | `tests/test_status_friction.py`, corrected real-owner friction regressions |
| SL9A | `tests/test_orc_packet_retirement.py` |
| SL9B | `tests/test_advisor_host_retirement.py`, added parser-retirement regression |
| SL9D | `tests/test_packaging.py`, `tests/test_evidence_single_copy.py` |
| SL9E | `tests/test_request_key_alias.py` |

**The automatic sweep misses nested source tests.** Verified in `canon/main:ops/bootstrap/land.sh:286–319`. Explicitly include these importing files for the relevant landing:

```text
src/otto/portfolio/tests/test_direction_invocation.py
src/otto/portfolio/tests/test_direction_surface.py
src/otto/portfolio/tests/test_native_caller_ingress.py
src/otto/portfolio/tests/test_observability_views.py
src/otto/portfolio/tests/test_operating_setup.py
src/otto/portfolio/tests/test_project_onboarding.py
src/otto/portfolio/tests/test_reviewed_activation.py
src/otto/portfolio/tests/test_sessionless_help_return.py
src/otto/portfolio/tests/test_vision_pack_and_command.py
```

SL8’s replacement tests must cover actual retained issues/usage/completion dispositions, empty unsupported coverage, denied scope, lag and continuation beyond 200 rows. The current denied-read test does not exercise pagination despite its “incomplete” name.

**D19 must explicitly decide the following incumbent assertion changes.** Deleted-file line numbers below refer to **`163925e`**. These comprise **29 deleted tests / 114 assertion sites**, plus two replaced assertions. Ranges identify assertion start lines, not execution counts.

| Task | File and every removed/replaced assertion site |
|---|---|
| SL1 | `tests/test_project_advisor_context.py`: **56–61, 71, 79–81, 104–106, 109, 117**. Removes context/pairing, quiet supervision, correction provenance and escalation contracts. |
| SL4 | `src/otto/portfolio/tests/test_d05_events_candidate_proof.py`: **33–36, 46–51, 57, 61–62, 66, 71, 74, 90**. Approve obsolete candidate checks separately from the live-reader checks that must move. |
| SL4 | `src/otto/portfolio/tests/test_observability_contract.py`: **27–34, 37–44, 56, 69–72, 81, 83, 88, 98**. Retires frozen contract, bounds/reference and fixture-inventory assertions. |
| SL9B | `tests/test_manager_advisor_paused_host.py`: **49–51, 53–56, 60–66, 73–77, 94, 106–109, 115–117, 119, 121–122, 130–132, 139–141, 146–147, 151–152, 164, 181–185**. Removes binding, replay, custody/refusal, readback and parsing checks for the retired adapter. |
| SL9C | `tests/test_admit.py`: **254–257, 263–266, 274–276**. Removes the three generic-denial tests, including no-write/no-admission assertions. |
| SL9D | `tests/test_packaging.py`: old **34** required `otto-gateway`; new **34–35** require its entrypoint and source module to be absent. |
| SL2 | `tests/test_execution_operations.py`: old **220** allowed manager admission with `app=None`; new **223–225** supply `_current` and require its exact invocation. This strengthens generation checking while retaining the worker-rule exemption. |

Also submit SL1’s strengthened existing replacement test: new assertions at `src/otto/portfolio/tests/test_direction_invocation.py:226,227,229,230`, plus its draft/foreign-direction fixture changes.

The gate’s current D19 detector only examines **modified top-level test files with removed assertions** (`canon/main:ops/bootstrap/land.sh:131–137`). It misses whole-file deletions and nested tests. A gate that does not request these decisions is not evidence that they are exempt.

Within SLIM, `af9e7c8` also replaces ledger-test expectations, and `e7abf8f` replaces bare held-result assertions with guidance checks. Land each task’s **final corrected patch together**; if those intermediate versions land separately, their later expectation changes also need D19.

**Integration order through the program gate:**

1. Preserve SL0’s audit evidence outside the product landing; exclude `.project` run/status metadata from canon.
2. Land **SL1**, then corrected **SL4**, **SL9A**, corrected **SL9B**, and **SL9D** as separate tasks.
3. Land **SL3** with its owner-grant and usage-error repairs, separating SL8-specific hunks; then **SL9C**, **SL9E**, and corrected **SL7A**.
4. Land corrected **SL8** only after its real retained-data tests pass.
5. Coordinate **SL2** with PROGRAM MGR; optionally land its live final-admission guard separately now. Keep replacement consolidation, SL6, SL7 and budget closure open.

Use each merge’s task delta—not the entire ancestry of its merge commit—to prepare the individual landing. Every landing receives a fresh rebase, explicit D19 decisions, isolated checks, staging evidence and deletion accounting.