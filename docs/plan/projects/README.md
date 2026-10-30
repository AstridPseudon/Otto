# Projects

**v1 is four projects that run at the same time.** Each has one manager and its own spec folder, and they all integrate continuously into **`main` of `AstridPseudon/Otto` (restarted fresh)**. More speed comes from **workers inside each project**, not from more managers.

| Folder | Manager | Days | What it delivers |
|---|---|---:|---|
| `state/` | M1 | 12 | The store, spec folders, tasks and attempts, the CLI, status |
| `runtime/` | M2 | 12.5 | The supervisor, spawn, messages, recovery, the vertical slice |
| `pack/` | M3 | 11 | Roles (with specialists), skills, schedules, the advisor, the idle rule |
| `delivery/` | M4 | 13.5 | Landing, the acceptance harness and journey test, install, the pilot |

**Before they start, on day 0**, the orchestrator does **X0a** (preserve old Otto and the plan branches) and **B0** (the new repo, skeleton, CI and landing script). Then:
- **S0:** the oh-my-pi trial, 1.5 days, with findings in `s0-findings.md`;
- **L0:** the contract, 2 days, written to `contract.md` here;

**At the very end, after release:** **X0b** archives the old surface.

**S0's findings** go in `s0-findings.md`. The orchestrator's decisions log goes in `LOG.md`. Each project keeps its own `STATUS.md`.

**The pilot, run on the tool itself once v1 is qualified:**

| Folder | Days | What |
|---|---:|---|
| `attach/` | about 3 | **The pilot.** Connect an existing chat window to a seat |

**Where the code goes** (`main` of `AstridPseudon/Otto`, set up in B0; each project owns these paths, and anything else goes through the contract):

| Project | Owns |
|---|---|
| state | `src/otto/store/`, `src/otto/cli/`, `src/otto/spec/`, `src/otto/tasks/`, migrations |
| runtime | `src/otto/runtime/` (supervisor, spawn, messages, recovery) |
| pack | `packs/`, `skills/`, `src/otto/pack/`, `src/otto/behaviour/` (schedules, advisor, idle rule) |
| delivery | `tests/`, `install/`, `src/otto/land/`, CI config, docs |

**Running a folder:**
- **Today**, with Claude Code or Codex sessions: the orchestrator hands a manager its folder.
- **Once the tool exists:** `otto project new <name> --from docs/plan/projects/<name>`.
