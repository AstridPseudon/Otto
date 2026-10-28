# Brief: GATEPAR (normal, 0.5 focused days)

**Outcome:** Split the landing sweep into a run phase and a judge phase. Run each file's two test runs sequentially while running up to `OTTO_GATE_JOBS` files in parallel (default 3; 1 restores serial behavior), storing outputs under `$G/sweep/<file>/`. Keep judging serial and in file order, with the existing skip-check, failure-id, BASE comparison and isolated reproduction behavior. Preserve the existing `land.log` lines and all other gate behavior.

**Why it matters:** 37 committed tasks are waiting behind a serial gate sweep that takes about 11 minutes per clean landing. Parallel file runs should drain the queue faster while preserving the same verdicts.

**Your lab:** `<lab path>`, on branch `lab/GATEPAR`, from `canon/main` at `<sha>`. Work only here.

**Layer:** Otto product. This is Otto's landing infrastructure under `ops/bootstrap`.

**Files you own:** `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`.

**Other files:** You may edit other files required by this outcome, except files owned by the active SESSIONFD landing or any worker that starts while you run. List any additional files and why in your report.

**Do not touch:**
- `ops/bootstrap/land.sh` or `tests/test_bootstrap_gate.py` in another task's lab;
- files of the active SESSIONFD landing;
- `production/`, Stores, `~/.otto`, `~/.codex`, Codex's projects, vision or Native5;
- anything outside this lab.

**Build on what exists:** `ops/bootstrap/land.sh` constructs `SWEEP` at about lines 317-348, runs each file serially at about lines 403-428, then judges results and writes `land.log` entries. Preserve `run_pytest`, `ids_of`, `baseline_out`, `reproduces`, and the serial judge logic. `tests/test_bootstrap_gate.py` contains the gate's scratch-repo tests, including the sweep and refusal cases.

**Your check.** Add a fake sweep test that proves no more than `OTTO_GATE_JOBS` files run concurrently, each file's two runs remain sequential, `OTTO_GATE_JOBS=1` keeps the current verdicts and `land.log` lines, and a reproducible NEW failure is still refused. Run the whole gate test file.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

**Regression at the level the friction appears:** a multi-file fake landing demonstrating bounded parallelism, serial per-file runs, unchanged serial judge output, and refusal of a reproducible NEW failure.

**Deletion budget:** Replace the existing serial sweep loop with the run-phase/judge-phase implementation; do not add another sweep mechanism alongside it.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run.

**On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. **A long test runs to its end:** give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed (REDS and DISPATCH stopped at "30 seconds", 16 Oct). A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**
