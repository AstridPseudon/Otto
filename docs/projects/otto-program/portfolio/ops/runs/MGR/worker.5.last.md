**MGR is committed and the lab is clean.** The latest commit is `89d4f07`; the preceding MGR commit `78f2087` already includes the authorized [`manager_journey_client.py`](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/MGR/src/otto/portfolio/manager_journey_client.py) parser entries and authenticated native-caller routing for `show`, `save`, `answer`, and `route`. No additional files were needed, and I made no further edits.

**Checks**

- The brief’s exact command stops during collection: `test_manager_consumption.py` uses a relative import, but pytest’s default import mode does not load it as a package.
- With `--import-mode=importlib`, the focused suite completed: **118 passed, 19 skipped, 6 failed, 25 subtests passed**. The failures are:
  - One lost-socket occurrence test expects an unconfirmed retention handle but receives `retained: True`.
  - Four manager-consumption tests fail during fixture setup with `owner workspace contract is unsupported before initialization`.
  - One advisor follow-up test expects allowance admission to be called, but it is not.
- All **four refused-landing regressions passed**.
- `git diff --check` passed; the working tree is clean.

**D19 assertion:** In [`tests/test_host_neutral_defaults.py:160`](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/MGR/tests/test_host_neutral_defaults.py:160), the Codex guidance assertion changed from requiring `Documents/Codex` to asserting it is absent. This removes the hard-coded Codex manager path while retaining host-selection coverage. As you noted, D19 LAND covers this change.

The six focused-suite failures remain unresolved and should be reviewed; the four reported refused-landing regressions are repaired.