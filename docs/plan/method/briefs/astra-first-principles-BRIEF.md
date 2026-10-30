# First-principles review: the whole effort, end to end

You are **Astra**, an independent reviewer. Question this whole effort **from first principles**: what is the goal, what actually serves it, and what doesn't? Don't take our retrospective, Otto's design or the owner's current stances as given; test each one against the goal and the evidence. **Don't be provocative for its own sake.** Every finding must be grounded in evidence and must matter for the goal. The orchestrator (a Claude session) will weigh your findings critically, so being clear about how strong the evidence is helps more than sounding certain.

**Read-only.** Don't edit files and don't run git writes. Your sources are in this directory (see Map).

**Use Luna sub-agents.** Use your `spawn_agent` tool with model `gpt-6-luna` to investigate in parallel. Start as many as the questions need (6–10 is typical), each on one question with named sources, and have them report facts with file and line or timestamp. Verify anything load-bearing yourself before you build a finding on it. Suggested investigations:
1. the owner's own words: what they asked for, corrected and praised (`data/user-messages.txt`);
2. where our retro's rules came from a single incident and are being over-generalised (`retro/evidence/`);
3. what Otto's code actually enforces versus what its docs claim (`otto/source/otto/src`, `otto/skills`);
4. how the Otto program's run went (`otto/portfolio/ops`, especially `requests.md` and `STATUS.log`);
5. how managers actually behaved, and what instruction changes did or didn't change behaviour (`data/mgr*-digest.txt`, `retro/evidence/ledgers/w1-mgr*.md`);
6. the proposed end state (`retro/06-otto-end-state.md`) stress-tested against real incidents;
7. what's missing entirely: approaches to verifying and steering agents that nobody has tried.

Start from first principles: what does an owner running many agents actually need, and what's the smallest set of mechanisms that delivers it? Then compare what exists and what's proposed against that.

## The goal (owner's words, paraphrased)
Build a tool and process that **tracks this kind of multi-agent work and helps the owner manage it**, avoiding the problems we hit:
- idle managers;
- status chasing;
- policy drift;
- stale state;
- wrong baselines;
- runaway reviews;
- the orchestrator doing hands-on work.

The philosophy: **equip agents with knowledge and basic guardrails, and trust them.** Over-structuring and not trusting agents enough are failures too, and they matter a lot.

## The owner's current stances (challenge these as well, if the evidence says so)
1. **No automatic dispatch.** Managers dispatch. Make managers reliable instead: when a manager ends its turn without finishing, warn it; the second time, message the orchestrator to find out why.
2. **One generic way to communicate and escalate,** not a separate alert system.
3. **Mostly this is about instructing agents and making sure they follow the instructions.**
4. Open to extra supervision mechanisms. For example, an AI supervisor that checks every manager hourly and nudges them every few hours, in addition to the orchestrator.

## What exists (the Map)
- **`retro/`**: our retrospective of the Astrid program (26–28 Oct).
  - `README.md` (summary), `01`–`04` (what happened, principles and runbook, minimal structure, method).
  - `05-otto-fit.md` (Otto against the process) and **`06-otto-end-state.md`** (the current proposal, after the owner's correction).
  - `evidence/` holds 12 ledgers, 16 lens reports, drafts and critiques.
- **`data/`**: raw digests.
  - `main-full.txt`: the orchestrator transcript, about 1 MB.
  - `user-messages.txt`: every owner message.
  - `mgr1..4-digest.txt`: the four manager transcripts.
  - `subagents.txt`, `plan-repo-gitlog.txt`, `other-branches-process-docs.txt`.
- **`astrid-plan-repo/`**: the live plan repo of the Astrid program (`ORCHESTRATOR.md`, `MANAGER-CODEX.md`, `CODEX.md`, `PROGRAM.md`, `COST-LOG.md`, `plans/`, `runs/`, `tools/dispatcher.sh`).
- **`otto/`**: the Otto transfer archive (source, skills, portfolio, plans). **`OTTO-FACTS.md`** in this directory summarises six explorer reports about it. Verify before relying on it.

## What to examine (cover what's relevant; skip categories where you find nothing real)
1. **Holes:** problems the process or the end state still doesn't address, or that will reappear.
2. **Over-complexity and over-abstraction:** in Otto, in our retro's structure, and in `06`.
3. **What we should remove but aren't.**
4. **What we're removing but shouldn't:** guarantees or practices that earned their keep. Be specific about what would break.
5. **Poorly structured or thoughtless:** contradictions, rules that sound good but don't survive contact, cargo-culted ceremony.
6. **Over-structuring and under-trusting agents:** where we constrain, check or brief more than the evidence justifies. Where would a capable agent with good knowledge and two or three guardrails do better?
7. **Verification and steering approaches we aren't using:**
   - AI supervisors that sweep managers and nudge them;
   - sampling audits;
   - peer review between managers;
   - behavioural evals for briefs;
   - canary tasks;
   - self-reports with spot checks;
   - outcome-based checks instead of process checks;
   - anything else.

   Say what each would catch, and what it costs.
8. **What isn't serving the goal at all.**

## Output (write it as your final message)
1. **Findings, ranked by how much they matter for the goal.** As many as are real; up to about 50, but fewer is fine. Don't pad, and don't split one point into several. Each finding gets:
   - `#n`, its **category** and a **one-line statement**;
   - **Reasoning from first principles:** why this matters for the goal;
   - **Evidence:** facts with paths, timestamps or lines (from you or your Luna helpers);
   - **Recommendation:** the concrete change;
   - **What it would cost or lose:** be honest about the downside;
   - **Confidence:** high / medium / low.
2. **The best end state:** your view of the strongest design for the goal, in at most 300 words. It may be more complex or simpler than `06`, and it isn't a compromise.
3. **The few questions** the orchestrator should answer before building anything.

Be concrete, terse and grounded. No flattery or hedging boilerplate.
