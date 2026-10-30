> **HISTORY. This is not a current requirement.** This document is the keep-and-clean list. **Its instruction to prune plan branches is withdrawn: preserve every branch** (`DECISIONS.md` D15). The clean-up order is now in `14-plan.md` (X0a and X0b). The current documents start at `START-HERE.md`.

# The thin path: what it loses, what it gains, what to keep, what to clean up

This compares the 90:10 recommendation (`10`) with carrying Otto forward (`08`/`09`).

## What it loses
1. **Otto's hardened execution guarantees:**
   - process custody, with birth identity and orphan cleanup;
   - a ledger guaranteeing at-most-once effects across crashes;
   - authenticated multi-host authority;
   - exact admission-revision pinning;
   - fast local labs (APFS clones);
   - a single-Mac capacity pool with headroom for heavy jobs.

   At one-owner scale these matter mostly in rare failures. The thin path covers them with "hold and reconcile" rather than automation.
2. **The typed work model:** Otto's records for tasks, criteria and findings, and its assessment with findings and corrections. The thin path uses a queue table plus receipts. That's simpler, but less queryable.
3. **The "neutral platform" idea:** Herzchen's fleet as something Astrid's own product agents could later run on (the ASTRID-ON-FLEET study). If that's a real product direction, the thin path doesn't advance it.
4. **The sunk investment as working code:** about 118K lines of source and 50K of tests, plus four-plus weeks of program work. Much of the *learning* carries over (below); most of the *code* doesn't.
5. **Mac-local operation as the first-class mode.** The thin path is cloud-first. Running it on your Mac is possible, but not the design centre.

## What it gains
1. **Value in weeks, not months:** the behavioural fixes land in week 1, and the full end state takes about 30–35 days instead of 108.
2. **Built for how we actually work:** cloud sessions, git as the truth, and a fresh session able to recover.
3. **It uses the platform instead of rebuilding it:** session status, `send_message` wake-ups, scheduled tasks, stop hooks and GitHub. Less code to own.
4. **Small enough to understand,** for agents as well as people. A Haiku manager can hold the whole contract in context, which matters for lean briefs.
5. **A proven base:** it already ran a program of 60-plus tasks, and only the gaps we observed get hardened.
6. **Easier to change:** every control is measured, and removable if it doesn't earn its keep.

## What to keep from what's already built

### From Otto
| Keep | How | Why |
|---|---|---|
| **Megado** (the method skill) | Keep as *the* method, trimmed. Its pack form is 24 files and about 1,850 lines. | Pragmatic reviews (zero for directly verifiable work), the XHARD rubric, the improvement loop and the lifecycle modes are the best-written parts of all this |
| **Packs: roles and profiles** (`otto-roles`, `otto-profiles`, about 280 lines) | They become `POLICY.md` plus the role guides, versioned in git and pinned by hash in each brief | The idea of pinning versioned policy, with a source per instruction, solves the policy drift we hit. Its content is small. |
| **Packs: domain templates** (`astrid`, `engineering`, about 165 lines) | Keep as optional templates; load them only when a task needs them | Cheap, and possibly useful. Nothing should require them. |
| **Packs: the machinery** (role-context composition, validation and recovery surfaces) | **Don't carry it.** A git file pinned by hash does the job. | It grew well beyond its 5-task plan |
| **Usage normalisation** (`herzchen/usage/contract.py`, 734 lines) | **Reuse as code:** pure functions that parse Claude and Codex usage events | Needed for spend reconciliation; already tested |
| **Host invocation knowledge** (`fleet/hosts/claude.py`, `codex.py`: flags, stream-JSON parsing, resume) | Reuse as reference, or lift the parsing | Avoids relearning CLI quirks |
| **Integrate-then-bisect** (`ops/integ.py`, 134 lines) and **"what can start"** (`ops/ready.py`, 127 lines) | Port the logic into the thin path's batch integration and queue | Proven in the Otto program: 18 labs landed in one run |
| **The flake rule** (refuse only if the lab fails at least 2 of 3 runs while the base never fails) | Put it in the batch-integration gate | Stopped flaky tests blocking landings |
| **The landing order** (rebase → check the merged commit → fast-forward under a lock) | Copy it into `land.sh` | The correct, simple order |
| **The safety ideas** (claim an effect before invoking it, hold unknowns, use birth identity for processes, check the admitted revision at launch) | Implement the light versions in Tasks 2 and 3 of `10` | They're the non-negotiable guarantees, in miniature |
| **Otto's tests as specs** (e.g. `test_runner_checks_rebased_commit_not_lab_commit`) | Mine them for acceptance cases | They encode invariants that were learned the hard way |
| **The perch scenarios** (restart, refusal, overlap) and the real-worker canary idea | Turn them into incident-replay fixtures | Ready-made failure drills |

