# Brief: PROOFDOC (normal, 0.25 focused days)

**Outcome:** The runbook accurately describes the gate's `stages-gated` selection/default, distinguishes fake diagnostic `stage-run` from the separately required real-model stage review, and preserves the real-worker requirement.
**Why it matters:** Operators must be able to tell which evidence a run actually produced.
**Your lab:** Launcher creates this from current `canon/main`; work only there.
**Layer:** Program documentation.
**Files you own:** `RUNBOOK.md`, `tests/test_bootstrap_gate.py`, and a focused documentation contract test if needed.
**Other files:** Edit any directly required file except Do not touch; explain additions in report.
**Do not touch:** `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab.
**Build on:** `ops/bootstrap/land.sh` stage selection and `ops/stages-gated` semantics; existing gate contract coverage in `tests/test_bootstrap_gate.py`.
**Your check:** Add/update a contract check comparing runbook statements to the gate behavior and run the focused test file.
**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`
**Regression:** A documentation contract check rejects the current incorrect “all stages at every landing” description and does not let fake diagnostics satisfy real-worker review.
**Working rules:** Follow the Codex rules in `ops/brief-template.md`; no stash, commit, push or `ottoctl`; leave commit to launcher.
