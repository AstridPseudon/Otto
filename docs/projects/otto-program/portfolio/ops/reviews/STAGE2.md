**Verdict: FAIL.** Stage 2 doesn't meet its own gate, so it shouldn't pass yet. The harness patches a product method, `LabFleet.remove`, which the gate note forbids. That patch also hides a defect that would make every real Claude worker that lands settle as `unknown`. Separately, a worker process leaked by an earlier stage-2 run is still running, and this run's census can't see it.

Order did hold in this run: Store times show A completed (19.203) before B was dispatched (19.373), and B completed (21.312) before C (21.494). But several PASS checks would pass even if their claim were false.

## Findings

**1. The lab-cleanup patch hides an ordering bug: real Claude workers that land settle `unknown`.**
- **What happens:** `done` removes the lab inside the worker's turn (`herzchen/fleet/landing.py:97-102`, ending in `shutil.rmtree` at `labs.py:492`). After the turn, the owner reads the worker's Write artifact from that lab (`otto/agents/claude_adapter.py:81-92`, called at `:463`, required for workers at `:36`). With the lab gone, the read fails and the turn returns `unknown` with `retry_allowed: False` (`:488-494`).
- **The patch:** `defer_fake_lab_cleanup` makes `LabFleet.remove` refuse, and `perch.sh:735` deletes the labs itself. That deletion runs before the leftovers snapshot (`:744`), and the snapshot never looks in `canon.otto-labs`, where owner labs live. So `labs-left-behind` can't fail.
- **Nothing recovers a failed removal:** `cleanup_pending` is read by nothing in `src/`, and `LabFleet.sweep` has no caller.
- **Why it matters:** stage 3's real workers would hit this on every landing. It also undoes WORKERSETTLE in practice.
- **Fix task (xhard):** remove a landed lab only after the turn's result capture has settled, retry `cleanup_pending` there, and sweep leftovers at owner start. Then delete both harness pieces.
  - Check 1: a unit test on the real owner with a fake Claude stream (Write, then `done`) settles completed, and the lab is gone afterwards.
  - Check 2: stage 2 `--fake` passes with no `LabFleet` patch.
- **Perch assertion:** `labs-left-behind` reads the owner's lab root (`canon.otto-labs`) before any harness cleanup.

**2. A worker survives a forced owner stop, and the census can't see it.**
- **Evidence:** pid 88024, a `perch-fake-claude.py --resume` from run `2-20261017T160156Z`, was still alive at my check (`ps`: 32:26 elapsed, ppid 1). Its root `/private/tmp/stf` is gone. That run's `staging-down.log` says `down: stopped (forced)`.
- **What the owner covers:** its timeout path does kill the process group (`claude_cli.py:433-437` calls `custody.terminate`). A forced stop skips that, and the worker runs in its own process group.
- **Why this run missed it:** `leaks()` only looks under this run's root, and the census compares before with after (`perch_report.py:958-966`). 88024 appears in both.
- **Why it matters:** in production, an orphaned worker can keep a model turn running with no owner.
- **Fix task:**
  - `staging.sh down` (forced path) and owner start each kill or report every live group recorded in the owner's `capacity-process-groups.json`, verified by birth time.
  - Check: a unit test that force-stops an owner with a held worker and finds the worker gone.
- **Perch assertion:** fail at start if any worker or `perch-fake-claude` process from any root is alive, naming it. At down, every recorded worker process group must be gone.
- **Operator action:** someone needs to kill 88024 now.

**3. Stage-2 checks that pass by construction.**
- `timeline-events` loops over `config["tasks"]`, which is `[]`, so it can't fail. The Store timeline also shows no landing, completion or lab events, though §16 requires them.
- `pool-and-manager-reserve-held`:
  - The owner runs default limits (worker 6, manager 6). The canary's `pool_limit 2` / `manager_reserve 1` are read only by the report, never applied (`product_service.py:49-57`).
  - The chain is strictly serial (peak 1), and no manager turn ran.
