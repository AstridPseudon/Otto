PERCH2B remains **incomplete**. No files were edited, and the worktree is clean on `lab/PERCH2B` at `589d184888ffbd8e25f61eb9fa7eb7a40e19ec3d`; that commit is already the requested base.

I traced the owner path: registration and activation prepare the manager occurrence; the owner launches it with `start-manager`, then the authenticated manager uses the caller socket to issue `run-worker`. The integration fixture in `tests/test_claude_manager_admission.py` substitutes a synthetic provider while exercising owner admission, but it does not perform dispatch. The staging `service run` CLI uses the default provider and exposes no adapter-factory injection hook. Also, the registration CLI’s task-plan generation does not provide a route for adding the requested `otto.plan` repo and branch metadata.

The required check did not reach the scenario:

- With the default staging root, directory creation outside the lab was denied.
- With `OTTO_STAGING_ROOT="$PWD/_staging"`, the check stopped at census because Python could not launch `ps` (`PermissionError: Operation not permitted`).

No scenario ran, no seeded-fault red/green evidence was produced, and no stage-2 report was written under `ops/perch/2`. I did not mark dispatch as ran or create observations. The concrete integration gaps are the staging owner’s lack of adapter injection for a deterministic authenticated dispatch fixture, and the registration path’s lack of task `otto.plan` metadata input. No additional files were edited.