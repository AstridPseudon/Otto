> Astra (read-only review, 30 Oct). Links into `/tmp/...scratchpad` point at the restored Otto, oh-my-pi and Astrid clones used for the review; they are not in this repo.

**Use real SQLite, files, Git and processes; fake model responses.** Concentrate crash testing on the three hard invariants, and use a small suite against the installed omp binary to keep the fakes honest. Live models are needed to prove login and agent behaviour, not transaction correctness.

This is a read-only review of Otto `a70b3f2`, omp `95db18e`, and Astrid `origin/main` (`aadd0ff7`). I did not execute tests. Proposed test names and timings below are estimates.

**1. The approach, in ten lines.**

1. Use one pytest suite with `unit`, `acceptance`, `omp` and opt-in `live` directories.
2. Unit tests cover readiness, hierarchy, configuration precedence, validators and idle-manager policy.
3. Acceptance tests use the real application, a temporary SQLite file, real checkouts and real Git repositories.
4. Runtime acceptance tests launch the real supervisor and a small fake omp subprocess through the production `omp-rpc` client.
5. Control concurrency with barriers; advance an injected clock for schedules.
6. Kill actual processes at selected transaction and delivery boundaries.
7. A handful of compatibility tests run the pinned, installed omp binary against a scripted loopback provider.
8. Scripted agents perform state changes through the ordinary CLI; fixtures must not manufacture successful outcomes.
9. Real subscriptions run only at S0, VS and the pilot, and when relevant changes require requalification.
10. Gate on observable outcomes and clean teardown; retain a short failure trace, not a new proof framework.

This matches the intended reuse of tests as behaviour specifications and the three identified hard problems. [End state](/home/user/repo/astrid-install/retro/15-in-short.md:35)

**2. The fake harness should have two small boundaries.**

Use a **fake RPC process for failure control**, plus a **scripted provider behind real omp for compatibility**.

The Python client already supports a custom subprocess command, and its tests use a Python `FAKE_SERVER`. Borrow that pattern, implementing only the commands and events our supervisor consumes. Do not copy its thousand-line general-purpose fake or implement another production transport. The fake must distinguish admission, correlated `prompt_result`, and `session_settled`, including an admitted prompt that later fails or yields with background work pending. [Client fixture](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/research/oh-my-pi/sdk/python/omp-rpc/tests/test_client.py:1142), [settlement test](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/research/oh-my-pi/sdk/python/omp-rpc/tests/test_client.py:1528)

For real omp without subscription use, adapt upstream’s existing **loopback OpenAI-compatible server**. It already runs full RPC turns and tool calls with `fake/fake-model`, no authentication and no actual model. Use the installed binary, isolated omp configuration/session directories, no inherited credentials, and loopback-only networking. Extend its scripted responses just enough to exercise our CLI and one native `task` sub-agent. [Existing server and invocation](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/research/oh-my-pi/packages/coding-agent/test/rpc-wire/fake-openai-server.ts:1)

omp also supplies `createMockModel`, including scripted tool calls. That is useful upstream, but SDK fixtures with in-memory sessions cannot prove our installed CLI and disk-resume path. A downloaded local LLM adds hardware, latency and nondeterminism without improving these tests. [Mock provider](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/research/oh-my-pi/packages/ai/test/mock-provider.test.ts:18), [in-memory RPC fixture](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/research/oh-my-pi/packages/coding-agent/test/fixtures/queued-message-rpc-agent.ts:52)

Inject crashes through a no-op production callback at named boundaries. In tests, the callback signals a separate pipe and blocks; the parent sends `SIGKILL`, then restarts against the same files. Keep barriers off RPC stdout. Exceptions alone are insufficient because they run cleanup.

| Boundary | Required observation after restart |
|---|---|
| Check-in after some SQL writes, before commit | No changed heads, revisions or save notification; checkout base unchanged. |
| Check-in after commit, before checkout metadata update/response | Entire batch exists; retry creates neither extra revisions nor another logical notification; checkout recovery identifies the committed base. |
| Message persisted, before admission | Same message remains deliverable. |
| omp admitted it, but response/local bookkeeping is lost | Redelivery is permitted; no premature acknowledgement. |
| Effect committed, before acknowledgement; then after acknowledgement | Retry does not repeat the durable effect; acknowledged work stays resolved. |
| Supervisor dies while its child survives | Restart cannot launch a competing holder. |

