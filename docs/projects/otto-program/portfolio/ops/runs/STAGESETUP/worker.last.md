Implemented the setup flow in the lab:

- Added `ottoctl repo map --name NAME --path PATH` to update the installation’s repository map.
- Registration now writes tasklist `repo` and `branch` into `otto.plan`; project status shows those values and the bundle’s assessment policy.
- `staging.sh` checks the derived caller socket path before startup writes and gives the 100-byte limit and shorter-path guidance.
- Added focused tests for these paths.

**Checks:** The five focused requirement tests passed, and `git diff --check` passed. The full requested suite did not finish: after 294 seconds it had 32 passes and failures in two macOS sandbox preflights and history-import replay; I interrupted it before the staging tests completed.

No commit was created. The lab remains on base commit `589d184888ffbd8e25f61eb9fa7eb7a40e19ec3d` with edits for the launcher.