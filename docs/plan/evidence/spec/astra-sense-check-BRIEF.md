# Sense-check a spec against the owner's vision

You are **Astra**. Read-only. You may start Luna sub-agents (`spawn_agent`, model `gpt-6-luna`) for open questions, and verify load-bearing claims yourself.

**Read:**
- `retro/13-spec.md`: the spec under review.
- `retro/12-minimal-design.md`: the design it implements.
- `retro/evidence/spec/r-*.md`: five investigator reports on the existing code and branches.

The existing code is under `otto/` (Otto canon `otto/otto/src`, project branches `otto/projects/*`, lab branches `otto/labs/*`). The Astrid thin path is `astrid-plan-repo/`.

## The owner's vision (their words, condensed)
- **Roles:** orchestrator, manager, worker, and a sub-agent below the worker.
- **One central path to spin up any agent, with a role.** Use Pi or similar.
- **Instructions:**
  - A manager gets a project: that project's spec, plus generic instructions every manager gets.
  - Workers and sub-agents work the same way.
  - Orchestrators are similar, and they deploy managers based on instructions.
- **Scheduled reminders** every hour, or every 3 hours, based on settings. Every 3–6 hours, the orchestrator consults "another thing" (a second opinion).
- **Projects:**
  - They work on top of a **project spec folder** that agents can extend flexibly, which gets put into a task list and given to a manager as a project.
  - The **existing mechanism for syncing spec folders to SQLite, with check-out and check-in, should be kept**, or something like it.
- **Work flows down:** a manager works through its project by deploying workers, who deploy sub-agents, end to end.
- **No excessive controls:** just basic structures to enforce and facilitate this. Nothing fancy. **No spend control.** Trust the orchestrator's check-ins.
- **Skills for the basic processes:** speccing a project, sense-checking it, checking for over-engineering, best practices.
- **Packs:**
  - Megado is one protocol on this infrastructure.
  - Others can be created, with different skills, spec formats and orchestrator or manager configurations, all defined by the pack.
- **As minimal as possible:**
  - Use what we already have, even if that means simplifying or removing things.
  - Build it as a tool now, designed to become a protocol.
- **Storage:** a simple database that can move between machines or sync to the cloud (SQLite to Turso).
- **Not sold on keeping the Herzchen library layer.**
- **The approach should be minimalistic, elegant and tested,** reusing what's already built and tested on the branches.

## Questions
1. **Will this spec actually reach the vision?** Go point by point through the vision above: met, partly met, or not met, and why.
2. **Ambiguities:** what's underspecified enough that two engineers would build different things? Examples to check:
   - how a manager turns the spec into tasks, and keeps them in sync when the spec changes;
   - what "idle" means for message delivery;
   - Pi's session and resume semantics;
   - concurrent check-outs by several agents;
   - who can edit the spec;
   - how the orchestrator deploys managers "based on instructions";
   - what the second opinion is, mechanically;
   - how packs override each other or get versioned.
3. **What it isn't doing** that the vision or real operation will need. Be concrete about the consequence. Don't push back in the controls the owner rejected, such as spend limits; you may name a risk once.
4. **Over-engineering or under-engineering:** anything in the spec that's more than the vision asks for, or anything too thin to work.
5. **The reuse claims:** is "port semantics, not code" right? Did the spec miss tested pieces worth lifting directly (check the investigator reports and the branches)?
6. **The estimate and order:** are 23 days and a 15-day critical path credible? What's the riskiest task?

## Output (final message)
1. **The vision coverage table.**
2. **Ambiguities,** ranked, each with a suggested resolution.
3. **What's missing,** ranked.
4. **Over- and under-engineering.**
5. **Reuse:** corrections.
6. **Estimate and risks.**
7. **The 5 changes** you'd make to the spec before building.

Be concrete and terse. Cite the spec's sections and the code (path:line).
