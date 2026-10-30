> Astra (read-only review, 30 Oct). Links into `/tmp/...scratchpad` point at the restored Otto, oh-my-pi and Astrid clones used for the review; they are not in this repo.

Build the new tool beside frozen Otto. Extract the folder validators, the essential landing sequence and rewritten Megado guidance. Preserve the remaining implementation and tests as reference; **do not merge the cleanup branches before starting.** That matches the intended reuse boundary in [15-in-short.md](/home/user/repo/astrid-install/retro/15-in-short.md:40).

This was a read-only source and branch-diff review. Integrated Otto is `a70b3f2`; its 23 lab/project worktrees were clean. No runtime tests, installations or live sessions were run.

The inventory uses these dispositions:

- **Keep** — retain unchanged.
- **Simplify** — extract the named part into the new tool.
- **Reference** — preserve for behaviour or historical evidence; carry no implementation.
- **Leave** — exclude from the new tool; preserve in frozen history.

Line counts are physical lines, including comments and blanks. Folder counts include text fixtures and documentation. Extraction rows overlap their containing folders. Branch counts are additions/deletions from each branch’s merge base with integrated Otto, **not additive savings**.

For compact citations below, `O` means `otto/otto`, `L` means `otto/labs`, `P` means `otto/projects`, and `A` means `astrid-plan-repo`, relative to this review directory.

The first table covers every immediate module or package under `O/src/otto`; children inherit the folder decision except where an extraction is identified below.

| Module or folder | Rough lines | Decision | Reason / destination |
|---|---:|---|---|
| `src/otto/__init__.py` | 1 | Leave | Old package scaffold; create the new package directly. |
| `src/otto/agents/` | 9,982 | Reference | Replace adapters, gateway, capture and owner runtime with `omp-rpc`; retain failure lessons. `agents/gateway.py:1`, `owner_runtime.py:1`. |
| `src/otto/attention.py` | 3,249 | Reference | Its Due/attention-port architecture explicitly avoids owning a database or scheduler; the new tool owns both. Replace with messages, schedules and a small loop. `attention.py:1`. |
| `src/otto/cli.py` | 95 | Leave | Gateway diagnostic CLI, not the requested CLI. `cli.py:1–18`. |
| `src/otto/engineering/` | 550 | Reference | Release responsibility over the Herzchen Store becomes task results plus Git history. `engineering/release_records.py:1`. |
| `src/otto/host_bridge.py` | 479 | Leave | Host automation-update effects are unnecessary for local schedules. `host_bridge.py:1`. |
| `src/otto/hostctl/` | 9,612 | Leave | Owner enrollment, authenticated lanes, shared heavy runner and installation composition are replaced by one package and supervisor. `hostctl/service.py:1`, `heavy.py:1`. |
| `src/otto/portfolio/` | 60,280 | Reference | Preserve user behaviours; replace the WRK/DAT/EDT bindings, journey services, receipt recovery and owner projections with direct SQLite operations. `portfolio/herzchen_binding.py:1`, `manager_journey_service.py:1`. |
| `src/otto/runner_cli.py` | 137 | Leave | Old fleet-runner verbs would conflict with the new supervisor meaning of `otto run`. `runner_cli.py:1–11`. |
| **`src/otto` total** | **84,385** | | **71,286 production Python lines**, excluding tests and fixture directories. |
| `src/herzchen/` | 48,448 | Leave | No neutral kernel, domain-registration framework or compatibility layer in v1. Extract the two small areas below without retaining Herzchen imports. `src/herzchen/packs/composition.py:1–17`. |

Together, the two source trees contain approximately **117,500 production Python lines**. Leaving them frozen avoids owning that implementation; it does not erase it.

These are the useful extraction boundaries.

