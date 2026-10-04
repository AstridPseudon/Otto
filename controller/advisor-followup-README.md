# Owner-service advisor follow-up command

`advisor-followup` exposes the existing
`ManagerCommandServer.dispatch_scheduled_project_advisor_followup` through the
owner-held IPC channel. It uses the existing per-decision schedule identity;
there is no scheduler, automation provisioning, new occurrence ID, or allowance
reset in this adapter.

The operational controller is outside Git at
`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-advisor-20260930/work/canonical-bootstrap/controller/launch_manager_once.py`.
`advisor-followup-command.patch` adds only its IPC handler. The reviewed baseline
SHA256 is `a77850fb10b31e7b2346f01f4bcc812cbc4e3c2102cdb50021bbc416ae836f49`.
No runnable controller copy is maintained here.

For adoption, gracefully stop the owner service and confirm custody release.
Integrate this commit into the canonical manager worktree while preserving its
later source changes. Reconcile/apply the controller diff, install the matching
client and runtime modules, then restart through the ordinary owner lifecycle.
Do not hot-edit the running service or execute a historical occurrence to test
installation.

After adoption, this command is read-only (omitting `--operation` also means
`status`):

```sh
/Users/hannahomalley/Documents/Codex/2026-09-27/ba/.otto/runs/otto-worker-project-readiness-20260927/work/o12/d97-successor-integration/env/bin/python \
  /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-advisor-20260930/work/canonical-bootstrap/manager-worktree/manager_ctl.py \
  advisor-followup \
  --schedule-id advisor-followup-27a599f6cadb57bb25884b7d9627 \
  --decision-id decision-pa06-delivery-boundary-v1 \
  --operation status
```

An authorized active owner tick uses the same command with
`--operation dispatch`. This is an effectful operation: it may prepare existing
runtime pins and claim the existing Due occurrence before allowance admission.
Do not use it to validate a paused automation or to retry the exhausted PA06
pilot. `prepare` is rejected; status never calls preparation or dispatch.

The adapter checks the owner-selected project and the deterministic existing
decision/schedule join. A retained paused, pending, or failed host state holds
dispatch; an adopted automation configuration must say `ACTIVE`. These are
canonical checks, not independent live automation readback. Without an adopted
automation, explicit owner dispatch uses ordinary Otto admission. External
timer wiring must target the owner/controller and use exact app readback;
directly waking the advisor bypasses pre-provider admission.

Dispatch passes only the existing schedule and decision IDs to the maintained
method. Current pairing, assignment/generation, recipient, Due replay/claim,
adopted allowance reservation, and provider authorization remain in that path.
Allowance exhaustion becomes the existing unknown outcome before provider
execution; no fresh pool or occurrence is created. In-flight/unknown preparation
failures return `unknown` with `retry: false`. Inspect the original canonical
occurrence through owner operations; do not blindly resend.

The response preserves the owner dispatch outcome and evidence. Status returns
`read`; held, unknown, and reconciliation outcomes exit the CLI with status 1.
The adapter does not equate `runtime_called` with a provider invocation and does
not claim `provider_called: false` after an ambiguous dispatch exception.

Focused verification (inert callbacks and in-memory Due; no Store or provider):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /Users/hannahomalley/Documents/Codex/2026-09-27/ba/.otto/runs/otto-worker-project-readiness-20260927/work/o12/d97-successor-integration/env/bin/python \
  -m unittest -v tests.test_manager_advisor_followup_command
```
