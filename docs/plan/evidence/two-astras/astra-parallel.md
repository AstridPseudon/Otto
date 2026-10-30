> Astra (read-only review, 30 Oct). Links into `/tmp/...scratchpad` point at the clones used for the review; they are not in this repo.

**Run four projects concurrently, each with its own manager and spec folder.** The extra parallelism should come from workers within those projects: especially separate spawn/message workers under M2, and separate landing/harness/install workers under M4. Additional managers would not remove a dependency.

Using the plan’s task estimates, target **20.5 working days—about 21—with 22 as the fallback**. This preserves approximately **53 engineer-days** of work, including the pilot and contingency. It requires eight concurrent worker tasks at the busiest point; four managers must not become four serial implementers.

| Project / proposed spec folder | Scope and size | What it needs before starting / finishing | Interface to other projects | Manager |
|---|---|---|---|---|
| `projects/state/` | Schema, transactional spec folders, tasks/attempts, CLI, spec-change decisions, status. **12 days** | Start after L0. Spec/task work after C1; final reconciliation and status need runtime events. | Store transitions and transactions; task/attempt identities; spec snapshots; query results. | **M1** |
| `projects/runtime/` | Supervisor, spawn, messages, recovery, sub-agent recording, vertical slice. **12.5 days** | Adapter preparation against L0 stubs; R1 qualification needs C1. **R2 and R3 run concurrently after R1.** | Resolved launch configuration; admission/outcome/settled events; durable delivery and recovery operations. | **M2** |
| `projects/pack/` | Pack loader, role guides, skills, generated helper definitions, templates, schedules/advisor, idle-manager policy. **11 days** | Content starts against the frozen role format; behaviour starts against fake clock/events. Final behaviour qualification needs the real runtime and VS. | Role/configuration resolver; pack fixtures; schedule inputs and settled notifications. | **M3** |
| `projects/delivery/` | Three parallel work lanes: **Git landing**, **acceptance harness**, **install/OS units/docs**; then pilot and fixes. **13.5 days**, including 5 for pilot/fixes. | Install after S0; Git adapter and harness after L0. Landing qualification needs C4; service qualification needs C2/R1; pilot needs everything. | Repository/worktree/check-command contract; task commit records; installed CLI; fake RPC process and crash hooks. | **M4** |

These preserve the existing ownership boundaries, including M1’s migration ownership and M3’s ownership of pack text. The orchestrator’s S0, L0 and closeout add another **4 days**. Each folder should hold its own scope, task queue and acceptance, while referencing one shared L0 contract. Independence means independently implementable and testable; final release qualification remains shared. [14-plan.md:75](/home/user/repo/astrid-install/retro/14-plan.md:75), [14-plan.md:110](/home/user/repo/astrid-install/retro/14-plan.md:110), [14-plan.md:141](/home/user/repo/astrid-install/retro/14-plan.md:141)

**The narrow waist should take the existing two-day L0, after the 1.5-day S0.** Do not compress live feasibility into an assumption. Use L0’s first half-day to settle role-file and CLI shapes, then finish lifecycle semantics, examples, stubs and manager sign-off. Full parallel implementation starts at elapsed day 3.5. [14-plan.md:107](/home/user/repo/astrid-install/retro/14-plan.md:107)

The shared agreement can remain small:

| Contract | What must be settled |
|---|---|
| **State and ownership** | M1 owns migration numbering and merges schema changes. Define transactional save-plus-notification, one current attempt, stale-submission rejection, submitted/checked/landed commits, and persistent seat/session identity. Other managers implement their changes through that owner. |
| **Lifecycle and messages** | Distinguish admission, turn outcome and settlement; define acknowledgement and operation-key replay; retain exact session identity, profile and worktree during recovery; specify surviving-child handling. |
| **CLI and launch** | Freeze command arguments, identity resolution, result/error shapes and CLI-to-supervisor calls. Include `project new --from`, needed by the attach follow-up. M1 owns command registration; domain owners supply handlers. |
| **Pack format** | Freeze allowed ranks, role name, instruction file, skills, model alias, version/hash recording and configuration precedence. Choose one authoritative location for role skill selections—the current documents mention both front matter and `pack.toml`. |
| **Landing and crash points** | Define Git inputs and commit evidence, target-movement refusal and Git/database reconciliation. Name hooks around save commit/checkout update, message admission/effect/acknowledgement, supervisor loss with surviving children, and Git landing/database recording. |

