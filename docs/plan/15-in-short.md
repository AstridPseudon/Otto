# In short

> Names: **`otto`** is the new tool (a working name). **Old Otto** is the frozen predecessor we take parts from. See `GLOSSARY.md`.

## What it is
**A small tool that runs a team of AI agents on one machine.**

- **Five ranks, any number of roles.**
  - The tool knows five ranks: an *advisor* thinks, an *orchestrator* decides, *managers* run projects, *workers* do tasks, and *sub-agents* help workers.
  - The pack defines the roles at those ranks, each with fixed instructions and generic skills. That includes specialists like a *sense-checker* or an *over-engineering checker*, run as a worker task or as a sub-agent.
- **One way to start an agent.** Every agent is started the same way: a role, the general instructions for that role, and the instructions for its job.
- **Projects are spec folders.**
  - You check a project out, edit it and check it back in, all at once or not at all.
  - The manager turns the spec into tasks.
- **Packs carry the method.** A pack holds the role guides, skills and helper definitions. Megado is the first pack; others can follow.
- **One way to talk.** Agents send messages up and down the tree.
  - A message waits until it's handled.
  - A repeated message can't create a second task or reply.
  - A code task is done only when its work has landed.
- **Only three pieces of structure:**
  - the hierarchy;
  - the orchestrator's check-in (60 min) and advisor consultation (180 min);
  - one nudge, then an escalation, when a manager stops with work left undone.

  Everything else is trust and skills.
- **oh-my-pi does the running.** It runs the sessions, handles your subscription logins and chooses models. You pick any model for any role in its model picker. We seed the defaults, e.g. the advisor on Opus 5.5.
- **One SQLite file** holds the tool's state; oh-my-pi keeps the sessions and logins. It can sync to Turso later.
- **Any seat can be taken by hand.** The tool builds this feature itself, as its pilot.
  - `otto attach orchestrator` (or `advisor`, `manager`, `worker`) makes the chat window you're in that seat, and hands it the role, skills and current work.
  - `otto detach` hands the seat back.

## What we do to get there
0. **Day 0 (done):** old Otto is moved to the `deprecated` branch, and `main` of `AstridPseudon/Otto` is restarted fresh with the skeleton, CI and landing script.
1. **Prove oh-my-pi:** sessions, "all done", resume, sub-agents, model roles and logins, on a Mac and a Linux box *(1.5 days)*.
2. **Agree the contract:** how agents start, recover and hand off; when a message counts as handled; how spec changes reach running work *(2 days)*.
3. **Run four projects at once,** each with its own manager and folder in `projects/`:
   - **State:** the database, spec folders, tasks and the CLI.
   - **Runtime:** the supervisor, spawn, messages and recovery.
   - **Pack:** roles (including specialists), skills, schedules, the advisor and the nudge.
   - **Delivery:** install, landing, the acceptance tests.
4. **Prove the spine early:** spawn → ask → answer → continue → restart (around day 14).
5. **Pilot it by having it build its own next feature:** attach (`projects/attach/`, about 3 days of work). This uses every rank, a specialist, a spec change and a restart. After that, it builds its own follow-ups.
6. **Archive the old surface** (old Otto was already preserved on day 0; nothing is deleted), **then pick the next pack.**

**How we test:**
- Real storage, Git and processes, with faked model replies, in a 3–5 minute CI run that uses no logins.
- **One end-to-end journey test** drives the real tool and the real oh-my-pi with a scripted model, from install to landed work, including a crash.
- Real logins only at step 1, step 4 and the pilot. With real models, the same journey is the pilot's backbone.

**Size:** about 53.5 engineer-days for v1, and about **22 working days** end to end (20.5 if four tasks are split into preparation and qualification). Three tasks are genuinely hard:
- checking a project in all at once;
- one session per seat;
- messages that survive a crash.

**What we keep from Otto:** a few hundred of its 117,500 lines:
- the Megado method, rewritten into short guides;
- the folder validators;
- the landing sequence;
- its tests, as behaviour cases.

**What we leave behind:** its authority, receipt, process-custody, gateway and spend machinery.

*Next: `START-HERE.md` (reading order and first steps), `GLOSSARY.md` and `DECISIONS.md`. Detail: `13-spec.md` (what it does) and `14-plan.md` (how we build it).*
