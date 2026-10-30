> **Decision record.** This is a decision record from 30 Oct. Its decisions stand, but **its numbers and some task ids are superseded** by `14-plan.md` v3.2 (53 days, about 22 working days; attach is now the pilot; §B6.11 is now pack roles).

# Three reviews: remove, test, gaps

Three Astras reviewed `15-in-short.md`, the spec, the plan and the code, each with Luna helpers. All three reviews were read-only: nothing was installed, run or deleted.
- **What to remove or simplify:** `evidence/three-astras/astra-remove-simplify.md`
- **The minimal testing approach:** `evidence/three-astras/astra-testing.md`
- **The gaps between where we are and where we're going:** `evidence/three-astras/astra-gaps.md`

**The verdict across all three.** The shape is right; nobody argued for adding machinery back. But the plan as written could pass every task check without delivering the whole workflow. Five contracts were missing: acknowledgement, work recovery, landing → done, attach handover, and spec changes during work. The estimate was also light where we assumed Otto code would lift out cleanly. Both are fixed in plan v3, spec v3.3 and the one-pager.

---

## 1. Remove and simplify: build beside Otto, not on it
**The scale.** Otto's integrated code is about **117,500 lines of production Python:**
- `src/otto`: about 71,000 lines;
- `src/herzchen`: about 48,000 lines.

The new tool lifts out only a few hundred of those lines. Everything else stays frozen as **reference**: we keep the behaviour and the lessons, and carry no code.

**What we lift, and simplify on the way:**

| From | What survives |
|---|---|
| `portfolio/project_folder.py` + `herzchen/content/model.py` | The path and text validators, and the filesystem-safety checks. The save itself is **new**: Otto's commits one file at a time and reports `atomic: False`. |
| `herzchen/fleet/landing.py` | Rebase → check that exact commit → refuse if the target moved → fast-forward. **Not** its assessments, allowances or owner bindings. Our plan repo's `tools/land.sh` is *not* a safe substitute: it uses `--no-ff`, runs no check, and removes worktrees. |
| The Megado pack (`projects/packs`) | 24 files, 1,854 lines. Keep proportional review, the lifecycle, the escalation questions and the improvement loop. **Rewrite** them as short role guides and skills. Remove the seven responsibility slots, `run.json` model authority, the review allowances and the owner-service rules. |
| `dependencies.py`, `status.py`, `ready.py` | As references only: readiness from current state, cycle prevention, a read-only digest. |
| Astrid's omp launcher and installer | The login-readiness check and the pinned-install *pattern*. |

**The top cuts.** Each is replaced by oh-my-pi, by SQLite, or by nothing.
1. **The Herzchen and owner architecture,** with no compatibility layer.
2. **The custom Claude and Codex adapters, and the gateway** (replaced by `omp-rpc`).
3. **The installed controller and its migrations:** about 11,000 lines, replaced by a package plus launchd and systemd units.
4. **Fleet capacity, process custody and the heavy-job runner.** One small supervisor, one holder per seat.
5. **Receipt recovery for each document,** replaced by one transactional save.
6. **Spend controls and competing model policy,** in the code and in the pack.
7. **Five separate communication mechanisms.** Due ports, issue and help delivery, advisor delivery, file lanes and receipts become **one message table**.
8. **The pack framework** (registration, stacking, compilation). A pack is just content.
9. **Landing,** cut down to its correctness rules: no D19 approvals, batches or auto-publish.
10. **The shell control plane** (`dispatcher`, `keepalive`, `recover`, `watch`, plus Markdown queues). We archive it rather than run it alongside the new tool.

**Plan-level cuts, taken:**
- the duplicate 28-day schedule in spec Part C;
- pushing messages into busy sessions (`follow_up`): messages now wait for settle;
- the Claude Code inbox hook (deferred);
- "reconciliation helpers," narrowed to explicit task edit and cancel;
- pack version behaviour: pin the version, one simple precedence rule;
- "one SQLite file holds everything" → it holds **the tool's state**. omp keeps sessions and logins.

**Removals we must *not* make:**
- the five roles and the persistent advisor;
- manager-led dispatch;
- transactional check-in;
- message ids and reply routing;
- one holder per seat;
- dependency readiness, worktrees and checked landing;
- the spike, the vertical slice and the pilot;
- Otto's test history and branch refs.

