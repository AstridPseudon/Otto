**Do not integrate THROUGHPUT wholesale or mark its goal complete.** Review snapshot: `proj/throughput` at `8e2a97c`; canon advanced during review to `b635c93`. I delegated to three Luna reviewers and one Sol reviewer, then checked the findings myself. No tests or Otto services were run.

The [goal](${TRANSFER_ROOT}/source/projects/throughput/.project/agent_goal.md:3) is unmet: caching and the warm renderer are absent; feedback latency and heavy seconds per accepted task are unmeasured; the runner report has not demonstrated a reduction. The project [discloses these limitations](${TRANSFER_ROOT}/source/projects/throughput/.project/after.md:21). Deferring unmeasured caching was sensible, but it is deferred delivery. The cold-agent exercise was code inspection, explicitly **not an executed journey** ([ux.md:3](${TRANSFER_ROOT}/source/projects/throughput/.project/ux.md:3)).

| Task | Recommendation | Required disposition |
|---|---|---|
| **TP1 — `60600a3`** | **Merge after fixes** | Pin the measurement inputs; correct interrupted-run pairing; generate the reported statistics reproducibly. |
| **TP3 — `afff5cf`, `7b0e012`, `b109ce0`, `919407f`** | **Merge after fixes** | Integrate these together, after correcting command recognition and incomplete change selection, with service-level coverage. |
| **TP6 — `7085a26`** | **Merge after fixes** | Update the broken existing test through D19 and preserve refusal guidance through MCP listing. |
| **TP5 — `eb82164`** | **Drop the current standalone code landing** | Retain the report as audit evidence; delete its prose-matching test. Reopen actual before/after measurement work. |
| **TP2 / TP4** | **No landing** | They are blocked, not implemented. Keep them open; neither should count toward completion. |

**Defects and test quality**

1. **TP6 introduces a definite existing-test failure.**  
   [tests/test_tools.py:91](${TRANSFER_ROOT}/source/projects/throughput/tests/test_tools.py:91) compares the revoked-token refusal with the exact old three-key dictionary. [_refusal:96](${TRANSFER_ROOT}/source/projects/throughput/src/herzchen/fleet/tools/facade.py:96) now adds `next_action`. The equality therefore fails independently of sandbox permissions. This is a source-established failure, not a test result from this review.

   Update the expected response while retaining the authorization assertions. **That expectation change requires an Opus D19 decision naming `tests/test_tools.py`.** The recorded TP3 tools-suite results predate TP6 and do not validate the final branch.

2. **TP6’s recovery instruction disappears on the worker’s listing path.**  
   The facade supplies stale-token guidance, but [stdio_server.py:52](${TRANSFER_ROOT}/source/projects/throughput/src/herzchen/fleet/tools/stdio_server.py:52) turns every unsuccessful listing response into `{"tools": []}`. A worker listing tools with a revoked token sees no recovery instruction. This adapter behavior predates TP6, but prevents its new guidance from reaching that user path.

   Preserve the refusal and recovery information in the MCP error response and cover that transport path. The new tests only call the facade directly ([test_worker_refusal_next_action.py:23](${TRANSFER_ROOT}/source/projects/throughput/tests/test_worker_refusal_next_action.py:23)).

3. **TP3 can rewrite commands that are not pytest invocations.**  
   [landing.py:390](${TRANSFER_ROOT}/source/projects/throughput/src/herzchen/fleet/landing.py:390) treats any argv element equal to `pytest` as sufficient. **Code-derived failing scenario:** an admitted `["make", "pytest", "tests"]`, with an importing test selected, becomes a different set of Make targets because [lines 487–490](${TRANSFER_ROOT}/source/projects/throughput/src/herzchen/fleet/landing.py:487) remove `tests` and append test filenames. Conversely, `/venv/bin/pytest` bypasses narrowing.

   Recognize bounded supported invocation forms—direct pytest executables and Python’s `-m pytest`—and preserve unsupported commands.