| Source | Rough lines | Decision | What survives |
|---|---:|---|---|
| `O/src/otto/portfolio/project_folder.py` | 539 | Simplify | Extract `validate_files` and filesystem-safety behaviour into spec-folder validation. Replace the owner class completely. `:47`, `:203`, `:467`. |
| `O/src/herzchen/content/model.py::document_path` | 8 | Simplify | Portable relative-path validation, with a local exception type. `:53`. |
| `O/src/herzchen/fleet/landing.py` | 519 | Simplify | Rebase, check that exact commit, reject subsequent drift, then advance the target safely. Remove assessment, allowance and owner bindings. `:163`, `:226`. |
| `O/src/otto/hostctl/fleet_landing.py` | 507 | Reference | Task-to-landing integration cases; replace its composition with the new acceptance operation. `:1`. |
| `O/src/otto/portfolio/dependencies.py` | 239 | Reference | Dependency readiness and cycle prevention; implement against task rows, without portfolio gates and authenticated graph operations. `:122`, `:141`, `:162`. |
| `O/src/otto/portfolio/status.py` | 255 | Reference | Compact, read-only status; implement directly from the new tables. `:1`. |
| `O/src/otto/agents/host_profiles.py` | 116 | Leave | Seven-slot, host-specific model policy belongs to the old design. Use omp model roles. `:1–9`. |
| `O/src/herzchen/usage/contract.py` | 734 | Leave | Do not import a usage-accounting subsystem merely because an earlier plan recommended it. The current direction excludes spend controls. `:247`, `:470`; `retro/13-spec.md:93–104`. |
| `otto/portfolio/ops/ready.py` | 127 | Reference | Keep “derive readiness from current state”; discard Markdown parsing, merge-subject inference and PID-file inspection. `:1`, `:23`, `:35`. |
| `otto/portfolio/ops/integ.py` | 134 | Reference | Integrate-then-bisect is useful operational knowledge, not a required v1 batch subsystem. It has fixed paths and interpreter assumptions. `:2`, `:17–23`. |
| Astrid `origin/main` omp launcher / installer tools / recipe | 836 / 519 / 49 | Simplify | Lift login-readiness and pinned-install patterns, not the whole launcher or installer. At `aadd0ff`: `astrid/omp_agent.py:342`, `astrid/installer/tools.py:320`, `astrid/installer/omp/recipe.json:3`. |

**The folder implementation is not a transactional starting point.** It commits individual document operations and explicitly returns `atomic: False`, including partial-progress results. C3 needs a new transaction boundary, not a wrapper around this class. [Actual save result](../../otto-restored/otto/src/otto/portfolio/project_folder.py:467)

The surrounding implementation and evidence should be treated as follows.

| Folder | Rough lines | Decision | Reason |
|---|---:|---|---|
| `O/tests/` | 50,186 | Reference | Mine behaviour cases; do not port owner fixtures, authority assertions and receipt formats wholesale. Examples: `test_landing.py:275`, `test_work_readiness.py:98`. |
| `O/src/otto/portfolio/tests/` | 10,382 | Reference | Preserve document-concurrency, recovery and read-only-status expectations; replace their Store/owner setup. `test_document_sessions.py:43`. |
| `O/src/otto/agents/tests/` | 632 | Reference | Old adapter and proof fixtures; omp replaces the mechanism. `test_claude_binding.py:1`. |
| `O/src/herzchen/kernel/tests/` | 1,603 | Reference | Historical kernel evidence, not acceptance requirements for a kernel-free tool. |
| `O/controller/` | 529 | Leave | Patches and handoff instructions for an outside-Git controller at machine-specific paths. `README.md:3–19`. |
| `O/install/` | 11,146 | Leave | Includes 11,046 lines of controller code and one-off migrations. Replace with ordinary package installation and launchd/systemd units. `controller/operating_service.py:1–18`. |
| `O/install/runtime-manifest.json` | 1 | Keep | Historical installed snapshot. Do not regenerate it to describe the new tool. `install/README.md:1–3`. |
| `O/ops/` | 7,670 | Reference | Preserve bootstrap and disturbance scenarios; retire executable staging, spend bookkeeping and old gates. `bootstrap/perch_report.py:1`, `workers.py:1`. |
| `O/docs/` | 1,993 | Reference | Installation and operating documentation for the old product. Do not expose it as current guidance. `host-onboarding.md:1`, `manager-journey-commands.md:1`. |
| `O/policy-staging/` | 2,160 | Reference | Another policy copy, not a second maintained pack. Use the selected PACKS branch as the extraction source. |
| `otto/branches.json` and transfer provenance | 184 in branch map | Keep | Exact preservation identities, including installed baseline and draft-sync fix. `branches.json:2–21`. |

