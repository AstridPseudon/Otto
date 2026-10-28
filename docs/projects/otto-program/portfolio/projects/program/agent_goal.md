# Goal: the Otto program, edition 1 and the clean-up after it

**Objective:** deliver the end state in the shared PLAN.md §1. Edition 1 is the usable release.

**Scope:** the tasks in tasklist.md: takeover, the Herzchen model and fleet, dispatch and managers, plans in Otto, the proof, and the clean-up after edition 1.

**Not in scope:**
- Codex's own projects (vision, the union port, Native5), beyond saving the upcoming ones at CUTOVER;
- r4's timeline work, which is its own portfolio (CONV only converts it, and CUTOVER saves it);
- Astrid adopting the Herzchen fleet.

**Authority:**
- **The bootstrap:** started on 15 Oct (the user: "deploy the first project end to end"), and paused by the user at 00:57Z. Resuming needs the user's go.
- **CUTOVER:** needs the user's go, after they have seen the list of upcoming projects and their verified saves. Deleting the old Store is then authorized (the user, 15 Oct: "we can delete, so long as we still have the data on the upcoming projects all saved").
- Nothing activates or dispatches in the old Otto.

**Models and reviews:** run.json.
- Haiku for normal tasks and the manager.
- XHARD: a Sonnet lead delegating execution to Haiku sub-agents.
- Opus is the oracle, with a budget of 15 calls: 9 stage reviews, 1 final review and 5 in reserve (PLAN.md §16).

**Acceptance:**
- Each task lands through the landing gate (PLAN.md D19).
- Each stage of PLAN.md §16 passes its live run on the staging Otto and its Opus review.
- The final scenario is SKEL's two-host journey, MANY's measured concurrency, and the final Opus review.

**Stop criteria:**
- a go point refused;
- a stage review finds the system unsafe;
- an upcoming project's data can't be saved and verified before CUTOVER.

**Limits:**
- at most 2 bootstrap sessions at once (3 after a measured hour);
- nothing launches under 8 GB free disk;
- workers stop under 4 GB.
