## REALSTAGE4 implementation design

All line numbers below are from `canon/main`. This is a design only; I made no changes and ran no tests or owner commands.

### 1. Changes, in order

1. `tests/test_perch_stage1.py:349` → Add the failing test below before changing the harness. Follow it with doctored-input cases that independently remove or duplicate a `done` attempt, change a runner commit, remove capture evidence, delete the refused lab, and replace the refusal with a success. Each corresponding assertion must turn red.

2. `ops/bootstrap/canary/project.json:72-77,94-107` → Define three Stage 4 tasks: one independent happy task and two workers that edit the same slot from the **same base commit**. Admit and dispatch both conflicting workers before either lands. One then lands; the other receives a rebase-conflict refusal. Add the repository, branch, typed test command, assessment policy, and owner Store expectations needed for real dispatch. The current fixture has only one conflict worker and expects an empty Store.

3. `ops/bootstrap/perch_report.py:129-189` and `ops/bootstrap/perch.sh:168-224,262-411` → Reuse Stage 2’s bundle, registration, activation, operator admission, and retained-status flow for Stage 4. Give Stage 4 workers the toy repository’s actual test command, rather than Stage 2’s `/usr/bin/true`. Keep the three tasks independent so landing does not depend on the Stage 2 fake manager-completion patch.

4. `ops/bootstrap/perch.sh:72-87,684-716,807-810` → Start the mapped canary repository with the owner; dispatch Stage 4 through that owner in both modes. Under `--fake`, use the existing fake Claude launcher as the model stand-in. Without it, use real workers. Coordinate the two conflicting edits so both labs are based on the same line commit; release their `done` calls in sequence. Wait on owner states, with a watchdog only for a hang. Remove the explicit non-fake Stage 4 rejection.

5. `ops/bootstrap/perch_fake_claude.py:20-38,41-126` → Teach the fake model the Stage 4 task briefs and edits. Preserve the actual owner tool reply to `done`, including `{ok: false, error: "owner_unavailable", detail: "LandingError: rebase conflict; ..."}`. Do not turn that expected refusal into an invented harness event. The product’s facade currently formats `LandingError` this way (`src/herzchen/fleet/tools/facade.py:218-230`).

6. `ops/bootstrap/perch.sh:726-760` and `ops/bootstrap/perch_report.py:613-626` → Capture, before shutdown, each owner `done` reply, assignment and task identity, captured worker result, sealed runner receipt, line commit immediately after each successful landing, and lab state. Read runner receipts through the product’s `ResultStore`, not unchecked JSON. Preserve the refused lab and its repository after the report. The later final line HEAD cannot stand in for each earlier landing commit.

7. `ops/bootstrap/perch_report.py:62-66,938-959,1497-1530,1540-1612` → Judge Stage 4 from those owner records in fake and real modes. Require exactly one owner `done` landing attempt for each task; exactly two successes and one refusal; for each success, `runner_run_id` resolves to a passing sealed record whose `commit` equals that landing result’s `commit` **and the line commit captured at that landing**. Require successful labs removed only after exact worker-result capture. Require the refused `done` reply to name the conflict, no line advancement from that attempt, and that worker’s lab still present. Scope leftover and at-rest checks to allow precisely that retained lab, while still rejecting other residue.

8. `ops/bootstrap/perch_report.py:726-742,1770-1812` → Seed faults in owner evidence rather than deleting synthetic TSV event names; render the owner replies, commits, runner IDs, capture state, and retained lab in the report.

### 2. First failing test

Add to `StageFourLandingAssertionTests` in `tests/test_perch_stage1.py`:

```python
def test_fake_harness_events_cannot_stand_in_for_owner_landings(self):
    raw = self._raw()
    # _raw includes fabricated owner-* TSV events, but no owner landing,
    # captured worker result, or sealed runner receipt.
    got = {row["name"]: row for row in report.assertions(raw)}
    self.assertEqual(got["timeline-events"]["status"], "pass", got)
    self.assertEqual(got["owner-driven-canary"]["status"], "fail", got)
```

It fails now because `owner-driven-canary` is skipped in fake mode (`perch_report.py:1515-1519`). It also prevents a superficial fix that merely removes the skip and trusts the fixture’s forged `owner-*` rows.

### 3. Delete

Delete Stage 4’s use of `run_task` and its shell `git merge`/conflict injection (`perch.sh:524-581,712-716`); keep that helper only where older stages still need it. Delete the conflict lab-deletion requirement (`perch_report.py:65-66,1522-1527`), the fake-mode owner skip, and the Stage 4 “not wired” notes (`perch.sh:684-697`). Replace the direct fake-worker merge test at `tests/test_perch_stage1.py:433-471` with owner-evidence tests.

### 4. Plausible mistake

The worker could leave the shell merge as the effective landing, emit convincing timeline rows, and then delete the refused lab. The first test rejects those rows without a product landing. The follow-on mutations reject missing or duplicate owner attempts, a runner checked on another commit, cleanup without captured evidence, and a deleted refused lab.

### 5. Existing expectations requiring a D19 decision

- `tests/test_perch_stage1.py:381-421`: fake owner proof changes from `skip` to a required result; a refused lab changes from “deleted” to “kept.” The fabricated owner rows in its fixture must cease counting as proof.
- `tests/test_perch_stage1.py:424-471`: the two-task project and direct shell-merge expectations change to the three-task owner scenario.
- `tests/test_perch.py:1708-1725`: fake Stage 4 must pass owner-backed assertions and retain the refused lab; the seeded conflict fault must corrupt owner evidence and fail its dedicated assertion.

The written D19 decision should name both test files and explain these expectation changes.

### 6. Row details stale on `canon/main`

`perch.sh:809` currently **rejects** Stage 4 without `--fake`; it does not reach an unwired owner run. The fixture has one happy and one conflict task, not two workers conflicting with each other. The product fast-forwards to the rebased, checked lab commit (`src/herzchen/fleet/landing.py:211-225`), so “merged commit” means that exact line commit, not a new merge commit. A rebase conflict happens **before** the landing check (`landing.py:102-120`), so the refused attempt need not have a passing runner record. No `PLAN.md` or REALSTAGE3/4 document is tracked on `canon/main`; I could not verify the cited §16 there.