The Megado extraction needs more rewriting than “copy the pack” suggests.

| PACKS branch folder | Rough lines | Decision | Destination / reason |
|---|---:|---|---|
| `P/packs/src/otto/packs/megado/` | 1,854; 24 files | Simplify | Keep proportional review, lifecycle guidance, escalation questions and improvement habits. Rewrite as short role guides and on-demand skills. `skill/SKILL.md:71–86`, `skill/references/pragmatic-review.md:5–14`. |
| `…/otto-roles/` | 118 | Simplify | Keep responsibility boundaries; remove assignment generations, retained receipts, allowance holds and old command names. `roles.json:23–34`. |
| `…/otto-profiles/` | 165 | Leave | Replace host/profile/model tables and call caps with unset-only omp model-role seeds. `profiles.json:10–45`. |
| `…/astrid/` | 107 | Reference | Optional domain-template examples; no Astrid-specific protocol requirement in v1. `templates/film-edit.json:1`. |
| `…/engineering/` | 58 | Reference | Borrow task wording if useful; do not import its typed work-template machinery. `templates/code-task.json:1`. |
| `P/packs/src/herzchen/packs/` | 3,159 | Leave | Trusted-domain registration, authoring and template compilation are not needed for a folder of instructions. `composition.py:14–27`, `:58–65`. |

In particular, remove the pack’s **seven responsibility slots, `run.json` model authority, oracle/review allowances and owner-service activation rules**. They directly contradict the proposed five-role, omp-managed configuration. Preserve the historical text unchanged in the archive. Sources: `P/packs/src/otto/packs/megado/skill/references/run-config.md:3–15` and `skill/SKILL.md:24–37`.

Every lab and project branch has a disposition below. “Reference” does not mean its checks passed: the transfer records unresolved integration failures, including STAGE2CLIENT. See `otto/CURRENT-STATE.md:9–16`.

| Lab branch | Delta lines | Decision | What to retain or leave |
|---|---:|---|---|
| `BOOTCFG` | +97 / −11 | Reference | Exact installed interpreter/path and restart tests inform service units. `L/BOOTCFG/src/otto/hostctl/config.py:86`. |
| `BOOTLAND` | +355 / −46 | Reference | Crash-released locking and ambiguous-publication lessons; discard its old gate/push recovery. `L/BOOTLAND/ops/bootstrap/land.sh:17`. |
| `CLIARGS` | +143 / −19 | Reference | CLI round-trip case: absent arguments must not become explicit nulls. `L/CLIARGS/src/otto/portfolio/manager_journey_client.py:508`. |
| `DISTURB` | +2,061 / −34 | Reference | Translate disturbance scenarios to the new acceptance harness. `L/DISTURB/ops/bootstrap/perch.sh:175`. |
| `INTEG-PROCLIFE-PL3` | +413 / −23 | Reference | Supervisor-loss and surviving-child cases; omit durable custody-latch machinery. `L/INTEG-PROCLIFE-PL3/src/herzchen/fleet/hosts/contract.py:338`. |
| `LABPIN` | +755 / −90 | Reference | Preserve landed output until capture/cleanup is safe; omit occurrence-pin infrastructure. `L/LABPIN/src/herzchen/fleet/labs.py:390`. |
| `LANDBATCH` | +823 / −131 | Leave | Forty-task batches and D19 gate orchestration are outside the small landing path. `L/LANDBATCH/ops/bootstrap/land.sh:9`. |
| `LANDPROOF` | +782 / −49 | Reference | A code task is not done until its accepted commit actually reaches the configured branch. `L/LANDPROOF/src/herzchen/domains/work/assignments.py:764`. |
| `OBSOWNER` | +135 / −11 | Leave | Owner-authenticated native-process binding disappears with the gateway. `L/OBSOWNER/src/otto/portfolio/native_caller_ingress.py:103`. |
| `PROOFDOC` | +46 / −0 | Reference | Keep the distinction between fake and real-worker evidence. `L/PROOFDOC/RUNBOOK.md:3`. |
| `REALSTAGE3` | +1,878 / −116 | Reference | Real-worker canary scenario, not its owner-backed reporting system. `L/REALSTAGE3/ops/bootstrap/perch_stage3_report.py:1`. |
| `ROLEIDS` | +141 / −8 | Leave | Owner/operator/host principal taxonomy is unnecessary; retain ordinary unique agent IDs. `L/ROLEIDS/src/otto/hostctl/config.py:34`. |
| `ROOTFILE` | +43 / −38 | Leave | A blanket root-file landing prohibition is old program policy. `L/ROOTFILE/ops/bootstrap/land.sh:120`. |
| `STAGE2CLIENT` | +348 / −8 | Reference | Smoke-test the advertised installed CLI; do not repair the old service to obtain this lesson. `L/STAGE2CLIENT/src/otto/hostctl/cli.py:244`. |
| `TESTPATCH` | +507 / −235 | Reference | Realistic fixtures and integration seams, without old owner-record setup. `L/TESTPATCH/tests/test_fleet_custody.py:175`. |
| `XFERMAP` | +337 / −25 | Reference | Complete, fresh snapshot checks; omit the owner-to-owner transfer protocol. `L/XFERMAP/src/otto/portfolio/intake.py:1387`. |