### From the Astrid thin path
| Keep | Evolve into |
|---|---|
| `dispatcher.sh`, `land.sh`, `run-worker.sh` | The broker: one writer, one launch boundary, receipts |
| `handoff-upd/export.sh` and `import.sh` | The cold-start and handoff mechanism; proven with 140 refs |
| `MANAGER-CODEX.md` (the best current operating contract) | The manager role guide, made shorter |
| The queue-table format and `runs/<task>/` folders | Queue plus receipts |
| `COST-LOG.md` (one line per check-in) | A ledger generated from receipts |
| `retro/02` and `retro/03` | The runbook and the minimal structure |

## What to clean up

### The Astrid plan repo (`astrid-install`)
- **Superseded docs (about 1,350 lines).** `ORCHESTRATOR.md`, `MANAGER.md`, `CODEX.md`, `PROGRAM.md`, `STATUS.md`, `GOAL.md`, `CONTRACTS.md` and `README.md` describe the old paused program. Replace them with `POLICY.md`, three short role guides (orchestrator, manager, worker) and a README that points to the retro. Move the old files to `archive/`.
- **Scripts.** `keepalive.sh`, `recover.sh` and `watch.sh` are replaced by the broker's monitor. Point the dispatcher's CI target at the product repos instead of the hard-coded `astrid-install-ci`.
- **Bulky outputs** (out of git, but on disk):
  - `out/` (20 zips, 103 MB): keep the latest handover and the retro zip, delete the rest;
  - `runs/` (134 folders, 192 MB): keep the queues and `evidence/`, and archive the run folders to one tarball;
  - `handoff-upd/snapshot`: retire once the updater integration lands on `main`.
- **Stale branches in the plan repo:** 7 other `claude/*` branches. Prune them after a quick check for anything unmerged.
- **Retired machinery:**
  - delete the disabled hourly scheduled task;
  - retire the `AstridPseudon/astrid-install-ci` test repo once CI runs on the product repos.

### Otto (if you choose the thin path)
- **Freeze it, don't delete it.** Tag the transfer state (`a70b3f2`, plus the `transfer/20261028/*` refs that already exist) and keep the repo read-only as a reference.
- **Don't land the lab or project branches.** The preservation refs keep them. The roadmap in `08`/`09` stays valid if Otto is ever revived.
- **The live Otto install on your Mac** (paused since 19 Oct): stop its services and launchd entries cleanly, and archive the Store data. Earlier you said deletion is fine "so long as we still have the data". That's **your call and your machine**; nothing here touches it.
- **Archive the Otto program's records** (`portfolio/ops`, 11 MB) with the transfer zip. They're the evidence for this retro.

## Net effect
- **Kept as code:** about 2–3K lines (the usage parser, integration and readiness logic, landing order, CLI parsing), plus Megado and about 450 lines of policy content.
- **Kept as knowledge:** the invariants, tests-as-specs, failure drills and the method.
- **Retired:** about 115K lines of Otto service code, about 1,350 lines of superseded Astrid docs, and 3 scripts.
