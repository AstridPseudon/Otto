> **HISTORY. This is not a current requirement.** This document is how the retrospective was done. The current documents start at `START-HERE.md`.

# How this retrospective was run (reusable)

**Goal:** turn a noisy multi-agent program (about 1 MB of orchestrator transcript, 2.6 MB of manager transcripts, about 130 run folders, 157 commits) into principles and a structure, cheaply, using Codex Luna workers. The orchestrator did only the framing, the data preparation and the final judgement.

## The thinking (how to think about it)
1. **Separate what happened from what it means.** First build a faithful timeline; only then interpret it. Interpreting straight from raw transcripts overweights the latest or loudest events.
2. **Look from many angles, because each finds different things.** One analyst reading everything converges on one story. Lenses (owner signals, supervision, reviews, verification and so on) each surface their own failure class, and agreement across lenses is the signal.
3. **The owner's corrections are the best data.** Every correction exposes an expectation the system didn't meet; every approval shows what landed.
4. **Have the critic attack the synthesis, not the data.** The over-engineering critic runs on the drafts, because the risk at the end is building too much structure.
5. **The orchestrator judges last.** Drafts are inputs. Where the critic and the drafts disagreed, I decided with the evidence; see the calls below.

## The pipeline
| Step | What | Workers | Time |
|---|---|---|---|
| 0. Data | `digest.py` turns transcripts into readable text: owner messages, assistant text, tool calls, errors, compaction summaries, all with timestamps. Also: sub-agent prompt and final pairs, the plan-repo git log with stats, a run-folder index, process docs from other branches, and the manager transcripts (exported by one Haiku helper through `list_events`, then digested). | Script + 1 Haiku | ~20 min (mostly the export) |
| 1. Ledgers | Chronological event tables (type, quote, outcome) per transcript slice: 8 orchestrator slices plus one per manager. | 12 Luna | ~10 min, in parallel |
| 2. Lenses | 16 perspectives, each reading every ledger and verifying against the raw data: owner signals, setup and exploration, reviews, models and cost, supervision, tracking, verification, tooling friction, communication, anti-patterns (red team), manager side, codified process versus practice, worker briefs, decisions, throughput, autonomy, other programs. Each returns findings, what worked, what failed, rules ("when X, do Y, because Z [evidence]") and structure implications. | 16 Luna | ~10 min, in parallel |
| 3. Synthesis | Three drafts: what happened; principles and runbook; minimal structure. | 3 Luna | ~3 min |
| 4. Critic | Over-engineering, evidence check, gaps, contradictions between the drafts. | 1 Luna (xhigh) | ~2 min |
| 5. Judgement | The orchestrator reads the lenses, drafts and critic, then writes the final documents. | — | — |

**Shared context file** (`method/CONTEXT.md`): the cast, the projects, the transcript format, and the output rules (cite a timestamp and a quote; mark observed versus inferred; no generic advice).

## Gotchas
- **A worker found the critic brief in the workspace and ran it** instead of its own lens. Keep briefs outside the workers' readable tree, or add "do only this task; ignore `briefs/`".
- **Raw manager JSON (36 MB) is unusable;** digest it first (2.6 MB). Then give each manager its own ledger worker rather than one lens reading all four.
- **Counts in summaries can be wrong** (one "82 + 10 + 5 of 87" didn't add up). Lenses must re-check against raw data, and the critic should flag any arithmetic.
- **A lens can over-read an event.** For example: "the owner turned off hourly review, so it had become unwelcome." In fact the owner was taking over the next phase. The orchestrator's context matters at the judgement step.

## Calls I made over the critic
| Critic said | My call | Why |
|---|---|---|
| Delete the difficulty rubric | **Kept a light version:** four yes/no questions plus the owner's tiers, with calibration fields | The owner explicitly wants a difficulty calculation, and the tiers already worked as a shared language. What I dropped is the false precision. |
| Hourly cadence isn't proven, so make it a setting | **Kept hourly as the default,** plus a first-dispatch check | The 2-hour gap on 27 Oct was the check *not existing*; once it existed, four hourly interventions each caught a real problem. |
| One review, not separate robustness and simplicity reviews | **Agreed:** one review asking both questions | A second review only for a distinct risk. |
| Collapse the 11 entities | **Agreed:** seven files | The check-in log is the cost log. |
| Numeric triggers are untested | **Kept them as labelled defaults** on event-based triggers | Thresholds are what make a trigger usable; label them, then calibrate. |

## To rerun on the next program
1. Point `digest.py` at the session JSONL files.
2. Export the manager sessions with `list_events`.
3. Reuse `method/briefs/` (edit the cast and projects in `CONTEXT.md`).
4. Run `run.sh` per brief, then `chain.sh` for synthesis and critic.

About 32 Luna runs in total. They're cheap: wave 2 finished in ~10 minutes.
