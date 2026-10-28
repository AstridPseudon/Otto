# Brief: TOOLING17 (normal, 0.25 focused days), done by the orchestrator

**Title:** The gate passes a check failure canon shares, and lists it for REDS

**Outcome:** A task's check that failed only on tests canon also fails (the same ids, red on BASE) refused the landing. On 16 Oct, canon's manager-loop red refused CHANGE, A4 and COMPOSEFLEET until the orchestrator narrowed each check. The gate now treats those ids as pre-existing, as the sweep already does, and appends them to `ops/canon-reds.txt` (which the REDS row expected). Any other check failure still refuses: a new test file, an exit with no failing id, or an id that passes on BASE.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`