4. **TP3 can omit tests affected by the changes.**  
   These are code-derived scenarios, not executed reproductions:

   - **Source rename:** [landing.py:415](${TRANSFER_ROOT}/source/projects/throughput/src/herzchen/fleet/landing.py:415) discards the old path. Rename `src/pkg/old.py` to `new.py`, update one test to import `new`, and leave another importing `old`: the updated test is selected, while the broken old importer disappears from feedback. Retain both source-module identities; filter nonexistent paths only when choosing runnable test files.
   - **Shared configuration:** [landing.py:432](${TRANSFER_ROOT}/source/projects/throughput/src/herzchen/fleet/landing.py:432) ignores `pytest.ini`, `pyproject.toml` and `tests/conftest.py`. Change one alongside a source file that yields selected tests, and the selector drops other tests affected by the shared configuration. Fall back to the admitted command for such changes.
   - **Import/layout limits:** the parent-import regex excludes multiline imports, and discovery scans only top-level test files ([landing.py:451](${TRANSFER_ROOT}/source/projects/throughput/src/herzchen/fleet/landing.py:451)). Document and conservatively handle unsupported cases instead of silently treating the selected set as complete.

   The three new selection tests call `_feedback_argv` directly ([test_landing.py:332](${TRANSFER_ROOT}/source/projects/throughput/tests/test_landing.py:332)). They would still pass if the actual integration call at [landing.py:64](${TRANSFER_ROOT}/source/projects/throughput/src/herzchen/fleet/landing.py:64) were removed. Add a service-level assertion that `check` submits narrowed argv and `done` submits the original admitted argv.

   **Positive finding:** `done` still reloads the admitted task and runs its full check ([landing.py:75](${TRANSFER_ROOT}/source/projects/throughput/src/herzchen/fleet/landing.py:75), [landing.py:118](${TRANSFER_ROOT}/source/projects/throughput/src/herzchen/fleet/landing.py:118)). I found no acceptance-custody weakening in this diff.

5. **TP1’s baseline is not durably reproducible.**  
   [baseline.md:3](${TRANSFER_ROOT}/source/projects/throughput/.project/baseline.md:3) points to a live glob while recording 103 logs. My read-only recount found 104. For example, OWNERCOMPLETION subsequently added a 45-second hostctl pair ([land.out:58](${TRANSFER_ROOT}/portfolio/ops/runs/OWNERCOMPLETION/land.out:58)), changing that aggregate from **25 pairs / 3,394 seconds** to **26 / 3,439**. This is snapshot drift, not evidence of fabricated original figures. Pin the source set and captured contents or timestamp boundaries.

   There is also a latent pairing defect: [throughput_report.py:31](${TRANSFER_ROOT}/source/projects/throughput/ops/bootstrap/throughput_report.py:31) pairs occurrences by fixed offsets. An interrupted/retried sequence `1,1,2` loses the valid latter interval. Pair within landing attempts and report incomplete runs. I did not observe this sequence in the inspected current inputs.

6. **TP5’s test is an unnecessary maintenance burden.**  
   [test_throughput_after.py:7](${TRANSFER_ROOT}/source/projects/throughput/tests/test_throughput_after.py:7) checks hard-coded numbers and sentences. It cannot detect disagreement with logs, incorrect calculations or missing throughput improvement. Delete it. The report’s task accounting also omits TP5’s own `+62/-0`; regenerate the final ledger from actual program landings.

No newly added tests use sleeps or elapsed-time thresholds. The selector tests and refusal tests are useful unit checks, but provide no latency or live-journey evidence. The reports acknowledge that; I found no basis to allege deliberate dishonesty. Zero retired source paths is also disclosed. There is no evidenced justification here for deleting the runner, gate or heavy-work machinery.

**Canon conflicts**

At `b635c93`, `git log --oneline 163925e..canon/main` contains READYPIN (`1b1159d`, `eb9b6cd`) and OWNERCOMPLETION (`ec7c1b9`, `b635c93`).

| Canon landing | Files changed since the base | Shared with THROUGHPUT |
|---|---|---|
| READYPIN | `owner_bootstrap.py`, `owner_readers.py`, portfolio `test_operating_setup.py`, `test_completed_occurrence_readiness.py` | **None** |
| OWNERCOMPLETION | `hostctl/serve.py`, `execution_host.py`, `manager_journey_service.py`, `test_execution_host_manager_turn_queue.py` | **None** |

Thus **every THROUGHPUT task has low textual merge difficulty against this snapshot**. That does not establish runtime compatibility. Recheck the intersection before each landing because canon is actively advancing.

**Integration order**

1. **TP1, corrected**, as the measurement foundation.
2. **TP3’s complete net change**, including all three existing review fixes and the fixes above, as one landing.
3. **TP6, corrected**, with its D19 decision and MCP-path coverage.
4. **Replacement measurement work for TP5**, after comparable before/after runs exist. Record feedback latency, heavy execution per accepted task, workload/commit identity, and the actual cold-worker journey. Keep TP2/TP4 explicitly unresolved.

Each is a separate program landing: rebase onto current canon, run its concrete check, run affected files alone twice, establish regression failure on base, pass placement/boundary checks, and run staging on the exact tested commit before merging and generating deletion accounting ([RUNBOOK.md:62](${TRANSFER_ROOT}/portfolio/RUNBOOK.md:62)). The current [stages-gated](${TRANSFER_ROOT}/portfolio/ops/stages-gated) contains `0 1`; the gate reads that list ([land.sh:439](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:439)). Passing those stages must not be recorded as completion of the unexecuted worker UX journey.