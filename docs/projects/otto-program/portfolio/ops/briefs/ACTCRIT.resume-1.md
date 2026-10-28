# Resume: ACTCRIT (normal, 1.25 focused days)

**Task:** ACTCRIT. Fix the four new `tests/test_hostctl_serve.py` ManagerLoopTests regressions found by the landing gate. Keep the product outcome and existing changes: activation declares required assessment scopes idempotently, and `project status` projects persisted task dispatch state and failure reason.

**Your lab:** `~/Developer/otto-claude-host/labs/ACTCRIT`, branch `lab/ACTCRIT`. The manager rebases before this resume. Work only in the lab.

**Layer:** Otto product. Product code belongs in `src/`; regression coverage belongs in `tests/`.

**Files you own:** `src/`, `tests/`, plus any other product caller or fixture directly required by this fix.

**Do not touch:**
- `ops/bootstrap/`: PERCH2B is running and owns its harness files.
- `production/`, Store data, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**Failure evidence:** The landing gate refused the product commit with four reproducible NEW failures (each 3/3 on the lab, 0/3 on BASE): `tests/test_hostctl_serve.py::ManagerLoopTests::test_activation_launches_the_manager_which_authenticates_and_reads_its_documents`, `...::test_editing_generated_view_does_not_change_owner_show`, `...::test_manager_dispatches_normal_and_xhard_workers_and_is_resumed_with_results`, and `...::test_service_starts_no_due_relays_status_and_denies_a_foreign_socket_caller`. Full gate log: `${TRANSFER_ROOT}/portfolio/ops/runs/ACTCRIT/land.log`; first sweep output: `${TRANSFER_ROOT}/portfolio/ops/runs/ACTCRIT/.gate/fail-test_hostctl_serve.py-run1.txt`; isolated paired outputs are `${TRANSFER_ROOT}/portfolio/ops/runs/ACTCRIT/.gate/pair-1-*.txt` through `pair-4-*.txt`. The first failure's setup reaches activation and gets `StoreError: identity already exists with a different state`. Inspect all four paired outputs and trace the changed activation/status behavior to the shared cause.

**Outcome:** Preserve the ACTCRIT product behavior while fixing these regressions. Add or adjust focused regression coverage only where needed; do not weaken existing assertions or stub product fences. Do not alter harness files.

**Your check:** Run relevant changed tests. The prior requested check is `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_act_activation.py tests/test_hostctl_cli.py`. The landing gate runs `tests/test_hostctl_serve.py` outside the worker sandbox; don't stop a long run early. Never weaken a test to pass in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_act_activation.py tests/test_hostctl_cli.py`

**Working rules:** Follow the Codex rules in `ops/brief-template.md`: no git commits (the launcher commits on exit), no stash, never wait, long tests run to completion. A sandbox-only `sandbox_apply: Operation not permitted` is not a product failure. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.
