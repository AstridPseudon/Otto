## Lens: Tracking, logging and records

### Findings

1. **The queue became the operational source of truth for a project, but `STATUS.md` remained a second, overlapping tracker.** The UPD queue says it is “the source of truth,” carries task state, tier/model, dependencies, evidence and run-folder links, and the manager is told to keep it current ([`runs/QUEUE.md`](/home/user/repo/astrid-install/runs/QUEUE.md); transcript [10-26 02:52–02:55]). `STATUS.md` covers the wider program and earlier projects, with another task-state table and a different legend ([`STATUS.md`](/home/user/repo/astrid-install/STATUS.md)). **Observed:** the two files served different scopes, but duplicated some status. **Inferred:** the queue worked best for execution; the platform needs one authoritative state per project, with program-level views derived from it.

2. **Run folders gave tasks durable evidence, but grew into an inconsistent archive.** Folders typically contain `brief.md`, `final.md`, tests/logs, and often `dispatch.json`, request files, commit messages, and worktree/landing markers. The dispatcher explicitly used `dispatch.json`, `worktree.request`, `land.request`, `sync.request` and `status.request` ([`dispatcher.sh`](/home/user/repo/astrid-install/tools/dispatcher.sh); transcript [10-26 23:32–23:38], [10-27 01:44–01:46]). The actual folders also include retries and divergent artifacts—for example, `INS-C1` has multiple interrupted attempts and repeated test records. **Observed:** task evidence was saved and often reused to resolve review questions. **Inferred:** the unstructured, append-by-convention folder could make the latest authoritative result unclear.

3. **Request and completion markers enabled automation, but were not a clean state model.** Workers handed off via `state.json` with `ready` or `approved`, plus `commit-msg.txt` and `land.request`; `land.done`/`land.failed` recorded the outcome ([`MANAGER-CODEX.md`](/home/user/repo/astrid-install/MANAGER-CODEX.md), lines 74–109; transcript [10-26 23:42], [10-27 01:37]). `ESCALATE.md` was a manager-to-orchestrator signal; resolving one often meant renaming it to `ESCALATE-resolved.md` ([10-27 06:22], [10-27 10:54–10:55]). **Observed:** these markers surfaced work that needed action. **Inferred:** readiness, approval, escalation and completion were spread across JSON, filenames, and queue text, so stale marker files could disagree with current state. “READY” and “APPROVED” were states or annotations, not consistent standalone marker files.

4. **Snapshots and manifests provided cross-session continuity, but lag was a recurring operational failure.** The UPD export bundled branches, refs, run records and a `MANIFEST.md` with base heads, tips and branch counts ([`MANIFEST.md`](/home/user/repo/handoff-upd/snapshot/MANIFEST.md); transcript [10-28 00:10–00:23]). The orchestrator’s hourly review explicitly checked manifest freshness and queue state ([10-28 00:57]). Yet at 05:58 the snapshot omitted landed cleanup work and queue entries; at 14:17 it was still from 13:03; at 16:02 it was still from 14:17 ([`COST-LOG.md`](/home/user/repo/astrid-install/COST-LOG.md); transcript [10-28 05:58], [14:17], [16:02]). **Observed:** snapshots preserved work, but a snapshot was a point-in-time copy, not a live status. **Inferred:** freshness should be machine-visible and tied to the latest queue or landing change.

5. **Completion reports made test outcomes more honest, but the “complete” label could still overstate verification.** `FINAL-TESTS/preexisting.md` and `regressions.md` separated baseline failures from new failures; rebase records further distinguished regression, pre-existing, environmental and not-run results. The final report explicitly says 1,021 agent tests “did not run (hung)” and that verification was incomplete ([`REBASE-COMPLETE.md`](/home/user/repo/handoff-upd/snapshot/runs/REBASE-COMPLETE.md); transcript [10-28 20:38]). Earlier, the final-test policy required comparing branch and base and not fixing failures found on both ([10-28 06:58–08:59]). **Observed:** classification preserved critical caveats. **Inferred:** completion needs separate “work complete” and “verification complete” fields rather than a single done marker.

6. **Cost logging and digests helped the orchestrator report progress, but were manual summaries with limited comparability.** `COST-LOG.md` recorded timestamp, session cost, change and models used; the morning `DIGEST` summarized progress and was corrected when the Runtime failure count was misclassified ([`COST-LOG.md`](/home/user/repo/astrid-install/COST-LOG.md), [`DIGEST-2026-10-28.md`](/home/user/repo/astrid-install/DIGEST-2026-10-28.md); transcript [10-28 08:59]). **Observed:** these records supported hourly checks and owner updates. The log spans fresh manager sessions, so totals reset at session boundaries; it also contains a malformed model/cost note (“sonnet /bin/bash.98”). **Inferred:** automated usage records with session IDs would be easier to compare and less error-prone. Digests should link to underlying states and be treated as dated summaries, not live status.

