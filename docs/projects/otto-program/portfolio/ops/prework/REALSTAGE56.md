## REALSTAGE56 design

`canon/main` is `97f5f9702c9efbc6ccdc62c1820804590aea9b34`. This is an implementation design only; I made no changes and ran no tests or Otto commands.

1. [tests/test_perch.py:190](${TRANSFER_ROOT}/source/otto/tests/test_perch.py:190) → Add the failing verdict test below first. Follow it with a green raw-evidence fixture and one mutation per claim: remove the manager wake; change the resumed native session; show a launch against a changed, unadmitted revision; remove either actual landing; and switch otherwise valid evidence to fake mode. Each mutation must fail its named verdict. Add a real campaign test with an external watchdog used only to detect a hang.

2. [ops/bootstrap/canary/project.json:5](${TRANSFER_ROOT}/source/otto/ops/bootstrap/canary/project.json:5) → Declare separate stages 5 and 6. Stage 5 names the management scenarios and two projects activated before the first manager start. Stage 6 names two genuine Otto program tasks and their checks, not toy-canary edits. Pin both reports to one selected candidate SHA, installation identity and campaign ID; stage 6 refuses a missing or different stage-5 predecessor.

3. [ops/bootstrap/perch.sh:72](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:72), [staging.sh:226](${TRANSFER_ROOT}/source/otto/ops/bootstrap/staging.sh:226) → Extend the existing staging bootstrap to map the disposable candidate checkout and retain its Store through the stage-5 drain/restart and stage-6 run. Capture owner generation, exact project and task refs, request IDs, Due records and native session IDs before and after restart. A restart within the campaign must not wipe that Store.

4. [ops/bootstrap/perch.sh:144](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:144), [perch.sh:584](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:584) → Drive stage 5 through cold authenticated client commands and the normal owner service: register and activate both projects, wake the manager, carry one worker ask through an owner answer into its **same** native session, observe an actual failed check and one bounded REWORK/repair, then revise an admitted task and prove the stale launch is refused before a provider call. Drain one project while preserving the other; restart and reconcile the exact retained occurrences. Keep each command’s raw receipt and the owner’s corresponding Store/status observation. Do not use the stage-2 fake owner entrypoint as evidence.

5. [ops/bootstrap/perch.sh:712](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:712), [perch.sh:744](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:744) → Drive stage 6 through real manager and worker dispatch. Require two task results, passing checks, accepted candidate/gate and completion refs, and two distinct landed commits descended from the pinned base. Preserve a verifiable Git object artifact before scratch cleanup; cross-check its commits against owner landing receipts. Record cold-client project/document reads, the available read-only preview, and the actual save receipt. A report string or harness event cannot establish a landing.

6. [ops/bootstrap/perch_report.py:938](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:938), [perch_report.py:1479](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:1479), [perch_report.py:1628](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:1628) → Add explicit, separate `stage5-*` and `stage6-*` assertions over those raw product receipts, Store records and Git objects. Missing evidence, a skipped scenario, `fake:true`, an unmatched SHA or an unresolved retained request is **fail**, never pass or skip. Keep elapsed durations in diagnostics, not acceptance predicates.

7. [ops/bootstrap/perch.sh:789](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:789), [perch.sh:803](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:803) → Accept real stages 5 and 6 and propagate either stage’s red verdict. The external `otto-program/ops/stage-run.sh:34` should select one exact candidate, invoke both stages in order, retain their separate reports and fail cutover if either is red. That wrapper is absent from this repository’s `canon/main`, so its exact edit needs verification in its own source.

8. [ops/bootstrap/perch_report.py:1770](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:1770) → Render candidate SHA, campaign ID, mode, links to raw receipts and each stage’s verdict. Report real token/cost evidence where recorded; remove the unconditional statement that the worker was fake.

## First failing test

Add to `tests/test_perch_real_stages.py`. It fails on current `canon/main` because none of the required verdicts exists. It deliberately supplies “ran” notes and harness events, but no owner evidence.

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "bootstrap"))
import perch_report  # noqa: E402

