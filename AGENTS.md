# Rules for every agent in this repo

- **What this is:** the new `otto` tool. The plan is in `docs/plan/` (`START-HERE.md`, `GLOSSARY.md`, `DECISIONS.md`, `13-spec.md`, `14-plan.md`). Old Otto is on the `deprecated` branch: read it for parts, never build on it.
- **Your seat:**
  - **Orchestrator:** read `ORCHESTRATOR.md`.
  - **Manager:** read `docs/plan/projects/MANAGER-BRIEF.md` and your project folder.
  - **Worker:** do exactly the task in your brief, in your own branch or worktree.
- **Operating rules:** follow `docs/plan/POLICY.md`.
- **Getting onto `main`:** only through `scripts/land.sh <branch>`. Never push to `main` directly, never force-push, and never rewrite history.
- **Stay in your lane:** only touch the paths your project owns (`docs/plan/projects/README.md`). Interfaces come from `docs/plan/projects/contract.md`; to change one, send a contract diff, not a quiet edit.
- **Done** means the task's "done when" check passes, with evidence: CI output for automated checks, a logged run for live ones. "Written" is not "passed".
- **When something is unclear,** don't guess silently. Ask the next seat up, with a concrete question and a recommended answer.
- **Never** put credentials in Git, never delete branches or history, and never work around a permission denial.
