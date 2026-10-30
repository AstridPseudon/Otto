**Changes needed first.** The architecture fits the goal, but executing the plan literally would leave gaps in bootstrap, configuration and crash-safe delivery.

Read-only audit against omp commit `95db18e` (18.14.0), upstream Pi, Astrid `origin/main`, and the restored Otto sources. No live OAuth or recovery tests were run.

**1. Goal coverage**

| Requirement / acceptance | Delivering tasks | Missing or only implied |
|---|---|---|
| Five roles; manager chooses worker intelligence | C2, C4, R2, R4, P2, P4 | `init` creates records, but activation and the owner’s mandate are unspecified. Enforce one active manager per project. |
| One central spawn policy; generic + job instructions; **B6.6** | R1, R2, P2, P4 | Four roles use supervised RPC; sub-agents use native `task`. Explicitly share instruction/routing policy across these two mechanisms. Test recorded session identity. |
| Megado, shared skills, other packs | P1–P4, C2, R2 | No explicit task creates project templates. Define the organisation-level pack for advisor/orchestrator, configuration precedence and version behaviour. “Exactly those skills” needs qualification below. |
| Spec folders with transactional checkout/check-in; **B6.3** | C1, C3 | Explicit tests needed for tombstones, dirty refresh, multi-file rollback and crash between database commit and checkout-base update. |
| Spec → tasks; readiness; **B6.1** | C4, C5, P3 | Task dependencies are absent from the listed schema. Define rejected submissions and what happens to running workers after spec changes. |
| Orchestrator reminders every 1–3 hours | R4, P1, C2 | Creation of default schedules and schedule-management commands are unassigned. |
| Persistent advisor; requested and 3–6-hour consultations | R3, R4, P2 | Test snapshot contents, returned advice and continuation of the same advisor session. |
| Durable messages; answer resumes asker; **B6.4** | R3 | **Contradiction:** at-least-once delivery in the design versus “once across a crash” in acceptance. IDs alone do not solve this. |
| Schedule coalescing, pause, busy queue; **B6.5** | R4, R3 | R4’s done-when omits pause and busy-queue tests. |
| Basic structure and idle-manager check; **B6.7** | R2, R5 | Define one evaluation per settled activity, legitimate waiting, observation-mode behaviour and duplicate-escalation suppression. |
| One Mac/Linux machine; restart reconciliation; **B6.8** | R1, R5, D1 | Define supervisor-loss behaviour, surviving children, exact-session recovery and task state after agent failure. |
| One local SQLite file; later selective sync | C1, D3 | Root agents and portfolio messages need global scope. UUIDs and `project_id` help future sync; they do not establish “no schema changes.” |
| Subscription model/account selection; doctor; **B6.10** | S0, R2, C2, D1 | Correct profiles, provider IDs and installation compatibility; test readiness for the actual configured profiles. |
| Checked landing; **B6.2** | D2, R2, C4 | Connect submission/acceptance to landing. Specify that failure leaves the **target branch** unchanged; test concurrent target movement. |
| Complete read-only status; **B6.9** | C6, R6 | C6 checks counts, but acceptance also needs agent activity, pending messages, failures and upcoming schedules. |
| All pilot scenarios | D4, D5 | All are named. Assign creation of the alternative-pack fixture and require observable outcomes, not merely scenario execution. |

**2. omp claim checks**