| Project branch | Delta lines | Decision | What to retain or leave |
|---|---:|---|---|
| `astridfleet` | +202 / −0 | Reference | A study, not working Astrid integration; no fleet platform investment now. `P/astridfleet/.project/study.md:48–52`. |
| `effects` | +1,990 / −444 | Reference | Crash-window examples only; do not recreate its shared effect ledger. `P/effects/.project/PROJECT.md:8–12`. |
| `harness3` | +195 / −0 | Leave | A third custom host adapter is replaced by omp; core work was blocked on host selection. `P/harness3/.project/tasklist.md:8–12`. |
| `packs` | +2,867 / −454 | Simplify | Extract the content identified above; no branch merge or pack framework. |
| `proclife` | +3,505 / −345 | Reference | Keep orphan/overlap failure cases; leave generalized custody and heavy-job leases behind. `P/proclife/src/herzchen/fleet/custody.py:1`. |
| `slim` | +1,974 / −2,391 | Reference | Useful dependency/dead-code audit, but slimming the retired architecture is unnecessary. Preserve its warning about historical runtime manifests. `P/slim/.project/PROJECT.md:129–140`. |
| `throughput` | +625 / −8 | Reference | Keep actionable refusals and measurement lessons; omit adaptive test selection and caching work. `P/throughput/.project/PROJECT.md:7–16`. |

For the plan repo, archive old operating instructions without treating unfinished product work as completed.