These are already substantially required by L0; the work is to make them executable boundaries, not expand them into a framework. Freeze semantics and shared shapes. Allow internal implementation changes freely; change an interface through one contract diff reviewed by its producer and consumers, with M1 handling migrations and the orchestrator resolving disagreements. [14-plan.md:108](/home/user/repo/astrid-install/retro/14-plan.md:108), [13-spec.md:216](/home/user/repo/astrid-install/retro/13-spec.md:216), [13-spec.md:222](/home/user/repo/astrid-install/retro/13-spec.md:222), [16-three-reviews.md:79](/home/user/repo/astrid-install/retro/16-three-reviews.md:79)

**Integrate continuously into one new sibling repository.** Four project folders should not become four repositories or long-lived integration branches. The agreed direction already calls for building beside frozen Otto. [16-three-reviews.md:59](/home/user/repo/astrid-install/retro/16-three-reviews.md:59)

1. **The orchestrator owns integration priorities and the release gate; M4 operates landing into `main`.** Managers accept worker results and send small checked candidates to that lane. Workers use separate worktrees. Keep schema changes with M1 and supervisor lifecycle changes with M2.
2. **Land contracts, package/CLI skeleton and test infrastructure first**, followed by C1 and P1. Replace stubs incrementally with store, supervisor, spawn, messages and landing implementations. Stubs enable development; they do not satisfy task acceptance.
3. **Use checked fast-forward landing from the outset:** rebase, check that exact commit, verify the target has not moved, then advance it. A moved target requires another rebase/check. Preserve the worktree on failure. Otto’s implementation contains that sequence; the plan repository’s `tools/land.sh` uses `--no-ff` and removes worktrees, so it is unsuitable for this build. [landing.py:163](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/herzchen/fleet/landing.py:163), [landing.py:296](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/herzchen/fleet/landing.py:296), [land.sh:29](/home/user/repo/astrid-install/tools/land.sh:29)
4. **Run the installed-wheel CI gate on every candidate:** unit → acceptance → real-omp compatibility, using real storage/Git/processes and fake model replies. Keep the proposed serial 3–5-minute job. Skips, empty collection, hangs and leaked processes fail. Add acceptance tests with their implementations; an early partial suite must not be described as full B6 acceptance. [16-three-reviews.md:92](/home/user/repo/astrid-install/retro/16-three-reviews.md:92)
5. **Prove the runtime joins at VS, ending around day 13.5**, then prove the remaining joins through spec-change propagation, persistent advisor consultation, alternative-pack installation and the pilot. VS is necessary, but does not qualify all four projects. [14-plan.md:126](/home/user/repo/astrid-install/retro/14-plan.md:126), [16-three-reviews.md:87](/home/user/repo/astrid-install/retro/16-three-reviews.md:87)

**The schedule needs one arithmetic correction and two deliberate task splits.** The published 23.5-day schedule puts D6 and X0 together in a two-day window, although D6 takes two days and X0 takes another half-day **after** D6. Its serial version therefore totals 24 days. With R2/R3 parallel, the unchanged dependency chain totals **22 days**:

`S0 1.5 + L0 2 + C1 2 + R1 3.5 + max(R2 2, R3 3) + VS 1.5 + R4 2 + C6 1 + D5 3 + D6 2 + X0 0.5`

The plan’s “about 21” shortcut does not reconcile that full chain. [14-plan.md:149](/home/user/repo/astrid-install/retro/14-plan.md:149), [14-plan.md:173](/home/user/repo/astrid-install/retro/14-plan.md:173)

For the **20.5-day target**, retain all task effort but split preparation from qualification:

- **R4:** 1.5 days of scheduler/snapshot work against fixtures before VS; 0.5 day of real integration after VS.
- **C6:** 0.5 day of query/CLI preparation against representative rows; 0.5 day after R4.
- **D3:** 1.5 days of infrastructure, 1 day growing cases alongside implementations, 0.5 day of final qualification.
- **D2:** build its Git portion against a fake task store, then complete reconciliation against C4.

