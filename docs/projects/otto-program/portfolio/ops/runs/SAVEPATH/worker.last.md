**SAVEPATH is fixed in the lab.** The client now resolves the save file from its current directory and rebuilds the forwarded arguments from parsed fields. Other commands retain `_absolute_directories` behavior.

- **Pre-change red (canon-derived baseline):** The caller-A/owner-B regression failed; the owner saved “Owner B” instead of “Caller A.” The test also covers options before the filename.
- **Lab green:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_otto_open_release.py` — **37 passed, 8 subtests passed**.
- **Files changed:** [cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/SAVEPATH/src/otto/portfolio/cli.py) and [test_otto_open_release.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/SAVEPATH/tests/test_otto_open_release.py).
- `ops/prework/SAVEPATH.md` was missing from the lab, so I followed the brief. No other files were changed.

**Acceptance mismatch to report with the task row:** save returns refs on success and a diff on stale conflict; document persistence remains a separate gap and was not expanded into this change.