| Plan-repo item | Rough lines | Decision | Reason / replacement |
|---|---:|---|---|
| Eight old root documents named in `retro/11` | 1,216 | Reference | Archive `README`, `ORCHESTRATOR`, `MANAGER`, `CODEX`, `PROGRAM`, `STATUS`, `GOAL`, `CONTRACTS`; replace the active README with the current entrypoint. `retro/11-thin-path-keep-and-clean.md:59`. |
| `MANAGER-CODEX.md` | 130 | Simplify | Extract continuous manager-led delivery and evidence reporting into the manager guide. Remove project paths, model bindings and file protocols. `:3–15`. |
| `tools/dispatcher.sh` | 121 | Leave | File requests, hard-coded models/repos and CI routing are superseded by CLI/store operations. `:13–35`, `:54–64`, `:97–108`. |
| `tools/keepalive.sh` | 18 | Leave | Process-name polling and repeated manager launches become supervisor/service responsibilities. `:5–16`. |
| `tools/recover.sh` | 11 | Leave | Old dispatcher recovery, not exact-session recovery. `:1`. |
| `tools/watch.sh` | 14 | Leave | Retire the parallel monitoring loop. `:1`. |
| `tools/run-worker.sh` | 8 | Leave | Direct host invocation becomes the omp spawn path. `:1`. |
| `tools/land.sh` | 38 | Reference | It merges and removes worktrees without checking the integrated commit; unsuitable for direct reuse. `:19–36`. |
| `tools/status.py` | 19 | Leave | Markdown status mutation becomes a database-derived view. `:1`. |
| `tools/snapshot.sh` | 23 | Reference | Preserve verified bundle/restore practice, not its fixed repo list and branch filters. `:8–20`. |
| `plans/` | 1,770 | Reference | Existing Astrid product commitments remain recorded; they are not new-tool requirements. See `MANAGER-CODEX.md:5–15`. |
| `retro/` | 7,643 | Simplify | Keep 13/14/15 current; mark older designs and implementation paths historical. `retro/README.md:1`, `:14–24`. |
| `evidence/` | 503 | Keep | Preserve source-backed findings and validation history. |
| `archive/` | 1,844 | Keep | Already historical; no need to rewrite or delete it. |
| `incoming/` | 1,025 | Reference | Preserve imported planning sources outside the active operating instructions. |
| `runs/` | ≈2.43 million; 176 MiB | Reference | Archive logs and briefs; retain an accessible index of queues, unresolved work and evidence. `runs/QUEUE.md:3`, `runs/TEST-QUEUE.md:11–14`. |
| `out/` | ≈327,500 text lines plus binaries; 102 MiB | Keep | Inventory and verify archives before deduplicating local copies. Current checkout has 14 top-level ZIPs, not the 20 stated in `retro/11:62`. |
| `COST-LOG.md` | 24 | Reference | Historical accounting only; no new spend ledger. |
| `MANAGER-SESSION.id` | 1 | Leave | Archive as a historical locator; never adopt it as a live seat binding. |

The seven other remote plan branches also need preservation, not automatic pruning. These are measured deltas from their merge base with current `9f5a473`; `+0/−0` does not prove redundant history.

| `origin/claude/…` branch | Delta lines | Decision |
|---|---:|---|
| `gallant-brown-ulwhyx` | Current HEAD | Keep current working history. |
| `adoring-johnson-kev9qh` | +0 / −0 | Reference; preserve its distinct commit. |
| `epic-shannon-0o8n05` | +168,227 / −0 | Reference; 255 commits absent from current HEAD. |
| `intelligent-fermi-bv3jhu` | +399 / −0 | Reference; preserve unique work. |
| `loving-tesla-hxapi1` | No shared base | Reference; preserve independently. |
| `nifty-pascal-pxn03n` | +1,994 / −0 | Reference; preserve unique work. |
| `tender-bell-vwi7un` | +0 / −0 | Reference; ancestor of current HEAD. |
| `tender-ride-higxx2` | +951 / −0 | Reference; preserve unique work. |

This replaces the blanket pruning suggestion in `A/retro/11-thin-path-keep-and-clean.md:65`. The referenced `handoff-upd/snapshot` is absent from this checkout; its retirement cannot be assumed necessary.

The **top ten removals or simplifications, ordered by impact**, are:

1. **Leave the Herzchen/owner architecture behind.** Replace resource references, command facades, authenticated domain contributions and owner compositions with one SQLite store and explicit application operations. No compatibility facade. The current composition requires domain registration and conformance metadata before becoming ready: `O/src/herzchen/packs/composition.py:58–65`.

2. **Remove custom Claude/Codex execution adapters and gateway policy.** Use the pinned `omp-rpc` client for transport and omp for sessions, credentials, model roles and native sub-agents. Its client already supplies process-backed request correlation and event listeners: `oh-my-pi/sdk/python/omp-rpc/README.md:3–20`.

3. **Retire the installed controller and its migration patches.** Replace approximately 11,000 controller lines with the new package plus service units. Fixed original-machine paths and W0-specific source selections are historical migration machinery, not reusable installation infrastructure: `O/install/controller/operating_service.py:9–18`, `w0_selected_context_adapter.py:8`.

4. **Drop fleet capacity, generalized process custody and the shared heavy-job runner.** Retain a small supervisor that proves exclusive session ownership or stops for reconciliation. Use ordinary worker worktrees; managers choose dispatch. The old dispatcher composes capacity, token books, admission, MCP grants and host turns: `O/src/herzchen/fleet/dispatch.py:35–68`.

