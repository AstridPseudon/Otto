**The architecture can reach the vision; the spec is not yet build-ready.** Its largest gaps are the work lifecycle, Pi session lifecycle, and the mechanics of consultation. These need clearer contracts, not more controls.

References below use sections of [the spec](/home/user/repo/astrid-install/retro/13-spec.md:1). I read the design and all five reports, verified the main claims against source, and did not rerun tests.

1. **Vision coverage**

| Owner’s requirement | Verdict | Why |
|---|---|---|
| Four roles | **Met** | Explicit hierarchy and next-role spawning, §§1–2, 6. |
| One central spawn path | **Partly met** | Pi is central, but root-orchestrator creation is undefined; §11 still permits a different orchestrator host. |
| Generic plus job-specific instructions | **Partly met** | Manager/worker composition exists. Orchestrator-specific instructions and a sub-agent’s narrower assignment are missing, §6. |
| Configurable hourly/three-hourly reminders | **Partly met** | Interval storage and pack defaults exist; configuration/update commands and delivery during busy periods are unspecified, §§4, 6–7. |
| Second opinion every 3–6 hours | **Not met mechanically** | A reminder prompt is specified, not a second-model invocation and returned opinion, §§6, 11. |
| Extensible project spec folder → task list | **Partly met** | Documents and task rows exist; decomposition and reconciliation after edits are undefined, §§2, 5–6. |
| Keep checkout/check-in synchronization | **Partly met** | Core stale-base behavior is specified. Concurrent checkouts, deletion, refresh and crash recovery need completion, §5. |
| Manager → worker → sub-agent, end to end | **Partly met** | Spawning exists; child assignments, result acceptance and completion propagation do not. The pilot omits sub-agents, §§6, 8. |
| Basic structure; no spend controls | **Met** | Explicitly respected, §§1, 10. |
| Skills for basic processes | **Met in scope** | All requested skills are listed, §7. Their effectiveness remains untested. |
| Megado plus alternative packs | **Partly met** | Content/configuration layout exists; template initialization, precedence and version behavior are undefined, §§2, 7. |
| Minimal; reuse existing work | **Partly met** | Retiring the owner/Herzchen architecture fits. Blanket rejection of code reuse goes too far, §§1, 9. |
| Tool now, protocol later | **Partly met** | Sensible direction; publishing tables alone will not define interoperable command behavior, §§1–4. |
| Portable SQLite; optional Turso | **Partly met** | Database portability is covered; resumable sessions and working files live elsewhere, §§3–4. |
| No commitment to Herzchen | **Met** | Explicitly excluded, §10. |
| Elegant and tested | **Partly met** | Useful acceptance intentions, but inherited test names overstate coverage of the new architecture, §8. |

2. **Ambiguities, ranked, with suggested resolutions**

| Rank | Ambiguity | Suggested resolution |
|---:|---|---|
| **1** | **Spec → tasks → changed spec** (§§2, 5–6). Two engineers could build a one-time import or continuous synchronization. | Make reconciliation a **manager skill**. Record the spec revision snapshot used for planning and source references on tasks. Saving documents notifies the manager; it updates stable task IDs, cancels obsolete work, and explicitly redirects affected running workers. No automatic prose-to-task parser. |
| **2** | **Pi process, session, idle and restart semantics** (§§3, 6). “Resume” could mean a prompt to a live process or launching another process. | Pin Pi; use one RPC process per active agent, with session ID, session-file location and working directory recorded. Define idle as settled with no queued continuation. Define recovery separately from normal prompting; never silently create a replacement session. |
| **3** | **Delivery “once,” replies and resolution** (§§4, 6, 8, 10). `delivered_at` cannot atomically cover both SQLite and Pi. There is no `in_reply_to`. | Add message/reply correlation and serialize delivery per agent. Specify at-least-once delivery with stable message IDs and acknowledged delivery state; explicitly exclude exactly-once model/tool effects. Test the crash window after Pi accepts a prompt. |
| **4** | **Concurrent checkouts and editing rights** (§5). The conflict rule is useful, but checkout independence and base advancement are undefined. | Allow any assigned project agent to edit through its own checkout; manager reconciles resulting task changes. Different-path edits succeed; same-path edits conflict atomically. Advance a path’s base only when local bytes correspond to that revision. Specify deletion tombstones, conflict recovery and manifest recovery after a crash. |
| **5** | **Orchestrator deployment “based on instructions”** (§6). There is no root bootstrap, portfolio mandate or project-selection contract. | Root spawn needs neither parent nor project. Supply generic orchestrator instructions plus the owner’s mandate, project list and priorities. Its skill chooses projects and calls normal manager spawn. Enforce one active manager per project. Clarify that §10 excludes a deterministic dispatcher, not agent-driven dispatch. |
| **6** | **Sub-agent assignment and task ownership** (§§4, 6). Passing the worker’s task gives both agents the same brief and potentially the same assignee slot. | Give child agents a narrower assignment brief while retaining the task reference. Sub-agents report to workers without claiming the parent task. Workers submit results; managers decide completion. Define failure, cancellation and retry transitions. |
| **7** | **Second opinion** (§§6–7, 11). Model choice is only one missing piece; strict hierarchy also prevents a direct reviewer child. | Define a scheduled, one-shot peer consultation through the central launcher: separate session, configured model, portfolio/spec/status snapshot, explicit review prompt, answer delivered to the orchestrator. State how this consultation fits the root-role rule and suppress its own recurring schedules. |
| **8** | **Pack precedence and versions** (§§2, 7). Does editing a pack change existing projects or resumed agents? | Use one selected pack per project in v1; no pack stacking. Define explicit overrides → pack defaults. Record pack version/content identity and resolved configuration for each session; upgrades are explicit. Choose JSON/TOML or add a YAML dependency—§3’s standard-library-only promise does not supply YAML parsing. |
| **9** | **Turn-end strikes and legitimate waiting** (§6). “Consecutive,” “say why,” running children and observation mode have several interpretations. | Evaluate once per settled invocation. Distinguish unfinished assignments from actively generating processes, including workers awaiting sub-agents. Specify blocker handling, reset conditions and whether observation mode actually sends escalations. Prevent repeated hooks from creating repeated strikes. |

