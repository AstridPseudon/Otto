# Brief: TOOLING25 (normal, 0.25 focused days)

**Outcome:** Make `ops/bootstrap/land.sh` enforce the brief check-command contract: extract only the backticked command (ignore trailing text after the closing backtick), and refuse a command containing a `<…>` placeholder before any sweep, with a message naming the brief line and telling the author to fill it in.

**Your lab:** The launcher creates the TOOLING25 lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product. This is the Otto program's landing gate.

**Files you own:** `ops/bootstrap/land.sh`; focused tests in `tests/test_bootstrap_gate.py`.

**Other files:** Edit another file only if directly required by this outcome; explain it in your report.

**Do not touch:**
- `src/otto/portfolio/operating_brief.py`, `tests/test_operating_setup_pin_content.py`, `tests/test_fresh_worker_admission.py`, and `tests/test_manager_service_continuation.py` (PROJECTPIN landing/review);
- `src/otto/portfolio/execution_host.py` and its tests (OWNERCOMPLETION is running);
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on what exists:** `ops/bootstrap/land.sh` reads `Check command:` with `brief_field` near lines 68–70; its current extraction strips a backtick only at the start/end. `tests/test_bootstrap_gate.py` has the `Scratch` repo harness near line 32 and landing brief helper near lines 90–98.

**Your check:** Add focused cases proving trailing text after a closing backtick is ignored and placeholder commands are refused before the sweep with a useful line-specific message. Keep existing bootstrap gate tests green.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

**Regression at the level the friction appears:** A real brief with a valid backticked command plus trailing prose lands using only the backticked command; a placeholder check is rejected before tests/sweep begin.

**Working rules:** Do not run staging-owner tests in the worker sandbox. Do not commit or push; the launcher commits on exit. Keep the check running to completion and report its result.
