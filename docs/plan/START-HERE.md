# Start here

**This package plans a new, small, standalone tool that runs an organisation of AI agents on one machine.** Nothing has been built yet. The plan has been reviewed many times. The first two steps, a 1.5-day oh-my-pi trial (**S0**) and a 2-day agreed contract (**L0**), are real work still to do.

## Read these, in this order (about 45 minutes)
| # | File | What it gives you |
|---|---|---|
| 1 | `15-in-short.md` | The whole thing on one page |
| 2 | `GLOSSARY.md` | Every name and code used below |
| 3 | `DECISIONS.md` | What's decided and by whom, and **what's still open** |
| 4 | `13-spec.md` (v3.5) | **What the tool does** (Part A) and how it's built (Part B) |
| 5 | `14-plan.md` (v3.2) | **How we build it:** tasks, managers, schedule, done criteria |
| 6 | `projects/README.md` + your folder | The four parallel projects and the pilot |
| 7 | `POLICY.md` | How the build team operates before the tool exists |
| 8 | `SOURCES.md` | Where the code and the references are |

## Rules for reading
- **Authority.** `DECISIONS.md` > `13-spec.md` (behaviour) > `14-plan.md` (execution) > `projects/*` (task copies of the plan) > everything else. If two current documents disagree, don't pick one: raise it (see `POLICY.md`) and record the answer in `DECISIONS.md`.
- **History is not requirements.** `01`–`12` and the old parts of `16`–`17` explain how we got here. `evidence/` holds the raw reviews, snapshots taken at the time. **Nothing in them adds a current requirement,** even when it's written in the present tense.
- **"Otto" means two things.** *Old Otto* is the frozen predecessor we mine for parts. `otto` is the new tool's working name and CLI. See `GLOSSARY.md`.

## Milestones (what "done" means)
1. **Base qualified:** B0, X0a, S0 and L0, and every state, runtime and pack task, plus delivery's D1–D4, are done (the pilot, D5 and D6, comes next); the acceptance harness and the end-to-end journey test are green in CI; the live vertical slice and the fresh-machine checks have passed.
2. **Pilot passed:** the tool has built `projects/attach/` on itself, with all the pilot scenarios observed (`14-plan.md` §6). Attach has been used for real once, in a side-by-side test organisation.
3. **Released:** the owner approves, and the attach-capable version is installed in place of the base version.
4. **Closed:** Otto and the old plan surface are archived (X0b), and the next project is chosen.

## Your first steps
1. **Read `DECISIONS.md` §2** (the owner's day-1 answers). The repo is `AstridPseudon/Otto`; `main` is the new tool; old Otto is on `deprecated`.
2. **Day 0 is done (30 Oct):** **B0** (a fresh `main` with the skeleton, CI and landing script) and most of **X0a** (old `main` moved to `deprecated`; the transfer branches kept). The rest of X0a (a bundle of the planning repo, and a rehearsed restore) is in `../../ORCHESTRATOR.md`.
3. **Run S0** on the Mac and on the Linux box, and write the findings to `projects/s0-findings.md`.
4. **Fill in `projects/contract.md` (L0)** with the four managers; each one signs off.
5. **Start the four projects in parallel** (`projects/README.md`).
