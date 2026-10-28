# Brief: COMPOSEFLEET (xhard, 1.0 focused days)

**Outcome:** Compose one `LabFleet`, `LandingService`, and result store per owner. Resolve each assignment's task id and admitted revision from the dispatch record, its lab from that task, its line from the project's `otto.plan.lines` for that task's repo, and its runner `ResultStore` under the owner's home. The dispatcher-issued token resolves to that record; `done` lands only that task's lab on its own line, and `check` runs only its own check. Give the worker the required `worker_mcp` grant. Keep reusable fleet pieces in Herzchen and add Otto names, roles, and policies in the owner composition.

**Why it matters:** DISPATCH exposed that production does not yet compose the fleet, landing, result store, or assignment-to-lab resolver. A worker must only act on its own assignment's lab and line.

**Your lab:** `labs/COMPOSEFLEET`, on branch `lab/COMPOSEFLEET`, from `canon/main` at `812d06a86937873b15b6f1d5225873a5531930eb`. Work only here.

**Layer:** Otto product composition. Reuse the existing Herzchen fleet components; keep reusable dispatch and landing behavior in `src/herzchen/fleet/` and pass Otto roles and policies into them.

**Files you own:**
- `src/otto/hostctl/product_service.py` (composition near `:327`)
- `src/otto/hostctl/serve.py` (owner service composition near `:234`)
- `tests/test_hostctl_serve.py`
- `tests/test_fleet_dispatch.py`
- `tests/test_fleet_custody.py`

**Do not touch:** other tasks' files; `install/controller/` except its composition lines if required by the row; `production/`; any Store, `~/.otto` or `~/.codex`; Codex's projects, vision and Native5; anything outside this lab.

**Build on what exists:** `src/herzchen/fleet/dispatch.py`, `src/herzchen/fleet/labs.py`, `src/herzchen/fleet/landing.py`, `src/herzchen/fleet/runner/store.py`, and the owner composition in `product_service.py` and `serve.py`.

**Your check.** Prove on staging that a fake worker's `done` lands exactly its own task's lab on the project's line; `check` returns feedback only; a token for another assignment is refused; the staging perch passes. Preserve the invariant: a worker can act only on its own assignment's lab and line. Avoid resolving the lab or line from worker request fields.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_serve.py tests/test_fleet_dispatch.py tests/test_fleet_custody.py`

**Regression at the level the friction appears:** n/a: feature task.

**Deletion budget:** replace the uncomposed production path; name any obsolete mechanism removed.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. Never wait: no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. On Codex, don't commit; the launcher commits when you exit. Any sub-agent is `spawn_agent` with `model: "gpt-6-luna"`. As Sol on this XHARD task, lead the design and review, and delegate almost all execution to Luna sub-agents. Give each sub-brief the goal, exact files and functions, limits, command, and reporting request. Parallelize only non-overlapping files.

**When done:** leave the changes for the launcher; report the commit, checks, staging perch result, assignment-binding evidence, what was replaced, sub-agent work, and anything unfinished. Stop and ask if the brief contradicts the code.