5. **Replace per-document receipt recovery with transactional spec saves.** Keep path/text validation. Write revisions, checkout bookkeeping and the manager notification through the new transaction contract. The old partial-commit design is explicit: `O/src/otto/portfolio/project_folder.py:467–484`.

6. **Delete spend controls and competing model policy from the new product and pack.** No usage parser, oracle allowance, seven-slot profile table or `run.json` model authority. Use omp choices and ordinary role guidance. This also supersedes the usage-parser reuse recommendation in `retro/11:37`; see `retro/13-spec.md:171–175`.

7. **Collapse the communication mechanisms.** Replace Due ports, issue/help delivery, advisor delivery, file lanes and receipt projections with one durable message table and one delivery loop. Advisor consultations and nudges are messages, not new protocols. Current separate mechanisms include `O/src/otto/portfolio/advisor_delivery.py:1`, `help_delivery.py:1`, `client_lanes.py:1`.

8. **Make packs content, not a framework.** One manifest, four supervised-role guides, native sub-agent definitions, skills and templates. Remove pack stacking, domain registration, protocol compilation and duplicated host defaults. `P/packs/src/herzchen/packs/composition.py:14–27`; `retro/13-spec.md:177–188`.

9. **Reduce landing to its essential correctness rules.** Preserve exact-commit verification and concurrent-target protection. Drop D19 approvals, repeated baseline sweeps, batch orchestration, automatic publication and cleanup coupled to push success. The old bootstrap gate bundles all of these: `O/ops/bootstrap/land.sh:2–13`. The plan repo’s 38-line script is not a safe substitute.

10. **Retire the parallel shell control plane and stale operating documents.** `otto run`, database-derived status and pack guides replace dispatcher/keepalive/recover/watch and mutable Markdown queues for new work. Archive old queues as evidence rather than maintaining both systems. `A/tools/keepalive.sh:5–16`, `A/runs/QUEUE.md:3`.

The plan can still drop or narrow the following without sacrificing the owner’s direction.

| Current burden | Smaller choice | What would be lost |
|---|---|---|
| Two execution plans: spec Part C says ≈28 days; plan says 46 | Remove the task schedule from `13-spec.md`; link to `14-plan.md`. Keep 15 as the summary. Sources: `13:228–253`, `14:138–147`. | Nothing; removes contradictory estimates and duplicated upkeep. |
| SQLite delivery-on-settle **and** omp `follow_up` queueing while busy | For v1, keep pending messages in SQLite and submit when settled. Preserve acknowledgement and crash-safe retries. Sources: `13:75`, `13:128`, `14:111`. | No immediate enqueue into a busy session; the primary stated contract already permits waiting. |
| Optional Claude Code inbox hook in AT | Defer the hook. Pull-only inbox plus role instructions satisfies initial external attachment. Sources: `13:86`, `14:103`. | Convenience only. |
| Several orchestrators per database left open | Choose one orchestrator per database; a separate organisation uses another database. Source: `14:204`. | Shared-database multi-organisation operation. |
| Broad “reconciliation helpers” in C5 | Durable spec-change notification, snapshot references and explicit task edit/cancel commands; the manager interprets the changes. Sources: `13:74`, `13:99–100`, `14:102`. | Automatic reconciliation, which is already out of scope. |
| Generic pack version behaviour and overlapping shared/pack skill names | Pin the selected pack version, define simple precedence and keep each generic skill in one place. No resolver, migration engine or stacking. Sources: `13:165–184`, `14:119`. | Automatic pack upgrades and composition. |
| “Sync-ready … at no cost now” | Keep cheap UUID/project identifiers; drop the implication that replication solves future multi-writer semantics. No sync implementation now. Source: `13:153–160`. | A speculative guarantee, not present functionality. |
| “Every change” event logging becoming another evidence platform | Record meaningful application transitions transactionally; leave transcripts and provider accounting with omp. Sources: `13:65`, `13:151`. | Rich old-style forensic/usage queries. |
| “A repeated [message] does no harm” | Limit the guarantee to idempotent **tool-owned state transitions**. Do not build an arbitrary shell/provider effect ledger to satisfy a broader reading. Sources: `15:12`, `13:75`, `14:220`. | At-most-once guarantees for arbitrary external effects. |

