# Brief: PYSTUB (xhard, 0.5 focused days)

**Outcome:** A fenced worker or MCP server using Homebrew's framework Python can start. When an interpreter is pinned for execution, admit the interpreter's own framework re-exec target when it exists, by one additional literal realpath. Keep all other executables denied. Demonstrate the Python stub runs under the real fence, an unpinned binary remains denied, and stage 2 `--fake` launches A's worker.

**Why it matters:** The Homebrew `python3.11` stub re-execs `Python.app/Contents/MacOS/Python`. The process fence currently allows only the stub, so the child exits before its worker or MCP server starts; stage 2 dispatch then remains misleadingly admitted.

**Your lab:** `lab/PYSTUB`, on branch `lab/PYSTUB`, from `canon/main`. Work only here.

**Layer:** Herzchen model and Otto product wiring. The generic fence and pin behavior belongs in Herzchen; update Otto's matching pinned-executable loop so it agrees.

**Files you own:**
- `src/herzchen/fleet/hosts/claude.py` (the literal process-exec policy)
- `src/herzchen/fleet/tools/pins.py` (`exec_allow_for`)
- `src/otto/agents/claude_cli.py` (the matching executable pin loop)
- `tests/test_fleet_custody.py` (real-fence and unpinned-binary regression)

**Other files:** You may edit another file only if the outcome directly requires it. Do not change the stage-2 harness or `tests/test_perch.py`; the orchestrator will prove stage 2 `--fake` after this dependency lands. Explain any additional files in your report.

**Do not touch:**
- `ops/bootstrap/perch.sh`, `ops/bootstrap/perch_report.py`, `ops/bootstrap/canary/project.json`, `ops/bootstrap/canary/fake_worker.py`, `ops/bootstrap/staging.sh`, `tests/test_perch.py`, `tests/test_perch_stage1.py`, `tests/test_perch_staging.py`, `tests/test_perch_timeline.py` (SKEL0's files);
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex's projects, vision and Native5, or anything outside this lab.

**Build on what exists:** `sandbox_policy` in `src/herzchen/fleet/hosts/claude.py` (process-exec allowances around lines 81-119); `exec_allow_for` in `src/herzchen/fleet/tools/pins.py` (around line 29); `ClaudeCLI`'s `exec_allow` resolution in `src/otto/agents/claude_cli.py` (around lines 193-198). Preserve the literal-path allowlist and existing refusal of unpinned binaries.

**Your check.** Add a regression under the real `sandbox-exec` fence for Homebrew's stub/re-exec path (skip where `sandbox-exec` or that Python installation is unavailable), and retain an assertion that an unpinned binary is denied. Run the focused test and report both runs for new regression assertions where practical. Stage-2 `--fake` acceptance is run outside this worker by the orchestrator after landing.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_fleet_custody.py`

**Regression at the level the friction appears:** A worker process launched with the pinned Homebrew interpreter survives the OS fence; an unpinned executable still cannot run.

**XHARD only:**
- invariant: the fence allows exactly pinned binaries and each pinned interpreter's own existing re-exec target, by literal path;
- plausible mistake to avoid: allowing the framework directory or a subpath, which would admit arbitrary binaries there.

**Working rules:** Follow the Codex and XHARD rules in `ops/brief-template.md`: delegate execution to Luna sub-agents, retain design and review, never commit or push, never run `git stash`, `ottoctl`, or another checkout, and let long tests finish.