7. **Decision and review records preserved useful context, but were scattered.** `evidence/` holds a persistent copy of the Astra over-engineering review; task run folders hold other review reports and findings. Bigger-issues lists separated deferred structural questions from fixes, while release notes recorded rebase-specific pin and digest steps ([`evidence/2026-10-28-astra-handover-overeng.md`](/home/user/repo/astrid-install/evidence/2026-10-28-astra-handover-overeng.md); [`runs/REBASE/release-note.md`](/home/user/repo/handoff-upd/snapshot/runs/REBASE/release-note.md); transcript [10-28 05:51–06:58], [20:38]). **Observed:** the split prevented some out-of-scope changes and made owner decisions reviewable. **Inferred:** decision records should link to affected task and plan rather than rely on filenames and manual pointers.

8. **Commit conventions improved traceability but were not the main status record.** Tasks used `commit-msg.txt` with a task-prefixed subject, and the landing procedure added model/session trailers ([`MANAGER-CODEX.md`](/home/user/repo/astrid-install/MANAGER-CODEX.md); transcript [10-26 23:58], [10-27 01:37]). Plan-repo commits also used descriptive snapshot/check-in subjects and timestamped snapshots (`data/plan-repo-gitlog.txt`, e.g. `UPD snapshot 20:22Z`). **Observed:** commits made code changes and snapshots locatable. **Inferred:** commit messages are useful provenance, but should reference structured task/run IDs rather than carry the full progress state.

### What worked

- A queue row connected the work item to its dependencies, worker tier, state, evidence and task folder; it could serve as a practical manager worklist ([`runs/QUEUE.md`](/home/user/repo/astrid-install/runs/QUEUE.md)).
- Run-folder evidence let reviewers and the orchestrator check what was tested, what was merely written, and what needed another pass ([10-27 01:06]; [`REBASE-COMPLETE.md`](/home/user/repo/handoff-upd/snapshot/runs/REBASE-COMPLETE.md)).
- Explicit failure classes and base comparisons stopped known baseline failures from being silently treated as new regressions ([10-28 06:58–08:59]).
- Manifests and snapshots allowed a fresh manager to resume from recorded branches and task state ([10-28 00:10–00:23]).
- Escalation, queue-complete and rebase-complete signals gave the orchestrator clear handoff triggers, even though their formats differed ([10-27 10:54]; [10-28 20:38]).

### What failed / friction

- Snapshot lag hid landed work and led the orchestrator to repeatedly nudge managers to export after landings ([10-28 05:58], [14:17], [16:02]).
- Parallel queue and status documents created duplicate progress narratives and left room for stale references; the October 28 handover still noted a stale plan reference after editing the test queue ([10-28 17:06–17:11]).
- Markers and state files could outlive their meaning. Escalation was often resolved by renaming a file, while other state changes went into JSON or queue prose ([10-27 06:22], [10:27 10:55]).
- Manual cost entries and digest corrections were vulnerable to typos, session resets and aging ([10-28 08:59]; [`COST-LOG.md`](/home/user/repo/astrid-install/COST-LOG.md)).
- `REBASE-COMPLETE` communicated a finished phase while also documenting substantial tests not run. The caveat was visible, but the filename alone implied more assurance than the evidence supported ([10-28 20:38]).
- Task folders accumulated retries and heterogeneous artifacts. Useful history was retained, but finding the final answer required knowing which file was authoritative.

### Candidate principles

- When work is executable, keep one authoritative queue per project, because the UPD queue was explicitly the manager’s “source of truth” while `STATUS.md` tracked overlapping progress.
- When a worker hands off, record state and evidence in one structured task record, because the current workflow split that handoff across JSON, marker files, queue prose and folder contents.
- When exporting a snapshot, include the queue revision and latest landing time, because snapshots at 05:58, 14:17 and 16:02 were stale enough to conceal progress.
- When reporting completion, state work completion and verification completion separately, because `REBASE-COMPLETE` recorded 1,021 tests not run.
- When recording decisions or exceptions, link each to its task and evidence, because bigger-issues, review evidence and release notes were separate files with manual pointers.
- When recording usage, attach cost to a stable session ID and structured model usage, because manager sessions reset cost totals and one manual entry was malformed.

### Structure implications

Minimum platform records:

- **Program:** `program_id`, owner, scope, active manager, phase, plan revision, paused/active state.
- **Task:** `task_id`, `program_id`, title, owner/manager, status, tier/model, dependencies, branch/base commit, brief, acceptance criteria, timestamps, current run ID, blocked reason.
- **Run/attempt:** `run_id`, `task_id`, attempt number, worker/model, started/ended, result, log/evidence links, test commands and outcomes, commit IDs, land status.
- **Decision/escalation:** `decision_id`, task/program link, raised by, question, options/recommendation, decision maker, outcome, timestamp, affected plan/queue revision.
- **Snapshot/release:** `snapshot_id`, source revision, branch tips, manifest, created time, included task-state revision, test-verification state.
- **Usage event:** `session_id`, actor/model, time window, cost/tokens, task or phase attribution.
- **Derived views:** program status, queue, digest and completion report should be generated from these records; distinguish `work_status` from `verification_status` and show last-updated time plus stale age.