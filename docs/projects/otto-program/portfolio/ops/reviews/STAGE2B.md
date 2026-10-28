1. **Verdict: FAIL.** Stage 2 still doesn't meet its own gate, which says it "passes only with no product method patched by the harness" (`PLAN.md:403`). The harness now completes tasks A and B by replacing a product method, and the killed worker's fence is never settled. Five of the prior nine findings are closed and the rest are partly closed or open; the product behaved correctly where this run tested it.

2. **Prior findings**
   1. **Lab cleanup order: closed.** LABCAPTURE (`4c413d7`) removed the lab deletion from `done`. The lab is now removed only after capture and acceptance (`owner_runtime.py:1137-1151` → `product_service.py:340-371` → `labs.py:426`). Leftover labs are swept at owner start (`product_service.py:373`). Both harness hooks are gone. A unit test covers Write, then `done`, then capture, with the lab gone afterwards (`test_external_owner_execution.py:236`). Still to do: `LabFleet.sweep` has no caller in `src/` (delete it).
   2. **Orphaned worker: partly closed.** ORPHANWORKER (`ac02366`):
      - A forced `down` now kills the recorded worker groups (`staging.sh:302`).
      - Owner start reaps recorded groups after checking birth time (`execution_host.py:1142`, `claude_cli.py:112-115`).
      - Perch fails at start if a fake worker is alive in any root (`perch.sh:734`).

      Still open:
      - The census only matches marker strings, so a real `claude` worker is invisible to it.
      - `down` never re-checks that the groups are gone.
      - No test runs `down()` against a held worker; the one test slices the helper out of the script.
      - This run's stop was clean, so the forced path didn't run.
   3. **Checks that passed by construction: partly closed.**
      - `timeline-events` now uses the stage's own tasks and requires dispatch, then landing, then completion.
      - The pool (1) and manager reserve (1) are applied through `installation.json`, and the contention read shows a worker and a manager active.
      - Dependency order is read from Store times.
      - A real edit after admission is now attempted.

      But completion is supplied by the product-method patch (new finding 1), and `worker-kill-recovery` doesn't check the fence (new finding 3).
   4. **Completion citations: closed on the write path.** COMPLETECITE (`c2bc556`) adds exact citation match, digest check and required scope (`assignments.py:709-758`). Still open:
      - The read-side predicate compares only list-form digests (`module.py:1262-1268`), so `completion_blockers` misses a wrong map-form digest.
      - A map whose keys aren't in canonical form falls back to matching by position (`assignments.py:~748`).
      - The map-form test uses a non-canonical key.
   5. **Killed worker's fence: partly closed.**
      - KILLFENCE and FAILEDFENCE added a manager `execution-control --operation recover` (`manager_journey_service.py:1614`, `execution_host.py:684-722`).
      - The fence is now scoped to its project for activation and worker admission (`project_services.py:84-88`, `execution_host.py:895-901`).

      Still open:
      - The root-direction gate still refuses on any hold (`execution_host.py:2132`).
      - Status shows the holds with no action (`project_service.py:485-497`).
      - This run ends with `holds: ["worker-1c0db…"]` and C `unknown`, its lab kept.
   6. **Descriptor growth: closed.** LIMITFD (`9b33101`) builds one limit service per owner (`owner_bootstrap.py:680-683`, used at `:1391`). A test makes 200 calls within +3. This run's owner `lsof` count was 46 before and 46 after.
   7. **Manual launches without a dispatch record: closed for the five named paths.** MANUALDISPATCH (`1b36ba7`) records the dispatch inside `_start` for every worker (`execution.py:1346`). The successor files are deleted. Gaps:
      - Ask continuation now records two dispatches per launch (new finding 4).
      - Only start-retained-child has a test counting dispatch events.
      - The legacy `run_due_occurrence` and `continue_admitted_occurrence` are still exported.
   8. **Real presence: open.** No real-prover approval is recorded anywhere, and every stage-2 run used `--fake`. The report header now says presence is faked (`report.md:7`), though the title still says "(fake worker)".
   9. **Lower-severity items: mostly closed.**
      - The parity test now runs against a recorded fixture with no skip, and Herzchen's contract is clean.
      - Admission stamps without `reviewed_digest` are refused (`admission.py:147`).
      - Exec allowances must be absolute paths (`claude_cli.py:237-243`).
      - One creator fallback remains: `operator_actor or actor` at `herzchen/domains/work/orchestration.py:187`.

