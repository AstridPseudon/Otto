# Brief: PERCH1 (normal, 0.75 focused days)

**Outcome:** Stage 1 of the canary runs on the staging Otto. The owner socket accepts `work.project.save` and the reads a save needs, so a save can go through the socket from a cold shell. The canary has a stage `1` in its project file, and `perch.sh 1` can run on an empty Store. Its scenarios: save the canary from its file through the socket; read it back; edit one task and save again; save from a stale base. Each new assertion has its own seeded fault, and each fault turns only its own assertion red.

**Why it matters:** Stage 1 review cannot run until a save can reach the staging Otto through its socket. A2 built `otto save` in-process, but the socket route is a gap (A2 gap 2). PLAN.md §16 stage 1 is the gate for everything after it.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH1`, on branch `lab/PERCH1`, from `canon/main` at `2def964`. Work only here.

**Layer:** Otto product, plus bootstrap tooling (PLAN.md D14, §11). The allowlist and the stage 1 scenarios are Otto's wiring. Nothing goes into Herzchen. The test: `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/otto/hostctl/service.py` (only the lane allowlist near lines 352-370, where `portfolio-operation` is checked; add the save route and the reads a save needs, and nothing else);
- `ops/bootstrap/perch.sh` and `ops/bootstrap/perch_report.py` (stage 1 support);
- `ops/bootstrap/canary/project.json` (a stage `1` entry, and the expected Store contents for stage 1);
- `tests/test_perch_stage1.py` (new; the seeded-fault tests live here).

**Do not touch:**
- other tasks' files (in particular `src/otto/portfolio/cli.py`, `status.py`, and `document_editor_host.py`, which A3 uses);
- `install/controller/`;
- `production/`, any Store, `~/.otto` or `~/.codex`;
- the live Otto or its socket. Staging only;
- anything outside this lab.

**Build on what exists:**
- `ops/bootstrap/perch.sh` already runs stage `0`: `run_stage`, the `stage` and `tasks` keys of `perch_report.py`, and the `staging-lifecycle` scenario (see the header of perch.sh).
- A2's save route: `otto save` through `herzchen_binding.py` and batch replay (`intake.py:1094`, `batches.py:150`). Read A2's landing note in `ops/requests.md` (`## Manager 2026-10-16T09:48Z`, gap 2) and the A2 worker report under `ops/runs/A2/`.
- The allowlist code at `src/otto/hostctl/service.py:352-370` (the `portfolio-operation` branch and the other lane commands above it).
- Staging is already restarted by the landing gate. Don't restart it yourself.

**Your check.** Make it green and keep everything else green:
- `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py tests/test_perch_staging.py tests/test_perch_timeline.py tests/test_perch_stage1.py tests/test_otto_save.py`. Run tests with no env prefix (`pyproject.toml` sets pytest's `pythonpath`).
- Each new stage 1 assertion (`tasks-are-typed-records`, `nothing-runs`, `edit-makes-revision`, `stale-save-refused`, `store-growth-per-save`) needs its own seeded-fault test. Show that the fault turns that assertion red and that the others stay green.
- Regression for the socket route: a test that a save sent through the owner socket is accepted, and one that a non-allowlisted operation is still refused.
- Do not run `perch.sh 1` against the live machine yourself. The landing gate runs `perch.sh all --fake` on staging, and the orchestrator runs stage 1 for real.
- Run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "PERCH1 check" -- <cmd>`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py tests/test_perch_staging.py tests/test_perch_timeline.py tests/test_perch_stage1.py tests/test_otto_save.py`

**Callers, including production:** the allowlist is read by the owner. If you change its shape, find every caller in `src/otto/hostctl/` and in `install/controller/`.

**Existing tests:** don't change what an existing test asserts to make your change pass. If one must change, keep the change in its own commit and give the reason in your report. It then goes to an Opus decision (D19) before landing.

**Regression at the level the friction appears:** a save through the owner socket from a cold shell (the stage 1 scenario) and a refused stale save.

**Deletion budget:** the allowlist change replaces nothing, so keep it to the minimum: name the routes you add.

**Working rules:** commit work in progress to `lab/PERCH1` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet.

**When done:** commit to `lab/PERCH1` and don't push. Report the commit, the check runs (red, then green), the routes you added to the allowlist, what you deleted, and anything you couldn't finish.
