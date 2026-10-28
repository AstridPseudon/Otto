# Brief: FACADEFD (xhard, 1.0 focused days)

**Outcome:** Keep owner descriptors flat under dispatch by making in-process command facades bind no socket, activating transport only when a cross-process consumer requests it. Reuse owner-owned constructors where they are per-call by accident, keep assessment actor and evidence grants request-scoped, and bound the in-memory command-port audit list.

**Why it matters:** Stage 2 on bf25904 showed the owner's command sockets and descriptors growing from 344 to 1,116 entries and 388 to 1,160 descriptors. Repeated facades leaked sockets during handoff budget reads, assessments, and routed host operations.

**Your lab:** The launcher creates the FACADEFD lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product and Herzchen command-port transport. Fix the socket lifecycle at the facade source; retain Otto's request-specific assessment authority.

**Files you own:** `src/herzchen/command_ports.py`, `src/otto/portfolio/manager_journey_service.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/herzchen/domains/assessment/module.py`, `src/otto/hostctl/service.py`, and focused tests covering those paths.

**Other files:** Edit any additional file the outcome directly requires, except the files listed below. Explain each additional file in your report.

**Do not touch:**
- PERCH2C's stage-2 work: `ops/bootstrap/perch.sh`, `ops/bootstrap/perch_report.py`, `ops/bootstrap/perch_stage2_evidence.py`, `ops/bootstrap/canary/project.json`, and `tests/test_perch.py`;
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on what exists:** `src/herzchen/command_ports.py` around lines 342-347 and 442-480 constructs and owns the socket transport; add lazy activation when cross-process transport is requested. `src/otto/portfolio/manager_journey_service.py` around 646-656 and 716 constructs `LimitService` for handoff budget reads. `src/otto/portfolio/owner_bootstrap.py` around 1071-1075 creates assessment modules; `src/herzchen/domains/assessment/module.py` around 250-264 builds limit and operation services. `src/otto/hostctl/service.py` around 441 routes `HOST_OPERATIONS` through a bootstrap. Reuse per-owner constructors only where the constructor is accidentally per-call; never cache actor-bound assessment objects or widen evidence grants. Bound the audit list in `command_ports.py` around line 411.

**Your check:** Add real-owner coverage showing 200 handoff budget reads, 200 assessments, and 200 routed host operations keep this process's descriptor count within +3; verify a cross-process facade still has a working socket and one task's actor cannot use another task's evidence grant. Bound and test audit retention. Run only focused non-staging-owner tests in this lab; the gate owns stage 2 `--fake`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_manager_journey_service.py tests/test_local_assessment_composition.py tests/test_hostctl_service_routing.py tests/test_manager_assessment_ipc.py`

**Regression at the level the friction appears:** Repeated in-process owner operations leave descriptor count within +3 while real cross-process facades still communicate and assessment authority remains scoped to its task.

**XHARD only:**
- Invariant: Owner descriptors stay flat under dispatch without widening any actor's authority.
- Plausible mistake: Caching the entire actor-bound assessment module so one task's evidence grant serves another, or binding lazily without releasing a socket requested by a consumer.

**Working rules:** Follow the Codex rules in the template: no commits or pushes; the launcher commits on exit. Do not run `git stash`, check out another commit, run `ottoctl`, or run tests that start a staging owner in the worker sandbox. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`. As XHARD lead, delegate execution and keep design, invariant review, and final review yourself.

**When done:** Report the commit, red then green focused checks, descriptor counts, cross-process behavior, task-isolation evidence, audit bound, and any remaining limitations. Stop and report if this brief contradicts the code.
