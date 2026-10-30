# Glossary

## Names
| Name | Means |
|---|---|
| **`otto` (the new tool)** | The tool this package plans. It's a Python package with an `otto` CLI and an `otto run` supervisor. "otto" is a working name (`DECISIONS.md` §2). When people say *"auto"*, that's speech-to-text for "Otto". |
| **Old Otto** | The **frozen** predecessor program, at commit `a70b3f2`, now on the **`deprecated`** branch of `AstridPseudon/Otto`. It's far bigger (about 117,500 lines). We lift a few hundred lines from it and archive the rest. "Otto (frozen)" in the documents means this. |
| **Astrid** | A separate product, Banodoco's agent app. Its build programme is what the retrospective (`01`–`04`) studied, and its installer pattern for oh-my-pi is reused. **It's not what we're building.** |
| **astrid-install** | The planning repo this package lives in. Not a code repo for the new tool. |
| **oh-my-pi (omp)** | The open-source agent harness we build on (`can1357/oh-my-pi`). It runs sessions, does subscription logins, chooses models, and runs native sub-agents. `omp` is its CLI; `omp-rpc` is its Python client. |
| **Pi** | Upstream of oh-my-pi. Considered, not used. |
| **Megado** | A working method (lifecycle, pragmatic review, escalation and improvement habits). The **first pack** translates it into short role guides and skills. The source text is on old Otto's `packs` branch (`SOURCES.md`). |
| **Pack** | A versioned folder of role files, skills, templates and default schedules. A protocol on top of the tool. |
| **Herzchen** | Old Otto's internal kernel and framework. **Left behind entirely.** |
| **Turso** | A hosted SQLite service. **Later**, maybe, for syncing between machines. |
| **Astra, Luna, Terra, Sol** | Names of OpenAI (Codex) model tiers used **during planning and review**: Astra is the strongest, Luna is light. They're examples, not requirements. The real model ids are whatever oh-my-pi's catalogue lists at S0. |
| **Opus, Sonnet, Haiku** | Anthropic (Claude) model families. "Opus 5.5" is the seeded default for the advisor. |

## The organisation
| Term | Means |
|---|---|
| **Rank** | One of five fixed levels built into the tool: **advisor, orchestrator, manager, worker, sub-agent**. A rank decides who starts whom, who reports to whom, and how the agent is run. |
| **Role** | A named job at a rank, defined by the **pack** in `roles/<name>.md`, with fixed instructions, skills and a model role. For example: `manager`, `worker`, `sense-checker`, `over-engineering-checker`. |
| **Specialist** | A pack role that can run at worker rank (its own task) or at sub-agent rank (a helper inside a worker), from the same role file. |
| **Model role** | oh-my-pi's named model slot (e.g. `otto-manager`), set in its `/model` picker. Every role resolves to one; there's no model table in our tool. |
| **Seat** | One position in the tree (e.g. "the manager of project X"). It has **one holder** at a time. |
| **Host** | Who runs a seat: `otto` (the supervisor runs it) or `external` (an outside chat window attached to it; the pilot builds this). |
| **Binding** | The current attachment of an outside window to a seat; a stale one is refused. |
| **Supervisor** | The `otto run` process that owns every agent's omp process. **Not** a person and **not** the orchestrator. |

## Runtime words (they matter)
| Term | Means |
|---|---|
| **Admitted** | omp accepted a prompt. That doesn't mean it ran. |
| **Settled** | omp's `session_settled`: the session is idle, including any background work. That doesn't mean it succeeded. |
| **Acknowledged** | A message has been handled: the recipient's turn ended normally after it, or it replied. Until then it stays in SQLite and may be delivered again. |
| **Operation key** | `<message-id>/<step>` passed with each command a message triggers, so a replay can't do the same thing twice. |
| **Attempt** | One worker's go at a task. Only one is current at a time; a stale attempt's submission is refused. |
| **Landed** | The checked commit has been fast-forwarded onto the target branch. A code task is only **done** once it has landed. |

## Projects and documents
| Term | Means |
|---|---|
| **Project (build)** | One of the four v1 workstreams in `projects/`: state, runtime, pack, delivery. |
| **Project (in the tool)** | A spec folder the tool manages, imported with `otto project new <name> --from <folder>`. Once the tool exists, the folders in `projects/` are exactly that. |
| **Spec folder / check-out / check-in** | A project's documents, stored as revisions in SQLite. You check them out to files, edit them, and check them back in, all or nothing. These are **not** Git checkouts. |
| **Worktree** | A Git worktree per worker, for code. |

## Task codes (in `14-plan.md`)
| Code | Means |
|---|---|
| **S0** | The oh-my-pi trial (1.5 days). |
| **L0** | The lifecycle and configuration contract (2 days), written to `projects/contract.md`. |
| **VS** | The vertical slice: the first live end-to-end run of spawn → ask → answer → continue → restart. |
| **B0** | Day 0: restarting `main` of `AstridPseudon/Otto` fresh, with the skeleton, initial CI and landing script. Done 30 Oct. |
| **X0a / X0b** | Preserving old Otto and the plan branches before the build; archiving the old surface after. |
| **C1–C6** | State tasks (M1). |
| **R1–R6** | Runtime tasks (M2). R4 and R5a belong to **M3**, despite the R. |
| **P1–P5** | Pack tasks (M3). |
| **D1–D6** | Delivery tasks (M4). D5 is the pilot; D6 is contingency. |
| **A1–A5** | The attach project's tasks (the pilot). |
| **M1–M4** | The four managers: State, Runtime, Pack and behaviour, Delivery and integration. |
| **G1–G14** | Gaps found in the review (`16-three-reviews.md`). All resolved. |
| **§B6 / §B7** | The spec's acceptance list and testing section. |

## Difficulty (current system only)
**Normal, X-hard, Super-hard,** as defined in `14-plan.md` §4.

Other systems you may meet in the history documents (`XHARD`, 1–10 scores, "intelligence tiers") are **superseded**.

## Versions (separate axes)
| Axis | Means |
|---|---|
| **Document versions** | e.g. spec v3.5, plan v3.2. These number our planning documents. |
| **v1** | The first release of the tool: the base plus the pilot (attach). |
| **Pack version** | Recorded per agent, with the hash of its role file. |
| **omp pin** | The oh-my-pi version fixed at S0 (18.14.0 when this package was written). |