Also correct `15:20`: one SQLite file holds **tool state**, not literally everything. The spec already requires omp’s sessions/credentials and repositories when moving machines (`13:113`). A misleading “copy one file” promise could otherwise recreate an unnecessary import/export subsystem.

The meaningful losses are explicit: authenticated multi-host authority, at-most-once effect custody, comprehensive descendant cleanup, APFS lab optimisations, shared heavy-job capacity, and richly typed assessment/usage records. Preserve the evidence for these features, but accept their absence in the one-machine tool. These are already identified in `retro/11-thin-path-keep-and-clean.md:6–16`; they are not supplied automatically by switching to omp.

The following removals should **not** be made:

- **Do not remove the five roles, persistent advisor or manager-led dispatch.** The advisor is an ongoing portfolio-consultation seat; worker completion remains submission for manager acceptance. `retro/13-spec.md:43–47`, `:61`, `:76`.
- **Do not remove transactional check-in, conflict detection, tombstones or filesystem validation.** These are the requested product, not excessive controls. Preserve independent-path saves and all-or-nothing failure. `retro/14-plan.md:99`; `O/src/otto/portfolio/project_folder.py:47`.
- **Do not remove durable message IDs, acknowledgement, reply correlation or idempotent state changes.** Old asks explicitly distinguish the asking session from a replacement session: `O/tests/test_ask_runner_session.py:18–32`.
- **Do not remove exclusive seat ownership and exact-session recovery.** Retiring process-custody architecture does not permit two holders or silent replacement. Preserve attachment to any seat; AT’s orchestrator/manager examples must not silently narrow that requirement. `retro/13-spec.md:82–90`; `retro/15-in-short.md:21`.
- **Do not remove dependency readiness, isolated worker worktrees or checked landing.** Preserve the rebased-commit and target-drift cases: `O/tests/test_landing.py:243`, `:275`; `O/src/herzchen/fleet/landing.py:231–234`.
- **Do not remove the spike, early vertical slice, platform smoke tests or real pilot.** They test the replacement’s difficult boundaries. Update D3 and the completion checklist from B6 “1–10” to **1–11**, retaining attach coverage already present in the spec. `retro/14-plan.md:92`, `:112`, `:133`, `:179`; `retro/13-spec.md:202`.
- **Do not discard test history, installed manifests, branch refs or unfinished product decisions.** Archived tests remain useful even where their implementation-specific assertions no longer apply. `otto/START-HERE.md:7–15`, `:36–44`.

A safe cleanup sequence is:

1. **Freeze before extraction.** Record/tag integrated `a70b3f2`, installed `bbd9b6d`, draft-sync `b834793`, and all lab/project tips from `branches.json`. Preserve the existing refs. Do not resume the paused program or land preservation branches. `otto/START-HERE.md:7–11`; `CURRENT-STATE.md:5`.

2. **Create and verify complete archives.** Preserve Git history, portfolio records, source manifests, selected evidence and any untracked material. Verify bundles and rehearse restoration into a separate location before retiring duplicate checkouts. Archive all plan-repo refs, including the unrelated-history branch.

3. **Treat live state separately.** The transfer explicitly contains no live database, credentials or session stores. Any eventual retirement of the Mac installation needs its own consistent state backup after shutdown; this review does not establish that those data are backed up. `otto/START-HERE.md:34–36`.

4. **Extract into a new sibling repository/package.** Record the source commit for each lifted helper, test case and pack passage. Keep the frozen repository untouched. Avoid compatibility wrappers and wholesale cherry-picks.

5. **Prove the replacement before changing the active entrypoint.** Validate atomic saves, exclusive sessions, durable replies, checked landing, both operating systems and external attachment. Keep useful old tests as traceable behaviour sources rather than making the old suite the new acceptance gate.

6. **Archive the old operating surface.** Move superseded plan documents and scripts behind a historical index; preserve queues and unresolved obligations. Deduplicate outputs only after checking archive contents. Retire redundant worktrees without deleting refs or history. Inventory any external schedules and CI repository separately—the local files do not prove their current operational state.

No cleanup, tag, archive, branch or service changes were performed.