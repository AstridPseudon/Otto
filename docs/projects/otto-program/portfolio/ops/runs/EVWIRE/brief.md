# Brief: EVWIRE (normal, 0.25 focused days)

**Outcome:** Every production composition that builds an `AssessmentModule` passes the evidence handler as `payload_resolver`, so a managed result verifies and is accepted through the production owner, and a tampered managed result is refused. Before this, `accept` refused unverified DAT evidence because no production composition passed a resolver.

**Why it matters:** EVIDENCE (landed f49e17c) made `verify_dat_evidence` verify managed payloads through a `payload_resolver`, and made `accept` refuse DAT evidence that isn't verified. Without the wiring, live acceptance of a managed result fails.

**Your lab:** `~/Developer/otto-claude-host/labs/EVWIRE`, on branch `lab/EVWIRE`, from `canon/main` at f49e17c. Work only here.

**Layer:** Otto composition (PLAN.md D14). The wiring goes in `src/otto/portfolio/`; nothing in `src/herzchen`.

**Files you own:**
- `src/otto/portfolio/owner_bootstrap.py` (the `AssessmentModule` built at line ~976);
- `src/otto/portfolio/manager_application.py` (line ~310);
- `src/otto/portfolio/reviewed_activation.py` (line ~377);
- `src/otto/portfolio/operator.py` (line ~195; DELETE removes this file later, so either wire it or confirm it never sees DAT evidence, and say which in your report);
- one new test file, `tests/test_evidence_wiring.py`.

**Do not touch:** other tasks' files; `production/`; any Store, `~/.otto` or `~/.codex`; anything outside this lab. Don't change existing assertions in any test.

**Build on what exists:** the evidence handler's `resolve` at `src/herzchen/evidence/commands.py:1948`, passed as `payload_resolver`; `AssessmentModule` takes `payload_resolver` in its constructor (`src/herzchen/domains/assessment/module.py:244`).

**Your check.** Both tests must exist; the first must fail on canon before your change and pass after:
- `production_owner_accepts_verified_managed_result`: through `owner_bootstrap`'s composition, not a hand-built module;
- `production_owner_refuses_tampered_managed_result`.

Run tests with no env prefix: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`, or through `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "EVWIRE check" -- /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`. Also run every test file that imports a module you changed, each alone, twice. Show the red run on canon and the green run on your change.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_evidence_wiring.py`

**Callers, including production:** you change constructor calls, so find every caller and update it, including `install/controller/` (e.g. `install/controller/w0_completion_policy.py:106` builds `AssessmentModule(owner.store, actor=actor)`; decide whether it sees DAT evidence and say so).

**Regression:** a refusal → recovery pair: a tampered managed result is refused by the production owner; the same result untampered is accepted.

**Deletion budget:** n/a (wiring only).

**Working rules:** commit work in progress to `lab/EVWIRE`; never `git stash`; never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`.

**When done:** commit to `lab/EVWIRE` and don't push. Report the commit, the check runs (red, then green), the net lines by file, and anything you couldn't finish.
