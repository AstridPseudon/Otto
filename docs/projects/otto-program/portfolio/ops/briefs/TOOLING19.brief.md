# Brief: TOOLING19 (normal, 0.25 focused days)

**Outcome:** A collection error cannot make a landing check pass when pytest ran zero tests. The check and sweep continue past collection errors so independent tests can run; the gate refuses output containing `no tests ran` or `Interrupted:`.

**Why it matters:** The landing gate must require evidence that tests actually ran before accepting a task.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TOOLING19`, on branch `lab/TOOLING19`, from `canon/main`. Work only here.

**Layer:** model. This changes the bootstrap landing gate, not product behavior.

**Files you own:** `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`.

**Other files:** You may edit another file only if the outcome directly requires it; list each such file and why in your report.

**Do not touch:**
- `src/otto/portfolio/manager_journey_client.py` (MGR) and OPERATOR-ADMIT's owned files: `src/otto/hostctl/config.py`, `cli.py`, `register.py`, `owner_bootstrap.py`, `src/otto/portfolio/herzchen_binding.py`, `admit.py`, `src/herzchen/domains/work/orchestration.py`, `tests/test_owner_lane.py`, `tests/test_admit.py`, `tests/test_operator_admission.py`;
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex projects, vision, Native5, or anything outside this lab.

**Build on what exists:** `ops/bootstrap/land.sh` functions `run_pytest` / `ids_of` and its check/sweep calls; gate behavior is exercised through `tests/test_bootstrap_gate.py`.

**Your check:** Add regression coverage for (1) a broken-to-collect file plus passing file, where landing proceeds and records the collection error as canon red, and (2) a check where all files fail collection, which must be refused.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

**Regression at the level the friction appears:** landing gate check and sweep when one or all selected files fail collection.

**Invariant:** A check passes only if it ran tests. Plausible mistake: treating `Interrupted` as one more pre-existing id.

**Working rules:** Follow the Codex instructions in `ops/brief-template.md`: don't commit or push, leave the lab for the launcher to commit, run the check to completion, and don't stop to ask about routine file scope.
