# Brief: TOOLING20 (normal, 0.25 focused days)

**Outcome:** The landing gate refuses when a D19 decision file does not name every changed test file, using exact paths so one test filename cannot loosely cover another.

**Why it matters:** A changed test expectation must have an explicit decision naming its file before it can land.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/TOOLING20`, on branch `lab/TOOLING20`, from `canon/main`. Work only here.

**Layer:** Herzchen model. This is a development gate used by the model workflow, not product behavior.

**Files you own:** `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`.

**Other files:** You may edit other files directly required by this outcome, except files under Do not touch. List each in your report with the reason.

**Do not touch:**
- the files of tasks running now: STAGESETUP;
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects, vision and Native5, or anything outside this lab.

**Build on what exists:** `ops/bootstrap/land.sh` contains the D19 gate and its changed-test detection; `tests/test_bootstrap_gate.py` builds scratch repositories to test the landing gate.

**Your check.** Add focused regression coverage for a decision naming one changed test file while another changed test is omitted, and for exact path matching. Run the focused file.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

**Callers, including production:** If you change a signature, constructor argument or default, find and update every caller, including production startup.

**Existing tests:** Don't change what an existing test asserts to make your change pass. If an expectation must change, list each changed assertion as file:line and explain why; it lands only after an Opus D19 decision.

**Regression at the level the friction appears:** A scratch landing with a decision naming test A and changed expectations in test A and test B must stop and identify B; naming both paths must pass; similar basenames must not match loosely.

**Working rules:** Never run `git stash` or check out another commit. Don't run `ottoctl`. Never wait or poll. Run tests in the foreground. If blocked, make a reasonable decision within the brief or report the question. On Codex, don't commit; the launcher commits your work when you exit. Long tests must run to completion. If a test fails with `sandbox_apply: Operation not permitted`, report it for the landing gate to run outside the sandbox. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work in the lab for the launcher to commit. Report the focused check and anything unfinished. Don't push.