Those splits are proposals requiring confirmation during L0. They preserve the original completion gates. The final half-days must contain verification and small integration work, not unfinished feature development. [14-plan.md:118](/home/user/repo/astrid-install/retro/14-plan.md:118), [14-plan.md:138](/home/user/repo/astrid-install/retro/14-plan.md:138), [14-plan.md:146](/home/user/repo/astrid-install/retro/14-plan.md:146)

| Working day | Parallel work and milestone |
|---|---|
| **1** | S0: pinned omp/client, real login/session/recovery probes. |
| **2** | Finish S0 halfway through; begin L0 and installation work. |
| **3** | L0 interfaces, failure semantics and examples; install smoke tests. |
| **4** | Finish L0 halfway through; start C1, P1, fake RPC/provider infrastructure and Git landing adapter. |
| **5** | Continue C1; complete P1 and initial harness/Git scaffolds. |
| **6** | C1 finishes halfway through. Start R1, C3, C4 and C2; parallel role guides, skills, helper definitions, templates and docs. |
| **7** | Continue supervisor, transactional save and task work; join CLI/templates; pack content continues. |
| **8** | C4 completes; landing connects to real task records. Continue R1/C3 and pack qualification. |
| **9** | Complete and qualify R1/C3; landing reconciliation finishes. |
| **10** | **R2 and R3 run concurrently**; separate worker handles R5b. Qualify OS service units against real CLI/runtime. |
| **11** | R2/R3/R5b continue; harness cases grow; fixture-backed R4 work begins. |
| **12** | R3 completes; record sub-agents through R6; finish R4 preparation. |
| **13** | Begin live VS; spec→task reconciliation and idle policy work; status preparation. Include fresh-agent skill qualification in this stage. |
| **14** | VS finishes halfway through; complete R4 integration. Finish spec-change propagation and cancellation checks. |
| **15** | Final status integration, remaining acceptance joins and full installed-wheel qualification. |
| **16** | Pilot: all ranks, concurrent workers/checkouts and specialist roles. |
| **17** | Pilot: spec change and advisor consultations; switch idle policy from observation to enforcement halfway through the pilot. |
| **18** | Pilot: delivery restart, checked landing, alternative pack; record outcomes. |
| **19** | Pilot fixes. |
| **20** | Pilot rerun and qualification. |
| **21, first half** | X0: preservation, verified bundles and archive closeout. |

The bottleneck remains **C1 → R1 → R3 → live VS**, followed by qualification. More content or installer workers will not shorten it. Further acceleration would require demonstrating that substantial R1 adapter work can safely precede C1; I would re-estimate that after S0 rather than assume it now. Keep the three-day pilot and two-day contingency. Review availability also matters: managers must accept finished work promptly, as the runbook explicitly records queues waiting on overloaded managers. [14-plan.md:123](/home/user/repo/astrid-install/retro/14-plan.md:123), [02-principles-and-runbook.md:20](/home/user/repo/astrid-install/retro/02-principles-and-runbook.md:20)

**Bootstrap with today’s Claude Code or Codex sessions.** Use one orchestrator, four manager sessions and bounded worker sessions, with Git-backed project folders and explicit queues. Prove one worker end to end before fan-out. Briefs name the task, repository/base, owned files, completion check and evidence; managers drain completed results before dispatching more work. Apply the current minimal policy rather than importing obsolete controls from the historical runbook. [02-principles-and-runbook.md:67](/home/user/repo/astrid-install/retro/02-principles-and-runbook.md:67), [02-principles-and-runbook.md:89](/home/user/repo/astrid-install/retro/02-principles-and-runbook.md:89)

After VS, use the tool experimentally for a bounded, noncritical task **only once task/landing/recovery checks are also green**. Keep the external build organisation authoritative through the pilot. After successful qualification, start the new managed organisation and use it for follow-ups. Attach is not needed for that transition: v1 starts its own orchestrator and managers.

