# COMPOSEFLEET: the orchestrator's answer (16 Oct 2026), resume

You're right, and my row was wrong on both counts:
1. **The line is `otto.plan.branch` in `otto.plan.repo`**, the task's own plan metadata (`plan_metadata.py`). `otto.plan.lines` is a size estimate. A task dispatched without `repo` and `branch` is refused, naming the missing key.
2. **One `LabFleet` and one `LandingService` per (repo, branch), not per owner.** The owner keeps a small registry keyed by (repo, branch), creates each pair on first use and reuses it. Nothing is per assignment.
3. **Repo name to checkout:** the owner's configuration maps each repo name to its local path. An unknown repo is refused, naming it. Put the map where the owner's other host configuration lives, and the staging Otto's in its own home.
4. **Everything per assignment comes from records** (the dispatch record: task id and admitted revision; then the task's plan metadata), never from the worker's request. A worker's token resolves to its assignment, and so to its own lab and line.

Your files, as the row says: the owner composition in `src/otto/hostctl/` (and `install/controller/`'s composition lines only, named in your report). The pieces stay in `herzchen/fleet/`. Show each new test red on `canon/main`, then green. Every sub-agent is `spawn_agent` with `model: "gpt-6-luna"`.
