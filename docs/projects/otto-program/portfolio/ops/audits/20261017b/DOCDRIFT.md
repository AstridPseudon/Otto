## Findings

### 1. The documented manager-turn cap is accepted but ignored

**Evidence:** [docs/portfolio.md:50](/private/tmp/otto-audit-tree/docs/portfolio.md:50) says `service run --max-active-manager-turns N` sets the limit. [product_service.py:1437](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:1437) only validates `N`; [product_service.py:1356](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:1356) constructs the service with the pool’s limit instead. The default pool permits six managers ([capacity.py:29](/private/tmp/otto-audit-tree/src/herzchen/fleet/capacity.py:29), [capacity.py:52](/private/tmp/otto-audit-tree/src/herzchen/fleet/capacity.py:52)).

**Scenario and impact:** With the default policy, an operator starts the product owner with `--max-active-manager-turns 1` and admits two ready manager turns. **Inference from the construction path:** both can take slots while the operator expects the second to queue. The advertised operating limit is unreliable.

**Proposed fix row — normal:** Apply the requested lower limit to `ProjectOwnerService`; update `src/otto/hostctl/product_service.py`, `docs/portfolio.md` and `OTTO-ONE.md`. Acceptance: with the default pool and flag `1`, the service reports a limit of one and queues a second ready manager turn; this fails before the fix.

### 2. The project walkthrough omits required task admission

**Evidence:** [docs/megado-from-any-host.md:53](/private/tmp/otto-audit-tree/docs/megado-from-any-host.md:53) takes a new project from editing through activation and manager dispatch without task review or operator admission. A worker launch rechecks admission and refuses unready work ([execution_operations.py:1321](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_operations.py:1321)). The owner exposes a separate, presence checked `service admit` operation ([cli.py:148](/private/tmp/otto-audit-tree/src/otto/hostctl/cli.py:148), [service.py:473](/private/tmp/otto-audit-tree/src/otto/hostctl/service.py:473)).

**Scenario and impact:** A reader follows the walkthrough with newly materialized, unadmitted tasks. Manager startup can succeed, but worker launches stop at the admission gate. The guide gives no route to resolve that blocker.

**Proposed fix row — normal:** Add the exact review, operator admission, and changed-revision re-admission steps to `docs/megado-from-any-host.md` and `docs/host-onboarding.md`, distinguishing task admission from `admit-host`. Acceptance: a fresh-project walkthrough names every required owner operation and reaches a worker launch only after the reviewed revision is admitted; the present guide fails that walkthrough.

### 3. The installation example omits a required argument

**Evidence:** [docs/host-onboarding.md:19](/private/tmp/otto-audit-tree/docs/host-onboarding.md:19) shows `ottoctl install` without `--operator`; the parser requires it ([cli.py:49](/private/tmp/otto-audit-tree/src/otto/hostctl/cli.py:49), [cli.py:53](/private/tmp/otto-audit-tree/src/otto/hostctl/cli.py:53)).

**Scenario and impact:** On a fresh machine, copying the documented install command ends in argument parsing failure before an installation is recorded.

**Proposed fix row — normal:** Supply and explain a distinct operator principal in `docs/host-onboarding.md`. Acceptance: parse the guide’s example with placeholder values and assert all required arguments are present; it fails before the documentation fix.

### 4. Document-sync commands in the guides do not exist

**Evidence:** [docs/megado-from-any-host.md:55](/private/tmp/otto-audit-tree/docs/megado-from-any-host.md:55) and [docs/host-onboarding.md:48](/private/tmp/otto-audit-tree/docs/host-onboarding.md:48) prescribe `project sync-docs`; [docs/portfolio.md:163](/private/tmp/otto-audit-tree/docs/portfolio.md:163) prescribes `portfolio sync-docs`. Neither appears among the project commands ([cli.py:75](/private/tmp/otto-audit-tree/src/otto/hostctl/cli.py:75), [cli.py:1034](/private/tmp/otto-audit-tree/src/otto/hostctl/cli.py:1034)) or portfolio commands ([portfolio.py:38](/private/tmp/otto-audit-tree/src/otto/hostctl/portfolio.py:38)).

**Scenario and impact:** After editing run-directory or shared documents, a reader invokes the documented sync command and gets a usage error. Later activation or review can then use older stored content.

**Proposed fix row — normal:** Reconcile these guides and `OTTO-ONE.md` with the supported document-writing route, or implement the documented commands if that remains the intended workflow. Acceptance: each documented sync example resolves to a registered command and records an edited document; all three examples fail command lookup before the fix.

### 5. The program runbook overstates staging coverage and real-worker proof

**Evidence:** [RUNBOOK.md:69](${TRANSFER_ROOT}/portfolio/RUNBOOK.md:69) says each landing runs `perch.sh all --fake`. The gate runs only stages listed in `ops/stages-gated`, defaulting to `0 1` when that file is absent ([land.sh:439](/private/tmp/otto-audit-tree/ops/bootstrap/land.sh:439)). [RUNBOOK.md:101](${TRANSFER_ROOT}/portfolio/RUNBOOK.md:101) says stage runs use real Haiku workers, while the current manager stage-run effect specifies `--fake` ([manager-codex.md:46](${TRANSFER_ROOT}/portfolio/ops/manager-codex.md:46)); `perch.sh` defines that as no model call ([perch.sh:7](/private/tmp/otto-audit-tree/ops/bootstrap/perch.sh:7)). This is a runbook sibling of PERCH2C’s report-header work.

**Scenario and impact:** An orchestrator treats a passing landing as coverage of a later stage, or treats a fake stage run as real-worker evidence. Neither conclusion follows from the run performed.

**Proposed fix row — normal:** Update `RUNBOOK.md` to state how gated stages are selected and when a separate real-worker run is required. Acceptance: the runbook’s landing-stage list agrees with `land.sh`, and its stage procedure labels `--fake` evidence accurately; both statements fail that check now.

## Checked and sound

- The brief template’s backticked `Check command:` format matches the gate’s current extraction path ([brief-template.md:32](${TRANSFER_ROOT}/portfolio/ops/brief-template.md:32), [land.sh:67](/private/tmp/otto-audit-tree/ops/bootstrap/land.sh:67)). TOOLING25 already covers its placeholder and trailing-text cases.
- `manager-codex.md`’s `land.sh` and `stage-run` effect names are accepted by the manager loop ([manager-codex.md:27](${TRANSFER_ROOT}/portfolio/ops/manager-codex.md:27), [manager_loop.py:117](${TRANSFER_ROOT}/portfolio/ops/manager_loop.py:117)).
- The host guide’s one-owner, client-lane model matches the `ottoctl` entry contract ([host-onboarding.md:3](/private/tmp/otto-audit-tree/docs/host-onboarding.md:3), [cli.py:3](/private/tmp/otto-audit-tree/src/otto/hostctl/cli.py:3)).

## Not checked

- I did not execute commands or tests, inspect the live installation, or verify the historical paths named in older controller documents. This was a source-only audit; the failing outcomes above are traced from parsers and call paths.