**Clean-up order** (never deleting history):
1. **Freeze.** Tag `a70b3f2`, the installed `bbd9b6d`, draft-sync `b834793`, and every lab and project tip.
2. **Archive.** Make verified bundles, and rehearse a restore.
3. **Back up live state separately** before the Mac installation is retired.
4. **Build in a new sibling repo,** recording the source commit of everything lifted.
5. **Prove the new tool** before changing the active entry point.
6. **Archive the old operating surface,** behind an index.

The seven other plan-repo branches are **preserved, not pruned**. Several hold unique work; `epic-shannon` alone has 255 commits that aren't on our branch.

## 2. Testing: real storage and processes, fake models
**The approach in one line:** real SQLite, files, Git and processes, with model replies faked. Crash tests concentrate on the three hard invariants, and a few tests run the real oh-my-pi binary to keep the fakes honest.

| Layer | What's real | What's faked | Runs |
|---|---|---|---|
| **Unit** | Rules: readiness, hierarchy, config precedence, validators, the idle policy | — | Every change, under 45 seconds |
| **Acceptance** | The app, a temporary SQLite file, checkouts, Git repos, the supervisor, the CLI | omp, as a tiny **fake RPC process** behind the real `omp-rpc` client; a test clock | Every change, 1–2 minutes |
| **omp compatibility** | **The installed omp binary**, with isolated config and no credentials | The model, as a **loopback scripted provider** (omp already ships one in its own tests) | Every change, 1–2 minutes |
| **Live** | Real subscription logins and real models | — | Only at S0, the vertical slice and the pilot, plus re-runs after a pin or login change |

**Crashes are injected at named points.** A no-op hook in the production code blocks at each point, the test kills the process (`SIGKILL`), restarts it, and checks:
- a crash mid-check-in leaves the old state, with no notification;
- a crash after commit gives the whole batch, and a retry adds nothing;
- a message that was saved but not admitted is still deliverable;
- a message that was admitted but whose bookkeeping was lost is redelivered and not acknowledged too early;
- a crash after the effect but before acknowledgement doesn't repeat the effect;
- a supervisor that dies while its child survives can't start a second holder.

**Tests map one-to-one to acceptance.** Each of the 11 spec §B6 behaviours and each of the three hard invariants has a few named tests. There are also three bridging tests:
- a spec change reaches the manager and the worker;
- a consultation carries the right snapshot and keeps the advisor's session;
- the installed CLI works with the alternative pack.

**CI:** one serial job on one machine, about 3–5 minutes, using no models and no credentials:
```
build wheel → tests/unit → tests/acceptance → tests/omp
```
- The CLI is tested **from the installed wheel.** Otto once shipped a command that installation never created, and a fake test hid it.
- A skip, an empty test collection, a hang or a leaked process **fails** the run.
- A hard invariant is never waved through as flaky.

**Reuse from Otto:** the *cases*, not the fixtures. Otto has 202 test files, about 50,000 lines and 1,796 tests. We keep:
- readiness;
- stale-save and replay;
- rebased-commit landing;
- a read-only status;
- "accepted ≠ landed" (LANDPROOF);
- "fake evidence ≠ real evidence" (PROOFDOC);
- disturbance scenarios (DISTURB);
- the two-then-one canary (REALSTAGE3).

**What we won't test:**
- spend, gateway, authority or receipt suites;
- every provider-and-model combination;
- the exact wording of prompts;
- an LLM judging transactions;
- crashes at every line;
- chaos farms.

**Plan change:** D3 grows from 2 to 3 days, and covers §B6 1–11.

## 3. Gaps, and what we decided