- `harness-pool-within-limit` counts `fake_worker.py` processes (`perch_report.py:573-576`). Stage-2 workers are `perch-fake-claude`, so its "peak 0" never read the owner's pool.
- `admitted-ready-dependency-order` uses a fixed `("A","B","C")` list and a literal `admitted: True` (`perch_report.py:429-442`). It reads no timestamps.
- `unadmitted-revision-refused` sends `admit` with a made-up revision. The owner answers `sheet_changed`, and the harness relabels that `unadmitted_revision`. No dispatch of content edited after admission is ever attempted.
- **Perch assertions:**
  - (a) In the Store, every dependent's `work.assignment.dispatched` comes after the prerequisite's completion observation.
  - (b) Apply the canary's limits through the product's `capacity` config. Make two independent tasks ready plus a manager turn; assert the second worker waits and the manager still starts.
  - (c) After admitting C, edit C's instructions. Assert the owner doesn't launch C, then that a metadata-only write still launches it.
  - (d) Feed `timeline-events` from the stage's own tasks, and require landed and completed events.

**4. Completion doesn't tie the cited evidence to the check that passed.**
- `WorkAssignments.complete` checks only that the cited `evidence_refs` are retained, which any owner-authority ref satisfies (`assignments.py:663-666`).
- The predicate verifies the accepted decision's pinned evidence, not the caller's citation. Map-form `evidence_hashes`, the form both the harness and the manager send, are never compared (`assessment/module.py:1262-1264`).
- With no required scope there is no gate at all (`:1142-1143`).
- The harness stand-in does checks the product doesn't (managed content, full verification, digest equal to the manifest).
- **Fix task:** completion requires the cited evidence to equal the accepted decision's evidence refs. It verifies each digest in either form, and refuses a governed task with no required scope. Check: unit tests where completion with another task's retained ref, or a wrong digest, is refused.

**5. A killed worker's custody fence never clears.**
- After the kill, `holds` still lists `worker-07fea8…` (`stage2-capacity-after-kill.json`). The slot itself was freed about 1 s after the kill by the owner's own process-exit path (`execution_host.py:402-407, 491-496`), not by a timeout or the harness.
- But `_capacity_holds` blocks installing a project view (`project_services.py:78`) and root direction changes (`execution_host.py:1778`).
- `Execution.release_capacity_failed_worker` has no caller in `src/`.
- **Why it matters:** after one killed worker, no second project can be activated on this owner. That breaks stage 5's run and the "zero activations refused" metric.
- **Fix task:** give the assigned manager a recovery command that settles the unknown worker and clears its fence. Scope the fence to its own project.
- **Perch assertion:** after the kill, a second canary project activates, or status names the action required.

**6. Descriptor growth per worker launch.** I checked this in code, not by measurement.
- `role_runtime` builds `LimitService(self.store)` on each call (`owner_bootstrap.py:1354`). That is a command facade, which creates a temp dir and a listening socket immediately (`command_ports.py:469`, `:342-347`). These close only at exit (`:445-461`).
- `role_runtime` runs once per `_execution` (`manager_journey_service.py:239`).
- FDLEAK's flat-count tests cover `direction_surface` and `dispatch_ready` only, and the census records no descriptor counts.
- **Fix task:** reuse one `LimitService` per owner, as FDLEAK did for direction bindings. Check: a test where 200 `role_runtime()` calls keep the descriptor count flat (+3).
- **Perch assertion:** owner `lsof -p` count before the first dispatch and after the last stays within a small bound.

**7. Manual launches record no dispatch.**
- Since AUTODISPATCHREC, the automatic path calls `WorkAssignments.dispatch` (`manager_journey_service.py:2393-2400`).
- Five manual paths don't: `run-worker`, `reroute`, `retry`, `start-retained-child` and ask continuation. They are still gated at start (`execution.py:1245`, which checks admission and readiness). The gap is the missing Store record, not an unadmitted start.
- **Fix task:** route every worker start through `dispatch()`. Check: one `work.assignment.dispatched` per launch, on each path.

**8. Real presence has never approved an admission.**
- OPERATOR-ADMIT acceptance 7 is unverified. The only real-Mac attempt returned `unavailable` (NSCocoaErrorDomain 4099), per its `worker.2.last.md:9`.
- `--fake` also fakes presence at stage 2 (`perch.sh:73-74`), while the header says only "fake worker".
- **Action (user at the Mac):** run the acceptance-7 probe, plus one stage-2 run with the real prover. Fix the `--fake` header.

**9. Lower-severity items.**
- **PACKLOAD:** the parity test is skipped, because Astrid isn't importable under `python3` or `/opt/homebrew/bin/python3.11`. Without `ASTRID_SOURCE_STATE`, `source_inventory_identity` differs from Astrid's by construction (`authoring.py:638-640`). Herzchen also hard-codes an Otto authority and a `Documents/Codex` path (`herzchen/usage/contract.py:30-38`). The boundary test checks only `otto` imports and fleet names.
  - Fix task: make the parity test runnable, or compare against a recorded Astrid record. Remove the Otto constants from Herzchen.
