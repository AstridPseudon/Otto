## Design

1. [test_runbook_contract.py](<${TRANSFER_ROOT}/portfolio/test_runbook_contract.py>) (new) → Write the failing documentation contract test below first. It reads Otto’s gate from `canon/main`, so the stated stage selection is checked against the implementation.
2. [RUNBOOK.md:69](<${TRANSFER_ROOT}/portfolio/RUNBOOK.md:69>) → Replace the “startup test” and `perch.sh all --fake` claim. State that, when both staging scripts are present, the gate reads `$OPS_DIR/stages-gated` (default `0 1` **when absent**), runs `ops/bootstrap/perch.sh <stage> --fake` for each listed stage with `OTTO_STAGING_REF=<tested SHA>`, and requires a passing, SHA-matched report. Unlisted stages receive no landing coverage. This matches [land.sh:435](<${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:435>) through line 451.
3. [RUNBOOK.md:100](<${TRANSFER_ROOT}/portfolio/RUNBOOK.md:100>) → Separate **Diagnostic stage-run** from **Real-worker stage review**. Document `bash ops/stage-run.sh NAME STAGE [TASK ...]` as a fake, no-model diagnostic, with its `land.out`, report, and raw evidence. Document the separate `ops/bootstrap/perch.sh <stage>` command without `--fake` for a real-worker review. Require report and raw owner/worker evidence of a real worker model invocation and completed task output before `ops/launch_review.sh STAGE<n> opus`; leave the review pending where that scenario is not implemented. A fake diagnostic report cannot satisfy it.

### Failing test to write first

File: [test_runbook_contract.py](<${TRANSFER_ROOT}/portfolio/test_runbook_contract.py>)  
Name: `test_landing_stage_selection_and_review_evidence`

```python
import os
import re
import subprocess
import unittest
from pathlib import Path

PROGRAM = Path(__file__).resolve().parent
OTTO = Path(os.environ.get(
    "OTTO_REPO", PROGRAM.parent / "otto-claude-host" / "otto"
))


def canon(path):
    return subprocess.check_output(
        ["git", "-C", str(OTTO), "show", f"canon/main:{path}"],
        text=True,
    )


class RunbookContract(unittest.TestCase):
    def test_landing_stage_selection_and_review_evidence(self):
        doc = (PROGRAM / "RUNBOOK.md").read_text()
        runner = (PROGRAM / "ops/stage-run.sh").read_text()
        gate = canon("ops/bootstrap/land.sh")
        perch = canon("ops/bootstrap/perch.sh")

        landing = doc.split("## 4. Landing", 1)[1].split("## 5.", 1)[0]
        stages = doc.split("## 6. Stages", 1)[1].split("## 7.", 1)[0]

        self.assertNotIn("perch.sh all --fake", landing)
        selection = re.search(
            r'GATED="\$\(cat "\$OPS_DIR/([^"]+)" '
            r'2>/dev/null \|\| echo "([^"]+)"\)"',
            gate,
        )
        self.assertIsNotNone(selection)
        filename, default = selection.groups()
        self.assertIn(
            f"`$OPS_DIR/{filename}` (default `{default}` when absent)",
            landing,
        )
        self.assertIn("for stage in $GATED; do", gate)
        self.assertIn('bash "$ST/perch.sh" "$stage" --fake', gate)
        self.assertIn("`ops/bootstrap/perch.sh <stage> --fake`", landing)
        self.assertIn('OTTO_STAGING_REF="$SHA"', gate)
        self.assertIn("`OTTO_STAGING_REF=<tested SHA>`", landing)
        self.assertIn("staging tree sha $SHA", gate)
        self.assertIn("`staging tree sha <tested SHA>`", landing)

        diagnostic_label = "  - **Diagnostic stage-run:**"
        real_label = "  - **Real-worker stage review:**"
        self.assertIn(diagnostic_label, stages)
        self.assertIn(real_label, stages)
        diagnostic = stages.split(diagnostic_label, 1)[1].split(real_label, 1)[0]
        real = stages.split(real_label, 1)[1].split(
            "- **The Opus budget", 1
        )[0]

        self.assertIn(
            'bash ops/bootstrap/perch.sh "$STAGE" --fake', runner
        )
        self.assertIn(
            "`bash ops/stage-run.sh NAME STAGE [TASK ...]`", diagnostic
        )
        self.assertIn(
            "`ops/bootstrap/perch.sh <stage> --fake`", diagnostic
        )
        self.assertIn("no model call", diagnostic)
        self.assertIn("`ops/runs/<NAME>/land.out`", diagnostic)
        self.assertIn(
            "`ops/perch-reports/<stage>/<stamp>/report.md`", diagnostic
        )
        self.assertIn("raw evidence", diagnostic)

        self.assertIn('FAKE=""', perch)
        self.assertIn("--fake) FAKE=1", perch)
        self.assertIn(
            "`ops/bootstrap/perch.sh <stage>` without `--fake`", real
        )
        self.assertIn("real worker model invocation", real)
        self.assertIn("completed task output", real)
        self.assertIn("report and raw owner/worker logs", real)
        self.assertIn("`ops/launch_review.sh STAGE<n> opus`", real)
        self.assertIn("fake diagnostic report cannot satisfy", real)
        self.assertIn("pending", real)


if __name__ == "__main__":
    unittest.main()
```

## Delete

Delete the obsolete `perch.sh all --fake` and separate “startup test” claim at [RUNBOOK.md:69](<${TRANSFER_ROOT}/portfolio/RUNBOOK.md:69>), and the blanket “real Haiku workers” claim at [RUNBOOK.md:101](<${TRANSFER_ROOT}/portfolio/RUNBOOK.md:101>). No product path needs deletion.

## Plausible mistake

A worker might relabel the manager’s passing `stage-run` report as real-worker proof. The test checks that [stage-run.sh:34](<${TRANSFER_ROOT}/portfolio/ops/stage-run.sh:34>) actually passes `--fake`, then requires a distinct nonfake command and real worker evidence in the runbook.

## Existing test expectations and D19

None change. This adds a new test; it requires no D19 decision.

## Stale or misleading row context

The runbook is in the **program repository**, outside Otto’s `canon/main`; its cited lines are current program-file lines, not canon lines. The current `ops/stages-gated` contains `0 1`, while [land.sh:442](<${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:442>) uses that value only as the **absent-file default**. Also, a nonfake command alone is not real-worker proof: [perch.sh:807](<${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch.sh:807>) says stage 1 has no worker tasks, and line 809 rejects nonfake stages above 2 today. This was a read-only design review; I did not run the proposed test.