**Building attach on the tool itself is sound.** Its project already specifies the essential separation: workers modify the repository while the running tool stays on its installed, pinned version until release. Retain that arrangement for every self-development project. [projects/attach/PROJECT.md:5](/home/user/repo/astrid-install/retro/projects/attach/PROJECT.md:5)

I recommend keeping these follow-ups separate:

- **Attach first**, including its own takeover, stale-binding, recovery and real-use qualification.
- **External-session inbox hooks**, after pull-based attach works.
- **A second production pack**; retain the tiny alternative-pack fixture in v1.
- **Turso/multiple-machine work and shared authentication infrastructure**, when a concrete second-machine need exists.

Most are already deferred. I would not carve another substantial feature out of v1: atomic saves, task recovery, durable messaging, checked landing, the advisor and the pilot are the product’s core proof obligations. Moving small pack-content tasks out would save effort but not shorten this critical path. [16-three-reviews.md:41](/home/user/repo/astrid-install/retro/16-three-reviews.md:41), [16-three-reviews.md:49](/home/user/repo/astrid-install/retro/16-three-reviews.md:49), [13-spec.md:301](/home/user/repo/astrid-install/retro/13-spec.md:301)

**The rank/role model holds up and is appropriately small.** A sense-checker or over-engineering-checker can be a supervised worker with an assignment, or a native helper returning to its worker, using the same fixed role instructions. Three details need explicit resolution:

- Persist **rank separately from role name**; the published agent field list currently exposes only `role`. Infer specialist execution rank from the calling path—manager CLI spawn versus worker’s native helper call—and validate allowed ranks.
- Add a short rank-specific execution wrapper: a worker submits to its manager; a helper returns to its worker. Keep the specialist instructions shared.
- Record pack version and source-role hash for **both** paths, including generated helpers. Resolve model aliases from the role configuration rather than constructing an alias from every specialist name. Preserve the accepted helper skill-inheritance behaviour.

These belong in P1/R2/P4/R6 and the existing specialist acceptance case, not a new role framework. [13-spec.md:56](/home/user/repo/astrid-install/retro/13-spec.md:56), [13-spec.md:184](/home/user/repo/astrid-install/retro/13-spec.md:184), [13-spec.md:202](/home/user/repo/astrid-install/retro/13-spec.md:202), [13-spec.md:257](/home/user/repo/astrid-install/retro/13-spec.md:257)

**The attach carve-out is right; its v1 reservation is underspecified.** `host`, identity lookup and one-holder-per-seat express intent, but the follow-up additionally requires a current binding identifier and crash-safe handover. Its sequence stops a process, commits a binding, then writes local files; detach commits before starting a fresh process. Those gaps need defined reconciliation. [projects/attach/PROJECT.md:14](/home/user/repo/astrid-install/retro/projects/attach/PROJECT.md:14), [projects/attach/SPEC.md:8](/home/user/repo/astrid-install/retro/projects/attach/SPEC.md:8)

Reserve in L0:

- A persisted current binding identifier, with stale-binding checks across every identity source.
- A serialized handover operation that prevents the supervisor or another claimant from taking the seat during transfer.
- Recovery outcomes after stopping the old holder, committing the new binding, writing local identity files and committing detach.

Reuse R1’s single-holder and recovery machinery. The attach claim “never neither, after restart reconciliation” needs those rules; temporary interruption during handover is unavoidable. Promise no schema migration only once binding storage is specified—otherwise allow a small migration in the follow-up. [projects/attach/SPEC.md:22](/home/user/repo/astrid-install/retro/projects/attach/SPEC.md:22), [projects/attach/SPEC.md:32](/home/user/repo/astrid-install/retro/projects/attach/SPEC.md:32)

Before dispatch, reconcile the brief sources: the one-pager still includes attach in State and the pilot, and still reports 54.5 engineer-days; the plan’s open pilot description also mentions attach. Use spec v3.4 and plan v3.1 as authoritative, with the schedule corrections above. [15-in-short.md:32](/home/user/repo/astrid-install/retro/15-in-short.md:32), [15-in-short.md:44](/home/user/repo/astrid-install/retro/15-in-short.md:44), [14-plan.md:234](/home/user/repo/astrid-install/retro/14-plan.md:234)