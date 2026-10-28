# Oracle decision: who admits a task revision, and through what path (17 Oct 2026)

You are the Otto program's oracle (PLAN.md D10): decide one consequential question, with evidence. Stay read-only: never edit, create or delete files, commit, push, stash or check out; never run `ottoctl` or pass `--help` to any Otto command; never open the live Store, `~/.otto`, `~/.otto-clients`, `~/.codex` or `~/Documents/Codex`. Hand the legwork (reading code, finding callers) to Haiku sub-agents (`haiku-worker`), each with a self-contained brief; check any claim they make in the source before you rely on it.

## The question
On canon/main (`~/Developer/otto-claude-host/otto`, `canon/main`), there is no working path for the operator to admit a task revision. Admission is what lets the owner dispatch work (ADMIT, DISPATCH, AUTODISPATCH). **Decide who admits a revision, and through which path, so that an agent can't admit its own work.**

## Evidence (from a scratch-staging exploration, 17 Oct; check it)
- `ottoctl portfolio admit` through the owner lane is refused: OWNERLANE (STAGE1 F6) made the owner lane's portfolio set explicit and refused `admit` and `complete-task`, because any same-account process that can write the lane folder could otherwise admit its own revision (`src/otto/hostctl/service.py:~375`, `src/otto/hostctl/portfolio.py`).
- Run directly, `portfolio admit` returns `owner_session_unavailable`. Run in-process by the owner, it is rejected: "only the project's user admits a task revision" (the work domain's admit, `herzchen/domains/work/admission.py` `is_user`, and the admit in `module.py`).
- A project registered with `ottoctl project register` has the host principal (`claude-code-orchestrator`) as its creator, not a user (`src/otto/hostctl/register.py`).
- The explorer could admit only by stopping the owner and calling `graph.admit` offline with the creator's actor.
- Agents today: the program's manager and workers run in Codex's workspace-write sandbox. Their writable roots are their lab or the program folder plus the labs, so they cannot write `~/.otto-clients` (the owner lane). Claude-hosted workers, if any are used again, run under permission rules, not a sandbox (TOOLS: `dontAsk` with path rules).
- PLAN.md: D5 retires the file lane for an authenticated socket with peer identity (later work); ADMIT's row and D-rows on admission; AGENT-UX.md on what the user does.

## Options to weigh (or a better one)
1. The project's **user** is the operator's principal: `register` records the operator as the project's user, and admission goes through a user-authenticated path that agents can't reach.
2. Re-allow `admit` on the owner lane for the operator, on the ground that sandboxed agents can't write the lane, with the trust boundary stated and logged, until D5's peer identity.
3. A dedicated admit command that needs something only the operator holds.
4. Something else.

## Answer in this shape
1. **Decision** in two lines.
2. **Why**, with the evidence (file:line) that settles it, and what it costs.
3. **The task row** that delivers it: outcome, files, acceptance (including the refusal of an agent's attempt to admit), the invariant and the plausible mistake.
4. **What stays open** until D5, if anything.

Don't pad. No claim without evidence.