The Pi distinction is material: current documentation says `turn_end` finishes one assistant response/tool batch; even `agent_end` can precede retries or compaction. `agent_settled` is the session-level boundary. A successful RPC prompt response means acceptance, not completion. [Pi event reference](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/json.md), [Pi RPC lifecycle](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md).

3. **What’s missing, ranked**

1. **A usable bootstrap and operating command set.** §6 lacks project creation/import/template initialization, schedule management, and explicit stop/resume/retry operations. The pilot currently assumes someone has already populated and configured the database.

2. **A workspace and integration contract.** Neither projects nor agents identify repository, working directory, branch/worktree, landing target or check command. Parallel workers can edit the same checkout, and the landing script cannot determine what to check. Add these as small project/assignment settings.

3. **Basic failure recovery.** No transition explains failed launches, provider errors, vanished processes, or an interrupted `otto run`. A dead child can remain “running”; a dead reminder loop cannot wake the orchestrator. Define startup reconciliation, visible failure reasons and manual recovery, with an ordinary OS service keeping the loop running.

4. **Portability of actual work.** Copying the SQLite file does not copy Pi’s session files, repositories, packs or unpublished checkout edits. Pi exposes a separate `sessionFile` alongside its session ID. Define a stopped-instance backup/move procedure and what must accompany the DB. Select one Turso operating mode; cloud replication and offline multi-writer operation are different scopes. [Pi state reference](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc-commands.md#get_state).

5. **Acceptance coverage for the distinctive promises.** Extend §8’s pilot to include a sub-agent, a spec change during work, two concurrent checkouts, an actual second opinion, restart during delivery, and an alternative pack. Existing acceptance names do not establish those behaviors.

4. **Over- and under-engineering**

- **Appropriate:** nine tables, immutable revisions, optimistic conflicts, an event log and one hierarchy. These directly support requested behavior.
- **Potential excess:** the optional flake policy and project-dependency machinery. Defer both unless the pilot needs them.
- **Possibly unnecessary:** a TypeScript extension solely for turn-end checks. If `otto run` owns every RPC session, it can consume the settled event and invoke the Python check itself.
- **Too thin:** the lifecycle connecting spec edits, task assignments, sessions, messages and accepted results. This needs a few explicit transitions and invariants—not an authority framework.
- **Misleading precision:** “50 lines,” “300–500 lines” and “every behaviour has a test” are not acceptance criteria. Define observable outcomes and failure cases instead.
- **Keep the rejected controls rejected.** None of these corrections requires spend limits, authenticated decisions, an owner service or a general effect ledger.

5. **Reuse corrections**

**“Port semantics, not code” is right for the large architecture, wrong as a blanket rule.** Replace it with “rewrite coupled boundaries; extract small tested units.”

- **Lift/adapt the folder validators.** `validate_files` already handles UTF-8 sizes, case collisions and file/directory conflicts. Adapt reserved names for `.otto-checkout.json`; preserve the corresponding cases. See [project_folder.py:47](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/spec-minimal/otto/otto/src/otto/portfolio/project_folder.py:47) and [fixtures/project_folder.py:404](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/spec-minimal/otto/otto/src/otto/portfolio/fixtures/project_folder.py:404).

- **A real reusable code unit was missed:** throughput’s `_feedback_argv` is a standalone function using standard-library/git operations. Its selector and focused tests can be extracted if fast worker feedback is wanted; it must remain separate from final acceptance. See [throughput/landing.py:388](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/spec-minimal/otto/projects/throughput/src/herzchen/fleet/landing.py:388) and [throughput/test_landing.py:332](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/spec-minimal/otto/projects/throughput/tests/test_landing.py:332). This is optional reuse, not a reason to expand v1.

- **Correct the landing source attribution.** Astrid’s script commits and performs `merge --no-ff`; it neither rebases nor runs post-integration checks. The intended sequence is evidenced in Otto’s landing implementation and tests. See [astrid-plan-repo/tools/land.sh:19](/home/user/repo/astrid-install/tools/land.sh:19), [throughput/landing.py:104](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/spec-minimal/otto/projects/throughput/src/herzchen/fleet/landing.py:104) and [throughput/test_landing.py:273](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/spec-minimal/otto/projects/throughput/tests/test_landing.py:273).

- **Atomic folder saves are new behavior.** Otto explicitly commits document operations separately; its folder CLI refuses removed files. Thus §5’s atomic transaction and deletion support are improvements requiring new tests, not already-proven behavior. See [project_folder.py:1](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/spec-minimal/otto/otto/src/otto/portfolio/project_folder.py:1) and [cli.py:1403](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/spec-minimal/otto/otto/src/otto/portfolio/cli.py:1403).

- **The inherited checkout tests have different assumptions.** The restart test rejects a competing open as `occupied`; the conflict test injects an external revision. Neither proves several independent writable checkouts. See [test_document_verification.py:81](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/spec-minimal/otto/otto/src/otto/portfolio/tests/test_document_verification.py:81).

- **Reuse pack content and test scenarios, with honest provenance.** Pack passes are recorded in [packs/.project/PROJECT.md:8](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/spec-minimal/otto/projects/packs/.project/PROJECT.md:8); they do not validate the newly condensed four-role pack. The sixteen lab snapshots share tests rather than supplying sixteen independent validations. Harness3 also supplies no completed Pi adapter: [harness3/tasklist.md:7](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/spec-minimal/otto/projects/harness3/.project/tasklist.md:7).

6. **Estimate and risks**

- **Arithmetic:** §9 totals **23.5 engineer-days**, or **22.5 without Turso**. The rounded total is reasonable.
- **Critical path:** the written stage ordering totals **18 days**. Starting pack work earlier reduces it to **17**, not 15.
- **Credibility:** roughly 23 days is plausible for a tightly scoped prototype after resolving the ambiguities. It is optimistic for the complete tested operating behavior. My planning allowance would be **25–35 engineer-days for a single-host pilot**, excluding offline multi-writer sync; re-estimate after the Pi spike.
- **Riskiest task:** **#6, Pi spawn/resume, tightly coupled to #7 messaging.** Session identity, asynchronous completion, process loss and uncertain delivery affect almost every other feature. **#3 checkout synchronization** is next.
- **Better order:** first prove spawn → ask → answer → same-session continuation → settled check → restart. Build pack content alongside it. Then add spec/task reconciliation and concurrent checkout tests, schedules/consultation, and the full four-role pilot. Turso comes afterward.
- **“About a week with agents” is unsupported.** Parallel coding does not remove the stated dependencies or live integration work.

7. **The five changes I would make before building**

1. **Add one lifecycle contract:** root bootstrap, role-specific inputs, task ownership, child results, acceptance, cancellation and failure recovery.
2. **Specify spec/task reconciliation and checkout behavior:** revision linkage, editing rights, independent checkouts, deletion, refresh and crash-safe base handling.
3. **Replace “resume once” with a pinned Pi/RPC contract:** precise idle boundary, session storage, reply correlation and explicit delivery guarantees.
4. **Finish the configuration contract:** one pack per project, versions/overrides/templates, editable schedules, and an executable second-opinion flow.
5. **Rewrite §9 around verified reuse and an early vertical slice:** correct the landing claim, extract bounded helpers, expand the pilot, and replace the 15-day/one-week claim with the actual dependency calculation.