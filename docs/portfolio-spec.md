# Portfolio: one orchestrator, many projects (core spec)

**Status:** spec for the `portfolio-core` branch (on `claude-host/one-otto` f9bece3).
**Author:** the Claude Code orchestrator, 11 Oct 2026.
**Builder:** Astra (Codex CLI); review and integration by the Otto host lead.

## Why
One orchestrator runs a PORTFOLIO of related projects end to end. Each project has its own manager; managers run in parallel; projects depend on each other's milestones; they share programme documents (contracts, the North Star); and the orchestrator sees the whole portfolio at a glance.

**The first real user** is the timeline refactor: about ten projects. Projects 2–7 wait on project 1's "contracts frozen" milestone, projects 8–9 on milestones in 4 and 5, project 10 integrates everything. See `/Users/hannahomalley/Developer/astrid-video/.otto/runs/timeline-platform-r4/PORTFOLIO-PROPOSAL.md`.

**Decision:** CORE functionality now (packs are content-only and can't run code or add storage); a pack later, once the pack platform supports it. **No new SQLite table and no new store schema:** build on existing primitives.

## Existing primitives to reuse (verified read-only; re-check while building)
- **Grouping:** the orchestrator portfolio (`wrk.portfolio`) and the supervision relation `work.orchestrator.projects.attach`.
  - `src/herzchen/domains/work/orchestration.py:38, 182, 205`: the portfolio identity;
  - `orchestration.py:686-712`: attach;
  - `orchestration.py:372`: `create_pending_with_supervisor`;
  - `orchestration.py:505`: `transfer_supervision`;
  - a project supervised elsewhere is refused (`orchestration.py:866-868`).
- **Dependencies:** `WorkGraph.link_dependency`, with no kind gate and existing cycle detection.
  - `src/herzchen/domains/work/batches.py:346`, delegating to `module.py:421-445`; cycles at `module.py:766-794`;
  - a mutation port for `work.project` dependency-linked is declared at `module.py:125-137`;
  - the RESTRICTION to `kind=task` + same project lives in the binding (`src/otto/agents/herzchen_binding.py` ~697-709, `dependency_scope_mismatch`);
  - `set_readiness` (`module.py:447`) stores a readiness observation;
  - `WorkKind` includes `gate` (`domains/work/model.py:16-22`).
- **Shared documents:** a standalone `dat.content.document` is its own scope (`src/herzchen/content/authoring.py:263-270`); `DocumentAssociation` is a many-to-many edge to any ResourceRef (`content/model.py:235-257`; `_parse_link` at `authoring.py:278`). Cross-project reads are refused because `_subject_allowed` (`src/otto/portfolio/documents.py:166-170`) admits only the project or its tasks; the response is at `documents.py:72-85`.
- **Listing:** `otto/portfolio/intake.py:839-856` (`list_projects`); `otto/portfolio/cli.py:95-139`.
- **The host command surface:** `src/otto/hostctl/cli.py` (`ottoctl`) and the one owner service with client lanes (`src/otto/hostctl/serve.py`, `owner.py`). The manager's document read is `ottoctl manager project-documents`.

## What to build (the smallest correct version)

### F1. Project dependencies with readiness
- A project may depend on:
  - (a) another PROJECT in the same portfolio, satisfied when that project is completed; or
  - (b) a GATE/milestone inside another project in the same portfolio, satisfied when that gate is passed (use Otto's existing gate/criterion semantics; find exactly how a gate is "passed").
- **Commands:**
  - `ottoctl project depend --project B --on A[#gate-id-or-alias] [--remove]`;
  - `ottoctl project dependencies --project B` (lists each dependency and whether it's satisfied).
- **Storage:** the existing work dependency graph. Relax the binding restriction ONLY for project→project and project→gate links where both projects are supervised by the same portfolio. Everything else keeps today's refusal. Reuse the cycle detection.
- **Readiness:** computed on read from the dependencies: `ready` | `blocked` (with the list of unmet dependencies). Record an observation with `set_readiness` when the status is computed, if cheap.
- **Gating:** `project activate` refuses a blocked project with a clear message listing the blockers. `--override-readiness --reason "…"` lets the orchestrator principal (or the owner) proceed, and the reason is recorded.
- **Scale:** with ~10 projects there's no need for anything clever, but avoid an O(N²) read of the store.

### F2. Portfolio documents (shared across the portfolio's projects)
- A portfolio document is a standalone DAT document **associated with each project in the portfolio** via a `DocumentAssociation` in a dedicated namespace (e.g. `portfolio.shared`). New projects attached later get the associations too (when they're attached, or through an explicit sync).
- **Visibility:** extend `_subject_allowed` (documents.py) so that a project's readers (its manager and workers) can READ documents associated with that project through the `portfolio.shared` namespace. Only the orchestrator principal (and the owner) can WRITE them.
- **Commands:**
  - `ottoctl portfolio documents --operation list|read --path …` (orchestrator);
  - `ottoctl portfolio sync-docs --dir DIR` registers or updates a directory of UTF-8 files as portfolio documents (nested up to 4 levels, digest-based like project `sync-docs`, never overwriting an Otto-side edit);
  - the manager's `project-documents --operation list` shows them in a separate "portfolio" section, and `read` works for them.

### F3. Portfolio status
- `ottoctl portfolio status [--json]` shows, for the caller's portfolio (the owner may pass `--portfolio`):
  - per project:
    - ref and title;
    - lifecycle;
    - readiness (ready/blocked + blockers);
    - manager state (none/running/paused + last heartbeat if available);
    - task counts by state;
    - open help/escalation requests;
    - allowance use;
    - last activity time;
  - portfolio totals;
  - a short **"needs the orchestrator"** list: help requests, projects that are ready but not active, overridden readiness, stalled managers.
- **Speed:** a few seconds on the 7.6 GB live store. Do NOT export a sheet per project (today's `projects` takes ~65 s that way); read the minimal records.
- **Megado's hourly summary:** this command is it. Update the Megado skill reference to use it (`policy-staging/megado/skill/references/manager-communication.md:8`).

### F4. Detach
`ottoctl project detach --project X` (orchestrator or owner): removes the project from the portfolio's supervision. It refuses while that project's manager is running, and it removes the project's `portfolio.shared` associations.

### F5. Docs and skill
- `docs/portfolio.md`: a short user guide with the timeline portfolio as the worked example.
- A "Portfolios" section in the Megado skill, covering:
  - one orchestrator, a manager per project;
  - contract-freeze gates as dependencies;
  - shared portfolio documents for contracts;
  - `portfolio status` as the check-in;
  - light per-project testing + a live walking skeleton + one final integration project.
- Keep both short.

## Non-goals (notes, not built)
- Cross-portfolio dependencies.
- Cross-project TASK dependencies: use gates.
- Automatic activation when ready: the orchestrator activates.
- A portfolio record kind or a new table.
- Pack packaging.

## Tests
**Unit tests:**
- dependency link allowed and refused (same vs different portfolio, wrong kinds);
- cycle refused;
- readiness flips when a gate passes or a dependency project completes;
- activate is refused when blocked, and the override is recorded;
- portfolio document visibility: a manager of project 3 can read it, a worker can read it, a worker can't write it, a project outside the portfolio can't read it;
- sync-docs conflict detection;
- detach is refused while a manager is running.

**End to end on a DISPOSABLE new store** (never Codex's live store), deleted afterwards:
1. `service run`;
2. admit-host claude-code;
3. register ~10 projects:
   - prefer the real timeline portfolio bundles under `/Users/hannahomalley/Developer/astrid-video/.otto/runs/timeline-platform-r4/projects/NN-*/` if they exist (read-only);
   - otherwise a synthetic fixture mirroring PORTFOLIO-PROPOSAL.md;
4. sync the portfolio documents from that dir's `portfolio.md` + `spec-*.md`;
5. declare the dependencies (2–7 → 1#contracts-frozen; 8 → 4#…, 9 → 5#…; 10 → all);
6. `portfolio status` shows the right blocked/ready;
7. pass project 1's gate → 2–7 become ready;
8. a project-3 manager process reads the portfolio contract document through `manager project-documents`;
9. detach a project;
10. stop the service.

Record the receipts and timings.

## Constraints
- Work ONLY in `/Users/hannahomalley/Developer/otto-claude-host/otto-portfolio-core` (branch `portfolio-core`). Don't touch the main clone's working tree, Codex's trees (`~/Documents/Codex`), `~/.codex`, or any live store.
- **Tests:** Python 3.9 (`python3`), and 3.11 where available (`/opt/homebrew/bin/python3.11`). The suite is unittest-based; run the affected modules, plus the hostctl/serve and portfolio modules, at most 3 in parallel (8 GB machine).
- Follow the existing code conventions and the existing error/receipt shapes. Small, clear commits.
- Clean up every temp store and directory you create.
