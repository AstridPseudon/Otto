# Brief: BOOTLAND (xhard, 1 focused day)

**Outcome:** Publish exactly the checked, reconciled commit and recover interrupted publication/cleanup before admitting the next landing.

**Your lab:** launcher lab from canon/main; work only there.

**Layer:** Otto bootstrap and landing gate.

**Files you own:** `ops/bootstrap/land.sh`, `ops/bootstrap/otto-lab.sh`, `tests/test_bootstrap_gate.py`.

**Other files:** directly required tests/helpers are allowed; explain additions.

**Do not touch:** `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, and files outside your lab. Concurrent workers: LANDPROOF (`ops/bootstrap/land.sh`), STOPATOM (staging/status), ASSESSCAP (capacity), plus other running tasks; avoid their files where possible and coordinate on the shared landing script through careful local edits.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/BOOTLAND.md` first. Follow its implementation order, retained TESTED_SHA, crash-released exclusion, remote reconciliation, and idempotent cleanup. Report departures. Existing lock-file assertions identified in the design need written D19 approval; keep those assertion changes isolated and do not treat them as approved.

**Your check:** Add the failing disposable-repository regressions in the design, run them red on canon and green in the lab, plus focused landing-gate checks. Do not weaken tests.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

**Invariant:** Published main contains exactly the checked and reconciled landing commits. **Plausible mistake:** Resetting after a failed push whose merge was accepted remotely, or merging a moved branch tip.

**Working rules:** Never stash, check out another commit, run `ottoctl`, or commit/push. Leave work for launcher commit. Long tests run to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.
