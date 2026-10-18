# ROOTFILE landing gate report

- Added an early `land.sh` refusal for newly introduced repository root files. The refusal names each path and runs before the test sweep; deletions remain eligible.
- Added regressions for a named root-file refusal and a successful landing with `src/` and `tests/` additions.
- Updated existing scratch-lab payloads to use an allowed `src/otto/` path.
- Deleted the stray root `D19.md`.
- Check: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py` — 57 passed.
