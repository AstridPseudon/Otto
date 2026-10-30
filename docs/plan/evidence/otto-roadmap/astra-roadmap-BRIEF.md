# Otto: the roadmap from today's branches to the end state

You are **Astra**. Read-only: don't edit files, don't run git writes, don't run any Otto service or install.

## Investigation already done by nine Luna investigators
Their reports are in `luna/r-*.md`:
- `canon`: what canon/main provides against each target point;
- `labs`: a verdict per lab branch;
- `slim`, `packs`, `effects-proclife`, `throughput-harness-fleet`: the project branches;
- `pause`: the resume queue and the minimum to get green;
- `target`: the smallest change per target point;
- `thinpath`: the Astrid thin path as a pilot base.

**Read all nine.** Verify the load-bearing claims yourself in the repo; they can be wrong. Where you disagree with an investigator, say so. If something important is still open, you may start more Luna sub-agents (`spawn_agent`, model `gpt-6-luna`) for it.

## Map
- `otto/otto`: the Otto git repo, checked out at `canon/main` (`a70b3f2`, also GitHub main). Every branch is local: `lab/*` (16 integration fixes, unlanded) and `proj/*` (7 follow-on projects with partial work).
  - Worktrees are under `otto/labs/<name>` and `otto/projects/<name>`.
  - `BRANCH-LOG.md` in this directory lists each branch's commits and diff stats against canon/main.
- `otto/portfolio`: `PLAN.md`, `AGENT-UX.md`, `RUNBOOK.md`, the `projects/*` plans and tasklists, and `ops/` (the program's run records).
- `otto/CURRENT-STATE.md`, `FIXES-ESSENCE.md`, `PROJECT-ESSENCE.md`: the state at pause.
- `retro/`: our retrospective. **`07-first-principles-review.md` is the current target end state**; `06` came before it; `02` and `03` are the principles and the minimal structure.
- `OTTO-FACTS.md`: an earlier summary of Otto. Verify it.
- `data/`: transcripts from the Astrid program. `astrid-plan-repo/`: its plan repo and tools.

## The target, in brief (from `07`; challenge it where the evidence says so)
1. The owner sets a **mandate**: outcome, acceptance through the real user path, scope and effects, budget, reserved decisions.
2. **Managers dispatch.** There is no automatic dispatch; this is the owner's firm stance. Otto **wakes** the responsible manager on events.
3. **Turn exits are declared and checked:** a nudge to the agent first, then its supervisor. Observation mode first.
4. **A liveness monitor** catches never-started runs, dead sessions and declared deadlines that pass.
5. **Tools record their own receipts,** with base and execution identity. Status and handoffs are derived from them.
6. **One launch boundary** enforces model, spend and capacity.
7. **One message interface,** with wake-up and resolution.
8. **A cheap supervisor sweep** nudges managers; only exceptions go to the orchestrator.
9. **Capable workers:** shell or a capable check, `ask`, and turns sized to the task.
10. **Verification:** user-path acceptance; separate states for implemented, verified and accepted-with-gaps; batch integration, then qualification; reviews with a stopping rule.
11. **Instructions:** a small compulsory core, plus judgement guidance; tested by replaying real incidents.
12. **Measured:** a control stays only if it earns its keep.
13. Cloud sessions with git as the store are a first-class environment.

## Answer two questions
**Q1. The path.** From where Otto is today (canon/main plus its lab and project branches, paused with a resume queue), what tasks get it to the target?
- First decide what to do with the in-flight work: finish and land, rewrite, or drop. Cover each lab branch and each project branch, with a reason.
- Then give the task sequence to the target, as rows:
  - `ID | task | why (which target point) | depends on | tier (Normal / Hard / Super-hard) | done when`.
- Group the rows into phases. Mark which rows **delete** code, and roughly how much.
- Include a **pilot**: one real project run end to end. Say where it fits, and what has to exist before it.
- Say what to **stop**: work in the plans or branches that doesn't serve the target.

**Q2. The end state, concretely.** What exactly does Otto look like when done?
- The components and their responsibilities.
- The commands or tools each role uses: owner, orchestrator, supervisor, manager, worker.
- The records and their key fields.
- One day in the life: a worked example from a project starting, through a stalled manager and a question, to verified delivery.
- What remains of today's code: kept, rewritten, deleted, as a rough proportion.

**Then: ten provocative statements about that end state,** each one or two lines. Make them sharp enough to test the owner's thinking at the edges, but grounded in what you found.

## Output (your final message)
1. **In-flight work:** a table with the verdict per branch.
2. **Q1:** the phased task table, the pilot, and the stop list.
3. **Q2:** the concrete end state.
4. **Ten provocative statements.**
5. **Investigator findings:** one line each on what you relied on and what you overruled.

Be concrete and terse. Cite evidence (path:line, commit). No padding.
