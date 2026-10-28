# Status: the Otto program

**15 Oct 2026, evening: the bootstrap is PAUSED by the user** (since 00:57Z). Nothing is running.

**Landed on `canon/main`** (github.com/AstridPseudon/Otto `main`):
- S0 and OWNERSAFE, before the bootstrap;
- S0B `b68b3a4`;
- STATUSREAD `009548c`;
- BOUNDARY `51fcfb9`;
- HOLD `c3880e0`;
- the orchestrator's TOOLING `e13c927` and TOOLING2 `16825ca`.

**Finished, not landed** (in labs):
- HOSTKIT `43a743d`;
- POOL `f57688d`, which needs three fixes first: the production call, a flaky test, and moving the pool into `herzchen/fleet` (see its row). HOSTKIT also needs Otto's names taken out of the fleet;
- GREEN `186c7e1`.

The POOL rerun with Haiku sub-agents is on `lab/POOLX`. It's an experiment, not for landing.

**Spend:** about $14 on agents so far (`ops/cost-eta-20261015.md`, `ops/experiments/POOLX/comparison.md`). The orchestrator's own Opus use comes on top.

**The plan was revised on 15 Oct, evening (PLAN.md §16):**
- a staging Otto;
- the observation perch and nine stages;
- the old Store is deleted at CUTOVER;
- the landing gate (D19);
- a Sonnet lead with Haiku sub-agents for XHARD;
- an Opus budget of 15 calls.

**The old Otto:**
- The shared owner runs unsupervised. It was restarted by hand on 15 Oct, and `ops/launch_owner.py` restarts it again.
- The project is still registered there as pending (`project-ec31f6e480bdedd0ef8ee98bd831`), as are the six follow-ups.

**On resume** (RUNBOOK §1):
1. TOOLING3;
2. land HOSTKIT, GREEN and POOL;
3. STAGE and A1, then PERCH and CUSTODY.