3. **New findings** (most severe first)
   1. **The harness patches a product method to complete tasks.**
      - **Evidence:** `perch_stage2_owner.py:77-91` sets `_OwnerExecutorPort.call = finish_after_landing`. After a landed `worker-done`, it calls `portfolio.complete_task` as the manager (`:61-68`). The fake manager turn does nothing except print "PERCH manager turn complete" (`perch_fake_claude.py:125-130`). The Store then credits these completions to the manager (`perch-stage2-complete-A/B`).
      - **Why it matters:** the dependency order (C dispatched 33.807, after B completed 31.164), the pool check and the timeline's completion events all rest on a completion the product never started. Completion runs inside the landing call, so the gap between landing and completion, where OWNERCOMPLETION-class defects live, is never exercised. Citations are copied from the accepted decision (`:41-53`), so the new completion checks pass by construction.
      - **Fix (row):** the scripted manager turn (the model stand-in) completes A and B through the manager's real completion command when the owner wakes it. Then delete `install_fake_completion`.
      - **Perch assertion (§17.5):** a test that scans `ops/bootstrap/*.py` for assignments to product attributes and allows only `presence.LocalAuthenticationProver`. Also require each completion event to belong to a manager turn the owner started.
   2. **Time limits remain, against §17.5 and beyond the PERCH2C ruling.** The ruling named three deadlines, and those are gone. These still fail the stage:
      - 180 s on admission (`perch.sh:289, 306-335, 242-258`)
      - 180 s on dispatch (`:497-561`)
      - 45/30/45 s in the kill step (`:566-601`)
      - a 90 s socket timeout inside the stand-in (`perch_fake_claude.py:47`), which `test_perch.py:811` asserts
      - **Fix (row):** convert each to an untimed poll that ends on the evidence or on owner death, like `stage2_wait_marker` (`:363-374`). Extend the deadline-absence test at `test_perch.py:1313` to every `stage2_*` function and the stand-in.
   3. **The stage claims the manager settles the killed worker's fence, but nothing does.**
      - **Evidence:** after the kill, every status snapshot still lists `holds: ["worker-1c0db…"]` with the schedule `active`. C ends `unknown`/pending with no next action. `worker-kill-recovery` reads only `active_or_uncertain` (`perch_report.py:397-416, 1790-1794`).
      - **Risk:** `recover` accepts a worker only if it has a retained terminal `unknown` result with code `authorized_result_unverified` (`worker_custody.py:133-160`). Its test fakes that record; whether a SIGKILLed worker produces one is never shown.
      - **Fix (disturbance step):** after the kill, the scripted manager runs `recover` on C's schedule.
      - **Invariant (b):** at the end, `holds` is empty or status names each hold's next action.
      - **Fix (row):** status names the action for each hold, and the root-direction gate is scoped by project.
   4. **Ask continuation records two dispatches per launch** (plausible, from reading code).
      - **Evidence:** `continue_from_answer` dispatches with key `answer-session:…:dispatch` (`execution.py:2059-2060`). The new occurrence has no `launch_request` (`:650-659`), so `_start` dispatches again under `execution-start:<schedule>` (`:1262-1264, 1346`). `dispatch` removes duplicates only by key (`assignments.py:857-868`).
      - **Fix (row):** give `_start`'s fallback key the same request key, and add a one-event-per-launch test for run-worker, reroute, retry and ask.
      - **Invariant (a) in perch:** count launched worker schedules against dispatch events. Today no check counts launches.
   5. **Status shows the edited C as `admitted`.** Before re-admission, C reads `dispatch.state: "admitted"` with reason null (`stage2-edited-C-no-launch.json`), yet the owner won't launch it. An operator would wait forever.
      - **Fix (row):** status reports that re-admission is needed when a stamp no longer matches the current content.
      - **Perch:** the no-launch snapshot must name that reason.
   6. **Check gaps.**
      - No doctored-input test for `worker-kill-recovery`'s other two branches (worker absent, owner survived), for `stage2-census`'s killed-worker-still-present branch, or for `no-leaked-process` on stage-2 evidence.
      - The +3 descriptor bound over three dispatches would let a leak of one descriptor per dispatch pass. Require an equal count per descriptor type, or loop more operations.

4. **Answers to the five questions, and what I didn't check**
   - **Sound (Q4):**
     - The Store times give one dispatch per task, in the right order: A at 22.225; B at 28.908, after A completed at 27.990; C at 33.807, after B completed.
     - The edited C stayed unlaunched: the owner was idle at 33.150, two seconds after B completed, and dispatched C 0.38 s after re-admission at 33.430.
     - With pool 1, the second worker waited while the manager ran.
     - No process was left after down, labs A and B are gone, and the 39 stage-2 perch tests pass.
   - **Q5:** not yet. The runtime is acceptable: about 19-47 s per run (28 s for this one, 103 s for one early failed run), against about 12 s for stages 0 and 1, and landings already take 28-1451 s, mostly the test sweep. But gating now would add the product patch and the 180 s limits to every landing. Gate stage 2 once new findings 1-3 are fixed and SESSIONFD has landed; SESSIONFD is in the stage row and `requests.md:1385` says it gates stage 2.
   - **Not checked:**
     - Real Claude workers (stage 3).
     - Whether `recover` accepts a SIGKILLed worker.
     - The double dispatch, which I didn't run.
     - Whether lifecycle `_deliver_role` launches a worker without a dispatch.
     - The staged tree itself (I read canon at `8c2641d`, whose harness matches `825843c`).
     - Any tests beyond the stage-2 perch tests.
   - **Helpers:** 11 `haiku-worker`, one each for prior findings 1, 2, 4, 5, 6 and 7, one for 8 and 9 together, plus the doctored-input tests, harness patches and time limits, runtime, and the run's Store evidence. I checked the completion patch, the deadlines, the fence data, the recovery requirements and the double-dispatch path in the source myself.