Implemented the A4 changes in the five owned files. Generated `run.json` now labels itself a read-only projection; bundle parsing rejects generated views before reading their task tables. Registration rebuilds parsed data from the supplied files, so separately supplied task rows cannot override them. The serve regression edits the rendered view and confirms Otto’s project status is unchanged.

**Checks**

- `test_hostctl_bundle.py`: 18 passed.
- Generated-view and service-status regressions: 2 passed.
- Service startup/status regression: 1 passed.
- Registration and activation regression: 1 passed.
- `test_herzchen_boundary.py`: 4 passed.
- The full `test_hostctl_serve.py` run hit the existing manager-launch failure `sandbox_apply: Operation not permitted`; I stopped the run as the brief directs. The landing gate should rerun it outside this sandbox.
- `git diff --check`: passed.

The owned source files matched `canon/main` before changes. The baseline bundle regression failed because generated views were accepted; the first serve regression attempt also failed because its setup had not rendered a view. I corrected the setup, and the focused regressions pass.

No signature changes or production caller updates were needed. No files were physically deleted; the pre-parsed task-row authority path is replaced by parsing the supplied files. No commit was created; the Codex launcher handles that on exit.