- **Legacy admission stamps:** stamps without `reviewed_digest` still admit edited bodies and instructions (`admission.py:145-149`). Current writers always include it; the gap matters at switch-over, on the old Store. Fix task: treat such stamps as unadmitted.
- **Creator fallbacks fail open:** `operator_actor or actor` (`herzchen_binding.py:489,1097,1589,2369`; `project_folder.py:249`) and `operator_actor or owner_actor` (`owner_bootstrap.py:663`). The hostctl owner always passes the operator, so this is latent. Fix task: refuse instead of falling back.
- **Fence nit:** `MacWriteScope` realpaths exec allowances without checking they are absolute (`claude_cli.py:207-210`). The fence rules themselves are literal (finding below).

## Sound
- The automatic pump checks admission and readiness on the current revision (`fleet/dispatch.py:93, 103, 127-133`). It is checked again before the provider call (`execution.py:1245`; `execution_operations.py:1327`). This run showed it in practice: C stayed `admitted` while B ran.
- The owner's `admit` makes one fresh presence check per request, with no reuse (`service.py:474`; `presence.py:30`). It writes as the operator, and the request can't name the actor or carry a presence field.
- Host lanes can't save as the operator (`bound_actor_mismatch`, `portfolio/cli.py:1093-1106`).
- The fake presence stub is reachable only through `staging.sh` with `OTTO_STAGING_*` set, and only from `perch.sh` stage 2 `--fake`. Nothing in `src/` selects it.
- One content comparator for task pins (`task_content_matches`), with digests always computed from payloads. `metadata_namespaces`, including the `otto.plan` repo, branch and route, count as content.
- The policy-basis admission check reads the historical policy revision, so later metadata writes don't break it.
- The landing applies one run policy (`fleet_landing.py:314-321`). The check receipt is captured as managed, fully verified evidence (`:266-281`).
- The worker fence allows only the realpath'd pins plus the Python.app re-exec target, each as a literal path. The target is derived from the path layout, not from anything the worker controls (`pins.py:20-51`; `claude.py:116-117`).
- Herzchen has no static or dynamic imports of `otto` or `astrid`.
- The fake worker calls `done` through the real token-checked worker socket. The completion stand-in calls the real `complete_task` and goes through the owner's checks.

## Not checked
- The owner log, which is kept only on failure, and the scratch Store, which is gone. Which release path freed C's slot is inferred from the ~1 s timing.
- Descriptor counts at runtime: finding 6 comes from reading code. I ran no tests or probes, under the read-only brief.
- The legacy gateway functions `run_due_occurrence` and `continue_admitted_occurrence`, which are exported but have no `src/` caller.
- Whether the lab-capture bug also affects Codex workers.
- How Seatbelt matches `literal` rules for symlinked exec paths.

## Delete list
- `defer_fake_lab_cleanup` and `stage2_cleanup_owner_labs`, once finding 1 is fixed.
- `otto/portfolio/successor_entry.py` and `successor_runner.py`: no callers or tests anywhere, and they relaunch a worker with no admission or readiness check.
- `cmd_sample`'s `fake_worker.py` pool counter for stage 2.
- The canary's `pool_limit` / `manager_reserve`, unless finding 3(b) applies them.
- The report header's check command: the canary actually checks with `/usr/bin/true`.
- Either wire or delete: `LabFleet.sweep` (no caller) and landing's `cleanup_pending` field (never read).

## Helpers (10, all `haiku-worker`)
1. Q1: traced the launch path from the pump to the worker and listed every launch caller.
2. Q2: admission path, presence checks per admission, fake-presence isolation, acceptance 7.
3. Q3: content comparators, crafted metadata, remaining exact-revision checks.
4. Q4: every completion path and its evidence checks, compared with the harness stand-in.
5. Q5: pool and reserve maths, the meaning of `holds`, kill release, capacity assertions; it also spotted pid 88024.
6. Q6: FDLEAK reuse, census method, TOOLING21-23, the order of lab removal and the leftovers check.
7. Q7: harness monkeypatches, the fake worker's flow, the stand-in compared with the real manager's completion.
8. Q8/Q9: PACKLOAD provenance field by field, Herzchen imports, the PYSTUB fence.
9. The code and data behind each stage-2 assertion, and the dispatch timestamps.
10. Post-turn reads of a deleted lab: found the `capture_artifacts` path behind finding 1.