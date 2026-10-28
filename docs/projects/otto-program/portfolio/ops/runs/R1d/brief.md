# Brief: R1d (xhard, 1.0 focused days)

**Outcome:** A render requested by a leased job carries that lease through the Runtime request and consumes no second capacity slot. A standalone render takes a weight-3 lease and waits until 3 slots are free. The Runtime executor gate remains the render's own bound.

**Why it matters:** Astrid renders must be visible to the shared pool without deadlocking a job that already holds capacity. The invariant is that a nested render never waits on its parent's slots; the plausible mistake is counting it separately or not at all.

**Your lab:** `labs/R1d`, on branch `lab/R1d`, from `canon/main` at the launcher's current SHA. Work only here.

**Layer:** Herzchen fleet for lease propagation; Astrid Runtime request client for carrying the lease. New pool code goes in `src/herzchen/fleet/`.

**Files you own:** `src/herzchen/fleet/capacity.py`, the existing Astrid Runtime render-request client that sends the Runtime request, and focused tests for nested and standalone renders. Identify and report the exact Runtime client path before editing. Do not edit `src/otto/portfolio/` or any work-domain/save files; SAVEFIX and ACT are in flight.

**Do not touch:**
- other tasks' files;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** POOL's `CapacityPool`/lease API in `herzchen/fleet/capacity.py` and the existing Runtime render request path. Keep `store.py`'s executor gate as the render's own bound.

**Your check.** Make it green and keep everything else green:
- Prove a journey holding 2 of 4 slots can complete its render; prove a standalone render waits for 3 free slots; prove no render runs uncounted.
- Regression tests must fail on `canon/main` first; show both runs.
- Run tests with no env prefix (the Bash allowlist refuses one): `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`; run heavy commands through `otto-heavy --weight N --purpose "R1d" -- <cmd>`.
- Do not sweep the rest: the landing gate runs every test file that imports a module you changed, twice.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests -k "render"`

**Regression at the level the friction appears:** an active leased journey requests a render when only its own held slots are available; nested work proceeds without a second lease, while a standalone render waits for a weight-3 lease.

**XHARD only:**
- invariant: A nested render never waits on its own parent's slots.
- plausible mistake to avoid: Counting the render separately, or not at all; preserve the render's executor bound.

**Deletion budget:** replace the unpooled Runtime request path with lease propagation; identify the retired path in your report.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**

**XHARD only: you lead, a cheaper model executes** (PLAN.md D10). On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** leave changes for the launcher to commit and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish. Stop and ask if the brief contradicts the code.
