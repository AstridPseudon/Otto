Updated test fixtures only; production behavior is unchanged. Legacy hand-built admission stamps now use `authoring_stamp`, and owner fixtures that create projects supply an explicit operator identity. The strict admission check remains intact.

**Cause and fix for each failing file in `land.out`:**

- `test_document_editor_host.py`: its shared project-authoring setup failed because it lacked an operator; added one in the shared fixture.
- `test_execution_operations.py`: its synthetic stamp lacked `reviewed_digest`; switched it to `authoring_stamp`.
- `test_fleet_custody.py`: its landing check uses `_admitted_task()` from `test_landing.py`, whose stamp lacked `reviewed_digest`; fixed that shared helper.
- `test_landing.py`: both hand-built task and gate stamps lacked `reviewed_digest`; switched both helpers to `authoring_stamp`.
- `test_otto_open_release.py`: shared authoring and transfer-target fixtures lacked operator identity; added it in the shared fixtures.
- `test_otto_save.py`: its owner setup lacked operator identity; added one.
- `test_otto_show_status.py`: its shared authoring fixture and direct seed owners lacked operator identity; added one.
- `test_pending_inert_tasks.py`: its owner setup lacked operator identity; added one.
- `test_project_folder_scale.py`: its overridden owner setup and transfer-target fixture lacked operator identity; added one.
- `test_revisions.py`: its owner setup lacked operator identity; added one, and made the task-authorship actor match the project creator so the authoring admission remains valid.

**Verification:** Ran all ten failing files together: **201 passed, 38 subtests passed, 8 failed**. The eight failures are all in `test_fleet_custody.py` and are sandbox-only: `sandbox-exec` reports `sandbox_apply: Operation not permitted`, and process-census tests cannot observe processes in this worker sandbox. No staging-owner tests were run. `git diff --check` passed; changes are uncommitted.

Changed shared fixture files: [project_authoring.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/src/otto/portfolio/fixtures/project_authoring.py) and [project_folder.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/src/otto/portfolio/fixtures/project_folder.py). Changed test files: [test_execution_operations.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/tests/test_execution_operations.py), [test_landing.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/tests/test_landing.py), [test_otto_save.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/tests/test_otto_save.py), [test_otto_show_status.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/tests/test_otto_show_status.py), [test_pending_inert_tasks.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/tests/test_pending_inert_tasks.py), [test_project_folder_scale.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/tests/test_project_folder_scale.py), and [test_revisions.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/tests/test_revisions.py).