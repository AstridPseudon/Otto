# Shared context (read first)

You are **Astra**, reviewing read-only. You may start Luna sub-agents (`spawn_agent`, model `gpt-6-luna`) to check things in parallel. Verify anything load-bearing yourself, and cite file paths with line numbers.

**Where we're going**
- `retro/15-in-short.md`: the end state and the path, on one page. **Start here.**
- `retro/13-spec.md` (v3.2): the spec.
- `retro/14-plan.md` (v2.1): the plan, with 28 tasks, 4 managers and about 46 engineer-days.
- `retro/12-minimal-design.md`: the owner's direction.
- `retro/11-thin-path-keep-and-clean.md`: the earlier keep and clean-up list.
- `retro/evidence/spec/astra-plan-check.md`: the last check.

**The current code base**
- `otto/`: the frozen Otto program, restored.
  - `otto/otto/`: the integrated code at `a70b3f2` (`src/otto`, `tests/`, `controller/`, `install/`, `ops/`, `docs/`).
  - `otto/labs/*` and `otto/projects/*`: worktrees of 16 lab branches and 7 follow-up project branches. `otto/projects/packs` holds the Megado pack work.
  - `otto/START-HERE.md`, `otto/CURRENT-STATE.md`, `otto/PROJECT-ESSENCE.md`, `otto/branches.json`.
- `banodoco/astrid-agent`: Astrid's omp integration. Use `git -C banodoco/astrid-agent show origin/main:<path>` for `astrid/omp_agent.py`, `astrid/installer/tools.py` and `astrid/installer/omp/recipe.json`.
- `astrid-plan-repo/`: our plan repo (the retro docs, `out/`, scripts).
- `oh-my-pi/`: the harness we build on (`docs/`, `sdk/python/omp-rpc`).

**The owner's direction, which governs everything**
- **Minimal, elegant and tested.** Reuse what's already tested; no excessive controls; no spend control.
- **One machine, one SQLite file.**
- **oh-my-pi** handles sessions, logins and model choice.
- **Five roles** and **packs**.
- **Spec folders** with check-out and check-in.
- **Managers dispatch;** there's no automatic dispatch.
- **Any seat can be attached** from an outside session.

**Output rules**
- Be concrete and terse, and prioritise by impact.
- Ground each point in a file or a doc line.
- Write your final answer as markdown; it is saved as your output file.
