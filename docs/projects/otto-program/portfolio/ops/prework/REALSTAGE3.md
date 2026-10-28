## 1. Implementation design

1. [tests/test_perch.py:734](${TRANSFER_ROOT}/source/otto/tests/test_perch.py:734) → Write the Due regression test below first. Add separate doctored owner-record cases for every new stage 3 assertion: lab count and measurements, facade calls, runner checks and heavy-unit overlap, verified landing evidence, Haiku provenance, and terminal Due state. Add a real-run acceptance check that inspects the resulting report; unit fixtures alone cannot prove a Claude run.

2. [ops/bootstrap/canary/project.json:45](${TRANSFER_ROOT}/source/otto/ops/bootstrap/canary/project.json:45) → Add stage 3 with three admitted `normal` tasks on `toy`: A and B independent, C dependent on both. Give A an explicit edit to existing `toy/mathx.py`; put B in a different file to avoid a merge conflict. Give each task a concrete typed check that tests its requested behavior. A passing `/usr/bin/true`, as stage 2 uses, is insufficient.

3. [ops/bootstrap/perch_report.py:129](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:129) → Parameterize the existing bundle and plan-save construction for stage 2 or 3. Stage 3 gets its own project/run ID, execution brief, task instructions, checks, and `worker_normal` binding to `claude-haiku-5-5`; preserve stage 2’s current output and assertions.

4. [ops/bootstrap/perch.sh:70](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:70) and [perch.sh:618](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:618) → Create the toy checkout before restarting the stage 3 owner and pass it through the existing canary repository mapping. Use the ordinary owner entrypoint and the real, pinned Claude launcher. Reuse the owner registration, activation, exact-revision admission, and retained-request polling path at [perch.sh:168](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:168), with stage-specific inputs; do not copy that shell flow.

5. [ops/bootstrap/perch.sh:335](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:335) → After admission, start the prepared Haiku manager through the owner’s normal manager route. Its brief directs it to review and finish landed work using owner evidence. Poll owner project status and full project schedules until each task lifecycle is `completed` and its worker Due has `completion_state=succeeded` and `stop_state=completed`. Preserve any `unknown` or `failed` Due and its owner reason as a stage failure. These are state checks; recorded durations have no passing threshold.

6. [src/otto/hostctl/product_service.py:565](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:565) → On the owner’s **create** branch, retain one lab record bound to project, task, and assignment: creation start/end, elapsed time, path, and measured bytes. Record the size rule (for example, apparent bytes of regular files including `.git`) and require exactly one creation record per task. Do not derive these measurements later from perch events or filesystem timestamps.

7. [src/herzchen/fleet/tools/facade.py:169](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/tools/facade.py:169) and [src/otto/hostctl/product_service.py:427](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:427) → Retain an owner audit entry for each authenticated `task`, `check`, and `done` call, bound to the assignment and its result. Keep `FeedbackLedger`’s check-feedback meaning intact. The stage requires the actual call sequence; the current in-memory check ledger cannot supply it after shutdown.

8. [ops/bootstrap/perch_report.py:938](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:938) and [perch_report.py:1479](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:1479) → Add mandatory stage 3 assertions over copied **owner** records. Join each task’s exact admission, assignment, Due, lab, facade calls, and landing candidate. For every facade `check`, resolve one verified sealed runner record ([runner/store.py:116](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/runner/store.py:116)); require matching lab commit, successful settlement, positive heavy units, and overlapping runner units within owner headroom. Verify the landing’s managed evidence at full digest and length against that runner receipt ([fleet_landing.py:232](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/fleet_landing.py:232)). Require owner Due/model evidence for real Haiku workers. Missing prerequisites fail these assertions; they do not skip.

9. [ops/bootstrap/perch.sh:712](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:712), [perch.sh:745](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:745), and [perch.sh:807](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:807) → Route stage 3 exclusively through the owner, capture the owner records before teardown, render their identities and failure reasons, and allow `perch.sh 3` without `--fake`. A `--fake` run must never satisfy the real-worker verdict. The worker should finish with an actual non-fake orchestrator run and its report showing the owner was reached and all three Dues completed.

## 2. Failing test to write first

Add this method to `AssertionKindTests` in [tests/test_perch.py:225](${TRANSFER_ROOT}/source/otto/tests/test_perch.py:225). It specifies `stage3_due_failures(dues, expected) -> list[str]`, called by the stage verdict on full owner schedule records.

```python
def test_stage_three_rejects_unknown_or_failed_owner_due_with_reason(self):
    task = {"authority": "owner", "kind": "work.task",
            "id": "task-A", "revision": "rev-A"}
    assignment = {"authority": "owner", "kind": "wrk.assignment",
                  "id": "assignment-A", "revision": "rev-A"}
    expected = {"A": {"task_ref": task, "assignment_ref": assignment,
                      "schedule_id": "due-A"}}
    completed = {
        "schedule_id": "due-A", "role": "worker",
        "target": {"task_ref": task}, "assignment_ref": assignment,
        "requested_model": "claude-haiku-5-5",
        "completion_state": "succeeded", "stop_state": "completed",
        "last_result": {"outcome": "succeeded"},
    }
    self.assertEqual(perch_report.stage3_due_failures([completed], expected), [])

    for state in ("unknown", "failed"):
        with self.subTest(state=state):
            doctored = json.loads(json.dumps(completed))
            doctored["completion_state"] = state
            doctored["last_result"] = {
                "outcome": state, "reason": "owner gateway lost the worker result"
            }
            failures = perch_report.stage3_due_failures([doctored], expected)
            self.assertEqual(len(failures), 1)
            self.assertIn("A", failures[0])
            self.assertIn(state, failures[0])
            self.assertIn("owner gateway lost the worker result", failures[0])
```

## 3. What to delete

Remove stage 3 from the direct fake-worker route at [perch.sh:712](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:712); it must have no `run_task` fallback or synthetic worker-event verdict. Do not add a second copy of stage 2’s setup and polling functions. Keep stage 2’s fake manager stand-in isolated from stage 3.

## 4. Plausible mistake

A worker could make green `events.tsv` lines or accept a fake Claude response while the real worker Due settles `unknown`. The test requires the exact owner Due’s terminal state and reason; the stage assertion joins it to the admitted assignment, so harness events and fake output cannot turn that run green.

## 5. Existing test expectations and D19

**None should change.** Add tests and retain stage 2 and stage 4 expectations. If implementation instead removes the stage 2 fake completion hook, the assertions in [tests/test_perch.py:1257](${TRANSFER_ROOT}/source/otto/tests/test_perch.py:1257), [test_perch.py:1420](${TRANSFER_ROOT}/source/otto/tests/test_perch.py:1420), and [test_perch.py:1459](${TRANSFER_ROOT}/source/otto/tests/test_perch.py:1459) change and need a written D19 decision.

## 6. Row corrections on `canon/main`

The two cited blockers are current: stage 3 is absent from [project.json:5](${TRANSFER_ROOT}/source/otto/ops/bootstrap/canary/project.json:5), and [perch.sh:809](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:809) rejects non-fake stage 3. The canary actually declares **0, 1, 2, and 4**. The row’s “facade ledger” and owner lab creation time/size are not existing durable records: [rules.py:87](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/tools/rules.py:87) retains check feedback only in memory, and [labs.py:301](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/labs.py:301) returns a lab without those measurements. `PLAN.md §16` is not present in tracked `canon/main`, so its wording could not be checked there.

No files were changed and no tests or Otto commands were run.