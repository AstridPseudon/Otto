# Review P: how do we run this as simultaneously as possible?

**The owner asks:** "How would we manage this as simultaneously as possible? Could we break this into multiple projects that go at the same time, or does it all need to be one stream?"

**Answer concretely, from the plan's real dependencies:**

1. **The streams.** What's the smallest number of genuinely independent **projects**, each with its own manager and its own spec folder, that can run at the same time? List each project's scope, its interfaces to the others, and what it needs before it starts. Start from the four managers in plan §3, but re-cut freely. Look for work that can run fully in parallel with stubs or fakes, e.g.:
   - pack content against a frozen role-file format;
   - the test harness and fake omp against the L0 contract;
   - landing against a Git interface;
   - install and OS units.
2. **The narrow waist.** What must be agreed first, so the projects don't collide? Think of the L0 contract, the schema and migration ownership, the CLI surface, the role-file format and the crash-point list. How small can that be, and how fast? Which pieces are frozen, and which may change through a change process?
3. **Integration.** How do the parallel projects come together without a big-bang merge? Consider:
   - the order of integration;
   - one repo or several;
   - who owns `main`;
   - the landing rule;
   - the CI gate;
   - when the vertical slice proves the joins.
4. **The fastest critical path:** the realistic number of working days with maximum parallelism, compared with the plan's 23.5. Where is it bound (dependencies, live testing, review), and what would shorten it safely?
5. **Bootstrapping.** The tool doesn't exist yet, so how is the build itself run? Consider today's machinery (Claude Code or Codex sessions acting as orchestrator, managers and workers, following the retro runbook), and the point at which the new tool can start running its own remaining work (after VS? after the pilot?). Is "run the follow-ups (`projects/attach/`) on the tool itself" sound, and are there other parts that should be carved out as follow-ups so v1 gets smaller?
6. **Sense-check two recent design choices:**
   - **ranks fixed in the tool, roles in the pack** (spec A2). Does it hold up for specialists like sense-checker and over-engineering-checker at both worker and sub-agent rank? Is anything missing, or over-built?
   - **the attach carve-out:** is the v1 reservation enough?

**Output**
- A table of the projects (streams): scope, size, depends on, interface, and which manager.
- The narrow waist: what must be agreed first, and how long that takes.
- The integration plan.
- A day-by-day outline of the fastest safe schedule.
- The bootstrap plan.
- The follow-up carve-outs you recommend.
- A verdict on the role model and the attach carve-out.