| # | Gap | Decision (now in the spec and plan) | Owner |
|---|---|---|---|
| G1 | **When is a message "handled"?** Being admitted isn't the same as being acted on, and a replay could create a second task or reply. | **Acknowledged once the recipient's turn ends normally,** or when it replies. Commands carry the message id as an operation key, so a replay can't create a second task, worker or reply. The guarantee covers **the tool's own state,** not arbitrary shell effects. | L0, R3 |
| G2 | **Reopening a session doesn't recover the work.** | **One current attempt per task.** On restart the agent gets a short "you were interrupted" prompt with its task, and its worktree is kept. Stale submissions are refused. Stop, cancel and replace are distinct. | L0, R1, R5b, C4 |
| G3 | **Git and the database can disagree** about whether a task is done. | **A code task is done only when its checked commit is on the target.** The task records the submitted and checked commits, and a restart reconciles them against Git. | D2, C4 |
| G4 | **"Any seat" wasn't implemented, and handover was thin.** | **Seats you can attach:** advisor, orchestrator, manager, worker. Sub-agents stay inside omp. `attach` returns a **handover packet** (role guide, skills, mandate, current work, inbox instructions). Taking a seat from another outside session needs `--force`, and stale bindings are refused. | AT, L0, P2 |
| G5 | **A spec change in the middle of work.** | **For each running assignment, the manager decides: continue, amend or cancel.** The assignment keeps its original snapshot, and a submission is checked against its assignment. | L0, C3–C5 |
| G6 | **When does a model change take effect?** | **For new agents.** A resumed session keeps its model unless switched explicitly at a settled point. Status shows the configured role and the actual model. | L0, R2, C6 |
| G7 | **Megado needs translating, not copying.** | P2 and P3 grow to 4.5 days, done when **a fresh agent can perform the workflow** from the skills. | P2, P3 |
| G8 | **Advice could go nowhere.** | The orchestrator records **adopt, defer or reject** for each piece of advice. The next snapshot includes earlier advice and what happened to it. | P2, P3, R4 |
| G9 | **Where native sub-agents stop.** | **Only workers delegate,** set through omp's spawn policy. Sub-agent results return to their worker; the durable-message promise covers seats, not helpers. | L0, R2, R6 |
| G10 | **The idle check missed some unfinished work.** | **Unfinished work** now includes submitted tasks awaiting acceptance and spec changes not yet reconciled. Enforcement starts after observation in the pilot's first half. | R5a |
| G11 | **The validators aren't one module.** | Extract the leaf and filesystem checks, then validate the **resulting tree** inside the transaction. C3 grows to 3.5 days. | C3 |
| G12 | **Attach was missing from the final gate.** | §B6 is now 1–11, and the pilot includes an attached orchestrator. | D3, D5 |
| G13 | **Moving machines was only a copying suggestion.** | D4 documents the full state bundle (the SQLite file, omp's directory, repos and worktrees) and a restore exercise. | D4 |
| G14 | **Closeout wasn't owned by any task.** | New **X0** (0.5 days): tag and preserve the refs, including the packs branch, archive, and remove spec Part C's duplicate plan. | Orchestrator |

**Decisions I've made on your behalf.** These are the defaults the reviewers recommended; change any of them.
- **One orchestrator and one advisor per database;** a separate organisation uses another file. *(Both Astras recommended this.)*
- **Attach covers four seats,** and sub-agents stay under their worker.
- **A model change applies to new agents;** a running seat switches only explicitly.
- **A spec change mid-work goes to the manager,** who continues, amends or cancels each running assignment.
- **"A repeat does no harm"** covers the tool's own state, not shell or external effects.

**Still open:**
- *(Since resolved: the pilot is the attach project, and the advisor interval is 180 minutes.)*

## 4. What it does to the size
| Change | Days |
|---|---:|
| D2 landing, with Git ↔ task reconciliation: 1.5 → 3 | +1.5 |
| P2 + P3, translating Megado: 3 → 4.5 | +1.5 |
| D3 acceptance harness, with fakes and crash points: 2 → 3 | +1 |
| R1 + R5b, recovering the work: 4.5 → 5.5 | +1 |
| AT, four seats plus the handover packet (the hook deferred): 1.5 → 2.5 | +1 |
| L0, the five contracts: 1.5 → 2 | +0.5 |
| C3, extracting the validators: 3 → 3.5 | +0.5 |
| R3, acknowledgement and operation keys: 2.5 → 3 | +0.5 |
| C5, the policy for running work: 1.5 → 2 | +0.5 |
| X0 closeout (new) | +0.5 |
| **Total** | **46 → 54.5** |

- **Planning range:** 52–58 engineer-days. Astra-gaps put it at 53–58, and I've trimmed attach by deferring the hook and fixing one orchestrator per database.
- **Critical path:** about 23.5 working days.
- **Hard tasks:** still three Super-hard (C3, R1, R3). D2 stays X-hard, but now carries an invariant: a task is done only when its commit has landed.