These boundaries directly exercise the specified atomic save notification and at-least-once delivery contract. **L0 must define who acknowledges and when.** Admission and settlement alone must not delete a message. Test idempotence of the application’s durable state changes; do not claim exactly-once arbitrary shell effects. [Message contract](/home/user/repo/astrid-install/retro/13-spec.md:75), [transaction requirement](/home/user/repo/astrid-install/retro/13-spec.md:162), [runtime semantics](/home/user/repo/astrid-install/retro/13-spec.md:127)

**3. The test list should map directly to acceptance.**

Layers: **U** = unit; **A** = real application/storage, fake omp where needed; **O** = installed omp with scripted provider. Sizes are approximate parametrized cases and elapsed time per family. The mapping below covers all [11 §B6 behaviours](/home/user/repo/astrid-install/retro/13-spec.md:190).

| §B6 | Proposed tests and essential assertions | Layer; rough size |
|---|---|---|
| **1. Readiness** | `test_readiness_and_task_transitions`: unfinished/missing dependencies block; terminal tasks cannot start; submit, reject and accept preserve the intended lifecycle. Readiness never dispatches automatically. | U/A; 8–10 cases, <5s |
| **2. Landing** | `test_land_checks_rebased_head`; `test_land_refusal_preserves_target`: run the check on the actual rebased commit; check failure, conflict and a moving target cannot publish unchecked work. | A, real Git/check command; 4 cases, 5–15s |
| **3. Spec concurrency** | `test_spec_parallel_paths`; `test_spec_conflict_rolls_back_batch`; `test_spec_replay_delete_refresh_release`: disjoint edits succeed, one stale path rejects the batch, retries are no-ops, tombstones persist, dirty refresh preserves edits. Plus C3 below. | A; 6–8 cases, 5–10s |
| **4. Messages** | R3 below; `test_reply_resumes_exact_asker`: two outstanding asks cannot cross-route; busy replies queue; continuation uses the recorded session. | A; 3–4 cases plus crash matrix; one O journey |
| **5. Schedules** | `test_schedule_missed_paused_busy`: advance the clock across several slots and restart; coalesce, pause/resume, and queue without duplicate delivery. | A + fake clock; 4 cases, <5s |
| **6. Spawn** | `test_spawn_roles_config_identity`: allowed/refused hierarchy, one manager per project, role + job inputs, skills, override precedence, preserved user model choices and recorded identity. `test_native_subagent_is_recorded`: actual `task` invocation and subscribed frames. | U/A; 6–8 cases, <10s; O sub-agent journey |
| **7. Idle manager** | `test_idle_manager_policy`: observation/enforcement, strike→nudge→escalation, duplicate-settle/escalation suppression, dispatch/blocker reset; waiting, busy and external seats excluded. | U/A; 6–8 cases, <5s |
| **8. Restart** | R1 below; `test_stop_resume_replace_releases_task`: recovery preserves identity or explicitly fails; failure informs parent and releases task; replacement is intentional. | A; 4–6 cases, 10–20s; O resume journey |
| **9. Read-only status** | `test_status_is_read_only`: correct digest with a frozen clock; reject and record attempted SQL writes, compare logical state before/after, including events and activity timestamps. | A; 2 cases, <2s |
| **10. Doctor** | `test_doctor_readiness_via_omp`: signed-in/out, unresolved role, malformed response and omp failure; no prompt and no direct token-store access by our code. | A; 5 cases, <5s; O metadata check |
| **11. Attach/detach** | `test_attach_detach_cli_inbox`: orchestrator and manager takeover, CLI identity precedence, pull-only inbox, reminders retained, idle check skipped, detach starts a fresh supervised session with handover. Plus R1 overlap tests. | A; 4–6 cases, 10–20s |

The hard invariants deserve explicit tests, rather than being inferred from those happy paths:

| Invariant | Named tests | Size and strongest assertion |
|---|---|---|
| **C3: atomic check-in** | `test_checkin_kill_boundaries`; `test_concurrent_checkins_are_atomic` | A; about 5 cases, 15–30s. Separate connections/processes observe either the complete old state or complete new state; exactly one logical save notification after successful replay. |
| **R1: one live holder per seat/session** | `test_supervisor_restart_with_surviving_child`; `test_competing_start_and_attach`; `test_resume_identity_or_fail` | A; about 6 cases, 20–40s, plus one O kill/resume case. Two supervisors, takeover races, delayed old-child exit, missing file, wrong identity/profile. Observe process lifetimes and accepted commands—not just the agents table. |
| **R3: crash-surviving messages** | `test_delivery_kill_boundaries`; `test_replayed_effect_and_ack`; `test_reply_resumes_exact_asker` | A; about 6 cases, 20–40s, plus one O journey. Original message survives until acknowledged; repeated delivery produces one durable state transition and reaches the correct asker. |

“One holder” means **at most one live holder**, not one session forever: detach explicitly creates a fresh session. If the old holder’s exit cannot be established, takeover must fail visibly rather than overlap. [Attach contract](/home/user/repo/astrid-install/retro/13-spec.md:83)

Add only three bridging tests beyond §B6:

- `test_spec_change_reaches_manager_and_worker`: save notification, task snapshot, manager-driven reconciliation and running-worker notification.
- `test_consultation_snapshot_and_session`: requested and scheduled consultations carry mandate/status/spec index and retain the advisor session.
- `test_installed_cli_with_alternative_pack`: fresh installation, bootstrap, second pack’s template/skills and a worker invoking the delivered CLI.

These cover the pilot’s otherwise untested joins. [Pilot requirements](/home/user/repo/astrid-install/retro/13-spec.md:204), [C5](/home/user/repo/astrid-install/retro/14-plan.md:102), [R4](/home/user/repo/astrid-install/retro/14-plan.md:124)

**4. Live tests prove authentication and useful agent behaviour.**

| Gate | What must really happen | Frequency | Expected cost |
|---|---|---|---|
| **S0** | On Mac and Linux: actual subscription login flows; Anthropic and `openai-codex` in one profile; custom roles/model picker; overlays and skills; native sub-agent frames; admission/result/settlement; exact-file resume with identity check. Demonstrate every workaround. | Once before implementation; repeat affected checks on omp/client pin or login/configuration changes. | Existing **1.5 engineer-days**. Plan roughly **20–40 short model turns** across both machines; consumes subscription quota. |
| **VS** | Real agents spawn→ask non-blockingly→answer→continue the same session→settle→restart. Controlled kills immediately before/after admission; inspect persisted message IDs and continuation. | At the early milestone; repeat after material lifecycle/delivery changes and before release when affected. | Existing **1.5 engineer-days** includes construction/debugging. Successful rerun target **5–15 minutes**, roughly **6–12 short model turns**, plus crash replays. |
| **Pilot** | A real project with all five roles, useful sub-agent work, mid-work spec change, concurrent checkouts, both advisor consultation paths, restart during delivery, alternative-pack project, and an externally attached orchestrator that later detaches. | Once all prerequisites pass; rerun affected scenarios after fixes and complete D6’s clean rerun. | Existing **3 days + 2 contingency**. Model cost depends on the owner’s chosen project; no defensible dollar estimate yet. |

S0 and VS already have live evidence requirements; do not replace them with the loopback suite. [S0](/home/user/repo/astrid-install/retro/14-plan.md:92), [VS](/home/user/repo/astrid-install/retro/14-plan.md:112), [pilot allocation](/home/user/repo/astrid-install/retro/14-plan.md:135)

For the pilot, record each observable result alongside revision, message and session IDs, Git commit and actual model/provider. Shorten configurable schedule intervals for the demonstration; automated tests cover 60/180-minute defaults. Judge accepted project output and correct continuation, not exact model wording. Report observed usage; add no spend-control machinery.

**5. Reuse the evidence and small helpers, not Otto’s entire suite.**

