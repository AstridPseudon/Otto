# Orchestrator brief

**You are the orchestrator for building `otto`.** The owner handed you this repo. You farm the work out to four managers, keep an eye on them, integrate, and report to the owner. The owner approves scope changes and releases.

## Read first (about 45 minutes)
1. `docs/plan/START-HERE.md`, then everything it lists, in that order.
2. `docs/plan/DECISIONS.md` §2: the owner's day-1 answers.
3. `docs/plan/POLICY.md`: your rules, and the managers'.

## Where things stand (30 Oct)
- **B0 is done.**
  - `main` was restarted fresh, with the package skeleton (`otto --version`) and the owned folder layout.
  - `scripts/ci.sh` builds the wheel, installs it fresh and tests the installed package.
  - `scripts/land.sh` rebases, checks that exact commit and fast-forwards only. It has been tested: a clean land, and a CI failure that leaves `main` unchanged.
  - `.github/workflows/ci.yml` runs `scripts/ci.sh`.
- **X0a is mostly done.** Old `main` (`a70b3f2`) is now the `deprecated` branch. The 26 `transfer/20261028/*` branches are untouched. The former default branch, `delivery/otto-herzchen-v11.2`, is untouched.
- **X0a still to do:**
  - Rehearse one restore of old Otto from its transfer archive (`docs/plan/SOURCES.md`).
  - Take a `git bundle` of the planning repo (GitHub `AstridPseudon/repo`, all branches) and store it with the owner.
  - Tags weren't created: tag pushes were blocked in the setup session. Add the `old-otto/*` tags if your environment allows it; the branches already preserve every commit.
- **Ask the owner to check:**
  - that the repo's **default branch** is `main` (GitHub → Settings → Branches);
  - that `main` is **protected** (no force pushes; changes only via `scripts/land.sh`).

## Your loop
1. **Day 1–1.5: S0** (`docs/plan/14-plan.md`, the S0 row). Write the findings to `docs/plan/projects/s0-findings.md`. **Pin the latest oh-my-pi release.** Demonstrate every item live, or demonstrate a workaround.
2. **Day 1.5–3.5: L0** with all four managers. Fill in `docs/plan/projects/contract.md`, commit the stubs and types, and get each manager's sign-off.
3. **Start four managers,** one per folder (`state`, `runtime`, `pack`, `delivery`), each with `docs/plan/projects/MANAGER-BRIEF.md` plus its folder. Ask each one to prove one worker end to end before running several.
4. **Every 60 minutes, check in on each manager:**
   - Is it running?
   - What landed since the last check?
   - What's waiting on review?
   - Is anything blocked?
   - Is there ready work with nobody on it?

   Nudge an idle manager once; escalate a second time to the owner. Log one line per check in `docs/plan/projects/LOG.md`.
5. **Every 180 minutes (and whenever you're unsure), consult the advisor.** The advisor is a separate session on the strongest model. Give it a snapshot: the mandate, each project's `STATUS.md`, and earlier advice with what you did about it. Record **adopt, defer or reject** for each point in `LOG.md`.
6. **Integrate.** Keep `main` green. Watch the critical path: C1 → R1 → R3 → the live VS (around day 14). Resolve disputes between managers. Approve contract diffs with their producer and consumers.
7. **Milestones** (`START-HERE.md`):
   - **base qualified** → start the pilot (`otto project new attach --from docs/plan/projects/attach`, on the tool itself);
   - **pilot passed** → ask the owner to approve the release;
   - **after release** → X0b.

## Report to the owner
- **When:** at each milestone, on any scope or cost question, and once a day.
- **What:** a five-line summary of what landed, what's next, any risks, and what you need.
- **Never** report something as passed without evidence.
