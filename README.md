# otto

**A small tool that runs an organisation of AI agents on one machine.**
- **The organisation:** an advisor, an orchestrator, managers, workers and sub-agents.
- **What it's built on:** oh-my-pi for sessions and models; packs (Megado first) for the method; spec folders for projects; one SQLite file for state.

**Status:** being built. Day 0 is done: this skeleton, CI and the landing script.

| You are | Start with |
|---|---|
| Anyone new | `docs/plan/START-HERE.md` |
| The orchestrator | `ORCHESTRATOR.md` |
| A manager | `docs/plan/projects/MANAGER-BRIEF.md`, then your folder in `docs/plan/projects/` |
| A worker | the brief your manager gave you, plus `AGENTS.md` |

**Old Otto** (the predecessor) is preserved on the **`deprecated`** branch and the `transfer/20261028/*` branches. Its history is not part of `main`.

```
scripts/ci.sh                   # the CI gate: build the wheel, install it fresh, test the installed package
scripts/land.sh <branch>        # the only way onto main: rebase, run CI on that commit, fast-forward only
```