Static inventory found **202 top-level test files / 49,682 lines / 1,796 test functions**, plus **42 source-local files / 10,629 lines / 362 functions**. Otto mixes unittest fixtures and pytest, with no shared `conftest.py`. Fixtures often build a real disposable Store and owner graph; runtime fixtures also launch scripted Claude/Codex processes. [Store fixture](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/tests/test_otto_save.py:40), [scripted launcher](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/labs/TESTPATCH/tests/test_hostctl_serve.py:1)

Historical timings are **49.17s for LANDPROOF’s 36 tests**, **299.04s for TESTPATCH’s 91 passed/4 skipped**, and **624.05s for REALSTAGE3’s 92 tests**. These are different focused checks, not a measured full-suite runtime. [LANDPROOF log](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/portfolio/ops/runs/LANDPROOF/check.out:1), [TESTPATCH log](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/portfolio/ops/runs/TESTPATCH/check.out:1), [REALSTAGE3 log](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/portfolio/ops/runs/REALSTAGE3/check.out:1)

| Source | Keep | Leave behind |
|---|---|---|
| **Core tests** | Readiness/terminal-state examples; stale-save and replay cases; real-Git rebased-commit tests; read-only status assertions. Port their expected behaviour to the new API. | Authority, receipts, authenticated lanes and Herzchen fixture construction. |
| **LANDPROOF** | Checked commit must equal published commit; acceptance alone cannot imply successful landing; interrupted publication must be distinguishable. | Sealed evidence and owner-proof machinery. Its branch had integration failures, so it is not drop-in tested code. [Cases](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/labs/LANDPROOF/tests/test_fleet_custody.py:1223), [integration findings](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/portfolio/ops/integ/culprit-LANDPROOF.md:3) |
| **PROOFDOC** | Explicit distinction between fake diagnostic evidence and real-worker evidence. | Tests asserting exact runbook prose or shell-source strings. [Runbook](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/labs/PROOFDOC/RUNBOOK.md:11) |
| **TESTPATCH** | Drive supported commands and check independent outcomes; owner-down/drain must release a waiting caller. | Cross-imported heavyweight fixtures and obsolete authorization plumbing. [Drain regression](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/labs/TESTPATCH/tests/test_ask_socket_wait.py:73) |
| **DISTURB** | Controlled disturbances with before/after product observations; ensure a deliberately broken invariant turns the test red during harness development. | Six-invariant report framework and broad process censuses. The retained check is incomplete, not a green qualification. [Journey](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/labs/DISTURB/tests/test_perch.py:2888), [log](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/portfolio/ops/runs/DISTURB/check.out:1) |
| **REALSTAGE3** | Two independent tasks followed by one dependent task; real output checks; fake workers cannot satisfy live acceptance. | Owner-record joins, accounting/custody controls and large report generators. [Canary](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/labs/REALSTAGE3/ops/bootstrap/canary/project.json:99) |

Reuse the portable path/text validators as code, with their input cases. **Do not reuse Otto’s folder transaction algorithm:** it explicitly commits each document operation separately and supports partial recovery, unlike the new atomic-batch requirement. [Validator and old transaction contract](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/otto/portfolio/project_folder.py:1)

Astrid contributes useful lightweight patterns: fake executables for model/login metadata, launcher argument tests, mocked download/install checks, and explicit process cleanup. Its login-status query submits no inference request. Adapt these narrowly; do not import Astrid’s broader runtime suite or its older omp/Bun pin. [Login query](/home/user/banodoco/astrid-agent/astrid/omp_agent.py:342), [fake metadata tests](/home/user/banodoco/astrid-agent/tests/test_omp_agent_models.py:193), [installer checks](/home/user/banodoco/astrid-agent/tests/test_installer_omp_source.py:113) — these references were inspected at `origin/main`.

**6. Avoid tests that rebuild the retired system.**

