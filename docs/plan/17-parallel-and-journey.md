> **Decision record.** This is a decision record from 30 Oct. Its decisions are in the spec v3.5 and plan v3.2; **where the numbers differ, the plan wins**.

# Two reviews: running it in parallel, and testing the journey

Two Astras, each with a Luna helper, read the spec, the plan and the code. Both reviews were read-only.
- `evidence/two-astras/astra-parallel.md`
- `evidence/two-astras/astra-journey-test.md`

## 1. As simultaneous as possible
**Four projects at once, not one stream.** They are `projects/state`, `runtime`, `pack` and `delivery`, each with one manager and its own spec folder.
- **More managers wouldn't remove a dependency;** more workers inside each project do help. The busiest point has about eight workers at once.
- **R2 and R3 run as separate workers** after R1.
- **Delivery runs three lanes in parallel:** landing, the test harness, and install.

**The narrow waist is L0, 2 days after the 1.5-day trial.** Five things are frozen:
- state and migration ownership (M1);
- the lifecycle and message semantics;
- the CLI surface (the operation-key flag, `--json` fields, `project new --from`);
- the pack's role-file format;
- landing and the crash points.

Internals change freely; an interface changes through one contract diff.

**Integration happens continuously, into one new repo:**
- contracts, skeleton and tests first, then real pieces replace the stubs;
- M4 runs checked fast-forward landing into `main` from day one;
- installed-wheel CI runs on every candidate;
- VS proves the runtime joins around day 14.

**The schedule:**

| Reading | Days |
|---|---:|
| v3.1's figure | 23.5 (wrong: D6 and X0 overlapped; done one after another it was 24) |
| R2 and R3 in parallel, nothing else changed | **22** |
| Also splitting R4, C6, D3 and D2 into preparation against fixtures plus a short qualification | **20.5** (same effort, same gates) |

The bottleneck is **C1 → R1 → R3 → the live VS.** More content or install workers won't shorten it, and managers must accept finished work promptly.

**Bootstrap.**
- **Until the tool exists,** today's Claude Code or Codex sessions act as the orchestrator, four managers and workers, following the runbook.
- **After VS,** try the tool on one small, non-critical task.
- **The pilot is the tool building attach on itself;** after that, it runs its own follow-ups.

Plan §11 has the details.

**Follow-ups.** Attach stays first. Then come inbox hooks, a second production pack, and Turso or multi-machine support, each when it's needed. **Don't carve anything else out of v1:** what's left is the core proof.

**The role model holds up.** Three details were added to the spec (v3.5) and to L0:
- **rank is stored separately from role,** inferred from how the agent was started, and checked against what the role allows;
- **a short wrapper per rank:** a worker submits; a helper returns to its worker;
- **the pack version and role hash are recorded on both paths,** and a role's skills live only in its front matter.

**The attach carve-out is right,** but the reservation needed more. Two things were added:
- a **current binding id**, checked on every identity source;
- a **handover that can't be interleaved,** with defined recovery.

## 2. The end-to-end journey test
**One test, about 600 lines, owned by D3 and still within its 3 days.**
- **What runs:** the installed wheel and the real `otto run` drive the **real omp binary** against a **scripted loopback model.**
- **How the agents act:** the scripted model returns tool calls (`bash: otto spawn …`, `write`, `task`), so the agents drive the tool exactly as real ones would. The test never writes the database behind their backs.

**The journey:**
1. install, `init`, `project new`;
2. the manager plans and dispatches;
3. a sense-checker runs as a worker, and the implementer calls a sense-checker helper;
4. the owner changes the spec mid-work, and the manager amends the running task;
5. **`SIGKILL`** after the amendment is committed but before the message is acknowledged; restart and replay, with no duplicates;
6. submit, then checked landing (accepting doesn't mean done);
7. a requested consultation and a scheduled one, through the same advisor session;
8. status stays truthful at every step.

**The script is plain Python** (about 120 lines). It holds response lists per role and step, keyed on the model id and the job id, never on prompt text. An unknown route or an exhausted script fails at once.

**Checks** use `--json` output and Git. Waits use settle events (no sleeps), and schedules use a test clock. The target is 60–120 seconds, inside the 3–5 minute CI run.

**The live variant uses the same checkpoints** with real models, asserting on outcomes rather than wording. **It is the pilot's backbone,** run on your real project.

**Not built:** a scenario language, an agent simulator, record and replay, LLM judges, or a provider matrix.

**The first step a worker would take:** the installed omp → one loopback tool call → the installed `otto status`; then one native helper call; then grow that same test into the journey.
