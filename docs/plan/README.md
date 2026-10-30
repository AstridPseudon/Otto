# Plan package: a small tool for running agent organisations

**New here? Open `START-HERE.md`.** It has the reading order, the rules for which document wins, the milestones and the first steps.

## Current documents
| File | What |
|---|---|
| `START-HERE.md` | The front door: reading order, authority, milestones, first steps |
| `15-in-short.md` | The whole thing on one page |
| `GLOSSARY.md` | Names (new `otto` vs old Otto, Astrid, Megado, oh-my-pi), ranks and roles, runtime words, task codes |
| `DECISIONS.md` | What's decided, and the **open owner items** with recommended answers |
| `13-spec.md` (v3.5) | What the tool does (Part A) and how it's built (Part B); acceptance (B6); testing (B7) |
| `14-plan.md` (v3.2) | The plan: four parallel projects, 30 tasks plus contingency, about 53.5 engineer-days, about 22 working days, milestones, bootstrap |
| `projects/` | The four v1 project folders (state, runtime, pack, delivery), the pilot (`attach/`) and the L0 contract checklist (`contract.md`) |
| `POLICY.md` | How the build team operates until the tool runs itself |
| `SOURCES.md` | Where the code and references are (old Otto, oh-my-pi, Astrid) |
| `16-three-reviews.md`, `17-parallel-and-journey.md` | Decision records from the latest reviews (their decisions are already in the spec and plan) |

## History (it explains the decisions; it is not requirements)
| File | What |
|---|---|
| `01`–`04` | The retrospective of the Astrid build programme: what happened, the principles and runbook, a minimal structure, the method |
| `05`–`09` | Assessments and roadmaps for finishing old Otto: **paths we did not take** |
| `10`–`12` | The 90:10 option, keep-and-clean, and the owner's first minimal design: **superseded by the spec** |
| `evidence/` | Raw review and research outputs (`evidence/README.md`) |

---

# Retrospective: how the Astrid program was run, and what to keep

**Question:** what worked in running this program (orchestrator → managers → workers, 26–28 Oct), and what minimal structure would make it repeatable?
**Method:** about 32 Codex Luna analysts over the full orchestrator transcript, the four manager transcripts, about 130 task run folders, the plan repo history, and process docs from three other programs. Then a critic pass, then my judgement. See `04-retro-method.md`.

## The answer on one page

**What the program was:** three days, one orchestrator, about six manager sessions (Codex, then Haiku), dozens of workers. The updater was built, reviewed and rebased onto `main`; a testing plan and a Windows fix spec were written. Recorded manager spend was about $76.

**What actually made it work:**
1. **One queue per project** as the manager's single source of truth: tier, dependencies and a Done when per row.
2. **Strict roles:**
   - orchestrator guides, checks and decides;
   - manager executes back to back;
   - cheap models by default, escalating by difficulty;
   - Opus only for end reviews.
3. **The planning pattern:** cheap fan-out exploration → one strong planner → an over-engineering critic → orchestrator judgement → queue.
4. **Fixed evidence rules:**
   - the base decides;
   - written, not run, is never a pass;
   - hung tests are "not run";
   - built and verified are separate.
5. **Handoffs tested by a cold start,** and fresh managers at phase boundaries.
6. **Hourly check-ins that ask the same ten questions** and intervene specifically: idle, stale, looping, drifting, silent.

**What cost the most:**
- **The owner chasing status:** about 20 "is it running?" messages.
- **The owner re-correcting drifted policy** at handoffs.
- **Hand-built infrastructure breaking:** dispatch, sleeping containers, a missing trigger.
- **Stale inputs,** a wrong test baseline, and expensive full-suite debugging.
- **Plans that grew before they shrank.**

**The minimal structure** (`03` has the detail):

| Layer | Contents |
|---|---|
| **Roles** | Owner, orchestrator, manager, worker; "reviewer" is a read-only mode |
| **Files** | `POLICY.md` (rendered into every brief), `PLAN.md`, `QUEUE.md` (the source of truth), `runs/<task>/`, `DECISIONS.md`, `LOG.md` (one line per check-in plus cost), `HANDOFF.md` with snapshot |
| **Difficulty** | Four yes/no questions (multi-repo? stateful lifecycle? order or environment sensitive? root cause unknown?) → Normal, Hard or Super-hard. An unknown root cause gets a diagnosis task first. One failure escalates a tier. Record tier, attempts and outcome to calibrate. |
| **Loops** | The manager drains the queue continuously. The orchestrator checks right after the first dispatch, then hourly (every ~15 minutes only while actively iterating), and stops the schedule when ownership changes. |
| **Triggers** | Worker never started; idle with startable work; finished results waiting; snapshot older than the last landing; silent long run; second fix on the same mechanism; third review round; context above ~200K; spend over plan; plan contradicting a ruling |
| **Gates** | The owner approves scope, policy and project start, and everything about release, deploy and publication. The manager approves Done when and lands. The orchestrator reports "verified" separately from "built". |
| **v1 platform** | Managed worker lifecycle and heartbeat; live queue and status views; policy enforced at dispatch; schedules tied to the program's lifecycle; session rollover; spend ceiling |

**Don't build:** a per-event entity model, a numeric difficulty formula before there's data, review ceremonies for every project, one-off audit swarms, hand-kept status documents, self-scheduled wake-ups.