- No spend, gateway, authority, receipt, cloud-sync, owner-service or automatic-dispatch suites: those features are explicitly out of scope. [Scope](/home/user/repo/astrid-install/retro/13-spec.md:93)
- No provider/model cross-product, credential-refresh implementation tests or exhaustive RPC codec suite. Test our selected integration; upstream owns its internals.
- No exact prompt prose snapshots, source-string checks, “report contains heading” tests or LLM judges for transaction correctness.
- No duplicate unit assertions for behaviour already adequately proved by a small acceptance test.
- No random overnight chaos farm, exhaustive crash-at-every-line matrix or general mutation-testing service. Named boundaries cover the actual risks.
- No promise that fake agents prove planning quality or that a local model proves subscription login. Those remain live gates.

Do retain process teardown and bounded test deadlines. Otto recorded a test run finishing in **91 seconds** but holding the interpreter for **53 minutes** because of a leaked thread. A deadline must fail with diagnostics; it must never count as success. [Recorded failure](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/ops/bootstrap/otto_gate_exit.py:1)

**7. CI should be one serial, credential-free job.**

Proposed commands, after installing pinned development dependencies and omp:

```bash
python -m build --wheel
python -m pytest -q tests/unit --durations=10
python -m pytest -q tests/acceptance --durations=10
python -m pytest -q tests/omp --durations=10
```

The installed-entrypoint fixture installs that wheel into a fresh environment and invokes its actual CLI. This matters: Otto previously advertised an executable that installation had not created, while a fake-manager test created its own executable and missed the defect. [Incident diagnosis](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/portfolio/ops/integ/stage2-hang/DIAG.md:3)

| Stage | Warm-machine target | Gate |
|---|---:|---|
| Build + unit | 20–45s | Package and deterministic rules pass. |
| Acceptance, including crashes | 1–2 minutes | All 11 behaviours and three invariants pass. |
| Installed omp compatibility | 1–2 minutes | Roughly 5–8 journeys pass against the exact binary/client pair. |
| **Total** | **About 3–5 minutes** | Zero model usage; no surviving test-owned processes. |

Run the complete job on each proposed merge; it is small enough not to need selective-test machinery or sharding. Unexpected skips, empty collection, hangs and leaked processes fail the gate. Do not inherit Otto’s automatic “flaky, therefore allow landing” rule for hard invariants. [Existing flake rule](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/ops/bootstrap/land.sh:378)

Pin the exact client artifact/commit alongside omp. On a pin change, also run the matching upstream Python client suite:

```bash
python -m unittest discover -s sdk/python/omp-rpc/tests -v
```

Keep ordinary CI on one host. Fresh Mac/Linux installation, launchd/systemd and reboot checks remain explicit D1/D1b release qualification; one machine cannot establish both OS behaviours. [Platform gates](/home/user/repo/astrid-install/retro/14-plan.md:130)

**8. Change D3 now, and make test ownership explicit.**

- **Correct D3 and the final gate from §B6 “1–10” to “1–11”.** Add attached-orchestrator takeover/detach to the plan’s pilot checklist; the spec already requires it. [D3](/home/user/repo/astrid-install/retro/14-plan.md:133), [current pilot checklist](/home/user/repo/astrid-install/retro/14-plan.md:177)
- **Increase D3 from 2 to 3 engineer-days:** allocate the extra day to the fake RPC process, crash barriers, cleanup fixture and installed-omp loopback tests. This changes M4 from 11 to 12 days and the overall estimate from **46 to 47 engineer-days**.
- **Keep implementation-specific tests inside C3, R1, R3, AT and D2.** D3 supplies fixtures and integrates coverage; it cannot absorb all their invariant testing.
- **Extend L0’s done-when** to define acknowledgement/effect semantics, recovery identity, takeover completion and the named crash boundaries. S0 supplies example frames from the pinned pair.
- **Finish D3 only after every mapped dependency, including AT, passes**, rather than describing C6 as its only finishing dependency.

Build the fixtures during the already scheduled D3 skeleton period. Keep S0, VS and pilot allocations unchanged initially; measure the first complete offline run and re-estimate after S0 if the pinned protocol requires more work. [Existing task checks and schedule](/home/user/repo/astrid-install/retro/14-plan.md:95), [D3 start window](/home/user/repo/astrid-install/retro/14-plan.md:153)