VERDICTS = {
    "5": (
        "stage5-real-origin",
        "stage5-manager-wake",
        "stage5-ask-answer-session",
        "stage5-bounded-rework",
        "stage5-changed-admission-refused",
        "stage5-two-project-drain-restart",
    ),
    "6": (
        "stage6-real-origin",
        "stage6-two-program-landings",
        "stage6-cold-client-read-preview-save",
    ),
}

class RealStageVerdictTests(unittest.TestCase):
    def test_claimed_real_stages_fail_without_product_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            for stage, names in VERDICTS.items():
                for fake in (False, True):
                    with self.subTest(stage=stage, fake=fake):
                        raw = Path(folder) / f"{stage}-{fake}"
                        raw.mkdir()
                        (raw / "config.json").write_text(json.dumps({
                            "stage": stage, "fake": fake,
                            "staging_restart": 0, "tasks": [],
                            "scenarios": ["real-management" if stage == "5"
                                          else "real-dogfood"],
                            "pool_limit": 1,
                        }), encoding="utf-8")
                        (raw / "notes.json").write_text(json.dumps({
                            "real-management": "ran", "real-dogfood": "ran",
                        }), encoding="utf-8")
                        (raw / "events.tsv").write_text(
                            "2026-10-17T00:00:00Z\tT1\t"
                            "owner-dispatch-launched\tclaimed by harness\n",
                            encoding="utf-8")
                        got = {row["name"]: row["status"]
                               for row in perch_report.assertions(raw)}
                        for name in names:
                            self.assertIn(name, got)
                            self.assertEqual(got[name], "fail", got)
```

## Delete and guard against the plausible mistake

Delete the real-mode “not wired” placeholder branches at [perch.sh:684](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:684) when their scenario dispatch is implemented, and the unconditional fake-worker report text at [perch_report.py:1830](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:1830). Reuse the owner’s existing commands and receipts; do not add a second path that turns harness bookkeeping into a release verdict.

The plausible mistake is to let stage 5/6 run under `--fake`, or mark a scenario “ran,” then infer success from `events.tsv` and a report’s landed line. The first test rejects that shortcut. Its follow-on mutation tests must compare immutable ask/answer/continuation pins, refusal and provider-call evidence, and actual Git objects with owner landing refs.

## Existing expectations and stale row details

No existing test assertion needs to change for this design. Preserve the stage-4 fake-run expectations at [tests/test_perch.py:1708](${TRANSFER_ROOT}/source/otto/tests/test_perch.py:1708) and [tests/test_perch_stage1.py:381](${TRANSFER_ROOT}/source/otto/tests/test_perch_stage1.py:381). If the worker also removes the existing stage-2 fake completion hook, its expectations at [tests/test_perch.py:1257](${TRANSFER_ROOT}/source/otto/tests/test_perch.py:1257) and [tests/test_perch.py:1319](${TRANSFER_ROOT}/source/otto/tests/test_perch.py:1319) need a written D19 decision before changing them.

The row’s first blocker is stale: stage 5/6 are absent from [project.json:5](${TRANSFER_ROOT}/source/otto/ops/bootstrap/canary/project.json:5), so `perch.sh:803` rejects them **before** the real-worker guard at `:809`. The external wrapper and PATH-TO-CUTOVER are not tracked on this `canon/main`, so their current behavior is unverified. Also, `portfolio save` has no preview option at [src/otto/hostctl/portfolio.py:78](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/portfolio.py:78); the available read-only previews are `project register --plan-only` and `operating-setup --operation preview`. Finally, [perch_stage2_owner.py:75](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_stage2_owner.py:75) already patches a product method for fake completion, contrary to the stated harness rule, and [tests/test_perch.py:1269](${TRANSFER_ROOT}/source/otto/tests/test_perch.py:1269) references a `defer_fake_lab_cleanup` function absent from that canonical file.