| Claim | Finding and required correction |
|---|---|
| `--model provider/model` | **Confirmed.** Provider-qualified model IDs must be exact. For ChatGPT subscription routing, use the `openai-codex` provider; do not assume the spec’s `openai/...` example selects subscription auth. Resolve model names and effort from the pinned catalogue. [CLI:104](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/cli-reference.md:104), [providers:221](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/providers.md:221) |
| `--profile <account>` chooses an account | **Wrong as stated.** It selects an isolated settings/auth/session store. A profile containing the intended account is a valid convention; it is not an account selector within a multi-account store. Record the profile with the session and reuse it on recovery. [settings:24](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/settings.md:24) |
| Per-process `skills.customDirectories` and `--skills` | **Confirmed, with different functions.** Custom directories add discovery roots; `--skills` filters discovered names/globs. Use a generated **`--config <file>` overlay plus the filter**. Cwd `.omp/config.yml` also works, but native settings do **not** search ancestors. No dedicated custom-directory environment variable is declared. [settings:19](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/settings.md:19), [skills:77](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/skills.md:77), [CLI:162](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/cli-reference.md:162) |
| Every role receives exactly its selected skills | **Wrong for native sub-agents.** `autoloadSkills` selects injected skills, but children receive the parent’s full skill list. Prefer documenting that inheritance over maintaining an omp fork for strict isolation. [structured-subagent.ts:572](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/packages/coding-agent/src/task/structured-subagent.ts:572) |
| `session_settled` | **Confirmed.** Includes queued input and background work. However, spec B2 incorrectly calls `prompt_result` acceptance: the command **response** acknowledges admission; `prompt_result` reports yield/error/abort. Settlement does not mean success. Consume both outcome and settled state. [RPC:328](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/rpc.md:328), [settle predicate:22](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/packages/coding-agent/src/session/session-settle.ts:22) |
| Resume and `open_session` | **Confirmed, but not interchangeable.** `--resume <exact-file>` targets a saved session. `open_session` selects a conversation from a directory and can create a new one. Verify returned identity and `resumed`; never silently accept replacement. Neither implies replay of interrupted execution; `--restore` is interactive-only. [RPC:370](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/rpc.md:370), [CLI:87](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/cli-reference.md:87) |
| `task` model/account per agent | **Confirmed through named-agent configuration.** Model frontmatter/overrides and `task.agentAccountPools` work. Pools select OAuth identity keys within available credentials; they do not switch profiles. Children inherit the worker’s auth storage, so required child-provider credentials must be available there. [routing:224](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/task-agent-discovery.md:224), [account pools:260](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/task-agent-discovery.md:260), [inherited auth:646](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/packages/coding-agent/src/task/structured-subagent.ts:646) |
| Subscription login on headless Linux | **Confirmed in source; live demonstration remains S0.** Device-code command is `omp login openai-codex-device`, storing credentials as `openai-codex`. Anthropic supports pasted redirect/code. Remote login syntax needs the provider: `omp auth-broker login <provider> --via=user@host`. [Codex auth definition:1](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/packages/catalog/src/compat/rules/auth/openai-codex-device.kdl:1), [Anthropic:17](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/packages/catalog/src/compat/rules/auth/anthropic.kdl:17), [broker:63](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/auth-broker-gateway.md:63) |
| Python RPC client | **Confirmed.** Bundled `omp-rpc` supplies process management, correlation and settled waits. It is marked alpha and requires Python ≥3.11. Pin the client with the tested server revision. [README:3](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/sdk/python/omp-rpc/README.md:3), [package metadata:6](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/sdk/python/omp-rpc/pyproject.toml:6) |
| Astrid’s pin supplies these capabilities unchanged | **Unclear until tested.** Astrid `origin/main` pins 18.12.6/Bun 1.3.14; the audited clone declares 18.14.0/Bun ≥1.4.4. Its recipe verifies native artifacts and lock compatibility. Reuse the installation pattern, not old hashes/runtime assumptions for a newer pin. Evidence: `origin/main:astrid/installer/omp/recipe.json:3`, `astrid/installer/tools.py:320,365`; [omp package:205](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/package.json:205). |

Two additional integration details:

- `packs/<name>/agents/` is not automatically discovered. P4/R2 must expose it through a supported native or extension root. [Discovery:150](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/docs/task-agent-discovery.md:150)
- R6 must enable sub-agent subscriptions; frames are off by default. Upstream Pi already has `agent_settled`; omp’s relevant addition is its background-work-aware session boundary.

**3. Manager split**

Four managers are reasonable; **M2 is overloaded while M3 finishes early**. Improve the cut:

| Manager | Recommended ownership |
|---|---|
| M1 State | Schema, documents, tasks, reconciliation and their CLI commands |
| M2 Runtime | RPC lifecycle, spawn, durable delivery, recovery, sub-agent observation |
| M3 Pack and behaviour | Pack loader/content, resolved role configuration, schedules/advisor and idle-manager rule |
| M4 Delivery and integration | Installation, OS service units, landing, acceptance harness and pilot |

Keep lifecycle failure handling with M2; move only R5’s strike/nudge policy to M3.

Agree small interfaces immediately after S0: resolved launch configuration, store transitions, message delivery and settled notifications. M1 should integrate migrations without becoming the sole implementer of every runtime schema change.

Resolve the concrete ownership collision: **P3 and D2 both own the `land` skill.** M3 owns the text; M4 owns the script and its tests.

**4. Tiers, estimates and risks**

The arithmetic is **22 tasks, 34 engineer-days**. Tier totals are correct. **M4 is 7.5 days, not 7.**

The schedule has three different interpretations:

- **14.5 days:** unlimited parallelism using the declared dependency table.
- **16.5 days:** additionally serialize R2 → R3, as the written critical path does.
- **18.5 days:** one executor serializes M2’s 11 days, followed by pilot/fixes.

Thus “about 18” is plausible as a resource-constrained schedule, but is not the dependency calculation presented.

Tier corrections:

- **C3 → Super-hard:** all changed paths commit together; independent-path saves succeed; crash recovery cannot falsely advance checkout bases or publish twice.
- **R1 stays Super-hard:** never allow two processes to continue the same managed session; recovery must preserve identity or report explicit failure.
- **R3 stays Super-hard:** persist pending delivery, tolerate uncertain admission and correlate replies to the original asker/session. Remove the unsupported exactly-once promise.
- **R2 remains X-hard**, but two days is tight for profile/configuration isolation, discovery, routing and worktrees.
- **R5 should be split:** the idle rule is modest; stop/resume/replace belongs to the harder lifecycle work.
- **D5 is contingency**, not a predictably bounded implementation task.

**34 days is an optimistic target.** My planning allowance is **36–44 engineer-days and roughly 18–23 working days**, contingent on the early slice. The highest risks are R1/R3, C3, then R2 and pin/platform compatibility.

Restore the spec’s early vertical slice: **spawn → nonblocking ask → answer → same-session continuation → settled → restart**, including crashes immediately before/after prompt admission.

**5. Missing tasks and dependency fixes**

1. **Add an explicit lifecycle/configuration contract before parallel implementation.** Define root bootstrap and mandate, CLI-to-supervisor launch requests, task assignment/rejection/cancellation, session identity, fallback behaviour and pack precedence.

2. **Fix R3’s delivery contract.** RPC request IDs are correlation IDs: the implementation creates a fresh in-memory ticket for each request, including repeated IDs. They are not durable deduplication keys. Keep messages in SQLite while busy; specify acknowledged, at-least-once delivery and idempotent state changes. Test the admission/commit crash window. [rpc-prompt-results.ts:86](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/oh-my-pi/packages/coding-agent/src/modes/rpc/rpc-prompt-results.ts:86)

3. **Complete C1/C4’s data contract.** Store dependencies, model overrides, resolved profile/configuration and recovery information; distinguish global from project-scoped rows. Make spec-save notification durable in the save transaction. Define how failed/cancelled agents release running tasks.

4. **Expand P1/P4/R2.** Assign templates and the alternative-pack fixture; generated per-process overlays; agent discovery; actual fallback tests; and worker-only native delegation. The upper four roles are separate RPC sessions, so increasing native recursion depth to represent the entire hierarchy is unnecessary.

5. **Correct the dependency graph.**
   - Keep **C2 → P1** and **C5 → R3**; both already exist.
   - Add templates to C2’s prerequisites and P3’s planning skill to C5’s acceptance gate.
   - D1’s **doctor-green completion depends on C2**; separate installation smoke from that final check.
   - R4’s integration needs spawned roots and pack schedules: C2/R2/P1.
   - R6’s integration needs P4/R2; complete C6 against messages, schedules and sub-agent data.
   - Define D4 as depending on all **pre-pilot** tasks, excluding D5.
   - D2 can start early against an agreed repository/worktree/check-command interface.

6. **Strengthen completion checks.** Add missing-session recovery, wrong-profile recovery, busy replies, paused schedules, tombstones, dirty refresh and concurrent landing. A named S0 workaround must be demonstrated before it clears a load-bearing dependency.

**6. Over-engineering to cut**

- Do not build a second RPC transport; use the Python client.
- Do not require strict child-skill isolation unless it serves a demonstrated need.
- Use a tiny alternative-pack fixture, not a second production protocol.
- Keep auth broker/gateway deployment optional; local credentials plus device/paste login satisfy one-machine operation.
- Defer sync machinery and remove the promise that selective Turso sync needs no schema changes.
- Retain validators and behaviour tests, not Otto’s authority/receipt/process-custody architecture. Its folder implementation explicitly reports `atomic: False`; C3 is new work. [project_folder.py:467](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/plan-check/otto/otto/src/otto/portfolio/project_folder.py:467)
- Keep the separate persistent advisor: omp’s built-in advisor reviews transcript updates and is not a drop-in replacement for the requested portfolio consultation role.

**7. Verdict**

**Go with S0; revise before full execution.** First correct delivery guarantees and omp configuration, specify bootstrap/task recovery, assign templates and configuration generation, restore the early vertical slice, and reconcile dependencies with staffing.

Those changes preserve the small architecture and make its acceptance conditions achievable.